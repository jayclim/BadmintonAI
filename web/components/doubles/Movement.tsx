"use client";

/* Doubles "Court" view — the singles movement view's analogue, per TEAM. Each pair's two
   players are combined onto one near half (net at top), aggregated across all sets (the
   pairs swap ends each game, so a per-court-side view would mix the teams). The heatmap
   shows the team's whole court coverage; NET / MID / REAR is where the pair lived.
   Reuses the singles court.tsx HeatMap unchanged. */

import type { DoublesViewProps } from "@/components/DoublesDashboard";
import type { Team, TeamMovement } from "@/lib/doubles";
import { TEAM_COLOR, TEAMS } from "@/lib/doubles";
import { Card, Section, Metric } from "@/components/ui";
import { HeatMap } from "@/components/court";

/** net / mid / rear occupancy as one stacked bar, fading with depth. */
function ZoneBar({ mv, color }: { mv: TeamMovement; color: string }) {
  return (
    <div className="mt-3">
      <div className="flex h-2.5 rounded overflow-hidden">
        <div style={{ width: `${mv.front}%`, background: color, opacity: 0.95 }} />
        <div style={{ width: `${mv.mid}%`, background: color, opacity: 0.55 }} />
        <div style={{ width: `${mv.back}%`, background: color, opacity: 0.3 }} />
      </div>
      <div className="flex justify-between mono text-[10px] text-dim mt-1">
        <span>NET {mv.front}%</span>
        <span>MID {mv.mid}%</span>
        <span>REAR {mv.back}%</span>
      </div>
    </div>
  );
}

function TeamCard({ team, mv, delay }: { team: Team; mv: TeamMovement; delay?: 1 | 2 }) {
  const color = TEAM_COLOR[team];
  return (
    <Card delay={delay}>
      <div className="flex items-baseline gap-2 mb-2">
        <span className="inline-block w-2 h-2 rounded-full" style={{ background: color }} />
        <span className="font-semibold" style={{ color }}>
          {mv.name}
        </span>
        <span className="mono text-[10px] tracking-[0.16em] text-dim ml-auto">TEAM {team}</span>
      </div>
      <HeatMap heat={mv.heat} color={color} />
      <div className="grid grid-cols-3 gap-3 mt-3">
        <Metric label="DISTANCE" value={mv.distM.toLocaleString()} sub="m (pair, in rallies)" size="text-[1.5rem]" />
        <Metric label="SPEED" value={mv.speed.toFixed(2)} sub="m/s avg" size="text-[1.5rem]" />
        <Metric label="COVERAGE" value={mv.cov.toFixed(0)} sub="m² roamed" size="text-[1.5rem]" />
      </div>
      <ZoneBar mv={mv} color={color} />
    </Card>
  );
}

export default function DoublesMovement({ d }: DoublesViewProps) {
  const { movement, meta } = d;

  if (!movement || movement.length === 0) {
    return (
      <Card className="mt-6">
        <p className="text-mut text-[13px]">No continuous 4-player tracks for this match.</p>
      </Card>
    );
  }

  const byTeam = (t: Team) => movement.find((m) => m.pair === t);
  const multiSet = meta.nSets > 1;

  return (
    <div className="space-y-8 mt-2">
      <section>
        <Section
          kicker="FROM THE CV TRACKS — TRACKED RALLY SPAN"
          title="Who covered what"
          hint={
            "Each pair's court coverage over the tracked rallies, both partners combined and plotted on one near half (net at the top) so the teams compare directly. NET / MID / REAR is where the pair lived; coverage is the area roamed." +
            (multiSet ? " Aggregated across all sets — combining the pair keeps it correct through the end-swaps." : "")
          }
        />
        <div className="grid md:grid-cols-2 gap-6 [&>*]:min-w-0">
          {TEAMS.map((t, i) => {
            const mv = byTeam(t);
            return mv ? <TeamCard key={t} team={t} mv={mv} delay={(i + 1) as 1 | 2} /> : null;
          })}
        </div>
      </section>

      <Card className="self-start">
        <div className="kicker mb-2">READING THE HEAT</div>
        <ul className="text-[13px] text-mut space-y-2 leading-snug">
          <li>· A bright band hugging the net plus a deep blob = a clear front/back attacking shape.</li>
          <li>· One broad smear across the whole half = a side-by-side defensive pair, or one being pulled around.</li>
          <li>· Wider coverage isn&apos;t always better — it can mean scrambling out of position.</li>
          <li>· Far-side positions come from the same homography as the near side; treat small front/rear differences as indicative, not exact.</li>
        </ul>
      </Card>
    </div>
  );
}
