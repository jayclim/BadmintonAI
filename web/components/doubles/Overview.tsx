"use client";

import type { DoublesViewProps } from "@/components/DoublesDashboard";
import type { DSide, FormationSide, PlayerShare } from "@/lib/doubles";
import { Card, Section, Metric, WatchBtn } from "@/components/ui";
import { fmtClock } from "@/lib/fmt";

const SIDE_COLOR: Record<DSide, string> = { near: "var(--pa)", far: "var(--pb)" };

/** attack(left) vs defence(right) split bar */
function AttackBar({ attackPct, color }: { attackPct: number | null; color: string }) {
  const a = attackPct ?? 0;
  return (
    <div className="mt-2">
      <div className="h-3 w-full rounded-full overflow-hidden flex bg-[var(--line-soft)]">
        <div style={{ width: `${a}%`, background: color }} />
        <div style={{ width: `${100 - a}%`, background: "var(--line)" }} />
      </div>
      <div className="flex justify-between mt-1 text-[11px] mono text-dim">
        <span style={{ color }}>{a.toFixed(0)}% ATTACK</span>
        <span>{(100 - a).toFixed(0)}% DEFENCE</span>
      </div>
    </div>
  );
}

function SideCard({ side, f, pair }: { side: DSide; f: FormationSide; pair: string }) {
  const color = SIDE_COLOR[side];
  return (
    <Card>
      <div className="flex items-baseline justify-between gap-2">
        <div className="font-semibold text-[1.05rem]" style={{ color }}>
          {pair}
        </div>
        <span className="mono text-[10px] tracking-[0.16em] text-dim">{side.toUpperCase()}</span>
      </div>
      <AttackBar attackPct={f.attackPct} color={color} />
      <div className="grid grid-cols-2 gap-x-4 gap-y-3 mt-4">
        <Metric label="ROTATIONS" value={f.rotations} size="text-[1.5rem]" sub="attack ⇄ defence" />
        <Metric label="FRONT SWAPS" value={f.frontSwaps} size="text-[1.5rem]" sub="net player changed" />
        <Metric
          label="DEPTH GAP"
          value={f.medianDepthGapM != null ? `${f.medianDepthGapM.toFixed(1)}m` : "—"}
          size="text-[1.5rem]"
          sub="front↔back median"
        />
        <Metric
          label="LATERAL GAP"
          value={f.medianLateralGapM != null ? `${f.medianLateralGapM.toFixed(1)}m` : "—"}
          size="text-[1.5rem]"
          sub="left↔right median"
        />
      </div>
    </Card>
  );
}

function NetHunters({ players, color }: { players: PlayerShare[]; color: string }) {
  const sorted = [...players].sort((a, b) => b.frontPct - a.frontPct);
  return (
    <div className="space-y-3">
      {sorted.map((p) => (
        <div key={p.slot}>
          <div className="flex items-baseline justify-between text-[13px] mb-1">
            <span className="font-medium" style={{ color }}>
              {p.name}
            </span>
            <span className="mono text-dim">{p.frontPct.toFixed(0)}% front</span>
          </div>
          <div className="h-2 w-full rounded-full overflow-hidden bg-[var(--line-soft)]">
            <div style={{ width: `${p.frontPct}%`, background: color }} className="h-full" />
          </div>
        </div>
      ))}
    </div>
  );
}

export default function DoublesOverview({ d, goRally }: DoublesViewProps) {
  const { formation, players, rallies, meta } = d;
  const nearPlayers = players.filter((p) => p.side === "near");
  const farPlayers = players.filter((p) => p.side === "far");

  return (
    <div className="space-y-8 mt-2">
      <section>
        <Section
          kicker="FORMATION"
          title="Attack vs defence"
          hint="Attack = the pair stacked front-to-back (one hunts the net, partner covers the rear). Defence = side-by-side, receiving a smash. Rotations count debounced flips between the two."
        />
        <div className="grid md:grid-cols-2 gap-5">
          <SideCard side="near" f={formation.near} pair={meta.pairs.near} />
          <SideCard side="far" f={formation.far} pair={meta.pairs.far} />
        </div>
      </section>

      {players.length > 0 && (
        <section>
          <Section
            kicker="ROLES"
            title="Who hunts the net"
            hint="Share of in-rally frames each player spent as the front (net) player of their pair. The net player attacks; their partner covers the rear."
          />
          <div className="grid md:grid-cols-2 gap-5">
            <Card>
              <div className="font-semibold mb-3" style={{ color: SIDE_COLOR.near }}>
                {meta.pairs.near}
              </div>
              <NetHunters players={nearPlayers} color={SIDE_COLOR.near} />
            </Card>
            <Card>
              <div className="font-semibold mb-3" style={{ color: SIDE_COLOR.far }}>
                {meta.pairs.far}
              </div>
              <NetHunters players={farPlayers} color={SIDE_COLOR.far} />
            </Card>
          </div>
        </section>
      )}

      <section>
        <Section
          kicker="RALLIES"
          title={`${rallies.length} tracked rallies`}
          hint="Per-rally formation split for each side. Click to watch the 4-player replay."
        />
        <Card className="!p-0 overflow-hidden">
          <table className="w-full text-[13px]">
            <thead>
              <tr className="text-left text-dim mono text-[10px] tracking-[0.1em] border-b border-[var(--line-soft)]">
                <th className="px-4 py-2.5">#</th>
                <th className="px-4 py-2.5">LENGTH</th>
                <th className="px-4 py-2.5" style={{ color: SIDE_COLOR.near }}>NEAR ATTACK</th>
                <th className="px-4 py-2.5" style={{ color: SIDE_COLOR.far }}>FAR ATTACK</th>
                <th className="px-4 py-2.5">ROTATIONS</th>
                <th className="px-4 py-2.5"></th>
              </tr>
            </thead>
            <tbody>
              {rallies.map((r) => {
                const rot = (r.near?.rotations ?? 0) + (r.far?.rotations ?? 0);
                return (
                  <tr key={r.rally} className="border-b border-[var(--line-soft)] last:border-0 hover:bg-[var(--panel-solid)]/40">
                    <td className="px-4 py-2.5 mono text-mut">{r.rally}</td>
                    <td className="px-4 py-2.5 mono text-dim">{fmtClock(r.durS)}</td>
                    <td className="px-4 py-2.5"><MiniBar pct={r.near?.attackPct ?? null} color={SIDE_COLOR.near} /></td>
                    <td className="px-4 py-2.5"><MiniBar pct={r.far?.attackPct ?? null} color={SIDE_COLOR.far} /></td>
                    <td className="px-4 py-2.5 mono text-mut">{rot}</td>
                    <td className="px-4 py-2.5 text-right">
                      <WatchBtn n={1} onClick={() => goRally(r.rally)} />
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </Card>
      </section>
    </div>
  );
}

function MiniBar({ pct, color }: { pct: number | null; color: string }) {
  if (pct == null) return <span className="text-dim mono text-[11px]">—</span>;
  return (
    <div className="flex items-center gap-2">
      <div className="h-1.5 w-20 rounded-full overflow-hidden bg-[var(--line-soft)]">
        <div style={{ width: `${pct}%`, background: color }} className="h-full" />
      </div>
      <span className="mono text-[11px] text-dim w-8">{pct.toFixed(0)}%</span>
    </div>
  );
}
