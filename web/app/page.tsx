import fs from "node:fs";
import path from "node:path";
import Link from "next/link";
import type { IndexData } from "@/lib/types";
import type { DoublesIndex } from "@/lib/doubles";
import ThemeToggle from "@/components/ThemeToggle";

function readIndex(): IndexData {
  const p = path.join(process.cwd(), "public", "data", "index.json");
  return JSON.parse(fs.readFileSync(p, "utf-8"));
}

function readDoublesIndex(): DoublesIndex {
  const p = path.join(process.cwd(), "public", "data", "doubles_index.json");
  if (!fs.existsSync(p)) return { matches: [] };
  return JSON.parse(fs.readFileSync(p, "utf-8"));
}

const STAGES = [
  ["POSE + TRACKS", "0.57 m"],
  ["SHUTTLE", "99.8%"],
  ["HIT DETECTION", "F1 88"],
  ["SHOT CLASSES", "BST-0"],
  ["RALLY SEGMENTATION", "F1 94–98"],
  ["SCORE OCR", "95–97%"],
];

export default function Home() {
  const idx = readIndex();
  const dbl = readDoublesIndex();
  return (
    <main className="max-w-6xl mx-auto px-6 py-14 w-full">
      <header className="rise mb-14">
        <div className="flex items-center justify-between mb-3">
          <div className="kicker">BADMINTON MATCH INTELLIGENCE</div>
          <ThemeToggle />
        </div>
        <h1 className="text-[clamp(3rem,8vw,5.5rem)] font-bold leading-[0.92] tracking-tight">
          COURT<span style={{ color: "var(--ai)" }}>SIDE</span>
        </h1>
        <p className="text-mut max-w-2xl mt-4 text-[15px] leading-relaxed">
          A complete scouting report from broadcast video alone. Computer vision tracks both
          players and the shuttle, detects every hit, classifies every shot, and reads the
          scoreboard — then writes the coach&apos;s notes. Flip any match to{" "}
          <span style={{ color: "var(--ai)" }} className="font-semibold">
            AI VISION
          </span>{" "}
          to see the entire dashboard rebuilt with zero human labels.
        </p>
        <div className="flex flex-wrap gap-2 mt-6">
          {STAGES.map(([s, m], i) => (
            <span
              key={s}
              className="mono text-[10px] tracking-[0.14em] px-2 py-1 rounded border border-[var(--line)] text-dim rise"
              style={{ animationDelay: `${0.15 + i * 0.06}s` }}
            >
              {s} <span style={{ color: "var(--ai)" }}>{m}</span>
            </span>
          ))}
        </div>
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

      <footer className="mt-16 text-dim text-[12px] mono">
        YOLO11 pose · TrackNetV3 · BST-0 (CVPRW&apos;26) · template-matched score OCR — validated
        against ShuttleSet22 human labels, incl. a fully held-out match.
      </footer>
    </main>
  );
}
