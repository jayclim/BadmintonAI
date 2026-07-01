"use client";

/* Doubles "Court" view — per-PLAYER movement (FOUR players), the per-person answer the
   old pair-combined view couldn't give. A SET selector picks the game; within it, each of
   the four players gets a heatmap + distance/speed/coverage + NET/MID/REAR occupancy.
   Every player is plotted on one near half (net at top, far side mirrored) so all four are
   directly comparable. Set 1 carries the roster athlete names; later sets show the pair
   label + P1/P2 (the pairs swap ends and only set 1 is identity-anchored — see the note).
   Reuses the singles court.tsx HeatMap unchanged. */

import { useMemo, useState } from "react";
import type { DoublesViewProps } from "@/components/DoublesDashboard";
import type { PlayerMovement, PlayerShots, Team } from "@/lib/doubles";
import { TEAM_COLOR, TEAMS, playerLabel } from "@/lib/doubles";
import { Card, Section, Metric, Select } from "@/components/ui";
import { HeatMap } from "@/components/court";

/** net / mid / rear occupancy as one stacked bar, fading with depth. */
function ZoneBar({ mv, color }: { mv: PlayerMovement; color: string }) {
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

function PlayerCard({ mv, label, color, shots, delay }: {
  mv: PlayerMovement; label: string; color: string; shots?: PlayerShots; delay?: 1 | 2;
}) {
  return (
    <Card delay={delay}>
      <div className="flex items-baseline gap-2 mb-2">
        <span className="inline-block w-2 h-2 rounded-full" style={{ background: color }} />
        <span className="font-semibold text-[14px] truncate" style={{ color }}>{label}</span>
        <span className="mono text-[10px] tracking-[0.16em] text-dim ml-auto shrink-0">TEAM {mv.team}</span>
      </div>
      <HeatMap heat={mv.heat} color={color} />
      <div className="grid grid-cols-3 gap-2 mt-3">
        <Metric label="DISTANCE" value={mv.distM.toLocaleString()} sub="m, in rallies" size="text-[1.3rem]" />
        <Metric label="SPEED" value={mv.speed.toFixed(2)} sub="m/s avg" size="text-[1.3rem]" />
        <Metric label="COVERAGE" value={mv.cov.toFixed(0)} sub="m² roamed" size="text-[1.3rem]" />
      </div>
      <ZoneBar mv={mv} color={color} />
      {shots && shots.top.length > 0 && (
        <div className="mt-3 pt-2.5 border-t border-[var(--line-soft)]">
          <div className="mono text-[10px] text-dim mb-1.5">
            TOP SHOTS{shots.serves != null && shots.serves > 0 ? ` · ${shots.serves} SERVES` : ""}
          </div>
          <div className="flex flex-wrap gap-1.5">
            {shots.top.slice(0, 3).map((s) => (
              <span key={s.shot} className="text-[11px] px-1.5 py-0.5 rounded mono"
                style={{ background: "var(--panel-solid)", color: "var(--ink)" }}>
                {s.shot} <span className="text-dim">{s.pct}%</span>
              </span>
            ))}
          </div>
        </div>
      )}
    </Card>
  );
}

export default function DoublesMovement({ d }: DoublesViewProps) {
  const { movement, meta, shots } = d;

  const sets = useMemo(
    () => Array.from(new Set(movement.map((m) => m.set))).sort((a, b) => a - b),
    [movement],
  );
  const [setSel, setSetSel] = useState<number>(sets[0] ?? 1);
  const shotsBy = useMemo(
    () => new Map((shots?.players ?? []).map((p) => [`${p.set}-${p.team}-${p.idx}`, p])),
    [shots],
  );

  if (!movement || movement.length === 0) {
    return (
      <Card className="mt-6">
        <p className="text-mut text-[13px]">No continuous 4-player tracks for this match.</p>
      </Card>
    );
  }

  const inSet = movement.filter((m) => m.set === setSel);
  const named = setSel === 1; // only set 1 carries real athlete names
  const ofTeam = (t: Team) => inSet.filter((m) => m.team === t).sort((a, b) => a.idx - b.idx);

  return (
    <div className="space-y-8 mt-2">
      <section>
        <div className="flex items-end justify-between gap-4 flex-wrap">
          <Section
            kicker="FROM THE CV TRACKS — PER PLAYER, PER SET"
            title="Who covered what"
            hint="Each player's court coverage over the set's rallies, plotted on one near half (net at the top, far side mirrored) so all four compare directly. NET / MID / REAR is where they lived; coverage is the area roamed. TOP SHOTS attribute each CV contact to the nearer partner — the side is exact, the within-pair split approximate."
          />
          {sets.length > 1 && (
            <div className="w-32 shrink-0">
              <Select
                label="SET"
                value={String(setSel)}
                onChange={(v) => setSetSel(Number(v))}
                options={sets.map(String)}
              />
            </div>
          )}
        </div>

        {!named && (
          <p className="text-dim text-[12px] mb-3 -mt-2">
            Set {setSel}: the pairs swapped ends and only set 1 is identity-anchored, so the two
            players of each pair are shown as P1 / P2 rather than named.
          </p>
        )}

        <div className="grid md:grid-cols-2 xl:grid-cols-4 gap-5 [&>*]:min-w-0">
          {TEAMS.flatMap((t, ti) =>
            ofTeam(t).map((mv) => (
              <PlayerCard
                key={`${mv.team}-${mv.idx}`}
                mv={mv}
                label={playerLabel(mv, meta.teams)}
                color={TEAM_COLOR[t]}
                shots={shotsBy.get(`${mv.set}-${mv.team}-${mv.idx}`)}
                delay={(ti + 1) as 1 | 2}
              />
            )),
          )}
        </div>
      </section>

      <Card className="self-start">
        <div className="kicker mb-2">READING THE HEAT</div>
        <ul className="text-[13px] text-mut space-y-2 leading-snug">
          <li>· A blob hugging the net = a front (net) specialist; a deep blob = the rear cover.</li>
          <li>· The two players of a pair should look complementary — one forward, one back — when they&apos;re attacking well.</li>
          <li>· Wider coverage isn&apos;t always better — it can mean being pulled out of position.</li>
          <li>· Far-side players come from the same homography as the near side; the far pair is more occluded, so its heat is sparser — treat small differences as indicative, not exact.</li>
        </ul>
      </Card>
    </div>
  );
}
