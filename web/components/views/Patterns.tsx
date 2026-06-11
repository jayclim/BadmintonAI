"use client";

import { useState } from "react";
import type { ViewProps } from "@/components/Dashboard";
import { Card, Dot, Pills, Section, WatchBtn } from "@/components/ui";
import { Butterfly, SplitBar } from "@/components/charts";
import type { P } from "@/lib/types";
import { SHOT_ORDER } from "@/lib/types";
import { PCOLOR } from "@/lib/fmt";

export default function Patterns({ d, src, goFilm }: ViewProps) {
  const { meta, insights } = d;
  const names = meta.players;
  const [plen, setPlen] = useState<"2 shots" | "3 shots">("2 shots");
  const pats = plen === "2 shots" ? insights.patterns2 : insights.patterns3;
  const ep = insights.errorPressure;
  const bh = insights.backhand;

  const mixRows = SHOT_ORDER.filter((s) => insights.shotMix.some((m) => m.shot === s)).map(
    (shot) => ({
      shot,
      a: insights.shotMix.find((m) => m.p === "A" && m.shot === shot)?.pct ?? 0,
      b: insights.shotMix.find((m) => m.p === "B" && m.shot === shot)?.pct ?? 0,
    }),
  );

  return (
    <div className="space-y-8">
      <section className="grid lg:grid-cols-5 gap-4">
        <Card className="lg:col-span-3">
          <Section
            kicker="REHEARSABLE SITUATIONS"
            title="Rally-ending exchanges"
            hint="The last shots before the point ended, and who profited. A lopsided pattern is drillable — recognize the setup shot and break it early."
          >
            <Pills options={["2 shots", "3 shots"] as const} value={plen} onChange={setPlen} />
          </Section>
          {pats.length === 0 && <p className="text-mut text-[13px]">Not enough repeated patterns.</p>}
          <div className="space-y-2">
            {pats.map((pt) => {
              const lean = Math.max(pt.a_wins, pt.b_wins) / pt.n;
              return (
                <div
                  key={pt.pattern}
                  className="grid grid-cols-[1.4fr_auto_1fr_auto] items-center gap-3 py-1.5 border-b border-[var(--line-soft)] last:border-0"
                >
                  <div className="text-[13.5px] truncate">
                    {pt.pattern}
                    {lean >= 0.75 && pt.n >= 4 && (
                      <span className="mono text-[9.5px] px-1.5 py-0.5 rounded border border-[var(--warn)]/50 text-warn ml-2">
                        LOPSIDED
                      </span>
                    )}
                  </div>
                  <div className="mono text-[12px] text-dim w-8 text-right">{pt.n}×</div>
                  <div className="flex items-center gap-2">
                    <span className="mono text-[11px]" style={{ color: PCOLOR.B }}>{pt.b_wins}</span>
                    <SplitBar a={pt.a_wins} b={pt.b_wins} />
                    <span className="mono text-[11px]" style={{ color: PCOLOR.A }}>{pt.a_wins}</span>
                  </div>
                  <WatchBtn n={pt.keys.length} onClick={() => goFilm(`Pattern: ${pt.pattern}`, pt.keys)} />
                </div>
              );
            })}
          </div>
        </Card>

        <Card className="lg:col-span-2 self-start">
          <Section
            kicker="RALLY CONSTRUCTION"
            title="Shot mix"
            hint="Share of each player's own shots — two styles side by side."
          />
          <Butterfly rows={mixRows} names={names} />
        </Card>
      </section>

      <div className="rule" />

      {/* coach scouting: if-then response matrix */}
      <section>
        <Section
          kicker="THE IF-THEN SCOUTING TABLE"
          title="How he answers"
          hint="When a shot comes at him, what does he play back — and how do those rallies end? Predictable answers are attackable: know the reply before he hits it, and be standing where it goes."
        />
        <div className="grid lg:grid-cols-2 gap-4">
          {(["B", "A"] as P[]).map((p, i) => (
            <Card key={p} delay={(i + 1) as 1}>
              <div className="text-[13.5px] font-semibold mb-3" style={{ color: PCOLOR[p] }}>
                {names[p]} — most predictable answers first
              </div>
              <div className="space-y-3">
                {[...insights.responseMatrix[p]]
                  .sort((x, y) => (y.replies[0]?.pct ?? 0) - (x.replies[0]?.pct ?? 0))
                  .slice(0, 5)
                  .map((t) => (
                    <div key={t.trigger} className="grid grid-cols-[120px_1fr] gap-3 items-start">
                      <div className="text-[12.5px] text-mut pt-0.5">
                        vs <b className="text-ink">{t.trigger}</b>
                        <span className="mono text-[10px] text-dim block">{t.n}×</span>
                      </div>
                      <div className="space-y-1">
                        {t.replies.map((r) => (
                          <div key={r.shot} className="flex items-center gap-2 text-[12px]">
                            <div className="w-24 truncate text-ink/85">{r.shot}</div>
                            <div className="flex-1 h-3 rounded-sm bg-[var(--line-soft)] overflow-hidden">
                              <div className="h-full" style={{ width: `${r.pct}%`, background: PCOLOR[p], opacity: 0.75 }} />
                            </div>
                            <span className="mono text-[10.5px] text-dim w-9 text-right">{r.pct}%</span>
                            {r.winPct != null && (
                              <span
                                className="mono text-[10px] w-14 text-right"
                                style={{ color: r.winPct >= 55 ? "var(--win)" : r.winPct <= 45 ? "var(--err)" : "var(--dim)" }}
                                title="how often he goes on to win the rally after this reply"
                              >
                                {r.winPct}% win
                              </span>
                            )}
                          </div>
                        ))}
                      </div>
                    </div>
                  ))}
              </div>
            </Card>
          ))}
        </div>
      </section>

      <div className="rule" />

      {/* opening playbook */}
      <section>
        <Section
          kicker="THE FIRST THREE SHOTS"
          title="Opening playbook"
          hint="Each serve, what comes back, and who profits. A return that drops the server's win rate is the receive to drill; a serve that holds 60%+ is the one to keep trusting."
        />
        <div className="grid lg:grid-cols-2 gap-4">
          {(["B", "A"] as P[]).map((p, i) => (
            <Card key={p} delay={(i + 1) as 1}>
              <div className="text-[13.5px] font-semibold mb-3" style={{ color: PCOLOR[p] }}>
                {names[p]} serving
              </div>
              <div className="space-y-4">
                {Object.entries(insights.openings[p])
                  .sort((a, b) => b[1].n - a[1].n)
                  .map(([st, o]) => (
                    <div key={st}>
                      <div className="flex items-baseline gap-2 mb-1.5">
                        <span className="text-[13px] text-ink">{st}</span>
                        <span className="mono text-[10.5px] text-dim">{o.n}×</span>
                        {o.winPct != null && (
                          <span
                            className="mono text-[11px] ml-auto"
                            style={{ color: o.winPct >= 55 ? "var(--win)" : o.winPct <= 45 ? "var(--err)" : "var(--mut)" }}
                          >
                            holds {o.winPct}%
                          </span>
                        )}
                      </div>
                      <div className="space-y-1 pl-3 border-l border-[var(--line-soft)]">
                        {o.returns.map((r) => (
                          <div key={r.shot} className="flex items-center gap-2 text-[12px]">
                            <span className="text-dim">↩</span>
                            <span className="w-28 truncate text-mut">{r.shot}</span>
                            <span className="mono text-[10.5px] text-dim">{r.pct}% of returns</span>
                            {r.srvWinPct != null && (
                              <span
                                className="mono text-[10.5px] ml-auto"
                                style={{ color: r.srvWinPct >= 55 ? "var(--win)" : r.srvWinPct <= 45 ? "var(--err)" : "var(--dim)" }}
                                title="server's win rate against this return"
                              >
                                server {r.srvWinPct}%
                              </span>
                            )}
                          </div>
                        ))}
                      </div>
                    </div>
                  ))}
              </div>
            </Card>
          ))}
        </div>
      </section>

      <div className="rule" />

      <section className="grid lg:grid-cols-2 gap-4">
        <Card>
          <Section
            kicker={`FORCED = SCRAMBLING AT ≥2.5 M/S`}
            title="Forced vs unforced errors"
            hint="Unforced errors came from a comfortable position — free points to claw back in training. Forced errors were earned by the opponent's placement."
          />
          <div className="space-y-4 mt-2">
            {(["B", "A"] as P[]).map((p) => {
              const e = ep[p];
              const known = e.forced + e.unforced || 1;
              return (
                <div key={p}>
                  <div className="flex items-baseline justify-between mb-1">
                    <span className="text-[13.5px] font-semibold" style={{ color: PCOLOR[p] }}>
                      {names[p]}
                    </span>
                    <span className="mono text-[11px] text-dim">
                      {e.unforced} unforced / {e.forced} forced
                      {e.unknown ? ` (+${e.unknown} unrated)` : ""}
                    </span>
                  </div>
                  <div className="flex h-5 rounded overflow-hidden">
                    <div
                      style={{ width: `${(100 * e.forced) / known}%`, background: "var(--warn)", opacity: 0.85 }}
                      title={`forced: ${e.forced}`}
                    />
                    <div
                      style={{ width: `${(100 * e.unforced) / known}%`, background: "var(--err)", opacity: 0.85 }}
                      title={`unforced: ${e.unforced}`}
                    />
                  </div>
                </div>
              );
            })}
            <div className="flex gap-4 text-[11.5px] text-mut">
              <span><span className="inline-block w-2 h-2 rounded-sm mr-1.5" style={{ background: "var(--warn)" }} />forced (scrambling)</span>
              <span><span className="inline-block w-2 h-2 rounded-sm mr-1.5" style={{ background: "var(--err)" }} />unforced (comfortable)</span>
            </div>
          </div>
        </Card>

        <Card>
          <Section
            kicker="WING TO ATTACK"
            title="Backhand vulnerability"
            hint="Backhand share of all shots vs backhand share of rally-ending errors — a big gap is a wing to attack (or fix)."
          />
          {bh ? (
            <div className="space-y-5 mt-2">
              {(["B", "A"] as P[]).map((p) => {
                const v = bh[p];
                return (
                  <div key={p}>
                    <div className="flex items-baseline justify-between mb-1">
                      <span className="text-[13.5px] font-semibold" style={{ color: PCOLOR[p] }}>
                        {names[p]}
                      </span>
                      <span className="mono text-[11px] text-dim">{v.n_err} backhand-rated errors</span>
                    </div>
                    <Dumbbell usage={v.usage_pct} err={v.err_pct} />
                  </div>
                );
              })}
              <p className="text-dim text-[11.5px]">
                ● usage share — ● share of own rally-ending errors. Gap ≥ 12 pts = exploitable.
              </p>
            </div>
          ) : (
            <div className="mt-3 p-4 rounded border border-dashed border-[var(--line)] text-[13px] text-mut leading-relaxed">
              Backhand detection needs wing-level labels that the CV chain doesn&apos;t infer yet
              — the pose model sees the body, not the grip. Honest gap, on the roadmap.
              {src === "ai" && (
                <span className="block mt-2 text-dim">
                  Switch to <b className="text-ink">GROUND TRUTH</b> to see the labeled version.
                </span>
              )}
            </div>
          )}
        </Card>
      </section>
    </div>
  );
}

function Dumbbell({ usage, err }: { usage: number; err: number }) {
  return (
    <div className="relative h-6">
      <div className="absolute inset-x-0 top-1/2 h-px bg-[var(--line)]" />
      <div
        className="absolute top-1/2 h-[3px] -translate-y-1/2 rounded"
        style={{
          left: `${Math.min(usage, err)}%`,
          width: `${Math.abs(err - usage)}%`,
          background: err > usage ? "var(--err)" : "var(--win)",
          opacity: 0.6,
        }}
      />
      <div className="absolute top-1/2 w-2.5 h-2.5 rounded-full -translate-y-1/2 -translate-x-1/2 border border-[#06130c]"
        style={{ left: `${usage}%`, background: "var(--mut)" }} title={`usage ${usage}%`} />
      <div className="absolute top-1/2 w-2.5 h-2.5 rounded-full -translate-y-1/2 -translate-x-1/2 border border-[#06130c]"
        style={{ left: `${err}%`, background: "var(--err)" }} title={`errors ${err}%`} />
      <span className="absolute -top-0.5 mono text-[10px] text-dim" style={{ left: `${Math.max(usage, err) + 3}%` }}>
        {usage}% → {err}%
      </span>
    </div>
  );
}
