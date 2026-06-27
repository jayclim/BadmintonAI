"use client";

import type { DoublesViewProps } from "@/components/DoublesDashboard";
import type { CoachNote, DoublesMatch, FormationSide, PlayerShare, Team } from "@/lib/doubles";
import { TEAM_COLOR, TEAMS, useDoublesAnalysis } from "@/lib/doubles";
import { Card, Section, Metric, WatchBtn } from "@/components/ui";
import { fmtClock } from "@/lib/fmt";

const NOTE_COLOR: Record<CoachNote["kind"], string> = {
  good: "var(--win)",
  watch: "var(--warn)",
  info: "var(--ai)",
};

function CoachNotes({ notes }: { notes: CoachNote[] }) {
  if (!notes || notes.length === 0) return null;
  return (
    <section>
      <Section
        kicker="AI SCOUTING NOTES"
        title="What the tracking says"
        hint="Rule-based reads off the formation, role and movement tactics — no labels, no LLM. Each note is a measured tendency a coach would act on."
      />
      <div className="grid sm:grid-cols-2 gap-3">
        {notes.map((n, i) => {
          const c = NOTE_COLOR[n.kind];
          return (
            <Card key={i} delay={(Math.min(i + 1, 3)) as 1} className="border-l-2" >
              <div className="flex items-center gap-2 mb-1.5">
                <span
                  className="mono text-[9px] tracking-[0.16em] px-1.5 py-0.5 rounded"
                  style={{ color: c, background: "color-mix(in srgb, " + c + " 14%, transparent)" }}
                >
                  {n.kind.toUpperCase()}
                </span>
                <span className="font-semibold text-[13.5px]">{n.head}</span>
              </div>
              <p className="text-[12.5px] text-mut leading-snug">{n.body}</p>
            </Card>
          );
        })}
      </div>
    </section>
  );
}

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

function SideCard({ team, f, pair }: { team: Team; f: FormationSide; pair: string }) {
  const color = TEAM_COLOR[team];
  return (
    <Card>
      <div className="flex items-baseline justify-between gap-2">
        <div className="font-semibold text-[1.05rem]" style={{ color }}>
          {pair}
        </div>
        <span className="mono text-[10px] tracking-[0.16em] text-dim">TEAM {team}</span>
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
        <div key={`${p.set}-${p.slot}`}>
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

/** team A(left) vs team B(right) court-control split */
function ControlBar({ a, b }: { a: number; b: number }) {
  return (
    <div className="mt-2">
      <div className="h-3 w-full rounded-full overflow-hidden flex bg-[var(--line-soft)]">
        <div style={{ width: `${a}%`, background: TEAM_COLOR.A }} />
        <div style={{ width: `${b}%`, background: TEAM_COLOR.B }} />
      </div>
      <div className="flex justify-between mt-1 text-[11px] mono text-dim">
        <span style={{ color: TEAM_COLOR.A }}>{a.toFixed(0)}% A</span>
        <span style={{ color: TEAM_COLOR.B }}>{b.toFixed(0)}% B</span>
      </div>
    </div>
  );
}

function ControlSection({ d, goRally }: { d: DoublesMatch; goRally: (rally: number) => void }) {
  const c = d.control;
  if (!c || c.summary.A == null || c.summary.B == null) return null;
  const a = c.summary.A;
  const b = c.summary.B;
  const teamName = (t: Team) => d.meta.teams[t].split(" / ")[0];
  const top = [...c.rallies]
    .sort((x, y) => Math.abs(y.nearIndex) - Math.abs(x.nearIndex))
    .slice(0, 4);
  return (
    <section>
      <Section
        kicker="COURT CONTROL"
        title="Who owns the court"
        hint="Voronoi dominant region — each court point belongs to the team whose nearer player is closer; >50% means a pair commands more than its own half (a sign of attacking). A small static far-side bias sits under the raw share, so the most one-sided rallies are ranked by deviation from the match baseline."
      />
      <div className="grid md:grid-cols-2 gap-5">
        <Card>
          <div className="flex items-baseline justify-between">
            <span className="font-semibold text-[1.05rem]">Match control share</span>
            <span className="mono text-[10px] tracking-[0.16em] text-dim">VORONOI</span>
          </div>
          <ControlBar a={a} b={b} />
          <p className="text-[11px] text-dim mt-3 leading-snug">
            Frame-weighted over all rally play. Baseline {c.baseline.toFixed(0)}% near — the
            static far-side bias floor; rally swings are read against it.
          </p>
        </Card>
        <Card>
          <div className="font-semibold mb-3">Most one-sided rallies</div>
          <div className="space-y-1.5">
            {top.map((r) => {
              const dom = r.nearIndex >= 0 ? r.nearPair : r.farPair;
              return (
                <button
                  key={r.rally}
                  onClick={() => goRally(r.rally)}
                  className="flex items-center justify-between w-full text-[13px] rounded px-1.5 py-1 hover:bg-[var(--panel-solid)]/40"
                >
                  <span className="mono text-mut">#{r.rally}</span>
                  <span style={{ color: TEAM_COLOR[dom] }}>{teamName(dom)} dominated</span>
                  <span className="mono text-dim">+{Math.abs(r.nearIndex).toFixed(0)} pts</span>
                </button>
              );
            })}
          </div>
        </Card>
      </div>
    </section>
  );
}

/** LLM tactical report (optional — only renders once `doubles.commentary` has published). */
function AiAnalysis({ id }: { id: string }) {
  const { data } = useDoublesAnalysis(id);
  if (!data) return null;
  const c = data.commentary;
  return (
    <section>
      <Section
        kicker="AI ANALYSIS"
        title={c.headline}
        hint={`Generated by ${data.model} from the tracked formation, control, rotation and movement tactics — not from shot labels (doubles has none yet).`}
      />
      <Card className="mb-4">
        {c.match_story.split("\n").filter(Boolean).map((p, i) => (
          <p key={i} className="text-[13.5px] leading-relaxed text-mut mb-2 last:mb-0">{p}</p>
        ))}
        {c.turning_points.length > 0 && (
          <div className="mt-4 pt-3 border-t border-[var(--line-soft)]">
            <div className="kicker mb-2">TURNING POINTS</div>
            <ul className="space-y-1.5">
              {c.turning_points.map((t, i) => (
                <li key={i} className="text-[12.5px] text-mut leading-snug flex gap-2">
                  <span className="text-[var(--ai)]">▸</span>
                  <span>{t}</span>
                </li>
              ))}
            </ul>
          </div>
        )}
      </Card>
      <div className="grid md:grid-cols-2 gap-5">
        {c.pairs.map((p, i) => {
          const color = TEAM_COLOR[(i === 0 ? "A" : "B") as Team];
          return (
            <Card key={p.pair}>
              <div className="font-semibold text-[1.05rem] mb-1" style={{ color }}>{p.pair}</div>
              <p className="text-[12.5px] text-mut leading-snug mb-3">{p.overview}</p>
              <div className="space-y-3 text-[12.5px]">
                <AnalysisList head="STRENGTHS" items={p.strengths} c="var(--win)" />
                <AnalysisList head="WEAKNESSES" items={p.weaknesses} c="var(--warn)" />
                <AnalysisList head="TRAIN" items={p.training_priorities} c="var(--ai)" />
              </div>
              <p className="text-[12px] text-dim leading-snug mt-3 pt-3 border-t border-[var(--line-soft)]">
                <span className="font-medium text-mut">How to beat them: </span>{p.gameplan_against}
              </p>
            </Card>
          );
        })}
      </div>
    </section>
  );
}

function AnalysisList({ head, items, c }: { head: string; items: string[]; c: string }) {
  if (!items?.length) return null;
  return (
    <div>
      <div className="mono text-[9px] tracking-[0.16em] mb-1" style={{ color: c }}>{head}</div>
      <ul className="space-y-1">
        {items.map((s, i) => (
          <li key={i} className="text-mut leading-snug">{s}</li>
        ))}
      </ul>
    </div>
  );
}

export default function DoublesOverview({ d, goRally }: DoublesViewProps) {
  const { formation, players, rallies, meta, notes } = d;
  const multiSet = meta.nSets > 1;

  return (
    <div className="space-y-8 mt-2">
      <AiAnalysis id={meta.id} />

      <CoachNotes notes={notes} />

      <section>
        <Section
          kicker="FORMATION"
          title="Attack vs defence"
          hint={
            "Attack = the pair stacked front-to-back (one at the net, partner covering the rear). Defence = side-by-side, receiving a smash. Rotations count debounced flips between the two." +
            (multiSet ? " Aggregated across all sets — pairs swap ends each game, so stats follow the team, not the court side." : "")
          }
        />
        <div className="grid md:grid-cols-2 gap-5">
          {TEAMS.map((t) => (
            <SideCard key={t} team={t} f={formation[t]} pair={meta.teams[t]} />
          ))}
        </div>
      </section>

      {players.length > 0 && (
        <section>
          <Section
            kicker="ROLES"
            title="Who plays the net"
            hint={`Share of in-rally frames each player spent as the front (net) player of their pair${multiSet ? " — computed for the roster-named set(s)" : ""}. The net player attacks; their partner covers the rear.`}
          />
          <div className="grid md:grid-cols-2 gap-5">
            {TEAMS.map((t) => (
              <Card key={t}>
                <div className="font-semibold mb-3" style={{ color: TEAM_COLOR[t] }}>
                  {meta.teams[t]}
                </div>
                <NetHunters players={players.filter((p) => p.team === t)} color={TEAM_COLOR[t]} />
              </Card>
            ))}
          </div>
        </section>
      )}

      <ControlSection d={d} goRally={goRally} />

      <section>
        <Section
          kicker="RALLIES"
          title={`${rallies.length} tracked rallies`}
          hint="Per-rally attack share for each team. Click to watch the 4-player replay."
        />
        <Card className="!p-0 overflow-hidden">
          <table className="w-full text-[13px]">
            <thead>
              <tr className="text-left text-dim mono text-[10px] tracking-[0.1em] border-b border-[var(--line-soft)]">
                <th className="px-4 py-2.5">#</th>
                {multiSet && <th className="px-4 py-2.5">SET</th>}
                <th className="px-4 py-2.5">LENGTH</th>
                <th className="px-4 py-2.5" style={{ color: TEAM_COLOR.A }}>{meta.teams.A.split(" / ")[0]} ATTACK</th>
                <th className="px-4 py-2.5" style={{ color: TEAM_COLOR.B }}>{meta.teams.B.split(" / ")[0]} ATTACK</th>
                <th className="px-4 py-2.5">ROTATIONS</th>
                <th className="px-4 py-2.5"></th>
              </tr>
            </thead>
            <tbody>
              {rallies.map((r) => {
                const rot = (r.A?.rotations ?? 0) + (r.B?.rotations ?? 0);
                return (
                  <tr key={r.rally} className="border-b border-[var(--line-soft)] last:border-0 hover:bg-[var(--panel-solid)]/40">
                    <td className="px-4 py-2.5 mono text-mut">{r.rally}</td>
                    {multiSet && <td className="px-4 py-2.5 mono text-dim">{r.set}</td>}
                    <td className="px-4 py-2.5 mono text-dim">{fmtClock(r.durS)}</td>
                    <td className="px-4 py-2.5"><MiniBar pct={r.A?.attackPct ?? null} color={TEAM_COLOR.A} /></td>
                    <td className="px-4 py-2.5"><MiniBar pct={r.B?.attackPct ?? null} color={TEAM_COLOR.B} /></td>
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
