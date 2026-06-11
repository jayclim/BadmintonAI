"use client";

import type { ReactNode } from "react";
import type { P } from "@/lib/types";
import { PCOLOR } from "@/lib/fmt";

export function Card({
  children,
  className = "",
  delay = 0,
}: {
  children: ReactNode;
  className?: string;
  delay?: number;
}) {
  return (
    <div className={`card rise ${delay ? `rise-${delay}` : ""} p-5 ${className}`}>
      {children}
    </div>
  );
}

export function Section({
  kicker,
  title,
  hint,
  children,
  className = "",
}: {
  kicker?: string;
  title: string;
  hint?: string;
  children?: ReactNode;
  className?: string;
}) {
  return (
    <div className={`mb-4 ${className}`}>
      {kicker && <div className="kicker mb-1">{kicker}</div>}
      <div className="flex items-baseline gap-3 flex-wrap">
        <h2 className="text-[1.45rem] font-semibold leading-none">{title}</h2>
        {children}
      </div>
      {hint && <p className="text-[13px] text-mut mt-1.5 max-w-3xl leading-snug">{hint}</p>}
    </div>
  );
}

export function PName({ p, name, className = "" }: { p: P; name: string; className?: string }) {
  return (
    <span className={`font-semibold ${className}`} style={{ color: PCOLOR[p] }}>
      {name}
    </span>
  );
}

export function Dot({ p }: { p: P }) {
  return (
    <span
      className="inline-block w-2 h-2 rounded-full mr-1.5 align-middle"
      style={{ background: PCOLOR[p] }}
    />
  );
}

export function AiTag({ text = "AI" }: { text?: string }) {
  return (
    <span className="mono text-[10px] tracking-[0.18em] px-1.5 py-0.5 rounded border border-[var(--ai)]/40 text-[var(--ai)] bg-[var(--ai-soft)]">
      {text}
    </span>
  );
}

export function Metric({
  label,
  value,
  sub,
  accent,
  size = "text-[2rem]",
}: {
  label: string;
  value: ReactNode;
  sub?: string;
  accent?: string;
  size?: string;
}) {
  return (
    <div className="min-w-0">
      <div className={`bignum ${size}`} style={accent ? { color: accent } : undefined}>
        {value}
      </div>
      <div className="kicker mt-0.5">{label}</div>
      {sub && <div className="text-[11.5px] text-dim mono mt-0.5">{sub}</div>}
    </div>
  );
}

export function Pills<T extends string>({
  options,
  value,
  onChange,
  accent = "var(--ink)",
}: {
  options: readonly T[];
  value: T;
  onChange: (v: T) => void;
  accent?: string;
}) {
  return (
    <div className="flex flex-wrap gap-1.5">
      {options.map((o) => {
        const on = o === value;
        return (
          <button
            key={o}
            onClick={() => onChange(o)}
            className="px-2.5 py-1 rounded-full text-[12px] border transition-colors"
            style={{
              borderColor: on ? accent : "var(--line)",
              color: on ? "var(--bg)" : "var(--mut)",
              background: on ? accent : "transparent",
              fontWeight: on ? 600 : 400,
            }}
          >
            {o}
          </button>
        );
      })}
    </div>
  );
}

export function Select({
  label,
  options,
  value,
  onChange,
}: {
  label: string;
  options: readonly string[];
  value: string;
  onChange: (v: string) => void;
}) {
  return (
    <label className="flex flex-col gap-1 min-w-0">
      <span className="kicker">{label}</span>
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="bg-[var(--panel-solid)] border border-[var(--line)] rounded-md px-2 py-1.5 text-[13px] text-ink outline-none focus:border-[var(--mut)]"
      >
        {options.map((o) => (
          <option key={o} value={o}>
            {o}
          </option>
        ))}
      </select>
    </label>
  );
}

export function WatchBtn({ n, onClick }: { n: number; onClick: () => void }) {
  return (
    <button
      onClick={onClick}
      className="mono text-[11px] tracking-wide px-2.5 py-1 rounded border border-[var(--line)] text-mut hover:text-ink hover:border-[var(--mut)] transition-colors"
    >
      ▶ WATCH {n} {n === 1 ? "RALLY" : "RALLIES"}
    </button>
  );
}

/** simple absolute tooltip container — parent must be position:relative */
export function Tip({ x, y, children }: { x: number; y: number; children: ReactNode }) {
  return (
    <div
      className="absolute z-30 pointer-events-none card !rounded-md px-3 py-2 text-[12px] leading-snug shadow-xl"
      style={{
        left: x,
        top: y,
        transform: "translate(-50%, calc(-100% - 10px))",
        background: "var(--panel-solid)",
        minWidth: 150,
      }}
    >
      {children}
    </div>
  );
}
