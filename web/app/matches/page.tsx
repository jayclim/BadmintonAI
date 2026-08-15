import fs from "node:fs";
import path from "node:path";
import Link from "next/link";
import type { IndexData } from "@/lib/types";
import type { DoublesIndex } from "@/lib/doubles";
import ThemeToggle from "@/components/ThemeToggle";
import GitHubLink from "@/components/GitHubLink";

/* The match picker. This used to be the site's entry point; the landing page ("/")
   now opens straight into an analyzed rally and links here. */

function readIndex(): IndexData {
  const p = path.join(process.cwd(), "public", "data", "index.json");
  return JSON.parse(fs.readFileSync(p, "utf-8"));
}

function readDoublesIndex(): DoublesIndex {
  const p = path.join(process.cwd(), "public", "data", "doubles_index.json");
  if (!fs.existsSync(p)) return { matches: [] };
  return JSON.parse(fs.readFileSync(p, "utf-8"));
}

export default function Matches() {
  const idx = readIndex();
  const dbl = readDoublesIndex();
  return (
    <main className="max-w-6xl mx-auto px-6 py-8 w-full">
      <nav className="flex items-center gap-3 mb-10">
        <Link href="/" className="disp font-bold text-[1.15rem] tracking-tight shrink-0">
          COURT<span style={{ color: "var(--ai)" }}>SIDE</span>
        </Link>
        <Link href="/" className="text-dim text-[13px] hover:text-ink transition-colors">
          ← back
        </Link>
        <div className="ml-auto flex items-center gap-2">
          <GitHubLink />
          <ThemeToggle />
        </div>
      </nav>

      <header className="rise mb-10">
        <div className="kicker mb-3">EVERY ANALYZED MATCH</div>
        <h1 className="text-[clamp(2rem,5vw,3rem)] font-bold leading-[0.98] tracking-tight">
          Explore other matches
        </h1>
        <p className="text-mut max-w-2xl mt-4 text-[15px] leading-relaxed">
          Each match opens on a six-view scouting report built from broadcast video alone. Flip
          any match to{" "}
          <span style={{ color: "var(--ai)" }} className="font-semibold">
            AI VISION
          </span>{" "}
          to see the same dashboard rebuilt with zero human labels, or to GROUND TRUTH to see
          what the human annotators recorded.
        </p>
      </header>

      <div className="grid md:grid-cols-2 gap-5">
        {idx.matches.map((m, i) => (
          <Link
            key={m.id}
            href={`/m/${m.id}/${m.sources.includes("labels") ? "labels" : "ai"}/overview/`}
            className={`card rise rise-${Math.min(i + 2, 5)} p-6 hover:border-[var(--mut)] transition-colors group block`}
          >
            <div className="kicker mb-3">
              {m.tournament} · {m.round}
            </div>
            <div className="flex items-end justify-between gap-4">
              <div>
                <div className="disp text-[1.7rem] font-semibold leading-tight">
                  <span style={{ color: "var(--pa)" }}>{m.players.A}</span>
                  <span className="text-dim text-[1.1rem] mx-2">def.</span>
                  <span style={{ color: "var(--pb)" }}>{m.players.B}</span>
                </div>
                <div className="mono text-mut text-[13px] mt-2">
                  {m.sets.map((s) => s.join("–")).join("  ·  ")}
                </div>
              </div>
              <div className="text-right shrink-0">
                <div className="bignum text-[2.4rem] text-ink/90">{m.rallies}</div>
                <div className="kicker">RALLIES</div>
              </div>
            </div>
            <div className="flex items-center gap-2 mt-5">
              {m.sources.includes("labels") && (
                <span className="mono text-[10px] tracking-[0.15em] px-1.5 py-0.5 rounded border border-[var(--line)] text-mut">
                  GROUND TRUTH
                </span>
              )}
              {m.sources.includes("ai") && (
                <span className="mono text-[10px] tracking-[0.15em] px-1.5 py-0.5 rounded border border-[var(--ai)]/40 text-[var(--ai)] bg-[var(--ai-soft)]">
                  AI VISION
                </span>
              )}
              <span className="ml-auto text-dim text-[12px] group-hover:text-mut transition-colors">
                open match →
              </span>
            </div>
          </Link>
        ))}
      </div>

      {dbl.matches.length > 0 && (
        <section className="mt-14">
          <div className="flex items-baseline gap-3 mb-1">
            <h2 className="text-[1.6rem] font-semibold tracking-tight">Doubles</h2>
            <span className="mono text-[10px] tracking-[0.16em] px-1.5 py-0.5 rounded border border-[var(--line)] text-dim">
              EXPERIMENTAL
            </span>
          </div>
          <p className="text-mut text-[14px] max-w-2xl mb-6 leading-relaxed">
            Four players in identical kit, frequently occluded — so we track{" "}
            <span style={{ color: "var(--ai)" }} className="font-semibold">
              roles
            </span>{" "}
            rather than names: front and back, attacking vs defending formation, and net coverage.
          </p>
          <div className="grid md:grid-cols-2 gap-5">
            {dbl.matches.map((m, i) => (
              <Link
                key={m.id}
                href={`/d/${m.id}/overview/`}
                className={`card rise rise-${Math.min(i + 2, 5)} p-6 hover:border-[var(--mut)] transition-colors group block`}
              >
                <div className="kicker mb-3">
                  {m.tournament} · {m.round}
                </div>
                <div className="flex items-end justify-between gap-4">
                  <div>
                    <div className="disp text-[1.35rem] font-semibold leading-tight">
                      <span style={{ color: "var(--pa)" }}>{m.pairs.near}</span>
                      <span className="text-dim text-[1rem] mx-2">vs</span>
                      <span style={{ color: "var(--pb)" }}>{m.pairs.far}</span>
                    </div>
                    {m.result && (
                      <div className="mono text-mut text-[13px] mt-2">
                        {m.result.replace(/\s+/g, "  ·  ")}
                      </div>
                    )}
                  </div>
                  <div className="text-right shrink-0">
                    <div className="bignum text-[2.4rem] text-ink/90">{m.rallies}</div>
                    <div className="kicker">RALLIES</div>
                  </div>
                </div>
                <div className="flex items-center gap-2 mt-5">
                  <span className="mono text-[10px] tracking-[0.15em] px-1.5 py-0.5 rounded border border-[var(--ai)]/40 text-[var(--ai)] bg-[var(--ai-soft)]">
                    AI VISION
                  </span>
                  <span className="ml-auto text-dim text-[12px] group-hover:text-mut transition-colors">
                    open match →
                  </span>
                </div>
              </Link>
            ))}
          </div>
        </section>
      )}

      <footer className="mt-16 pb-16 text-dim text-[12px] mono">
        YOLO11 pose · TrackNetV3 · BST-0 (CVPRW&apos;26) · template-matched score OCR — validated
        against ShuttleSet22 human labels, incl. a fully held-out match.
      </footer>
    </main>
  );
}
