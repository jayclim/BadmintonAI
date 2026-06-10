"""LLM tactical commentary: a coach's match report generated from the stats tables.

Pipeline: build_dossier() condenses the insights/tactics layer into a compact
JSON dossier (real player names, no A/B) → an LLM turns it into a MatchCommentary
(pydantic-validated) → cached at data/commentary/<match_id>.<provider>.json so each
match is generated once per provider (same parse-once philosophy as the DuckDB cache).

Providers (toggleable; keys live in the gitignored .env at the repo root):
- "gemini" — GEMINI_API_KEY (+ optional GEMINI_MODEL, default gemini-2.5-flash). REST,
  JSON mode; the response schema is enforced by validating with pydantic.
- "claude" — ANTHROPIC_API_KEY / ANTHROPIC_AUTH_TOKEN (+ optional CLAUDE_MODEL).
  Native structured output via messages.parse, adaptive thinking.
default_provider() prefers gemini (free tier) when both keys are present.

CLI:  PYTHONPATH=src python -m badminton.commentary <match_id> [--provider gemini|claude]
      [--force | --dossier-only]
"""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from pydantic import BaseModel, Field

from . import config, insights, tactics

PROVIDERS = ("gemini", "claude")          # default_provider() preference order
CACHE_DIR = Path("data/commentary")


def _load_dotenv() -> None:
    """Load KEY=value lines from the repo-root .env into os.environ (no override)."""
    p = config.REPO_ROOT / ".env"
    if not p.exists():
        return
    for line in p.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip("'\""))

SYSTEM = """You are a world-class badminton coach and analyst writing a post-match \
tactical report on a professional men's singles match. You are given a statistical \
dossier extracted from human-labeled stroke data and computer-vision player tracking.

How to read the dossier:
- "pressure" / "required speed" (m/s) = how fast a player had to move to reach a shot. \
Mean ~2.3 m/s; ≥2.5 m/s means scrambling. "applied" = pressure forced on the opponent.
- "errors" are rally-ending mistakes, split into forced (scrambling when the error \
happened) vs unforced (hit from a comfortable position).
- "rule_based_flags" are observations a deterministic system already surfaced — build \
on them, reconcile them with the numbers, and go deeper; don't just restate them.
- Court positions and distances come from validated CV tracking (median error ~0.6 m).

Write like a coach talking to coaches: concrete, evidence-cited (use the actual \
numbers), tactically specific, no fluff. Prefer "his cross-court defensive lob under \
pressure" over "his defense". Every claim must be supported by a number in the dossier. \
Do not invent events (specific rallies, shouts, crowd, injuries) that are not in the data."""


# ---------------------------------------------------------------- output schema

class PlayerReport(BaseModel):
    name: str = Field(description="Player's name exactly as given in the dossier")
    overview: str = Field(description="2-3 sentence tactical assessment of his match")
    strengths: list[str] = Field(description="2-4 specific strengths, each citing numbers")
    weaknesses: list[str] = Field(description="2-4 specific weaknesses, each citing numbers")
    training_priorities: list[str] = Field(
        description="2-3 concrete drills/focus areas derived from the weaknesses")
    gameplan_against: str = Field(
        description="One paragraph: how a future opponent should play him")


class MatchCommentary(BaseModel):
    headline: str = Field(description="One punchy line capturing how the match was decided")
    match_story: str = Field(
        description="2-3 paragraph narrative of how the match unfolded and why the "
                    "winner won, grounded in the set scores, runs, and stats")
    turning_points: list[str] = Field(
        description="2-4 statistical turning points / deciding factors, each one sentence")
    players: list[PlayerReport] = Field(description="One report per player (both players)")


# ---------------------------------------------------------------- dossier

def _plain(o):
    """Recursively convert numpy/Counter/tuple-key structures to JSON-safe types."""
    import numpy as np
    if isinstance(o, dict):
        return {str(k): _plain(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_plain(v) for v in o]
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating,)):
        return float(o)
    return o


def _set_summaries(rdf, names) -> list[dict]:
    """Per set: final score, lead changes, longest run per player."""
    out = []
    for sn, g in rdf[rdf["winner"].notna()].groupby("set_no"):
        g = g.sort_values("rally_id")
        # a lead change = the (nonzero) lead switching sign; leads move ±1 per rally
        # so they always pass through 0 — compare against the last nonzero sign
        changes, last_sign = 0, 0
        for ld in (g["score_a"] - g["score_b"]).to_list():
            if ld == 0:
                continue
            sign = 1 if ld > 0 else -1
            if last_sign and sign != last_sign:
                changes += 1
            last_sign = sign
        runs, cur, last = {"A": 0, "B": 0}, 0, None
        for w in g["winner"]:
            cur = cur + 1 if w == last else 1
            last = w
            runs[w] = max(runs[w], cur)
        out.append({
            "set": int(sn),
            "final_score": f"{names['A']} {int(g['score_a'].max())}–{int(g['score_b'].max())} {names['B']}",
            "lead_changes": changes,
            "longest_run": {names[p]: runs[p] for p in ("A", "B")},
            "rallies": len(g),
        })
    return out


def build_dossier(match_id: str) -> dict:
    """Everything the LLM needs, with A/B replaced by real names, in a few KB."""
    m = config.get_match(match_id)
    names = {"A": m["players"][1], "B": m["players"][0]}  # ShuttleSet A = winner

    sdf = insights.stroke_df(match_id)
    rdf = insights.rally_df(match_id, sdf)

    def by_name(d: dict) -> dict:
        return {names[p]: d[p] for p in ("A", "B") if p in d}

    oc = insights.shot_outcome_counts(rdf)
    outcomes = {names[p]: oc[oc["player"] == p][["shot", "winners", "errors"]]
                .sort_values("winners", ascending=False).to_dict("records")
                for p in ("A", "B")}

    lb = insights.length_buckets(rdf)
    length = {names[p]: lb[lb["player"] == p][["bucket", "played", "won", "win_pct"]]
              .to_dict("records") for p in ("A", "B")}

    serve = {}
    for p, s in insights.serve_stats(rdf).items():
        serve[names[p]] = {
            "serving": f"won {s['serve_won']}/{s['serve_n']}",
            "receiving": f"won {s['recv_won']}/{s['recv_n']}",
            "by_serve_type": {str(t): f"won {v['won']}/{v['n']}"
                              for t, v in s["by_type"].items()},
        }

    pats = [{"ending_sequence": x["pattern"], "times": x["n"],
             names["A"]: x["a_wins"], names["B"]: x["b_wins"]}
            for x in insights.patterns(rdf, n=2, min_count=3)[:8]]

    movement = {}
    for p, mv in insights.movement_by_player(match_id).items():
        movement[names[p]] = {k: v for k, v in mv.items() if k != "positions"}

    dist = tactics.shot_distribution(match_id)
    shot_mix = {names[p]: dict(dist[p].most_common()) for p in ("A", "B") if p in dist}

    notes = insights.coach_notes(match_id, rdf, sdf, names)
    flags = [{"title": n["title"], "detail": n["body"]} for n in notes[:8]]

    return _plain({
        "match": {
            "players": [names["B"], names["A"]],
            "winner": names["A"],
            "tournament": m.get("tournament"),
            "round": m.get("round"),
            "sets": _set_summaries(rdf, names),
            "total_rallies": len(rdf),
            "total_shots": int(rdf["shots"].sum()),
        },
        "points_won": by_name(insights.points_won(rdf)),
        "longest_point_run": by_name(insights.longest_run(rdf)),
        "rally_length_win_rates": length,
        "serve": serve,
        "clutch_points_from_18": by_name(insights.clutch_stats(rdf)),
        "rally_ending_shots": outcomes,
        "shot_mix_counts": shot_mix,
        "ending_patterns_2shot": pats,
        "errors_forced_vs_unforced": by_name(insights.error_pressure(match_id, rdf)),
        "backhand": by_name(insights.backhand_stats(sdf, rdf)),
        "pressure_mps": by_name(tactics.pressure_summary(match_id)),
        "opponent_scramble_speed_by_shot_type": tactics.pressure_by_shot(match_id),
        "movement_from_cv_tracks": movement,
        "rule_based_flags": flags,
    })


# ---------------------------------------------------------------- providers

def available_providers() -> list[str]:
    """Providers we have credentials for, in preference order."""
    _load_dotenv()
    out = []
    if os.environ.get("GEMINI_API_KEY"):
        out.append("gemini")
    if os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"):
        out.append("claude")
    return out


def default_provider() -> str | None:
    avail = available_providers()
    return avail[0] if avail else None


def has_credentials() -> bool:
    return bool(available_providers())


def _parse_commentary(text: str) -> MatchCommentary:
    """Validate model output, tolerating markdown code fences."""
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1].rsplit("```", 1)[0]
    return MatchCommentary.model_validate_json(text)


def _generate_claude(prompt: str) -> tuple[MatchCommentary, str, dict]:
    import anthropic

    model = os.environ.get("CLAUDE_MODEL", "claude-opus-4-8")
    client = anthropic.Anthropic()
    response = client.messages.parse(
        model=model,
        max_tokens=16000,
        thinking={"type": "adaptive"},
        system=SYSTEM,
        messages=[{"role": "user", "content": prompt}],
        output_format=MatchCommentary,
    )
    usage = {"input_tokens": response.usage.input_tokens,
             "output_tokens": response.usage.output_tokens}
    return response.parsed_output, model, usage


def _generate_gemini(prompt: str) -> tuple[MatchCommentary, str, dict]:
    import requests

    model = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
    schema = json.dumps(MatchCommentary.model_json_schema(), indent=1)
    body = {
        "system_instruction": {"parts": [{"text": SYSTEM}]},
        "contents": [{"role": "user", "parts": [{"text":
            prompt + "\n\nRespond with a single JSON object matching this JSON schema "
                     "exactly (no markdown, no extra keys):\n" + schema}]}],
        "generationConfig": {"response_mime_type": "application/json"},
    }
    r = requests.post(
        f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
        params={"key": os.environ["GEMINI_API_KEY"]}, json=body, timeout=300)
    if not r.ok:
        raise RuntimeError(f"Gemini API {r.status_code}: {r.text[:500]}")
    data = r.json()
    text = data["candidates"][0]["content"]["parts"][0]["text"]
    um = data.get("usageMetadata", {})
    usage = {"input_tokens": um.get("promptTokenCount"),
             "output_tokens": um.get("candidatesTokenCount")}
    return _parse_commentary(text), model, usage


_GENERATORS = {"claude": _generate_claude, "gemini": _generate_gemini}


# ---------------------------------------------------------------- generation + cache

def cache_path(match_id: str, provider: str) -> Path:
    return CACHE_DIR / f"{match_id}.{provider}.json"


def cached(match_id: str, provider: str | None = None) -> dict | None:
    """Cached report for one provider, or — provider=None — the freshest of any."""
    paths = ([cache_path(match_id, provider)] if provider
             else [cache_path(match_id, p) for p in PROVIDERS])
    hits = [p for p in paths if p.exists()]
    if not hits:
        return None
    return json.loads(max(hits, key=lambda p: p.stat().st_mtime).read_text())


def generate(match_id: str, provider: str | None = None, force: bool = False) -> dict:
    """Generate (or return cached) commentary. Raises on missing credentials/API errors."""
    _load_dotenv()
    provider = provider or default_provider()
    if provider is None:
        raise RuntimeError("No LLM credentials — put GEMINI_API_KEY (or ANTHROPIC_API_KEY) "
                           "in the repo-root .env")
    if not force:
        hit = cached(match_id, provider)
        if hit is not None:
            return hit

    dossier = build_dossier(match_id)
    prompt = ("Here is the match dossier as JSON. Write the tactical report.\n\n"
              + json.dumps(dossier, indent=1, ensure_ascii=False))
    parsed, model, usage = _GENERATORS[provider](prompt)

    record = {
        "match_id": match_id,
        "provider": provider,
        "model": model,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "usage": usage,
        "commentary": parsed.model_dump(),
    }
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_path(match_id, provider).write_text(json.dumps(record, indent=2, ensure_ascii=False))
    return record


def to_markdown(record: dict) -> str:
    c = record["commentary"]
    lines = [f"# {c['headline']}", "", c["match_story"], "", "## Turning points"]
    lines += [f"- {t}" for t in c["turning_points"]]
    for p in c["players"]:
        lines += ["", f"## {p['name']}", p["overview"], "", "**Strengths**"]
        lines += [f"- {s}" for s in p["strengths"]]
        lines += ["", "**Weaknesses**"]
        lines += [f"- {w}" for w in p["weaknesses"]]
        lines += ["", "**Training priorities**"]
        lines += [f"- {t}" for t in p["training_priorities"]]
        lines += ["", f"**How to beat him:** {p['gameplan_against']}"]
    return "\n".join(lines)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Generate LLM tactical commentary for a match")
    ap.add_argument("match_id")
    ap.add_argument("--provider", choices=PROVIDERS, default=None,
                    help="LLM to use (default: first with credentials — gemini, then claude)")
    ap.add_argument("--force", action="store_true", help="regenerate even if cached")
    ap.add_argument("--dossier-only", action="store_true",
                    help="print the dossier JSON and exit (no API call)")
    args = ap.parse_args()
    if args.dossier_only:
        print(json.dumps(build_dossier(args.match_id), indent=2, ensure_ascii=False))
    else:
        rec = generate(args.match_id, provider=args.provider, force=args.force)
        print(to_markdown(rec))
