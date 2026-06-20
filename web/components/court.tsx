"use client";

/* Court visuals. All geometry is in true metres (court 6.10 × 13.40, net at 6.70),
   scaled by K px/m inside each SVG's viewBox. */

import { useEffect, useMemo, useRef, useState } from "react";
import type { Heat, P, Replay as ReplayT, Side, Stroke } from "@/lib/types";
import { COURT } from "@/lib/types";
import { PCOLOR } from "@/lib/fmt";
import { useChartTip } from "@/components/ui";

const K = 30;
const W = COURT.w, L = COURT.l, NET = COURT.net;
const LINE = "var(--court-line)";
const LINE_SOFT = "var(--court-line-soft)";

/** painted lines of a full court; y grows downward (near court at bottom). */
export function CourtLines({ half = false }: { half?: boolean }) {
  const sw = 0.045 * K;
  const ln = (x1: number, y1: number, x2: number, y2: number, soft = false) => (
    <line
      key={`${x1}-${y1}-${x2}-${y2}`}
      x1={x1 * K} y1={y1 * K} x2={x2 * K} y2={y2 * K}
      stroke={soft ? LINE_SOFT : LINE} strokeWidth={sw}
    />
  );
  const top = half ? NET : 0;
  const lines = [
    // outer boundary
    ln(0, top, W, top), ln(0, L, W, L), ln(0, top, 0, L), ln(W, top, W, L),
    // singles sidelines
    ln(0.46, top, 0.46, L, true), ln(W - 0.46, top, W - 0.46, L, true),
    // short service lines + doubles long service near baseline
    ln(0, NET + 1.98, W, NET + 1.98, true),
    ln(0, L - 0.76, W, L - 0.76, true),
    // centre line (short service line → baseline)
    ln(W / 2, NET + 1.98, W / 2, L, true),
  ];
  if (!half)
    lines.push(
      ln(0, NET - 1.98, W, NET - 1.98, true),
      ln(0, 0.76, W, 0.76, true),
      ln(W / 2, 0, W / 2, NET - 1.98, true),
    );
  return (
    <g>
      <rect
        x={0} y={top * K} width={W * K} height={(L - top) * K}
        fill="var(--court-fill)" rx={2}
      />
      {lines}
      {/* net */}
      <line
        x1={-0.25 * K} y1={NET * K} x2={(W + 0.25) * K} y2={NET * K}
        stroke="var(--court-net)" strokeWidth={sw * 1.4} strokeDasharray={`${0.12 * K} ${0.1 * K}`}
      />
    </g>
  );
}

function courtSvgProps(half: boolean, pad = 1.3) {
  const top = half ? NET - 0.35 : 0;
  return {
    viewBox: `${-pad * K} ${(top - pad) * K} ${(W + 2 * pad) * K} ${(L - top + 2 * pad) * K}`,
  };
}

/* ── placement map ──────────────────────────────────────────────────────── */

export interface Mark {
  x: number;
  y: number;
  kind: "rally" | "winner" | "error";
  label: string;
  set: number;
  rally: number;
}

export function PlacementMap({
  marks,
  onPick,
}: {
  marks: Mark[];
  onPick?: (set: number, rally: number) => void;
}) {
  const { ref, on, tipEl } = useChartTip();
  const tipFor = (m: Mark) => (
    <span>
      <span style={{ color: m.kind === "winner" ? "var(--win)" : m.kind === "error" ? "var(--err)" : "var(--mut)" }}>
        {m.kind === "winner" ? "★ winner" : m.kind === "error" ? "✕ error" : "●"}
      </span>{" "}
      {m.label} · set {m.set} rally {m.rally}
      <span className="text-dim"> · click to watch</span>
    </span>
  );
  return (
    <div className="relative" ref={ref}>
      <svg {...courtSvgProps(false)} className="w-full">
        <CourtLines />
        {marks
          .filter((m) => m.kind === "rally")
          .map((m, i) => (
            <g
              key={i}
              transform={`translate(${m.x * K},${m.y * K})`}
              onClick={() => onPick?.(m.set, m.rally)}
              className="cursor-pointer"
              {...on(tipFor(m))}
            >
              <circle r={6} fill="transparent" />
              <circle r={2.6} fill="var(--court-dot)" />
            </g>
          ))}
        {marks
          .filter((m) => m.kind !== "rally")
          .map((m, i) => (
            <g
              key={`e${i}`}
              transform={`translate(${m.x * K},${m.y * K})`}
              onClick={() => onPick?.(m.set, m.rally)}
              className="cursor-pointer"
              {...on(tipFor(m))}
            >
              <circle r={9} fill="transparent" />
              {m.kind === "winner" ? (
                <path
                  d={star(7.5)}
                  fill="var(--win)" stroke="var(--contact-ink)" strokeWidth={0.8}
                />
              ) : (
                <path
                  d="M-4.4,-4.4 L4.4,4.4 M-4.4,4.4 L4.4,-4.4"
                  stroke="var(--err)" strokeWidth={2.6} strokeLinecap="round"
                />
              )}
            </g>
          ))}
        <text x={(W / 2) * K} y={(L + 1.0) * K} textAnchor="middle"
          fontSize={11} fill="var(--dim)" className="mono">
          HITTING FROM HERE ↑
        </text>
      </svg>
      {tipEl}
    </div>
  );
}

function star(r: number) {
  const pts: string[] = [];
  for (let i = 0; i < 10; i++) {
    const rr = i % 2 ? r * 0.45 : r;
    const a = (Math.PI / 5) * i - Math.PI / 2;
    pts.push(`${rr * Math.cos(a)},${rr * Math.sin(a)}`);
  }
  return `M${pts.join("L")}Z`;
}

/* ── movement heatmap (half court, player normalized to near half) ─────── */

export function HeatMap({ heat, color }: { heat: Heat; color: string }) {
  const max = Math.max(...heat.cells.map((c) => c[2]), 1);
  const total = heat.cells.reduce((s, c) => s + c[2], 0) || 1;
  const cw = (heat.x1 / heat.nx) * K;
  const ch = (heat.y1 / heat.ny) * K;
  const { ref, on, tipEl } = useChartTip();
  return (
    <div className="relative" ref={ref}>
      <svg viewBox={`${-0.7 * K} ${-0.7 * K} ${(W + 1.4) * K} ${(NET + 1.6) * K}`} className="w-full">
        {/* near half drawn with net at TOP: mirror y so y=NET maps to top */}
        <g transform={`translate(0 ${NET * K}) scale(1 -1)`}>
          {heat.cells.map(([i, j, n]) => (
            <rect
              key={`${i}-${j}`}
              x={i * cw} y={j * ch} width={cw + 0.5} height={ch + 0.5}
              fill={color}
              opacity={0.06 + 0.78 * Math.pow(n / max, 0.6)}
              {...on(
                <span>
                  <b className="mono">{((100 * n) / total).toFixed(1)}%</b> of tracked time here
                </span>,
              )}
            />
          ))}
          <g transform={`scale(1 -1) translate(0 ${-NET * K})`}>{/* lines drawn unmirrored */}</g>
        </g>
        <HalfLines />
      </svg>
      {tipEl}
    </div>
  );
}

function HalfLines() {
  const sw = 0.045 * K;
  return (
    <g fill="none" stroke={LINE_SOFT} strokeWidth={sw}>
      <rect x={0} y={0} width={W * K} height={NET * K} stroke={LINE} />
      <line x1={0.46 * K} y1={0} x2={0.46 * K} y2={NET * K} />
      <line x1={(W - 0.46) * K} y1={0} x2={(W - 0.46) * K} y2={NET * K} />
      <line x1={0} y1={(NET - 1.98) * K} x2={W * K} y2={(NET - 1.98) * K} />
      <line x1={(W / 2) * K} y1={0} x2={(W / 2) * K} y2={(NET - 1.98) * K} />
      <line
        x1={-0.2 * K} y1={0} x2={(W + 0.2) * K} y2={0}
        stroke="var(--court-net)" strokeWidth={sw * 1.4}
        strokeDasharray={`${0.12 * K} ${0.1 * K}`}
      />
      <text x={(W / 2) * K} y={-0.25 * K} textAnchor="middle" fontSize={10}
        fill="var(--dim)" stroke="none" className="mono">NET</text>
    </g>
  );
}

/* ── static rally map: numbered contacts + arcs + landing star ─────────── */

export function RallyMap({
  strokes,
  land,
  replay,
  smap,
}: {
  strokes: Stroke[];
  land: { x: number; y: number } | null;
  replay: ReplayT | null;
  smap: Record<P, Side | null>;
}) {
  const sideOf = (s: Side): P => (smap.A === s ? "A" : "B");
  return (
    <svg {...courtSvgProps(false, 1.0)} className="w-full">
      <CourtLines />
      {/* movement trails from tracks */}
      {replay &&
        (["near", "far"] as Side[]).map((side) => {
          const pts = replay[side];
          if (!pts.length) return null;
          const p = sideOf(side);
          return (
            <polyline
              key={side}
              points={pts.map(([, x, y]) => `${x * K},${y * K}`).join(" ")}
              fill="none" stroke={PCOLOR[p]} strokeWidth={1.3} opacity={0.35}
            />
          );
        })}
      {/* stroke arcs */}
      {strokes.map((s) =>
        s.hx != null && s.lx != null ? (
          <line
            key={`a${s.br}`}
            x1={s.hx * K} y1={s.hy! * K} x2={s.lx * K} y2={s.ly! * K}
            stroke="var(--arc)" strokeWidth={1} strokeDasharray="3 3"
          />
        ) : null,
      )}
      {/* numbered contacts */}
      {strokes.map((s) =>
        s.hx != null ? (
          <g key={`c${s.br}`} transform={`translate(${s.hx * K},${s.hy! * K})`}>
            <circle r={7} fill={PCOLOR[s.p]} stroke="var(--contact-ink)" strokeWidth={0.8} />
            <text y={3} textAnchor="middle" fontSize={8} fontWeight={700} fill="var(--contact-ink)">
              {s.br}
            </text>
          </g>
        ) : null,
      )}
      {land && (
        <path
          d={star(10)}
          transform={`translate(${land.x * K},${land.y * K})`}
          fill="var(--gold)" stroke="var(--contact-ink)" strokeWidth={1}
        />
      )}
    </svg>
  );
}

/* ── animated 2D replay ─────────────────────────────────────────────────── */

export function Replay2D({
  rep,
  ai,
  onFrame,
}: {
  rep: ReplayT;
  ai: boolean;
  onFrame?: (f: number) => void;
}) {
  const [frame, setFrame] = useState(rep.f0);
  const [playing, setPlaying] = useState(true);
  const [speed, setSpeed] = useState(1);
  const raf = useRef<number>(0);
  const tPrev = useRef<number>(0);
  const fRef = useRef<number>(rep.f0);

  const byFrame = useMemo(() => {
    const m: Record<Side, Map<number, [number, number]>> = {
      near: new Map(), far: new Map(),
    };
    for (const s of ["near", "far"] as Side[])
      for (const [f, x, y] of rep[s]) m[s].set(f, [x, y]);
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
      const fi = Math.floor(fRef.current);
      setFrame(fi);
      onFrame?.(fi);
      raf.current = requestAnimationFrame(step);
    };
    raf.current = requestAnimationFrame(step);
    return () => {
      cancelAnimationFrame(raf.current);
      tPrev.current = 0;
    };
  }, [playing, speed, rep, onFrame]);

  const pos = (side: Side): [number, number] | null => {
    for (let f = frame; f >= frame - 8; f--) {
      const p = byFrame[side].get(f);
      if (p) return p;
    }
    return null;
  };
  const trail = (side: Side) =>
    rep[side].filter(([f]) => f <= frame && f >= frame - 40);

  const sideOf = (s: Side): P => (rep.smap.A === s ? "A" : "B");
  const curHits = rep.hits.filter((h) => frame >= h.f && frame < h.f + 18);
  const done = rep.hits.filter((h) => h.f <= frame).length;

  return (
    <div>
      <svg {...courtSvgProps(false, 1.0)} className="w-full">
        <CourtLines />
        {(["near", "far"] as Side[]).map((side) => {
          const p = sideOf(side);
          const cur = pos(side);
          return (
            <g key={side}>
              <polyline
                points={trail(side).map(([, x, y]) => `${x * K},${y * K}`).join(" ")}
                fill="none" stroke={PCOLOR[p]} strokeWidth={2} opacity={0.4} strokeLinecap="round"
              />
              {cur && (
                <g transform={`translate(${cur[0] * K},${cur[1] * K})`}>
                  <circle r={8} fill={PCOLOR[p]} stroke="var(--contact-ink)" strokeWidth={1.2} />
                  <text y={3.5} textAnchor="middle" fontSize={9} fontWeight={700} fill="var(--contact-ink)">
                    {p}
                  </text>
                </g>
              )}
            </g>
          );
        })}
        {curHits.map((h) => {
          const side = rep.smap.A === null ? null : (h.p === "A" ? rep.smap.A : rep.smap.B);
          const cur = side ? pos(side) : null;
          if (!cur) return null;
          const age = (frame - h.f) / 18;
          return (
            <g key={h.f} transform={`translate(${cur[0] * K},${cur[1] * K})`}>
              <circle
                r={10 + age * 16}
                fill="none"
                stroke={ai ? "var(--ai)" : "var(--hit-ring)"}
                strokeWidth={2.2 * (1 - age)}
                opacity={1 - age}
              />
              <text
                y={-16} textAnchor="middle" fontSize={10.5} fontWeight={600}
                fill={ai ? "var(--ai)" : "var(--ink)"} className="mono" opacity={1 - age * 0.6}
              >
                {h.shot}
                {ai && h.conf != null ? ` ${(h.conf * 100).toFixed(0)}%` : ""}
              </text>
            </g>
          );
        })}
        {rep.land && frame > rep.f1 - 30 && (
          <path
            d={star(10)}
            transform={`translate(${rep.land.x * K},${rep.land.y * K})`}
            fill="var(--gold)" stroke="var(--contact-ink)" strokeWidth={1}
          />
        )}
      </svg>

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
          min={rep.f0} max={rep.f1} value={frame}
          onChange={(e) => {
            setPlaying(false);
            fRef.current = Number(e.target.value);
            setFrame(fRef.current);
            onFrame?.(fRef.current);
          }}
          className="flex-1 accent-[var(--ai)] h-1"
        />
        <span className="mono text-[10.5px] text-dim w-24 text-right">
          {done}/{rep.hits.length} shots
        </span>
      </div>
    </div>
  );
}
