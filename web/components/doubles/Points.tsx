"use client";

/* Doubles "Points" — the score story: a per-set worm (which team led, by how much, point
   by point), the biggest momentum run, win-rate by rally length, and — where CV strokes
   exist — the serve/receive split and how points end. Scores come from the per-rally
   scoreboard OCR + the set/side structure — honest caveat shown, since the broadcast cuts
   away on the final point and tracks-only segmentation slightly over-counts rallies. */

import { useMemo, useState } from "react";
import type { DoublesViewProps } from "@/components/DoublesDashboard";
import type { DoublesShots, PointsSet, ScorePoint, ServeReceive, ShotCount, Team } from "@/lib/doubles";
import { TEAM_COLOR, TEAMS } from "@/lib/doubles";
import { Card, Section, Metric } from "@/components/ui";

const shortPair = (name: string) => name.split(" / ").map((p) => p.split(" ")[0]).join("/");

/** team-keyed score worm: x = points played, y = lead (team A up, team B down). */
function Worm({
  set,
  names,
  finish,
  onPick,
}: {
  set: PointsSet;
  names: Record<Team, string>;
  finish?: DoublesShots["rallyFinish"];
  onPick: (rally: number) => void;
}) {
  const W = 460, H = 220, padX = 46, padY = 24;
  const [tip, setTip] = useState<{ x: number; y: number; p: ScorePoint } | null>(null);

  const { pts, maxLead, maxPt } = useMemo(() => {
    const pts = set.points.map((p) => ({ p, played: p.a + p.b, lead: p.a - p.b }));
    return {
      pts,
      maxLead: Math.max(3, ...pts.map((q) => Math.abs(q.lead))),
      maxPt: Math.max(1, ...pts.map((q) => q.played)),
    };
  }, [set]);

  const x = (played: number) => padX + ((W - 2 * padX) * played) / maxPt;
  const y = (lead: number) => H / 2 - ((H / 2 - padY) * lead) / maxLead;

  let path = "";
  let prev = 0;
  pts.forEach((q, i) => {
    if (i === 0) path = `M${x(0)},${y(0)} L${x(q.played)},${y(prev)} L${x(q.played)},${y(q.lead)}`;
    else path += ` L${x(q.played)},${y(prev)} L${x(q.played)},${y(q.lead)}`;
    prev = q.lead;
  });

  return (
    <div className="relative">
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full">
        <line x1={padX} y1={H / 2} x2={W - padX + 14} y2={H / 2} stroke="var(--line)" strokeDasharray="4 4" />
        <text x={padX - 6} y={padY + 4} textAnchor="end" fontSize={10} fill={TEAM_COLOR.A} className="mono">
          {shortPair(names.A)} ↑
        </text>
        <text x={padX - 6} y={H - padY + 2} textAnchor="end" fontSize={10} fill={TEAM_COLOR.B} className="mono">
          {shortPair(names.B)} ↓
        </text>
        <path d={path} fill="none" stroke="var(--worm-line)" strokeWidth={1.8} />
        {pts.map((q, i) => (
          <g
            key={i}
            transform={`translate(${x(q.played)},${y(q.lead)})`}
            className="cursor-pointer"
            onMouseEnter={() => setTip({ x: (x(q.played) / W) * 100, y: (y(q.lead) / H) * 100, p: q.p })}
            onMouseLeave={() => setTip(null)}
            onClick={() => onPick(q.p.rally)}
          >
            <circle r={9} fill="transparent" />
            <circle r={4.2} fill={TEAM_COLOR[q.p.winner]} stroke="var(--contact-ink)" strokeWidth={0.7} />
          </g>
        ))}
        {set.points.length > 0 && (
          <text x={Math.min(x(maxPt) + 8, W - 40)} y={y(set.final.a - set.final.b) + 4}
            fontSize={13} fontWeight={700} fill="var(--ink)" className="mono">
            {set.final.a}–{set.final.b}
          </text>
        )}
        <text x={W / 2} y={H - 4} textAnchor="middle" fontSize={10} fill="var(--dim)" className="mono">
          SET {set.set} — POINTS PLAYED
        </text>
      </svg>
      {tip && (
        <div className="absolute z-20 pointer-events-none" style={{ left: `${tip.x}%`, top: `${tip.y}%` }}>
          <div className="card px-2.5 py-1.5 text-[11.5px] -translate-x-1/2 -translate-y-[calc(100%+8px)] whitespace-nowrap">
            <div className="mono font-semibold">{tip.p.a}–{tip.p.b}</div>
            <div>
              <span style={{ color: TEAM_COLOR[tip.p.winner] }}>{shortPair(names[tip.p.winner])}</span> won it
            </div>
            {finish?.[String(tip.p.rally)] && (
              <div className="text-dim">
                final shot · {finish[String(tip.p.rally)].shot}
                {finish[String(tip.p.rally)].team !== tip.p.winner && " (didn't come back)"}
              </div>
            )}
            <div className="text-dim mt-0.5">click to watch</div>
          </div>
        </div>
      )}
    </div>
  );
}

/** win-rate by rally length (short ≤6s · mid ≤12s · long) as paired team bars */
function LengthBars({ lengthWins, names }: {
  lengthWins: Record<Team, { short: number; mid: number; long: number }>;
  names: Record<Team, string>;
}) {
  const buckets: ("short" | "mid" | "long")[] = ["short", "mid", "long"];
  const labels = { short: "SHORT ≤6s", mid: "MID ≤12s", long: "LONG 12s+" };
  return (
    <div className="space-y-4">
      {buckets.map((bk) => {
        const a = lengthWins.A[bk], b = lengthWins.B[bk];
        const tot = Math.max(1, a + b);
        return (
          <div key={bk}>
            <div className="flex justify-between mono text-[11px] text-dim mb-1">
              <span>{labels[bk]}</span>
              <span>{a + b} points</span>
            </div>
            <div className="flex h-3 rounded-full overflow-hidden bg-[var(--line-soft)]">
              <div style={{ width: `${(100 * a) / tot}%`, background: TEAM_COLOR.A }} title={`${names.A}: ${a}`} />
              <div style={{ width: `${(100 * b) / tot}%`, background: TEAM_COLOR.B }} title={`${names.B}: ${b}`} />
            </div>
            <div className="flex justify-between mono text-[10.5px] mt-1">
              <span style={{ color: TEAM_COLOR.A }}>{a}</span>
              <span style={{ color: TEAM_COLOR.B }}>{b}</span>
            </div>
          </div>
        );
      })}
    </div>
  );
}

/** points won serving vs receiving, one row per team (doubles' side-out stat) */
function ServeReceiveRows({ sr, names }: {
  sr: Record<Team, ServeReceive>;
  names: Record<Team, string>;
}) {
  const bar = (won: number, played: number, color: string) => (
    <div>
      <div className="h-3 rounded-full overflow-hidden bg-[var(--line-soft)]">
        <div className="h-full" style={{ width: `${played ? (100 * won) / played : 0}%`, background: color }} />
      </div>
      <div className="mono text-[10.5px] text-dim mt-1">
        {won}/{played} · {played ? Math.round((100 * won) / played) : 0}%
      </div>
    </div>
  );
  return (
    <div className="space-y-4 mt-2">
      {TEAMS.map((t) => (
        <div key={t}>
          <div className="mono text-[11px] mb-1.5" style={{ color: TEAM_COLOR[t] }}>
            {shortPair(names[t])}
          </div>
          <div className="grid grid-cols-2 gap-4">
            <div>
              <div className="mono text-[10px] text-dim mb-1">WON SERVING</div>
              {bar(sr[t].serveWon, sr[t].servePlayed, TEAM_COLOR[t])}
            </div>
            <div>
              <div className="mono text-[10px] text-dim mb-1">WON RECEIVING</div>
              {bar(sr[t].recvWon, sr[t].recvPlayed, TEAM_COLOR[t])}
            </div>
          </div>
        </div>
      ))}
    </div>
  );
}

/** how points end: the winner's finishing shots vs the loser's shot that didn't come back */
function Finishers({ fin, names }: {
  fin: { won: Record<Team, ShotCount[]>; lost: Record<Team, ShotCount[]> };
  names: Record<Team, string>;
}) {
  const chips = (rows: ShotCount[], n: number) =>
    rows.slice(0, n).map((s) => (
      <span key={s.shot} className="text-[11px] px-1.5 py-0.5 rounded mono"
        style={{ background: "var(--panel-solid)", color: "var(--ink)" }}>
        {s.shot} <span className="text-dim">{s.n}</span>
      </span>
    ));
  return (
    <div className="space-y-4 mt-2">
      {TEAMS.map((t) => (
        <div key={t}>
          <div className="mono text-[11px] mb-1.5" style={{ color: TEAM_COLOR[t] }}>
            {shortPair(names[t])}
          </div>
          <div className="flex items-baseline gap-2 flex-wrap text-[11.5px]">
            <span className="mono text-[10px] text-dim shrink-0 w-20">FINISH WITH</span>
            {chips(fin.won[t], 3)}
          </div>
          <div className="flex items-baseline gap-2 flex-wrap text-[11.5px] mt-1.5">
            <span className="mono text-[10px] text-dim shrink-0 w-20">LOSE ON</span>
            {chips(fin.lost[t], 3)}
          </div>
        </div>
      ))}
    </div>
  );
}

export default function DoublesPoints({ d, goRally }: DoublesViewProps) {
  const { points: p, meta, shots } = d;

  if (!p || p.sets.length === 0) {
    return (
      <Card className="mt-6">
        <p className="text-mut text-[13px]">
          No score trajectory — the scoreboard OCR couldn&apos;t be read for this match.
        </p>
      </Card>
    );
  }

  const setsWonA = p.sets.filter((s) => s.winner === "A").length;
  const setsWonB = p.sets.filter((s) => s.winner === "B").length;

  return (
    <div className="space-y-8 mt-2">
      <section>
        <Section
          kicker="THE SCORE STORY"
          title="How each game was won"
          hint="The lead, point by point, read off the broadcast scoreboard. Above the centre line one team leads; below, the other. Each dot is a point — click to watch that rally."
        />
        <div className="grid lg:grid-cols-3 gap-5">
          {p.sets.map((s) => (
            <Card key={s.set}>
              <div className="flex items-baseline justify-between mb-1">
                <span className="kicker">SET {s.set}</span>
                {s.winner && (
                  <span className="mono text-[11px]" style={{ color: TEAM_COLOR[s.winner] }}>
                    {shortPair(meta.teams[s.winner])} took it
                  </span>
                )}
              </div>
              <Worm set={s} names={meta.teams} finish={shots?.rallyFinish} onPick={goRally} />
            </Card>
          ))}
        </div>
      </section>

      <section className="grid lg:grid-cols-3 gap-5 [&>*]:min-w-0">
        <Card>
          <Section kicker="MATCH" title="Sets won" />
          <div className="flex items-end gap-8 mt-2">
            {TEAMS.map((t) => (
              <div key={t}>
                <div className="bignum text-[3.2rem]" style={{ color: TEAM_COLOR[t] }}>
                  {t === "A" ? setsWonA : setsWonB}
                </div>
                <div className="kicker truncate max-w-[140px]">{shortPair(meta.teams[t])}</div>
              </div>
            ))}
          </div>
          {meta.result && (
            <div className="mono text-[12px] text-dim mt-4">
              official · {meta.result.replace(/\s+/g, "  ·  ")}
            </div>
          )}
        </Card>

        <Card>
          <Section kicker="MOMENTUM" title="Longest point run" hint="Most consecutive points won — a swing of momentum within a game." />
          <div className="flex items-end gap-8 mt-2">
            {TEAMS.map((t) => (
              <div key={t}>
                <div className="bignum text-[3.2rem]" style={{ color: TEAM_COLOR[t] }}>
                  {p.runs[t]}
                </div>
                <div className="kicker truncate max-w-[140px]">{shortPair(meta.teams[t])}</div>
              </div>
            ))}
          </div>
        </Card>

        <Card>
          <Section kicker="POINT LENGTH" title="Who wins short vs long" hint="Points won, split by rally duration — long-rally wins point to endurance, short-rally wins to fast starts." />
          <LengthBars lengthWins={p.lengthWins} names={meta.teams} />
        </Card>
      </section>

      {shots?.serveReceive && shots?.finishers && (
        <section className="grid lg:grid-cols-2 gap-5 [&>*]:min-w-0">
          <Card>
            <Section
              kicker="SERVE & RECEIVE"
              title="Points won serving vs receiving"
              hint="Doubles' side-out stat — the serving pair concedes the attack, so elite pairs win more receiving. The server comes from the score itself (the winner of a point serves the next); each game's first scored point has no predecessor and is skipped."
            />
            <ServeReceiveRows sr={shots.serveReceive} names={meta.teams} />
          </Card>
          <Card>
            <Section
              kicker="HOW POINTS END"
              title="Finishing shots"
              hint="Each scored rally's last CV-detected stroke. Hit by the winner = the shot that finished the point; hit by the loser = the shot that didn't come back (an error, or got punished — CV can't split those). Shot types are the unvalidated geometry baseline."
            />
            <Finishers fin={shots.finishers} names={meta.teams} />
          </Card>
        </section>
      )}

      <p className="text-dim text-[12px] leading-snug max-w-3xl">
        Scores are read from the broadcast scoreboard graphic by OCR over the segmented
        rallies — no human labels. The worm tracks the scoreboard, so a game&apos;s final
        point can be missed when the broadcast cuts away (the official scoreline is shown
        above); rally segmentation is tracks-only and can slightly over-count. The shape of
        each game — leads, runs, swings — is what to read here.
      </p>
    </div>
  );
}
