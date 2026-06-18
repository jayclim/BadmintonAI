"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useDoublesMatch } from "@/lib/doubles";
import type { DoublesMatch } from "@/lib/doubles";
import { fmtClock } from "@/lib/fmt";
import { useOverlayPref } from "@/lib/overlay";
import { AiTag } from "@/components/ui";
import ThemeToggle from "@/components/ThemeToggle";
import DoublesOverview from "@/components/doubles/Overview";
import DoublesPoints from "@/components/doubles/Points";
import DoublesMovement from "@/components/doubles/Movement";
import DoublesPatterns from "@/components/doubles/Patterns";
import DoublesLab from "@/components/doubles/Lab";
import DoublesFilm from "@/components/doubles/Film";

const TABS: [string, string][] = [
  ["overview", "Overview"],
  ["points", "Points"],
  ["court", "Court"],
  ["patterns", "Patterns"],
  ["film", "Film room"],
  ["lab", "AI Lab"],
];

export interface DoublesViewProps {
  d: DoublesMatch;
  id: string;
  goRally: (rally: number) => void;
}

export default function DoublesDashboard({ id, view }: { id: string; view: string }) {
  const { data: d, error } = useDoublesMatch(id);
  const router = useRouter();
  const [overlayOn, setOverlayOn] = useOverlayPref();
  const goRally = (rally: number) => router.push(`/d/${id}/film/?r=${rally}`);

  return (
    <main className="max-w-[1400px] mx-auto px-5 pb-20 w-full">
      <nav className="flex items-center gap-4 py-3.5 border-b border-[var(--line-soft)] sticky top-0 z-40 bg-[var(--bg)]/90 backdrop-blur-md -mx-5 px-5 overflow-x-auto [scrollbar-width:none]">
        <Link href="/" className="disp font-bold text-[1.25rem] tracking-tight shrink-0">
          COURT<span style={{ color: "var(--ai)" }}>SIDE</span>
        </Link>
        <div className="flex gap-0.5 shrink-0">
          {TABS.map(([v, label]) => {
            const on = view === v;
            return (
              <Link
                key={v}
                href={`/d/${id}/${v}/`}
                className="px-3 py-1.5 rounded-md text-[13.5px] transition-colors whitespace-nowrap"
                style={{
                  color: on ? "var(--ink)" : "var(--mut)",
                  background: on ? "var(--panel-solid)" : "transparent",
                  border: `1px solid ${on ? "var(--line)" : "transparent"}`,
                  fontWeight: on ? 600 : 400,
                }}
              >
                {label}
              </Link>
            );
          })}
        </div>
        <button
          onClick={() => setOverlayOn(!overlayOn)}
          className="ml-auto mono text-[10.5px] tracking-[0.12em] px-2.5 py-1.5 rounded-md border transition-colors shrink-0"
          style={{
            borderColor: overlayOn ? "var(--ai)" : "var(--line)",
            color: overlayOn ? "var(--ai)" : "var(--dim)",
            background: overlayOn ? "var(--ai-soft)" : "transparent",
          }}
          title="Play AI-annotated clips (4-player pose, names, roles, formation, score OCR baked into the video) instead of the raw broadcast — applies to all footage and persists"
        >
          {overlayOn ? "● AI OVERLAY ON" : "○ AI OVERLAY OFF"}
        </button>
        <span className="mono text-[10px] tracking-[0.16em] px-2 py-1 rounded border border-[var(--line)] text-dim shrink-0">
          DOUBLES
        </span>
        <ThemeToggle />
      </nav>

      <div className="mt-4 mb-1 px-4 py-2 rounded-md border border-[var(--ai)]/30 text-[13px] flex items-center gap-3 rise">
        <AiTag text="AI VISION" />
        <span className="text-mut">
          Formation, rotations and front-court roles inferred from 4-player tracking across the
          full broadcast — no human labels. Sets are read from the scoreboard; stats follow each
          team through the end-swaps.
        </span>
      </div>

      {error && (
        <div className="card p-6 mt-6 text-err text-[14px]">Failed to load match data: {error}</div>
      )}
      {!d && !error && (
        <div className="py-32 text-center text-dim mono text-[13px] animate-pulse">
          LOADING MATCH DATA…
        </div>
      )}

      {d && (
        <>
          <ScoreHeader d={d} />
          {view === "overview" && <DoublesOverview d={d} id={id} goRally={goRally} />}
          {view === "points" && <DoublesPoints d={d} id={id} goRally={goRally} />}
          {view === "court" && <DoublesMovement d={d} id={id} goRally={goRally} />}
          {view === "patterns" && <DoublesPatterns d={d} id={id} goRally={goRally} />}
          {view === "film" && <DoublesFilm d={d} id={id} goRally={goRally} />}
          {view === "lab" && <DoublesLab d={d} id={id} goRally={goRally} />}
        </>
      )}
    </main>
  );
}

function ScoreHeader({ d }: { d: DoublesMatch }) {
  const { meta } = d;
  return (
    <header className="rise flex items-center gap-x-6 gap-y-2 flex-wrap py-5">
      <div className="disp text-[1.5rem] font-semibold leading-none" style={{ color: "var(--pa)" }}>
        {meta.teams.A}
      </div>
      <span className="text-dim text-[1.1rem]">vs</span>
      <div className="disp text-[1.5rem] font-semibold leading-none" style={{ color: "var(--pb)" }}>
        {meta.teams.B}
      </div>
      {meta.result && (
        <span className="mono px-2.5 py-1 rounded border border-[var(--line)] bg-[var(--panel-solid)] text-[14px] font-semibold">
          {meta.result.replace(/\s+/g, "  ·  ")}
        </span>
      )}
      <div className="text-dim text-[12.5px] mono ml-auto">
        {meta.tournament} · {meta.round} · {meta.nSets > 1 ? `${meta.nSets} sets · ` : ""}
        {meta.totals.rallies} rallies tracked · {fmtClock(meta.totals.rallySecs)} rally time
      </div>
    </header>
  );
}
