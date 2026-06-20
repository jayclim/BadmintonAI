"use client";

import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useIndex, useMatch } from "@/lib/data";
import { useOverlayPref } from "@/lib/overlay";
import type { MatchData, Source } from "@/lib/types";
import { fmtClock } from "@/lib/fmt";
import Overview from "@/components/views/Overview";
import Points from "@/components/views/Points";
import CourtView from "@/components/views/CourtView";
import Patterns from "@/components/views/Patterns";
import Film from "@/components/views/Film";
import Lab from "@/components/views/Lab";
import ThemeToggle from "@/components/ThemeToggle";

const TABS: [string, string][] = [
  ["overview", "Overview"],
  ["points", "Points"],
  ["court", "Court"],
  ["patterns", "Patterns"],
  ["film", "Film room"],
  ["lab", "AI Lab"],
];

export interface ViewProps {
  d: MatchData;
  id: string;
  src: Source;
  goFilm: (title: string, keys: [number, number][]) => void;
  goRally: (set: number, rally: number) => void;
}

export default function Dashboard({ id, src, view }: { id: string; src: Source; view: string }) {
  const { data: d, error } = useMatch(id, src);
  const { data: idx } = useIndex();
  const router = useRouter();
  const pathname = usePathname();
  const sp = useSearchParams();

  const entry = idx?.matches.find((m) => m.id === id);
  const hasBoth = (entry?.sources.length ?? 0) > 1;
  const [overlayOn, setOverlayOn] = useOverlayPref();

  const goFilm = (title: string, keys: [number, number][]) => {
    const k = keys.map(([s, r]) => `${s}-${r}`).join(".");
    router.push(`/m/${id}/${src}/film/?title=${encodeURIComponent(title)}&keys=${k}`);
  };
  const goRally = (set: number, rally: number) => {
    router.push(`/m/${id}/${src}/film/?r=${set}-${rally}`);
  };

  return (
    <main className="max-w-[1400px] mx-auto px-5 pb-20 w-full">
      {/* ── top bar ── */}
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
                href={`/m/${id}/${src}/${v}/`}
                className="px-3 py-1.5 rounded-md text-[13.5px] transition-colors whitespace-nowrap"
                style={{
                  color: on ? "var(--ink)" : "var(--mut)",
                  background: on ? "var(--panel-solid)" : "transparent",
                  border: `1px solid ${on ? "var(--line)" : "transparent"}`,
                  fontWeight: on ? 600 : 400,
                }}
              >
                {v === "lab" ? (
                  <span>
                    {label} <span style={{ color: "var(--ai)" }}>●</span>
                  </span>
                ) : (
                  label
                )}
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
          title="Play AI-annotated clips (pose, shuttle, shot calls, score OCR baked into the video) instead of the raw broadcast — applies to all footage and persists"
        >
          {overlayOn ? "● AI OVERLAY ON" : "○ AI OVERLAY OFF"}
        </button>
        {hasBoth && (
          <div className="flex rounded-md overflow-hidden border border-[var(--line)] mono text-[11px] tracking-[0.12em] shrink-0">
            {(["labels", "ai"] as Source[]).map((s) => {
              const on = src === s;
              return (
                <Link
                  key={s}
                  href={`${pathname.replace(`/${src}/`, `/${s}/`)}${sp.size ? `?${sp.toString()}` : ""}`}
                  className="px-3 py-1.5 transition-colors"
                  style={{
                    background: on ? (s === "ai" ? "var(--ai)" : "var(--ink)") : "transparent",
                    color: on ? "var(--bg)" : "var(--mut)",
                    fontWeight: on ? 600 : 400,
                  }}
                >
                  {s === "labels" ? "GROUND TRUTH" : "AI VISION"}
                </Link>
              );
            })}
          </div>
        )}
        <ThemeToggle />
      </nav>

      {src === "ai" && (
        <div className="mt-4 mb-1 px-4 py-2 rounded-md border border-[var(--ai)]/30 text-[13px] flex items-center gap-3 rise">
          <span className="mono text-[10px] tracking-[0.18em] text-[var(--ai)] font-semibold shrink-0">
            AI VISION
          </span>
          <span className="text-mut">
            Every number on this page was inferred from the broadcast video — player tracking,
            shuttle tracking, hit detection, shot classification and score OCR. No human labels.
          </span>
        </div>
      )}

      {error && (
        <div className="card p-6 mt-6 text-err text-[14px]">
          Failed to load match data: {error}
        </div>
      )}

      {!d && !error && (
        <div className="py-32 text-center text-dim mono text-[13px] animate-pulse">
          LOADING MATCH DATA…
        </div>
      )}

      {d && (
        <>
          <ScoreHeader d={d} />
          {view === "overview" && <Overview d={d} id={id} src={src} goFilm={goFilm} goRally={goRally} />}
          {view === "points" && <Points d={d} id={id} src={src} goFilm={goFilm} goRally={goRally} />}
          {view === "court" && <CourtView d={d} id={id} src={src} goFilm={goFilm} goRally={goRally} />}
          {view === "patterns" && <Patterns d={d} id={id} src={src} goFilm={goFilm} goRally={goRally} />}
          {view === "film" && <Film d={d} id={id} src={src} goFilm={goFilm} goRally={goRally} />}
          {view === "lab" && <Lab d={d} id={id} src={src} goFilm={goFilm} goRally={goRally} />}
        </>
      )}
    </main>
  );
}

function ScoreHeader({ d }: { d: MatchData }) {
  const { meta } = d;
  return (
    <header className="rise flex items-center gap-x-6 gap-y-2 flex-wrap py-5">
      <div className="disp text-[1.6rem] font-semibold leading-none" style={{ color: "var(--pa)" }}>
        {meta.players.A} <span className="text-gold-400" style={{ color: "var(--gold)" }}>🏆</span>
      </div>
      <div className="flex gap-2">
        {meta.sets.map((s) => (
          <span
            key={s.set}
            className="mono px-2.5 py-1 rounded border border-[var(--line)] bg-[var(--panel-solid)] text-[15px] font-semibold"
          >
            {s.a}–{s.b}
          </span>
        ))}
      </div>
      <div className="disp text-[1.6rem] font-semibold leading-none" style={{ color: "var(--pb)" }}>
        {meta.players.B}
      </div>
      <div className="text-dim text-[12.5px] mono ml-auto">
        {meta.tournament} · {meta.round} · {meta.totals.shots.toLocaleString()} shots ·{" "}
        {meta.totals.rallies} rallies · {fmtClock(meta.totals.rallySecs)} rally time
      </div>
    </header>
  );
}
