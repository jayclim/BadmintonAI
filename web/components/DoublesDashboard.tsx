"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useDoublesMatch } from "@/lib/doubles";
import type { DoublesMatch } from "@/lib/doubles";
import { fmtClock } from "@/lib/fmt";
import { AiTag } from "@/components/ui";
import ThemeToggle from "@/components/ThemeToggle";
import DoublesOverview from "@/components/doubles/Overview";
import DoublesFilm from "@/components/doubles/Film";

const TABS: [string, string][] = [
  ["overview", "Overview"],
  ["film", "Film room"],
];

export interface DoublesViewProps {
  d: DoublesMatch;
  id: string;
  goRally: (rally: number) => void;
}

export default function DoublesDashboard({ id, view }: { id: string; view: string }) {
  const { data: d, error } = useDoublesMatch(id);
  const router = useRouter();
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
        <span className="ml-auto mono text-[10px] tracking-[0.16em] px-2 py-1 rounded border border-[var(--line)] text-dim shrink-0">
          DOUBLES
        </span>
        <ThemeToggle />
      </nav>

      <div className="mt-4 mb-1 px-4 py-2 rounded-md border border-[var(--ai)]/30 text-[13px] flex items-center gap-3 rise">
        <AiTag text="AI VISION" />
        <span className="text-mut">
          Formation, rotations and front-court roles inferred from 4-player tracking on the
          broadcast — no human labels. Numbers cover the tracked rally span, not the full match.
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
          {view === "film" && <DoublesFilm d={d} id={id} goRally={goRally} />}
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
        {meta.pairs.near}
      </div>
      <span className="text-dim text-[1.1rem]">vs</span>
      <div className="disp text-[1.5rem] font-semibold leading-none" style={{ color: "var(--pb)" }}>
        {meta.pairs.far}
      </div>
      {meta.result && (
        <span className="mono px-2.5 py-1 rounded border border-[var(--line)] bg-[var(--panel-solid)] text-[14px] font-semibold">
          {meta.result.replace(/\s+/g, "  ·  ")}
        </span>
      )}
      <div className="text-dim text-[12.5px] mono ml-auto">
        {meta.tournament} · {meta.round} · {meta.totals.rallies} rallies tracked ·{" "}
        {fmtClock(meta.totals.rallySecs)} rally time
      </div>
    </header>
  );
}
