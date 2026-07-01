"use client";

/* 4-player animated 2D replay for doubles, reusing the painted court from
   components/court.tsx (CourtLines). All geometry is true metres scaled by K px/m,
   identical to court.tsx so the lines and dots register. Front/back is derived per
   frame from geometry (closest-to-net = front), exactly as roles.py does, so it stays
   correct through slot swaps. Side hue = near/far; the FRONT player is drawn solid,
   the BACK player as a ring. */

import { useEffect, useMemo, useRef, useState } from "react";
import { CourtLines } from "@/components/court";
import { COURT } from "@/lib/types";
import { ytEmbed } from "@/lib/fmt";
import { useOverlayPref } from "@/lib/overlay";
import {
  type DoublesRally,
  type DoublesReplay,
  type DSide,
  type DSlot,
  type Formation,
  SLOTS_OF,
  TEAM_COLOR,
} from "@/lib/doubles";

/** Rally footage honouring the global AI-overlay preference: the pre-rendered annotated
    clip (4-player pose + names/roles + formation + score OCR baked in) when ON and
    rendered, else the raw YouTube broadcast. The doubles analogue of components/RallyVideo. */
export function DoublesVideo({ row, youtubeId }: { row: DoublesRally; youtubeId: string | null }) {
  const [overlayOn] = useOverlayPref();
  const useClip = overlayOn && !!row.clip;
  return (
    <div>
      <div className="aspect-video rounded-md overflow-hidden border border-[var(--line)] bg-black">
        {useClip ? (
          <video key={row.clip!} src={row.clip!} className="w-full h-full" controls autoPlay muted playsInline />
        ) : youtubeId ? (
          <iframe
            key={`${row.rally}-yt`}
            src={ytEmbed(youtubeId, row.t0, row.t1)}
            className="w-full h-full"
            allow="autoplay; encrypted-media; picture-in-picture"
            allowFullScreen
            title="rally clip"
          />
        ) : (
          <div className="w-full h-full flex items-center justify-center text-dim mono text-[12px]">
            NO FOOTAGE
          </div>
        )}
      </div>
      <div className="mt-1.5">
        {useClip ? (
          <span className="mono text-[10px] tracking-[0.14em]" style={{ color: "var(--ai)" }}>
            ● AI-ANNOTATED — 4-player pose · names · roles · formation · machine-read score
          </span>
        ) : (
          <span className="mono text-[10px] tracking-[0.14em] text-dim">
            RAW BROADCAST{overlayOn && !row.clip ? " — no annotated clip for this rally" : ""}
          </span>
        )}
      </div>
    </div>
  );
}

const K = 30;
const W = COURT.w, L = COURT.l, NET = COURT.net;
const PAD = 1.0;

const svgProps = {
  viewBox: `${-PAD * K} ${-PAD * K} ${(W + 2 * PAD) * K} ${(L + 2 * PAD) * K}`,
};

function initials(name: string | undefined, fallback: string) {
  if (!name) return fallback;
  return name.split(/[\s/]+/).filter(Boolean).map((w) => w[0]).join("").slice(0, 2).toUpperCase();
}

/** current formation per side at `frame`, from the run-length segments */
function formAt(segs: [number, number, Formation][], frame: number): Formation | null {
  for (const [a, b, f] of segs) if (frame >= a && frame <= b) return f;
  return null;
}

export function DoublesReplay2D({ rep }: { rep: DoublesReplay }) {
  const [frame, setFrame] = useState(rep.f0);
  const [playing, setPlaying] = useState(true);
  const [speed, setSpeed] = useState(1);
  const raf = useRef<number>(0);
  const tPrev = useRef<number>(0);
  const fRef = useRef<number>(rep.f0);

  const byFrame = useMemo(() => {
    const m = {} as Record<DSlot, Map<number, [number, number]>>;
    for (const slot of Object.keys(rep.tracks) as DSlot[]) {
      const mp = new Map<number, [number, number]>();
      for (const [f, x, y] of rep.tracks[slot]) mp.set(f, [x, y]);
      m[slot] = mp;
    }
    return m;
  }, [rep]);

  useEffect(() => {
    fRef.current = rep.f0;
    setFrame(rep.f0);
    setPlaying(true);
  }, [rep]);

  useEffect(() => {
    if (!playing) return;
    const step = (t: number) => {
      if (!tPrev.current) tPrev.current = t;
      const df = ((t - tPrev.current) / 1000) * rep.fps * speed;
      tPrev.current = t;
      fRef.current += df;
      if (fRef.current >= rep.f1) fRef.current = rep.f0;
      setFrame(Math.floor(fRef.current));
      raf.current = requestAnimationFrame(step);
    };
    raf.current = requestAnimationFrame(step);
    return () => {
      cancelAnimationFrame(raf.current);
      tPrev.current = 0;
    };
  }, [playing, speed, rep]);

  const pos = (slot: DSlot): [number, number] | null => {
    for (let f = frame; f >= frame - 10; f--) {
      const p = byFrame[slot]?.get(f);
      if (p) return p;
    }
    return null;
  };
  const trail = (slot: DSlot) => rep.tracks[slot].filter(([f]) => f <= frame && f >= frame - 40);

  // which slot of each side is currently the front (closest to net)
  const frontOf = (side: DSide): DSlot | null => {
    const [s0, s1] = SLOTS_OF[side];
    const p0 = pos(s0), p1 = pos(s1);
    if (!p0 || !p1) return p0 ? s0 : p1 ? s1 : null;
    return Math.abs(p0[1] - NET) <= Math.abs(p1[1] - NET) ? s0 : s1;
  };

  // colour each side by the TEAM occupying it this rally (so a team keeps its hue across
  // set end-swaps); fall back to fixed near/far hues for older replays without pair tags
  const sideColor = (side: DSide): string =>
    TEAM_COLOR[(side === "near" ? rep.nearPair : rep.farPair) ?? (side === "near" ? "A" : "B")];

  return (
    <div>
      <svg {...svgProps} className="w-full">
        <CourtLines />
        {(["near", "far"] as DSide[]).map((side) => {
          const color = sideColor(side);
          const front = frontOf(side);
          return SLOTS_OF[side].map((slot, i) => {
            const cur = pos(slot);
            if (!cur) return null;
            const isFront = slot === front;
            const tr = trail(slot);
            const label = initials(rep.names?.[slot], `${side[0].toUpperCase()}${i + 1}`);
            return (
              <g key={slot}>
                <polyline
                  points={tr.map(([, x, y]) => `${x * K},${y * K}`).join(" ")}
                  fill="none"
                  stroke={color}
                  strokeWidth={1.8}
                  opacity={0.32}
                  strokeLinecap="round"
                />
                <g transform={`translate(${cur[0] * K},${cur[1] * K})`}>
                  <circle
                    r={isFront ? 9 : 8}
                    fill={isFront ? color : "var(--panel-solid)"}
                    stroke={color}
                    strokeWidth={isFront ? 1.2 : 2.4}
                  />
                  <text
                    y={3.2}
                    textAnchor="middle"
                    fontSize={8.5}
                    fontWeight={700}
                    fill={isFront ? "var(--contact-ink)" : color}
                  >
                    {label}
                  </text>
                  {isFront && (
                    <text y={-12} textAnchor="middle" fontSize={7} fill={color} className="mono">
                      NET
                    </text>
                  )}
                </g>
              </g>
            );
          });
        })}
      </svg>

      {/* formation banner */}
      <div className="flex items-center gap-2 mt-2 mb-1">
        {(["far", "near"] as DSide[]).map((side) => {
          const f = formAt(rep.form[side], frame);
          return (
            <div
              key={side}
              className="flex-1 flex items-center justify-between px-3 py-1.5 rounded-md border"
              style={{ borderColor: "var(--line)" }}
            >
              <span className="mono text-[10px] tracking-[0.14em] truncate max-w-[60%]"
                style={{ color: sideColor(side) }}
                title={rep.pairs?.[side]}>
                {rep.pairs?.[side]?.split(" / ")[0]?.toUpperCase() ?? side.toUpperCase()}
              </span>
              <span
                className="mono text-[11px] tracking-[0.1em] font-semibold"
                style={{ color: f === "attack" ? "var(--win)" : "var(--mut)" }}
              >
                {f ? f.toUpperCase() : "—"}
              </span>
            </div>
          );
        })}
      </div>

      <Controls
        rep={rep}
        frame={frame}
        playing={playing}
        speed={speed}
        setPlaying={setPlaying}
        setSpeed={setSpeed}
        onScrub={(f) => {
          setPlaying(false);
          fRef.current = f;
          setFrame(f);
        }}
      />
    </div>
  );
}

function Controls({
  rep,
  frame,
  playing,
  speed,
  setPlaying,
  setSpeed,
  onScrub,
}: {
  rep: DoublesReplay;
  frame: number;
  playing: boolean;
  speed: number;
  setPlaying: (b: boolean) => void;
  setSpeed: (n: number) => void;
  onScrub: (f: number) => void;
}) {
  const pct = Math.round((100 * (frame - rep.f0)) / Math.max(1, rep.f1 - rep.f0));
  return (
    <div className="flex items-center gap-2 mt-2">
      <button
        onClick={() => setPlaying(!playing)}
        className="mono text-[11px] px-2.5 py-1 rounded border border-[var(--line)] text-ink hover:border-[var(--mut)]"
      >
        {playing ? "❚❚" : "▶"}
      </button>
      {[0.5, 1, 2].map((s) => (
        <button
          key={s}
          onClick={() => setSpeed(s)}
          className="mono text-[10.5px] px-2 py-1 rounded border"
          style={{
            borderColor: speed === s ? "var(--mut)" : "var(--line)",
            color: speed === s ? "var(--ink)" : "var(--dim)",
          }}
        >
          {s}×
        </button>
      ))}
      <input
        type="range"
        min={rep.f0}
        max={rep.f1}
        value={frame}
        onChange={(e) => onScrub(Number(e.target.value))}
        className="flex-1 accent-[var(--ai)] h-1"
      />
      <span className="mono text-[10.5px] text-dim w-10 text-right">{pct}%</span>
    </div>
  );
}

/** Horizontal attack/defence timeline for one side over a rally. With `marks`, each
    internal segment boundary (a debounced ROTATION event — attack⇄defence flip) is drawn
    as a tick over the bar; `ticks` (frame numbers, e.g. this side's shuttle contacts)
    are drawn as small ticks under it. */
export function FormationTimeline({
  segs,
  f0,
  f1,
  color,
  marks = false,
  ticks,
}: {
  segs: [number, number, Formation][];
  f0: number;
  f1: number;
  color: string;
  marks?: boolean;
  ticks?: number[];
}) {
  const span = Math.max(1, f1 - f0);
  // internal boundaries = rotation events (start frame of every segment after the first)
  const boundaries = segs.slice(1).map(([a]) => a);
  return (
    <div className="relative">
      <div className="h-2.5 w-full rounded-full overflow-hidden flex bg-[var(--line)]">
        {segs.map(([a, b, f], i) => (
          <div
            key={i}
            title={f}
            style={{
              width: `${(100 * (b - a + 1)) / span}%`,
              background: f === "attack" ? color : "var(--line-soft)",
              opacity: f === "attack" ? 0.9 : 1,
            }}
          />
        ))}
      </div>
      {marks &&
        boundaries.map((bf, i) => (
          <div
            key={i}
            title={`rotation @ ${(((bf - f0) / span) * 100).toFixed(0)}%`}
            className="absolute -top-0.5 h-3.5 w-px"
            style={{
              left: `${(100 * (bf - f0)) / span}%`,
              background: "var(--ink)",
              opacity: 0.55,
            }}
          />
        ))}
      {ticks?.map((tf, i) => (
        <div
          key={`c${i}`}
          title="shuttle contact"
          className="absolute top-full h-1.5 w-px"
          style={{
            left: `${(100 * (tf - f0)) / span}%`,
            background: color,
            opacity: 0.8,
          }}
        />
      ))}
    </div>
  );
}
