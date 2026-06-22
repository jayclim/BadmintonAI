"use client";

/* Doubles "Patterns" — the singles shot-pattern view has no doubles analogue (no strokes
   yet), so this reads the tactic doubles actually turns on: FORMATION FLOW. Who seizes the
   attack first, how long they hold it, how often they rotate, and the per-rally attack/
   defence trace for both pairs. All from the geometric roles layer — no strokes. */

import type { DoublesViewProps } from "@/components/DoublesDashboard";
import type { FlowSide, ShotCount, ShotResponse, Team } from "@/lib/doubles";
import { TEAM_COLOR, TEAMS } from "@/lib/doubles";
import { Card, Section, Metric, WatchBtn } from "@/components/ui";
import { FormationTimeline } from "@/components/doubles/court4";
import { fmtClock } from "@/lib/fmt";

/** attack-first share as a split bar (this team seized the attack vs conceded it). */
function AttackFirstBar({ color, f }: { color: string; f: FlowSide }) {
  const pct = f.attackFirstPct ?? 0;
  return (
    <div className="mt-2">
      <div className="h-3 w-full rounded-full overflow-hidden flex bg-[var(--line-soft)]">
        <div style={{ width: `${pct}%`, background: color }} />
        <div style={{ width: `${100 - pct}%`, background: "var(--line)" }} />
      </div>
      <div className="flex justify-between mt-1 text-[11px] mono text-dim">
        <span style={{ color }}>{pct}% SEIZED ATTACK FIRST</span>
        <span>
          {f.attackFirst}/{f.rallies} rallies
        </span>
      </div>
    </div>
  );
}

function SideCard({ team, f, pair }: { team: Team; f: FlowSide; pair: string }) {
  const color = TEAM_COLOR[team];
  const fmtS = (v: number | null) => (v != null ? `${v.toFixed(1)}s` : "—");
  return (
    <Card>
      <div className="flex items-baseline justify-between gap-2">
        <div className="font-semibold text-[1.05rem]" style={{ color }}>
          {pair}
        </div>
        <span className="mono text-[10px] tracking-[0.16em] text-dim">TEAM {team}</span>
      </div>
      <AttackFirstBar color={color} f={f} />
      <div className="grid grid-cols-2 gap-x-4 gap-y-3 mt-4">
        <Metric label="ATTACK SHARE" value={f.attackPct != null ? `${f.attackPct}%` : "—"} size="text-[1.5rem]" sub="of tracked frames" />
        <Metric label="ATTACK HOLD" value={fmtS(f.attackHoldMedS)} size="text-[1.5rem]" sub="median, before rotating off" />
        <Metric label="ROTATIONS" value={f.rotPerRally ?? "—"} size="text-[1.5rem]" sub="per rally (debounced)" />
        <Metric label="ROTATION RATE" value={f.rotPerMin != null ? f.rotPerMin.toFixed(1) : "—"} size="text-[1.5rem]" sub="per minute of play" />
      </div>
      <div className="mt-4 pt-3 border-t border-[var(--line-soft)] flex items-center gap-4 text-[12px]">
        <span className="mono text-dim">TRANSITIONS</span>
        <span className="flex items-center gap-1.5">
          <span style={{ color }}>{f.a2d}</span>
          <span className="text-dim">attack→defence</span>
        </span>
        <span className="flex items-center gap-1.5">
          <span style={{ color }}>{f.d2a}</span>
          <span className="text-dim">defence→attack</span>
        </span>
      </div>
    </Card>
  );
}

function TeamHead({ team, pair }: { team: Team; pair: string }) {
  return (
    <div className="flex items-baseline justify-between gap-2">
      <div className="font-semibold text-[1.05rem]" style={{ color: TEAM_COLOR[team] }}>{pair}</div>
      <span className="mono text-[10px] tracking-[0.16em] text-dim">TEAM {team}</span>
    </div>
  );
}

function ShotMixCard({ team, pair, mix }: { team: Team; pair: string; mix: ShotCount[] }) {
  const color = TEAM_COLOR[team];
  const max = mix.length ? mix[0].pct : 1;
  return (
    <Card>
      <TeamHead team={team} pair={pair} />
      <div className="mt-3 space-y-1.5">
        {mix.map((s) => (
          <div key={s.shot} className="flex items-center gap-2">
            <span className="w-24 shrink-0 text-[12px] text-mut truncate" title={s.shot}>{s.shot}</span>
            <div className="flex-1 h-3 rounded-full bg-[var(--line-soft)] overflow-hidden">
              <div className="h-full" style={{ width: `${(s.pct / max) * 100}%`, background: color }} />
            </div>
            <span className="mono text-[11px] text-dim w-9 text-right">{s.pct}%</span>
          </div>
        ))}
      </div>
    </Card>
  );
}

function ResponseCard({ team, pair, responses }: { team: Team; pair: string; responses: ShotResponse[] }) {
  return (
    <Card>
      <TeamHead team={team} pair={pair} />
      <div className="mt-2 divide-y divide-[var(--line-soft)]">
        {responses.slice(0, 6).map((r) => (
          <div key={r.vs} className="py-2 flex items-center gap-3">
            <span className="w-24 shrink-0 text-[12px] text-mut truncate" title={`vs ${r.vs}`}>
              vs {r.vs}
            </span>
            <div className="flex flex-wrap gap-1.5">
              {r.answers.slice(0, 3).map((a) => (
                <span
                  key={a.shot}
                  className="text-[11px] px-1.5 py-0.5 rounded mono"
                  style={{ background: "var(--panel-solid)", color: "var(--ink)" }}
                >
                  {a.shot} <span className="text-dim">{a.pct}%</span>
                </span>
              ))}
            </div>
          </div>
        ))}
      </div>
    </Card>
  );
}

export default function DoublesPatterns({ d, goRally }: DoublesViewProps) {
  const { flow, meta, shots } = d;
  const multiSet = meta.nSets > 1;

  if (!flow || flow.rallies.length === 0) {
    return (
      <Card className="mt-6">
        <p className="text-mut text-[13px]">No formation flow — re-run the doubles export.</p>
      </Card>
    );
  }

  return (
    <div className="space-y-8 mt-2">
      {shots && (
        <>
          <section>
            <Section
              kicker="SHOT SELECTION"
              title="What each pair hits"
              hint="Shot mix per pair from CV-detected contacts (img-y extrema on the tracked shuttle), kept per fixed team across the end-swaps. Shot TYPES are a geometry baseline transferred from the labelled singles matches — unvalidated on doubles (no doubles labels exist), so read the distribution, not any single call."
            />
            <div className="grid md:grid-cols-2 gap-5">
              {TEAMS.map((t) => (
                <ShotMixCard key={t} team={t} pair={meta.teams[t]} mix={shots.mix[t]} />
              ))}
            </div>
          </section>

          <section>
            <Section
              kicker="RESPONSE MATRIX"
              title="How each pair answers"
              hint="Given the opponent's last shot (left), the shots this pair replies with most. The doubles read: who blocks vs counter-drives a smash, who lifts vs spins back at the net."
            />
            <div className="grid md:grid-cols-2 gap-5">
              {TEAMS.map((t) => (
                <ResponseCard key={t} team={t} pair={meta.teams[t]} responses={shots.responses[t]} />
              ))}
            </div>
          </section>
        </>
      )}

      <section>
        <Section
          kicker="FORMATION FLOW"
          title="Who controls the attack"
          hint="Doubles is won by holding the attacking (front/back) formation and forcing the other pair into defence (side-by-side). Attack-first = seized the offence at the rally start; hold = how long the attack lasted before the pair was rotated back; rotation rate = formation flips per minute."
        />
        <div className="grid md:grid-cols-2 gap-5">
          {TEAMS.map((t) => (
            <SideCard key={t} team={t} f={flow[t]} pair={meta.teams[t]} />
          ))}
        </div>
      </section>

      <section>
        <Section
          kicker="RALLY BY RALLY"
          title="Attack ⇄ defence trace"
          hint="Each rally as two timelines — solid = that pair was attacking (front/back stack), faint = defending (side-by-side). When one fills solid while the other stays faint, that pair owned the rally. Click to watch."
        />
        <Card className="!p-0 overflow-hidden">
          <div className="divide-y divide-[var(--line-soft)]">
            {flow.rallies.map((r) => {
              const rows: { side: "near" | "far"; team: Team }[] = [
                { side: "far", team: r.farPair },
                { side: "near", team: r.nearPair },
              ];
              return (
                <div key={r.rally} className="px-4 py-3 hover:bg-[var(--panel-solid)]/40">
                  <div className="flex items-center gap-3 mb-2">
                    <span className="mono text-[11px] text-mut">RALLY {r.rally}</span>
                    {multiSet && <span className="mono text-[10px] text-dim">SET {r.set}</span>}
                    <span className="mono text-[11px] text-dim">{fmtClock(r.durS)}</span>
                    <span className="ml-auto">
                      <WatchBtn n={1} onClick={() => goRally(r.rally)} />
                    </span>
                  </div>
                  <div className="space-y-1.5">
                    {rows.map(({ side, team }) => (
                      <div key={side} className="flex items-center gap-2.5">
                        <span
                          className="mono text-[9.5px] tracking-[0.12em] w-16 shrink-0 truncate"
                          style={{ color: TEAM_COLOR[team] }}
                          title={meta.teams[team]}
                        >
                          {meta.teams[team].split(" / ")[0]}
                        </span>
                        <div className="flex-1">
                          <FormationTimeline
                            segs={r[side]}
                            f0={r.f0}
                            f1={r.f1}
                            color={TEAM_COLOR[team]}
                          />
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              );
            })}
          </div>
        </Card>
        <div className="flex items-center gap-5 mt-3 text-[11.5px] text-mut">
          <span className="flex items-center gap-1.5">
            <span className="inline-block w-3 h-2.5 rounded-sm" style={{ background: "var(--mut)" }} />
            solid (pair&apos;s colour) = attacking (front/back)
          </span>
          <span className="flex items-center gap-1.5">
            <span className="inline-block w-3 h-2.5 rounded-sm" style={{ background: "var(--line-soft)" }} />
            faint = defending (side-by-side)
          </span>
        </div>
      </section>
    </div>
  );
}
