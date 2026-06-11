"use client";

import { useState } from "react";
import type { ViewProps } from "@/components/Dashboard";
import { AiTag, Card, Dot, Metric, Pills, Section } from "@/components/ui";
import { HBars } from "@/components/charts";
import { HeatMap, PlacementMap, type Mark } from "@/components/court";
import type { P } from "@/lib/types";
import { SHOT_ORDER } from "@/lib/types";
import { PCOLOR, PHEX } from "@/lib/fmt";

export default function CourtView({ d, src, goRally }: ViewProps) {
  const { meta, rallies, strokes, insights, movement } = d;
  const names = meta.players;

  const shotsPresent = SHOT_ORDER.filter((s) => strokes.some((x) => x.shot === s));
  const [shotSel, setShotSel] = useState<string>("All");
  const [endersOnly, setEndersOnly] = useState<"All shots" | "Point-enders only">("All shots");

  const enderOf = new Map<string, { winner: string | null; category: string; endRound: number }>();
  for (const r of rallies) enderOf.set(`${r.set}-${r.rally}`, r);

  const marks = (p: P): Mark[] => {
    const out: Mark[] = [];
    for (const s of strokes) {
      if (s.p !== p || s.lnx == null || s.lny == null) continue;
      if (shotSel !== "All" && s.shot !== shotSel) continue;
      const r = enderOf.get(`${s.set}-${s.rally}`);
      const isEnd = r && r.winner && r.category !== "—" && r.endRound === s.br;
      const kind: Mark["kind"] = !isEnd
        ? "rally"
        : r!.winner === p
          ? "winner"
          : "error";
      if (endersOnly === "Point-enders only" && kind === "rally") continue;
      out.push({ x: s.lnx, y: s.lny, kind, label: s.shot, set: s.set, rally: s.rally });
    }
    return out;
  };

  return (
    <div className="space-y-8">
      <section>
        <Section
          kicker="SHOT PLACEMENT"
          title="Where their shots land"
          hint="Each player shown hitting upward into the opponent's half (sides normalized across sets). ★ winners · ✕ rally-ending errors · dots = everything else. ✕ beyond the far baseline = hit long; ✕ just past the net line = netted."
        >
          {src === "ai" && <AiTag text="CV LANDINGS" />}
        </Section>
        <div className="flex flex-wrap items-center gap-x-6 gap-y-2 mb-4">
          <Pills
            options={["All", ...shotsPresent] as const}
            value={shotSel}
            onChange={setShotSel}
          />
          <Pills
            options={["All shots", "Point-enders only"] as const}
            value={endersOnly}
            onChange={setEndersOnly}
            accent="var(--warn)"
          />
        </div>
        <div className="grid md:grid-cols-2 xl:grid-cols-[1fr_1fr_0.9fr] gap-4 [&>*]:min-w-0">
          {(["B", "A"] as P[]).map((p, i) => {
            const m = marks(p);
            return (
              <Card key={p} delay={(i + 1) as 1}>
                <div className="flex items-center gap-2 mb-2">
                  <Dot p={p} />
                  <span className="font-semibold" style={{ color: PCOLOR[p] }}>
                    {names[p]}
                  </span>
                  <span className="mono text-[11px] text-dim ml-auto">{m.length} shots</span>
                </div>
                <PlacementMap marks={m} onPick={goRally} />
              </Card>
            );
          })}
          <Card delay={3} className="self-start">
            <div className="kicker mb-2">READING THE MAPS</div>
            <ul className="text-[13px] text-mut space-y-2 leading-snug">
              <li>· A tight ★ cluster is a go-to finishing zone — both where this player kills, and where his opponent should not be standing.</li>
              <li>· ✕ above the far baseline or outside the lines = shots hit long / wide; ✕ just below the net line = netted.</li>
              <li>· Filter to one shot (e.g. smash) and compare the two maps — placement variety is a skill you can see.</li>
              <li>· Click any ★ or ✕ to watch that rally.</li>
            </ul>
          </Card>
        </div>
      </section>

      <div className="rule" />

      <section>
        <Section
          kicker="FROM THE CV TRACKS — VALIDATED ±0.57 m"
          title="Who did the running"
          hint="Per-player movement, correctly re-attributed each set as players swap ends. Heat shown on each player's own half, net at the top. Recovery = average distance from the ideal base — lower is better discipline."
        />
        <div className="grid md:grid-cols-2 xl:grid-cols-[1fr_1fr_0.9fr] gap-4 [&>*]:min-w-0">
          {(["B", "A"] as P[]).map((p, i) => {
            const mv = movement[p];
            if (!mv)
              return (
                <Card key={p}>
                  <p className="text-mut text-[13px]">No continuous tracks for {names[p]}.</p>
                </Card>
              );
            return (
              <Card key={p} delay={(i + 1) as 1}>
                <div className="flex items-center gap-2 mb-2">
                  <Dot p={p} />
                  <span className="font-semibold" style={{ color: PCOLOR[p] }}>
                    {names[p]}
                  </span>
                </div>
                <HeatMap heat={mv.heat} color={PHEX[p]} />
                <div className="grid grid-cols-3 gap-3 mt-3">
                  <Metric label="DISTANCE" value={mv.distM.toLocaleString()} sub="m in rallies" size="text-[1.5rem]" />
                  <Metric label="SPEED" value={mv.speed} sub="m/s avg" size="text-[1.5rem]" />
                  <Metric label="RECOVERY" value={mv.rec} sub="m from base" size="text-[1.5rem]" />
                </div>
                <div className="mt-3">
                  <div className="flex h-2.5 rounded overflow-hidden">
                    <div style={{ width: `${mv.front}%`, background: PHEX[p], opacity: 0.95 }} />
                    <div style={{ width: `${mv.mid}%`, background: PHEX[p], opacity: 0.55 }} />
                    <div style={{ width: `${mv.back}%`, background: PHEX[p], opacity: 0.3 }} />
                  </div>
                  <div className="flex justify-between mono text-[10px] text-dim mt-1">
                    <span>FRONT {mv.front}%</span>
                    <span>MID {mv.mid}%</span>
                    <span>BACK {mv.back}%</span>
                  </div>
                </div>
              </Card>
            );
          })}

          <Card delay={3} className="self-start">
            <Section
              kicker="PRESSURE BUILDERS"
              title="Shots that make the opponent scramble"
              hint="Average speed the opponent needed to reach the next shot — pressure even when it doesn't end the point."
            />
            <HBars
              rows={Object.entries(insights.pressureByShot)
                .sort((a, b) => b[1] - a[1])
                .map(([label, value]) => ({ label, value }))}
              unit=" m/s"
            />
            <div className="mt-4 pt-3 border-t border-[var(--line-soft)]">
              <div className="kicker mb-2">MOVEMENT PRESSURE (M/S)</div>
              {(["B", "A"] as P[]).map((p) => (
                <div key={p} className="flex items-center gap-3 text-[12.5px] py-0.5">
                  <span className="w-28 truncate" style={{ color: PCOLOR[p] }}>
                    {names[p]}
                  </span>
                  <span className="mono text-mut">
                    faced {insights.pressureSummary[p].faced} · applied{" "}
                    <b className="text-ink">{insights.pressureSummary[p].applied}</b>
                  </span>
                </div>
              ))}
              <p className="text-dim text-[11.5px] mt-1.5">
                Applied &gt; faced = made the opponent do the scrambling.
              </p>
            </div>
          </Card>
        </div>
      </section>
    </div>
  );
}
