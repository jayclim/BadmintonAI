"use client";

import type { ViewProps } from "@/components/Dashboard";
import { Card, Dot, Metric, Section } from "@/components/ui";
import { Diverging, LengthCols, StackedShare } from "@/components/charts";
import type { P } from "@/lib/types";
import { SHOT_ORDER } from "@/lib/types";
import { PCOLOR, pct } from "@/lib/fmt";

export default function Points({ d, goFilm }: ViewProps) {
  const { meta, rallies, insights } = d;
  const names = meta.players;
  const pw = insights.pointsWon;
  const sv = insights.serveStats;
  const cl = insights.clutch;

  const enders = rallies.filter((r) => r.winner && r.category !== "—");
  const keysFor = (p: P, shot: string, won: boolean): [number, number][] =>
    enders
      .filter(
        (r) =>
          r.endHitter === p &&
          r.endShot === shot &&
          (won ? r.category === "Winner" : r.category !== "Winner"),
      )
      .map((r) => [r.set, r.rally]);

  const maxBar = Math.max(...insights.shotOutcomes.flatMap((o) => [o.w, o.e]), 1);

  return (
    <div className="space-y-8">
      <section>
        <Section
          kicker="RALLY-ENDERS BY SHOT"
          title="Weapons vs leaks"
          hint="Green = outright winners hit with that shot; red = points thrown away with it. The biggest red bar is the cheapest place to improve. Click a bar to watch those rallies."
        />
        <div className="grid lg:grid-cols-2 gap-4 [&>*]:min-w-0">
          {(["B", "A"] as P[]).map((p, i) => {
            const mine = insights.shotOutcomes
              .filter((o) => o.p === p)
              .sort((x, y) => y.w + y.e - (x.w + x.e));
            const leak = mine.reduce((m, o) => (o.e > (m?.e ?? 0) ? o : m), mine[0]);
            return (
              <Card key={p} delay={(i + 1) as 1}>
                <div className="flex items-center gap-2 mb-4">
                  <Dot p={p} />
                  <span className="disp text-[1.15rem] font-semibold" style={{ color: PCOLOR[p] }}>
                    {names[p]}
                  </span>
                  {leak && leak.e >= 4 && (
                    <span className="mono text-[10px] px-1.5 py-0.5 rounded border border-[var(--err)]/40 text-err ml-auto">
                      ⚠ LEAK: {leak.shot.toUpperCase()} ({leak.e})
                    </span>
                  )}
                </div>
                <Diverging
                  rows={mine.map((o) => ({ shot: o.shot, w: o.w, e: o.e }))}
                  max={maxBar}
                  onPick={(shot, won) =>
                    goFilm(
                      `${names[p]} — ${shot} ${won ? "winners" : "errors"}`,
                      keysFor(p, shot, won),
                    )
                  }
                />
              </Card>
            );
          })}
        </div>
      </section>

      <div className="rule" />

      <section className="grid lg:grid-cols-5 gap-4 [&>*]:min-w-0">
        <Card className="lg:col-span-3">
          <Section
            kicker="PATIENCE VS FIRST STRIKE"
            title="Who wins the long rallies?"
            hint="Win rate by rally length. A big gap is a game plan: shorten or extend points on purpose."
          />
          <LengthCols rows={insights.lengthBuckets} names={names} />
        </Card>
        <Card className="lg:col-span-2">
          <Section kicker="POINT SOURCES" title="How each player's points came" />
          <div className="space-y-5">
            {(["B", "A"] as P[]).map((p) => (
              <div key={p}>
                <div className="text-[13px] mb-1.5 font-semibold" style={{ color: PCOLOR[p] }}>
                  {names[p]} — {pw[p].points} points
                </div>
                <StackedShare
                  parts={[
                    { label: "own winners", value: pw[p].winners, color: "var(--win)" },
                    { label: "opponent out", value: pw[p].opp_out, color: "#b9846a" },
                    { label: "opponent net", value: pw[p].opp_net, color: "#8a6a5c" },
                    { label: "other", value: pw[p].opp_other, color: "#5d7069" },
                  ]}
                />
              </div>
            ))}
            <p className="text-dim text-[12px] leading-snug">
              Most elite singles points come off the opponent&apos;s racket — forcing errors
              matters as much as hitting winners.
            </p>
          </div>
        </Card>
      </section>

      <div className="rule" />

      <section className="grid lg:grid-cols-3 gap-4 [&>*]:min-w-0">
        {(["B", "A"] as P[]).map((p, i) => {
          const s = sv[p];
          const types = Object.entries(s.by_type).sort(
            (a, b) => SHOT_ORDER.indexOf(a[0]) - SHOT_ORDER.indexOf(b[0]),
          );
          return (
            <Card key={p} delay={(i + 1) as 1}>
              <Section kicker="SERVE & RECEIVE" title={names[p]} />
              <div className="grid grid-cols-2 gap-4 mb-4">
                <Metric
                  label="WON SERVING"
                  value={`${pct(s.serve_won, s.serve_n)}%`}
                  sub={`${s.serve_won}/${s.serve_n}`}
                  accent={PCOLOR[p]}
                />
                <Metric
                  label="WON RECEIVING"
                  value={`${pct(s.recv_won, s.recv_n)}%`}
                  sub={`${s.recv_won}/${s.recv_n}`}
                />
              </div>
              {types.length > 0 && (
                <div className="flex gap-5 flex-wrap">
                  {types.map(([t, g]) => (
                    <div key={t}>
                      <div className="mono text-[14px] font-semibold">
                        {pct(g.won, g.n)}%
                      </div>
                      <div className="text-[11px] text-dim">
                        {t} <span className="mono">({g.won}/{g.n})</span>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </Card>
          );
        })}

        <Card delay={3}>
          <Section
            kicker="FROM 18-ALL TERRITORY"
            title="Clutch points"
            hint="Points decided once either player reached 18."
          />
          <div className="flex items-end gap-6 mt-2">
            {(["B", "A"] as P[]).map((p) => (
              <div key={p}>
                <div className="bignum text-[3.4rem]" style={{ color: PCOLOR[p] }}>
                  {cl[p]?.won ?? 0}
                </div>
                <div className="kicker">{names[p]}</div>
              </div>
            ))}
            <div className="text-dim text-[12px] mono pb-3">of {cl.A?.n ?? 0}</div>
          </div>
          {(cl.A?.n ?? 0) > 0 && (
            <div className="mt-3">
              <button
                className="mono text-[11px] tracking-wide px-2.5 py-1 rounded border border-[var(--line)] text-mut hover:text-ink hover:border-[var(--mut)] transition-colors"
                onClick={() =>
                  goFilm(
                    "Clutch points (18+)",
                    rallies.filter((r) => r.clutch && r.winner).map((r) => [r.set, r.rally]),
                  )
                }
              >
                ▶ WATCH THE CLUTCH RALLIES
              </button>
            </div>
          )}
        </Card>
      </section>
    </div>
  );
}
