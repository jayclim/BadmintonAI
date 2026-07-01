"""Doubles AI tactical commentary — LLM coach report from the doubles tactics (ISOLATED).

Mirrors the singles `badminton.commentary`, but doubles-tailored and kept in the doubles
package so the singles report path is untouched and this stays deletable. It does NOT
import the singles commentary module (isolation rule) — the small provider/.env plumbing
is re-implemented locally, the same way `doubles.export_web` re-implements its JSON helpers.

Source of truth: the assembled `web/public/data/<id>/doubles.json` written by
`doubles.export_web` (formation, flow, control, per-player front-court share, movement,
points, rule-based notes). build_dossier() condenses that into a compact JSON dossier
(heavy heat/replay grids dropped) → an LLM turns it into a DoublesCommentary
(pydantic-validated) → cached at data/commentary/<id>.doubles.<provider>.json, and the
commentary is also written to web/public/data/<id>/analysis.json for the dashboard to fetch.

Providers (keys in the gitignored repo-root .env): "gemini" (GEMINI_API_KEY) and
"claude" (ANTHROPIC_API_KEY/ANTHROPIC_AUTH_TOKEN, claude-opus-4-8, structured output +
adaptive thinking). default_provider() prefers gemini when both are present.

CLI:  PYTHONPATH=src python -m badminton.doubles.commentary <match_id>
          [--provider gemini|claude] [--force | --dossier-only]
"""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from pydantic import BaseModel, Field

from .. import config

PROVIDERS = ("gemini", "claude")
CACHE_DIR = config.REPO_ROOT / "data" / "commentary"
WEB_DATA = config.REPO_ROOT / "web" / "public" / "data"


def _load_dotenv() -> None:
    p = config.REPO_ROOT / ".env"
    if not p.exists():
        return
    for line in p.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip("'\""))


SYSTEM = """You are a world-class badminton doubles coach and analyst writing a post-match \
tactical report on a professional doubles match. Your input is a statistical dossier \
extracted from computer-vision player tracking and CV-detected shuttle contacts — no human \
labels. Positioning, formation and movement are exact; shot TYPES (when a "shots" section \
is present) come from a geometry classifier transferred from labelled singles and are \
unvalidated on doubles — trust distributions and contrasts between the teams, never a \
single call.

How to read the dossier (doubles-specific):
- Teams are A and B (fixed for the whole match); pairs swap ends between games, so every \
stat already follows the TEAM, not the court side.
- "formation": attack = the pair stacked FRONT/BACK (one hunts the net, partner covers the \
rear and hits down); defence = side-by-side (receiving a smash). attackPct is the share of \
rally frames in the attacking shape. "rotations" = debounced attack<->defence switches. \
"frontSwaps" = how often the two partners swapped who is at the net.
- "flow": attackFirstPct = how often the team seized the attack first in a rally; \
attackHoldMedS = median seconds it held the attack before being rotated off; rotPerMin = \
rotation cadence; a2d/d2a = attack->defence / defence->attack transitions.
- "control" = court-control via a Voronoi dominant-region model (each court point goes to \
the team whose nearer player is closer). IMPORTANT: raw control has a small static \
far-side tracking bias, so judge it by "summary" (per-team, frame-weighted, bias largely \
cancels because ends swap) and by the bias-cancelled per-rally "index", not raw percentages.
- "front_court_share" = % of in-rally frames each named player spent as the net player \
(the attacker); the partner covers the rear.
- "movement": per player distance / speed / court coverage and front/mid/back occupancy.
- "shots" (when present): shot_mix = what each team hits; response_matrix = given the \
opponent's shot (key), what the team answers with; serve_receive = points won serving vs \
receiving (doubles' side-out stat; only OCR-scored rallies count); finishers = each scored \
rally's LAST detected stroke — the winner's is the shot that finished the point, the \
loser's is the shot that didn't come back (error and got-punished are indistinguishable).
- "rule_based_flags" are deterministic observations already surfaced — build on them, \
reconcile with the numbers, go deeper; don't just restate them.

Write like a coach talking to coaches: concrete, evidence-cited (use the actual numbers), \
doubles-specific (rotation, net dominance, attack/defence, serve pressure, who covers the \
rear), no fluff. Every claim must be supported by a number in the dossier. Do not invent \
specific rallies or events that are not in the data."""


class PairReport(BaseModel):
    pair: str = Field(description="The pair's name exactly as given (e.g. 'Goh / Izzuddin')")
    overview: str = Field(description="2-3 sentence tactical assessment of this pair's match")
    strengths: list[str] = Field(description="2-4 specific strengths, each citing numbers")
    weaknesses: list[str] = Field(description="2-4 specific weaknesses, each citing numbers")
    training_priorities: list[str] = Field(
        description="2-3 concrete doubles drills/focus areas derived from the weaknesses")
    gameplan_against: str = Field(
        description="One paragraph: how a future pair should play against them")


class DoublesCommentary(BaseModel):
    headline: str = Field(description="One punchy line capturing how the match was decided")
    match_story: str = Field(
        description="2-3 paragraph narrative of how the match unfolded and why the winner "
                    "won, grounded in formation, control, rotation and the scores")
    turning_points: list[str] = Field(
        description="2-4 tactical turning points / deciding factors, each one sentence")
    pairs: list[PairReport] = Field(description="One report per pair (both teams)")


# ---------------------------------------------------------------- dossier

def _load_doubles_json(match_id: str) -> dict:
    p = WEB_DATA / match_id / "doubles.json"
    if not p.exists():
        raise SystemExit(f"no doubles.json for {match_id} — run "
                         f"`python -m badminton.doubles.export_web {match_id}` first")
    return json.loads(p.read_text())


def build_dossier(match_id: str) -> dict:
    """Condense the exported doubles.json into a compact, LLM-ready tactical dossier
    (drops the heavy movement heatmaps and control map grid — the LLM needs the numbers)."""
    d = _load_doubles_json(match_id)
    meta, teams = d["meta"], d["meta"].get("teams", {})

    def team_name(t: str) -> str:
        return teams.get(t, t)

    ctrl = d.get("control") or {}
    top_control = []
    for r in sorted(ctrl.get("rallies", []), key=lambda r: -abs(r.get("nearIndex", 0)))[:6]:
        dom = r.get("nearPair") if r.get("nearIndex", 0) >= 0 else r.get("farPair")
        top_control.append({"rally": r["rally"], "set": r.get("set"),
                            "dominant": team_name(dom), "index_pts": abs(r.get("nearIndex", 0))})

    # ponytail: readable label instead of null name, so the LLM stops inventing "Player A-0"
    movement = [{**{k: v for k, v in mv.items() if k != "heat"},
                 "player": mv.get("name") or f"{team_name(mv['team'])} P{mv.get('idx', 0) + 1}"}
                for mv in d.get("movement", [])]
    pts = d.get("points") or {}
    points = None
    if pts:
        points = {"sets": [{"set": s["set"], "final": s["final"], "winner": s["winner"]}
                           for s in pts.get("sets", [])],
                  "runs": pts.get("runs"), "lengthWins": pts.get("lengthWins")}

    sh = d.get("shots") or {}
    shots_block = None
    if sh:
        def mix(rows, n=6):
            return {r["shot"]: f"{r['pct']}%" for r in (rows or [])[:n]}
        shots_block = {
            "note": "shot types are a singles-trained geometry baseline, unvalidated on "
                    "doubles — read distributions, not single calls",
            "shot_mix": {team_name(t): mix(sh["mix"].get(t)) for t in ("A", "B")},
            "response_matrix": {team_name(t): {r["vs"]: mix(r["answers"], 3)
                                               for r in (sh.get("responses", {}).get(t) or [])[:5]}
                                for t in ("A", "B")},
            "serve_receive": {team_name(t): sh["serveReceive"][t] for t in ("A", "B")}
                             if sh.get("serveReceive") else None,
            "finishers": {"point_winning_final_shots":
                              {team_name(t): mix(sh["finishers"]["won"].get(t)) for t in ("A", "B")},
                          "point_losing_final_shots":
                              {team_name(t): mix(sh["finishers"]["lost"].get(t)) for t in ("A", "B")}}
                         if sh.get("finishers") else None,
        }

    return {
        "match": {"pairs": {k: team_name(k) for k in ("A", "B")},
                  "tournament": meta.get("tournament"), "round": meta.get("round"),
                  "result": meta.get("result"), "nSets": meta.get("nSets"),
                  "sets": meta.get("sets"), "totals": meta.get("totals")},
        "formation_per_team": {team_name(t): d["formation"].get(t) for t in ("A", "B")},
        "formation_flow_per_team": {team_name(t): (d.get("flow") or {}).get(t) for t in ("A", "B")},
        "court_control": {"note": "Voronoi dominant region; judge by summary + index, not raw "
                                  "% (small static far-side bias)",
                          "baseline_near_pct": ctrl.get("baseline"),
                          "per_team_pct": {team_name(t): (ctrl.get("summary") or {}).get(t)
                                           for t in ("A", "B")},
                          "most_one_sided_rallies": top_control},
        "front_court_share": [{"player": p["name"], "team": team_name(p["team"]),
                               "set": p["set"], "front_pct": p["frontPct"]}
                              for p in d.get("players", [])],
        "movement_from_cv": movement,
        "shots": shots_block,
        "points": points,
        "rule_based_flags": [{"title": n["head"], "detail": n["body"]} for n in d.get("notes", [])],
    }


# ---------------------------------------------------------------- providers

def available_providers() -> list[str]:
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


def _parse(text: str) -> DoublesCommentary:
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1].rsplit("```", 1)[0]
    return DoublesCommentary.model_validate_json(text)


def _generate_claude(prompt: str) -> tuple[DoublesCommentary, str, dict]:
    import anthropic

    model = os.environ.get("CLAUDE_MODEL", "claude-opus-4-8")
    client = anthropic.Anthropic()
    response = client.messages.parse(
        model=model,
        max_tokens=16000,
        thinking={"type": "adaptive"},
        system=SYSTEM,
        messages=[{"role": "user", "content": prompt}],
        output_format=DoublesCommentary,
    )
    usage = {"input_tokens": response.usage.input_tokens,
             "output_tokens": response.usage.output_tokens}
    return response.parsed_output, model, usage


def _generate_gemini(prompt: str) -> tuple[DoublesCommentary, str, dict]:
    import requests

    model = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
    schema = json.dumps(DoublesCommentary.model_json_schema(), indent=1)
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
    return _parse(text), model, usage


_GENERATORS = {"claude": _generate_claude, "gemini": _generate_gemini}


# ---------------------------------------------------------------- generate + cache

def cache_path(match_id: str, provider: str) -> Path:
    return CACHE_DIR / f"{match_id}.doubles.{provider}.json"


def cached(match_id: str, provider: str | None = None) -> dict | None:
    paths = ([cache_path(match_id, provider)] if provider
             else [cache_path(match_id, p) for p in PROVIDERS])
    hits = [p for p in paths if p.exists()]
    if not hits:
        return None
    return json.loads(max(hits, key=lambda p: p.stat().st_mtime).read_text())


def generate(match_id: str, provider: str | None = None, force: bool = False) -> dict:
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
    prompt = ("Here is the doubles match dossier as JSON. Write the tactical report.\n\n"
              + json.dumps(dossier, indent=1, ensure_ascii=False))
    parsed, model, usage = _GENERATORS[provider](prompt)

    record = {
        "match_id": match_id, "provider": provider, "model": model,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "usage": usage, "commentary": parsed.model_dump(),
    }
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_path(match_id, provider).write_text(json.dumps(record, indent=2, ensure_ascii=False))
    # also publish for the web dashboard to fetch (/data/<id>/analysis.json)
    web_dir = WEB_DATA / match_id
    if web_dir.exists():
        (web_dir / "analysis.json").write_text(
            json.dumps({k: record[k] for k in ("provider", "model", "generated_at", "commentary")},
                       ensure_ascii=False))
    return record


def to_markdown(record: dict) -> str:
    c = record["commentary"]
    lines = [f"# {c['headline']}", "", c["match_story"], "", "## Turning points"]
    lines += [f"- {t}" for t in c["turning_points"]]
    for p in c["pairs"]:
        lines += ["", f"## {p['pair']}", p["overview"], "", "**Strengths**"]
        lines += [f"- {s}" for s in p["strengths"]]
        lines += ["", "**Weaknesses**"]
        lines += [f"- {w}" for w in p["weaknesses"]]
        lines += ["", "**Training priorities**"]
        lines += [f"- {t}" for t in p["training_priorities"]]
        lines += ["", f"**How to beat them:** {p['gameplan_against']}"]
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser(description="Generate doubles AI tactical commentary (isolated)")
    ap.add_argument("match_id")
    ap.add_argument("--provider", choices=PROVIDERS, default=None)
    ap.add_argument("--force", action="store_true", help="regenerate even if cached")
    ap.add_argument("--dossier-only", action="store_true", help="print the dossier and exit")
    args = ap.parse_args()
    if args.dossier_only:
        print(json.dumps(build_dossier(args.match_id), indent=2, ensure_ascii=False))
    else:
        rec = generate(args.match_id, provider=args.provider, force=args.force)
        print(to_markdown(rec))


if __name__ == "__main__":
    main()
