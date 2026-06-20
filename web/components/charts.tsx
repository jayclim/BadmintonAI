"use client";

/* Bespoke SVG charts — no chart library. */

import { useMemo, useState } from "react";
import type { P, Rally } from "@/lib/types";
import { PCOLOR } from "@/lib/fmt";
import { Tip, useChartTip } from "@/components/ui";

/* ── score worm ─────────────────────────────────────────────────────────── */

export function Worm({
  rallies,
  names,
  setNo,
  onPick,
}: {
  rallies: Rally[];
  names: Record<P, string>;
  setNo: number;
  onPick: (set: number, rally: number) => void;
}) {
  const W = 460, H = 230, padX = 42, padY = 26;
  const d = rallies.filter((r) => r.set === setNo && r.winner);
  const [tip, setTip] = useState<{ x: number; y: number; r: Rally } | null>(null);

  const { pts, maxLead, maxPt } = useMemo(() => {
    const pts = d.map((r) => ({ r, pt: r.a + r.b, lead: r.a - r.b }));
    return {
      pts,
      maxLead: Math.max(4, ...pts.map((p) => Math.abs(p.lead))),
      maxPt: Math.max(1, ...pts.map((p) => p.pt)),
    };
  }, [d]);

  const x = (pt: number) => padX + ((W - 2 * padX) * pt) / maxPt;
  const y = (lead: number) => H / 2 - ((H / 2 - padY) * lead) / maxLead;

  let path = "";
  let prev = 0;
  pts.forEach((p, i) => {
    if (i === 0) path = `M${x(0)},${y(0)} L${x(p.pt)},${y(prev)} L${x(p.pt)},${y(p.lead)}`;
    else path += ` L${x(p.pt)},${y(prev)} L${x(p.pt)},${y(p.lead)}`;
    prev = p.lead;
  });

  const final = d[d.length - 1];

  return (
    <div className="relative">
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full">
        <line x1={padX} y1={H / 2} x2={W - padX + 14} y2={H / 2}
          stroke="var(--line)" strokeDasharray="4 4" />
        <text x={padX - 6} y={padY + 4} textAnchor="end" fontSize={10}
          fill={PCOLOR.A} className="mono">{shortName(names.A)} ↑</text>
        <text x={padX - 6} y={H - padY + 2} textAnchor="end" fontSize={10}
          fill={PCOLOR.B} className="mono">{shortName(names.B)} ↓</text>
        <path d={path} fill="none" stroke="var(--worm-line)" strokeWidth={1.8}
          className="worm-path" style={{ ["--dash" as string]: 1600 }} />
        {pts.map((p, i) => (
          <g
            key={i}
            transform={`translate(${x(p.pt)},${y(p.lead)})`}
            className="cursor-pointer"
            onMouseEnter={() => setTip({ x: (x(p.pt) / W) * 100, y: (y(p.lead) / H) * 100, r: p.r })}
            onMouseLeave={() => setTip(null)}
            onClick={() => onPick(p.r.set, p.r.rally)}
          >
            {/* generous invisible hit area for hover/click */}
            <circle r={9} fill="transparent" />
            {/* inner g animates: CSS transform must not override the translate above */}
            <g className="worm-dot" style={{ animationDelay: `${0.2 + (i / pts.length) * 1.0}s` }}>
              {p.r.clutch ? (
                <rect x={-4.6} y={-4.6} width={9.2} height={9.2} transform="rotate(45)"
                  fill={PCOLOR[p.r.winner!]} stroke="var(--contact-ink)" strokeWidth={0.7} />
              ) : (
                <circle r={4.4} fill={PCOLOR[p.r.winner!]} stroke="var(--contact-ink)" strokeWidth={0.7} />
              )}
            </g>
          </g>
        ))}
        {final && (
          <text x={Math.min(x(final.a + final.b) + 8, W - 38)} y={y(final.a - final.b) + 4}
            fontSize={13} fontWeight={700} fill="var(--ink)" className="mono">
            {final.a}–{final.b}
          </text>
        )}
        <text x={W / 2} y={H - 4} textAnchor="middle" fontSize={10} fill="var(--dim)" className="mono">
          SET {setNo} — POINTS PLAYED
        </text>
      </svg>
      {tip && (
        <div className="absolute z-20 pointer-events-none"
          style={{ left: `${tip.x}%`, top: `${tip.y}%` }}>
          <Tip x={0} y={0}>
            <div className="mono font-semibold mb-0.5">
              {tip.r.a}–{tip.r.b}
              {tip.r.clutch && <span className="text-warn"> ◆ clutch</span>}
            </div>
            <div>
              <span style={{ color: PCOLOR[tip.r.winner!] }}>{names[tip.r.winner!]}</span>
              {" — "}{tip.r.endPhrase}
            </div>
            <div className="text-dim mt-0.5">
              {tip.r.shots} shots · {tip.r.durS}s · click to watch
            </div>
          </Tip>
        </div>
      )}
    </div>
  );
}

const shortName = (n: string) => n.split(" ").map((w) => w[0]).join("");

/* ── diverging bars (weapons / leaks) ───────────────────────────────────── */

export function Diverging({
  rows,
  max,
  onPick,
}: {
  rows: { shot: string; w: number; e: number }[];
  max: number;
  onPick?: (shot: string, won: boolean) => void;
}) {
  const { ref, on, tipEl } = useChartTip();
  return (
    <div className="relative space-y-1" ref={ref}>
      {rows.map((r) => (
        <div key={r.shot} className="grid grid-cols-[1fr_auto_1fr] items-center gap-2 text-[12px]">
          <div className="flex justify-end items-center gap-1.5">
            {r.e > 0 && <span className="mono text-err text-[11px]">{r.e}</span>}
            <div
              className="h-4 rounded-l-sm cursor-pointer hover:opacity-80"
              style={{ width: `${(100 * r.e) / max}%`, background: "var(--err)", minWidth: r.e ? 3 : 0 }}
              onClick={() => onPick?.(r.shot, false)}
              {...on(
                <span>
                  <b className="text-err">{r.e}</b> {r.shot} {r.e === 1 ? "error" : "errors"}
                  <span className="text-dim"> · click to watch</span>
                </span>,
              )}
            />
          </div>
          <div className="w-28 text-center text-mut truncate">{r.shot}</div>
          <div className="flex items-center gap-1.5">
            <div
              className="h-4 rounded-r-sm cursor-pointer hover:opacity-80"
              style={{ width: `${(100 * r.w) / max}%`, background: "var(--win)", minWidth: r.w ? 3 : 0 }}
              onClick={() => onPick?.(r.shot, true)}
              {...on(
                <span>
                  <b className="text-win">{r.w}</b> {r.shot} {r.w === 1 ? "winner" : "winners"}
                  <span className="text-dim"> · click to watch</span>
                </span>,
              )}
            />
            {r.w > 0 && <span className="mono text-win text-[11px]">{r.w}</span>}
          </div>
        </div>
      ))}
      <div className="grid grid-cols-[1fr_auto_1fr] text-[10px] kicker pt-1">
        <div className="text-right">← ERRORS</div>
        <div className="w-28" />
        <div>WINNERS →</div>
      </div>
      {tipEl}
    </div>
  );
}

/* ── simple horizontal bar list ─────────────────────────────────────────── */

export function HBars({
  rows,
  color = "var(--pb)",
  unit = "",
  format = (v: number) => v.toFixed(2),
}: {
  rows: { label: string; value: number }[];
  color?: string;
  unit?: string;
  format?: (v: number) => string;
}) {
  const max = Math.max(...rows.map((r) => r.value), 0.001);
  const { ref, on, tipEl } = useChartTip();
  return (
    <div className="relative space-y-1.5" ref={ref}>
      {rows.map((r) => (
        <div
          key={r.label}
          className="flex items-center gap-2 text-[12px]"
          {...on(
            <span>
              {r.label}: <b className="mono">{format(r.value)}{unit}</b>
            </span>,
          )}
        >
          <div className="w-28 text-right text-mut truncate shrink-0">{r.label}</div>
          <div className="flex-1 h-4 relative">
            <div className="h-full rounded-sm" style={{ width: `${(100 * r.value) / max}%`, background: color, opacity: 0.85 }} />
          </div>
          <div className="mono text-[11px] w-14">{format(r.value)}{unit}</div>
        </div>
      ))}
      {tipEl}
    </div>
  );
}

/* ── butterfly (shot mix A vs B) ────────────────────────────────────────── */

export function Butterfly({
  rows,
  names,
}: {
  rows: { shot: string; a: number; b: number }[];
  names: Record<P, string>;
}) {
  const max = Math.max(...rows.flatMap((r) => [r.a, r.b]), 1);
  const { ref, on, tipEl } = useChartTip();
  return (
    <div className="relative" ref={ref}>
      <div className="grid grid-cols-[1fr_auto_1fr] text-[10.5px] kicker mb-1.5">
        <div className="text-right" style={{ color: PCOLOR.B }}>{names.B}</div>
        <div className="w-28" />
        <div style={{ color: PCOLOR.A }}>{names.A}</div>
      </div>
      <div className="space-y-1">
        {rows.map((r) => (
          <div
            key={r.shot}
            className="grid grid-cols-[1fr_auto_1fr] items-center gap-2 text-[12px]"
            {...on(
              <span>
                <b>{r.shot}</b> — <span style={{ color: PCOLOR.B }}>{names.B}</span>{" "}
                <b className="mono">{r.b.toFixed(0)}%</b> ·{" "}
                <span style={{ color: PCOLOR.A }}>{names.A}</span>{" "}
                <b className="mono">{r.a.toFixed(0)}%</b> of own shots
              </span>,
            )}
          >
            <div className="flex justify-end items-center gap-1.5">
              <span className="mono text-[10.5px] text-dim">{r.b.toFixed(0)}%</span>
              <div className="h-3.5 rounded-l-sm" style={{ width: `${(92 * r.b) / max}%`, background: PCOLOR.B, opacity: 0.8 }} />
            </div>
            <div className="w-28 text-center text-mut truncate">{r.shot}</div>
            <div className="flex items-center gap-1.5">
              <div className="h-3.5 rounded-r-sm" style={{ width: `${(92 * r.a) / max}%`, background: PCOLOR.A, opacity: 0.8 }} />
              <span className="mono text-[10.5px] text-dim">{r.a.toFixed(0)}%</span>
            </div>
          </div>
        ))}
      </div>
      {tipEl}
    </div>
  );
}

/* ── grouped columns (rally-length win rate) ────────────────────────────── */

export function LengthCols({
  rows,
  names,
}: {
  rows: { bucket: string; player: P; played: number; won: number; win_pct: number }[];
  names: Record<P, string>;
}) {
  const buckets = ["short (≤4)", "mid (5–9)", "long (10+)"].filter((b) =>
    rows.some((r) => r.bucket === b),
  );
  const { ref, on, tipEl } = useChartTip();
  return (
    <div className="relative" ref={ref}>
      <div className="grid gap-3" style={{ gridTemplateColumns: `repeat(${buckets.length},1fr)` }}>
        {buckets.map((b) => (
          <div key={b}>
            <div className="flex items-end gap-2 h-36 border-b border-[var(--line)] relative">
              <div className="absolute left-0 right-0 border-t border-dashed border-[var(--line)]"
                style={{ bottom: "50%" }} />
              {(["B", "A"] as P[]).map((p) => {
                const r = rows.find((x) => x.bucket === b && x.player === p);
                if (!r) return <div key={p} className="flex-1" />;
                return (
                  <div key={p} className="flex-1 flex flex-col items-center justify-end h-full gap-1">
                    <span className="mono text-[11px]" style={{ color: PCOLOR[p] }}>
                      {r.win_pct}%
                    </span>
                    <div
                      className="w-full max-w-12 rounded-t-sm"
                      style={{ height: `${r.win_pct}%`, background: PCOLOR[p], opacity: 0.85 }}
                      {...on(
                        <span>
                          <span style={{ color: PCOLOR[p] }}>{names[p]}</span> won{" "}
                          <b className="mono">{r.won}/{r.played}</b> {b} rallies (
                          <b className="mono">{r.win_pct}%</b>)
                        </span>,
                      )}
                    />
                  </div>
                );
              })}
            </div>
            <div className="text-center text-[11px] text-mut mt-1.5">{b}</div>
            <div className="text-center mono text-[10px] text-dim">
              {rows.find((x) => x.bucket === b)?.played ?? 0} rallies
            </div>
          </div>
        ))}
      </div>
      {tipEl}
    </div>
  );
}

/* ── split bar (pattern A/B wins) ───────────────────────────────────────── */

export function SplitBar({ a, b }: { a: number; b: number }) {
  const n = a + b || 1;
  return (
    <div className="flex h-3 rounded-sm overflow-hidden w-full min-w-20">
      <div style={{ width: `${(100 * b) / n}%`, background: PCOLOR.B, opacity: 0.85 }} />
      <div style={{ width: `${(100 * a) / n}%`, background: PCOLOR.A, opacity: 0.85 }} />
    </div>
  );
}

/* ── stacked share bar ──────────────────────────────────────────────────── */

export function StackedShare({
  parts,
}: {
  parts: { label: string; value: number; color: string }[];
}) {
  const total = parts.reduce((s, p) => s + p.value, 0) || 1;
  const { ref, on, tipEl } = useChartTip();
  return (
    <div className="relative" ref={ref}>
      <div className="flex h-5 rounded overflow-hidden">
        {parts.map((p) => (
          <div
            key={p.label}
            style={{ width: `${(100 * p.value) / total}%`, background: p.color, opacity: 0.9 }}
            {...on(
              <span>
                {p.label}: <b className="mono">{p.value}</b>{" "}
                <span className="text-dim">({Math.round((100 * p.value) / total)}%)</span>
              </span>,
            )}
          />
        ))}
      </div>
      <div className="flex flex-wrap gap-x-4 gap-y-1 mt-2">
        {parts.map((p) => (
          <span key={p.label} className="text-[11.5px] text-mut flex items-center gap-1.5">
            <span className="w-2 h-2 rounded-sm inline-block" style={{ background: p.color }} />
            {p.label} <span className="mono text-ink">{p.value}</span>
          </span>
        ))}
      </div>
      {tipEl}
    </div>
  );
}

/* ── confusion matrix (BST vs labels) ───────────────────────────────────── */

export function Confusion({
  cells,
  order,
}: {
  cells: { label: string; pred: string; n: number }[];
  order: string[];
}) {
  const classes = order.filter((s) =>
    cells.some((c) => c.label === s || c.pred === s),
  );
  const rowTot: Record<string, number> = {};
  for (const c of cells) rowTot[c.label] = (rowTot[c.label] ?? 0) + c.n;
  const get = (l: string, p: string) => cells.find((c) => c.label === l && c.pred === p)?.n ?? 0;
  const sz = 30;
  const padL = 96, padT = 78;
  const { ref, on, tipEl } = useChartTip();
  return (
    <div className="relative" ref={ref}>
      <svg viewBox={`0 0 ${padL + classes.length * sz + 8} ${padT + classes.length * sz + 8}`} className="w-full max-w-xl">
        {classes.map((l, i) => (
          <text key={`r${l}`} x={padL - 6} y={padT + i * sz + sz / 2 + 3.5} textAnchor="end"
            fontSize={10} fill="var(--mut)">{l}</text>
        ))}
        {classes.map((p, j) => (
          <text key={`c${p}`} x={padL + j * sz + sz / 2} y={padT - 8}
            fontSize={10} fill="var(--mut)"
            transform={`rotate(-40 ${padL + j * sz + sz / 2} ${padT - 8})`}>{p}</text>
        ))}
        {classes.map((l, i) =>
          classes.map((p, j) => {
            const n = get(l, p);
            const share = rowTot[l] ? n / rowTot[l] : 0;
            return (
              <g
                key={`${l}-${p}`}
                {...(n > 0
                  ? on(
                      <span>
                        human <b>{l}</b> → AI <b>{p}</b>: <b className="mono">{n}</b>{" "}
                        <span className="text-dim">({Math.round(share * 100)}% of {l}s)</span>
                      </span>,
                    )
                  : {})}
              >
                <rect
                  x={padL + j * sz + 1} y={padT + i * sz + 1} width={sz - 2} height={sz - 2} rx={2}
                  fill={l === p ? "var(--ai)" : "var(--err)"}
                  opacity={n === 0 ? 0.04 : 0.12 + share * 0.8}
                />
                {n >= 3 && (
                  <text x={padL + j * sz + sz / 2} y={padT + i * sz + sz / 2 + 3.5}
                    textAnchor="middle" fontSize={9.5} className="mono"
                    fill={share > 0.45 ? "var(--contact-ink)" : "var(--mut)"}>{n}</text>
                )}
              </g>
            );
          }),
        )}
        <text x={padL - 6} y={padT - 30} textAnchor="end" fontSize={9} fill="var(--dim)" className="mono">
          HUMAN LABEL ↓ · AI →
        </text>
      </svg>
      {tipEl}
    </div>
  );
}

/* ── OCR score staircase ────────────────────────────────────────────────── */

export function OcrStairs({
  events,
}: {
  events: { frame: number; set_no: number; top: number; bot: number; winner: string | null }[];
}) {
  const W = 720, H = 170, pad = 30;
  const { ref, on, tipEl } = useChartTip();
  if (!events.length) return null;
  const f0 = events[0].frame, f1 = events[events.length - 1].frame;
  const maxS = Math.max(...events.map((e) => Math.max(e.top, e.bot)));
  const x = (f: number) => pad + ((W - 2 * pad) * (f - f0)) / Math.max(1, f1 - f0);
  const y = (s: number) => H - pad - ((H - 2 * pad) * s) / maxS;
  const setBreaks = events.filter((e, i) => i > 0 && e.set_no !== events[i - 1].set_no);
  const stair = (key: "top" | "bot", color: string) => {
    let d = "";
    events.forEach((e, i) => {
      const X = x(e.frame), Y = y(e[key]);
      d += i === 0 ? `M${X},${Y}` : `L${X},${prevY[key]} L${X},${Y}`;
      prevY[key] = Y;
    });
    return <path d={d} fill="none" stroke={color} strokeWidth={1.8} opacity={0.9} />;
  };
  const prevY: Record<string, number> = { top: 0, bot: 0 };
  return (
    <div className="relative" ref={ref}>
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full">
        {setBreaks.map((e) => (
          <g key={e.frame}>
            <line x1={x(e.frame)} y1={pad - 6} x2={x(e.frame)} y2={H - pad}
              stroke="var(--line)" strokeDasharray="3 4" />
            <text x={x(e.frame) + 4} y={pad} fontSize={9.5} fill="var(--dim)" className="mono">
              SET {e.set_no}
            </text>
          </g>
        ))}
        {stair("top", "var(--mut)")}
        {stair("bot", "var(--ai)")}
        {events.filter((e) => e.winner).map((e) => (
          <circle key={e.frame} cx={x(e.frame)} cy={y(e[e.winner as "top" | "bot"])} r={2.6}
            fill={e.winner === "bot" ? "var(--ai)" : "var(--mut)"} />
        ))}
        {/* invisible hover strips, one per event */}
        {events.map((e, i) => {
          const x0 = i === 0 ? x(e.frame) - 4 : (x(events[i - 1].frame) + x(e.frame)) / 2;
          const x1e = i === events.length - 1 ? x(e.frame) + 4 : (x(e.frame) + x(events[i + 1].frame)) / 2;
          return (
            <rect
              key={`h${e.frame}`}
              x={x0} y={pad - 6} width={Math.max(x1e - x0, 2)} height={H - 2 * pad + 6}
              fill="transparent"
              {...on(
                <span>
                  <b className="mono">{e.top}–{e.bot}</b> · set {e.set_no}
                  {e.winner && (
                    <span className="text-dim"> · point to {e.winner} row</span>
                  )}
                  <span className="text-dim block mono text-[10.5px]">frame {e.frame}</span>
                </span>,
              )}
            />
          );
        })}
        <text x={pad} y={H - 8} fontSize={9.5} fill="var(--dim)" className="mono">
          BROADCAST TIME → (each step = one machine-read score change)
        </text>
      </svg>
      {tipEl}
    </div>
  );
}
