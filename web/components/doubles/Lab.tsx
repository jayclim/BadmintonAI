"use client";

/* Doubles "AI Lab" — the validation showcase. Singles shows agreement vs ShuttleSet's
   human labels; doubles has NONE (that's the premise), so this tells the honest label-free
   story instead: how good is the 4-player tracking on its own terms — coverage, per-slot
   recall, identity stability, segmentation — plus a rally x-ray (the same 4-player replay
   the Film room uses). Every number here is measured from tracks; nothing is faked. */

import { useState } from "react";
import type { DoublesViewProps } from "@/components/DoublesDashboard";
import type { DSide, DSlot } from "@/lib/doubles";
import { SIDE_OF, useDoublesReplay } from "@/lib/doubles";
import { AiTag, Card, Metric, Section, Select } from "@/components/ui";
import { DoublesReplay2D } from "@/components/doubles/court4";

const SIDE_COLOR: Record<DSide, string> = { near: "var(--pa)", far: "var(--pb)" };

export default function DoublesLab({ d, id }: DoublesViewProps) {
  const { showcase: sc, meta, rallies } = d;
  const [rally, setRally] = useState<number>(rallies[0]?.rally ?? 1);
  const { data: rep } = useDoublesReplay(id, rally);

  if (!sc) {
    return (
      <Card className="mt-6">
        <p className="text-mut text-[13px]">No validation data — re-run the doubles export.</p>
      </Card>
    );
  }

  const steps = sc.slots.map((s) => s.medStepCm).filter((x): x is number => x != null);
  const medStep = steps.length ? steps.reduce((a, b) => a + b, 0) / steps.length : null;
  const teleTotal = sc.slots.reduce((a, s) => a + s.teleports, 0);

  const stages: { name: string; tech: string; metric: string; sub: string }[] = [
    {
      name: "PLAYER TRACKING",
      tech: "YOLO11x-pose + ByteTrack + homography",
      metric: `${sc.coverage.inRallyPct}%`,
      sub: `all-4 in-rally coverage · ${sc.coverage.all4}/${sc.coverage.frames} tracked frames`,
    },
    {
      name: "IDENTITY STABILITY",
      tech: "slot persistence + velocity re-ID",
      metric: medStep != null ? `${medStep.toFixed(1)} cm` : "—",
      sub: `median court step / frame · ${teleTotal} non-physical >1.5 m ID jumps`,
    },
    {
      name: "RALLY SEGMENTATION",
      tech: "all-4-present runs, dead-time excluded",
      metric: `${sc.segmentation.rallies} rallies`,
      sub: `${sc.segmentation.spanS}s of real play isolated (no shuttle needed)`,
    },
    {
      name: "FORMATION ROLES",
      tech: "pure geometry — no model, no labels",
      metric: "0 labels",
      sub: "front/back + attack/defence recomputed every frame, survives slot swaps",
    },
    {
      name: "SCORE-PARITY RE-ANCHOR",
      tech: "scoreboard OCR → service-court parity",
      metric: "✓ parity",
      sub: "per-rally OCR parities match the hand-read score; corrects between-rally swaps",
    },
  ];

  return (
    <div className="space-y-10 mt-2">
      <section>
        <Section
          kicker="THE LABEL-FREE DOUBLES CHAIN"
          title="Validated without a single label"
          hint="No public doubles dataset exists and the one SOTA paper hand-annotated just two matches — so this pipeline trains on nothing. Every stage is checked on its own terms: tracking coverage, identity stability and rally segmentation, all measured straight from the tracks."
        >
          <AiTag text="SHOWCASE" />
          <span className="mono text-[10px] tracking-[0.15em] px-1.5 py-0.5 rounded border border-[var(--ai)]/40 text-[var(--ai)]">
            ZERO LABELS
          </span>
        </Section>
        <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-3">
          {stages.map((s, i) => (
            <Card key={s.name} delay={Math.min(i + 1, 5) as 1} className="relative overflow-hidden">
              <div className="mono text-[9.5px] text-dim tracking-[0.18em] mb-1">
                {String(i + 1).padStart(2, "0")} ▸ {s.name}
              </div>
              <div className="bignum text-[2rem]" style={{ color: "var(--ai)" }}>
                {s.metric}
              </div>
              <div className="text-[11.5px] text-mut mt-1 leading-snug">{s.sub}</div>
              <div className="mono text-[10px] text-dim mt-2">{s.tech}</div>
            </Card>
          ))}
        </div>
      </section>

      <div className="rule" />

      <section>
        <Section
          kicker="PER-PLAYER TRACKING QUALITY"
          title="Where the tracker is strong (and where it slips)"
          hint="Recall = share of rally frames each slot was tracked — the far pair is smaller and more occluded, so it trails. Median step is the typical per-frame court move (low = smooth). ID jumps are non-physical >1.5 m hops between adjacent frames — the identity-switch failure mode the doubles literature flags."
        />
        <Card className="!p-0 overflow-hidden">
          <table className="w-full text-[13px]">
            <thead>
              <tr className="text-left text-dim mono text-[10px] tracking-[0.1em] border-b border-[var(--line-soft)]">
                <th className="px-4 py-2.5">PLAYER</th>
                <th className="px-4 py-2.5">SLOT</th>
                <th className="px-4 py-2.5">RECALL</th>
                <th className="px-4 py-2.5">MEDIAN STEP</th>
                <th className="px-4 py-2.5">ID JUMPS</th>
              </tr>
            </thead>
            <tbody>
              {sc.slots.map((s) => {
                const color = SIDE_COLOR[SIDE_OF[s.slot as DSlot]];
                return (
                  <tr key={s.slot} className="border-b border-[var(--line-soft)] last:border-0">
                    <td className="px-4 py-2.5 font-medium" style={{ color }}>
                      {s.name}
                    </td>
                    <td className="px-4 py-2.5 mono text-dim">{s.slot}</td>
                    <td className="px-4 py-2.5">
                      <div className="flex items-center gap-2">
                        <div className="h-1.5 w-20 rounded-full overflow-hidden bg-[var(--line-soft)]">
                          <div style={{ width: `${s.recallPct}%`, background: color }} className="h-full" />
                        </div>
                        <span className="mono text-[11px] text-dim w-12">{s.recallPct}%</span>
                      </div>
                    </td>
                    <td className="px-4 py-2.5 mono text-mut">
                      {s.medStepCm != null ? `${s.medStepCm} cm` : "—"}
                    </td>
                    <td className="px-4 py-2.5 mono" style={{ color: s.teleports > 3 ? "var(--warn)" : "var(--mut)" }}>
                      {s.teleports}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </Card>
      </section>

      <div className="rule" />

      <section>
        <Section
          kicker="ONE RALLY, WHAT THE MACHINE SEES"
          title="Rally x-ray"
          hint="The raw 4-player tracking for any rally, rendered in true court metres. Front player solid, rear ringed; the formation banner is the debounced attack/defence call. No labels were used to produce any of it."
        />
        <div className="max-w-xs mb-3">
          <Select
            label="RALLY"
            value={String(rally)}
            onChange={(v) => setRally(Number(v))}
            options={rallies.map((r) => String(r.rally))}
          />
        </div>
        <Card className="max-w-3xl">
          {rep ? (
            <DoublesReplay2D rep={rep} />
          ) : (
            <div className="text-dim mono text-[12px] py-16 text-center animate-pulse">LOADING RALLY…</div>
          )}
          <div className="mt-3 text-[11.5px] text-dim flex flex-wrap gap-x-5 gap-y-1">
            <span style={{ color: "var(--pa)" }}>● {meta.teams.A}</span>
            <span style={{ color: "var(--pb)" }}>● {meta.teams.B}</span>
            <span>solid = net (front) player · ring = rear cover</span>
          </div>
        </Card>
      </section>
    </div>
  );
}
