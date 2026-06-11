"use client";

import type { ViewProps } from "@/components/Dashboard";
import { Card, Dot, Metric, Section, WatchBtn, AiTag } from "@/components/ui";
import { Worm } from "@/components/charts";
import { Md } from "@/components/md";
import type { P } from "@/lib/types";
import { PCOLOR } from "@/lib/fmt";

export default function Overview({ d, src, goFilm, goRally }: ViewProps) {
  const { meta, rallies, insights, movement, commentary } = d;
  const names = meta.players;
  const sets = [...new Set(rallies.map((r) => r.set))].sort();
  const pw = insights.pointsWon;
  const ps = insights.pressureSummary;

  return (
    <div className="space-y-8">
      {/* score worm */}
      <section>
        <Section
          kicker="THE MATCH IN ONE PICTURE"
          title="Who led, point by point"
          hint="Step line = the point lead. ◆ = clutch points (either player at 18+). Hover any point for the story; click to watch the rally."
        />
        <div className="grid lg:grid-cols-2 gap-4">
          {sets.map((sn, i) => (
            <Card key={sn} delay={(i + 1) as 1}>
              <Worm rallies={rallies} names={names} setNo={sn} onPick={goRally} />
            </Card>
          ))}
        </div>
      </section>

      {/* stat duel */}
      <section>
        <div className="rule mb-5" />
        <div className="grid md:grid-cols-2 gap-4">
          {(["B", "A"] as P[]).map((p, i) => {
            const o = p === "A" ? "B" : "A";
            const errs = pw[o].opp_out + pw[o].opp_net + pw[o].opp_other;
            const mov = movement[p];
            return (
              <Card key={p} delay={(i + 1) as 1}>
                <div className="flex items-center gap-2 mb-4">
                  <Dot p={p} />
                  <span className="disp text-[1.25rem] font-semibold" style={{ color: PCOLOR[p] }}>
                    {names[p]}
                  </span>
                  {meta.winner === p && <span className="text-[13px]">🏆</span>}
                </div>
                <div className="grid grid-cols-5 gap-3">
                  <Metric label="POINTS" value={pw[p].points} />
                  <Metric label="WINNERS" value={pw[p].winners} accent="var(--win)" />
                  <Metric label="ERRORS" value={errs} accent="var(--err)" />
                  <Metric label="BEST RUN" value={insights.longestRun[p] ?? 0} />
                  {mov ? (
                    <Metric label="RAN" value={`${(mov.distM / 1000).toFixed(1)}k`} sub="metres" />
                  ) : (
                    <Metric label="PRESSURE" value={ps[p].applied} sub="m/s applied" />
                  )}
                </div>
              </Card>
            );
          })}
        </div>
        <p className="text-dim text-[12px] mt-2">
          Errors = rally-ending mistakes gifted to the opponent. Distance from the CV player
          tracks, side-swap corrected per set.
        </p>
      </section>

      {/* coach's notes */}
      <section>
        <Section
          kicker="AUTO-READ FROM THE DATA"
          title="Coach's notes"
          hint="Rule-based findings ranked by how much they mattered. Every card links to the exact rallies behind it."
        >
          {src === "ai" && <AiTag text="AI-DERIVED" />}
        </Section>
        {insights.notes.length === 0 && (
          <Card>
            <p className="text-mut text-[14px]">Not enough rallies to generate insights.</p>
          </Card>
        )}
        <div className="grid md:grid-cols-2 gap-4">
          {insights.notes.slice(0, 6).map((n, i) => (
            <Card key={n.title} delay={Math.min(i + 1, 5) as 1} className="flex flex-col">
              <div className="flex items-start gap-3">
                <span className="text-[1.4rem] leading-none mt-0.5">{n.icon}</span>
                <div>
                  <div className="font-semibold text-[15.5px] leading-snug">{n.title}</div>
                  <p className="text-mut text-[13.5px] leading-relaxed mt-1.5">{n.body}</p>
                </div>
              </div>
              {n.keys.length > 0 && (
                <div className="mt-auto pt-3">
                  <WatchBtn n={n.keys.length} onClick={() => goFilm(n.title, n.keys)} />
                </div>
              )}
            </Card>
          ))}
        </div>
      </section>

      {/* LLM commentary */}
      {commentary && (
        <section>
          <Section
            kicker="AI MATCH REPORT"
            title={commentary.commentary.headline}
            hint={`Written by ${commentary.provider ?? "an LLM"} (${commentary.model ?? "?"}) from the statistical dossier — no video sent.`}
          />
          <Card className="mb-4">
            <p className="text-[14.5px] leading-relaxed text-ink/90">
              <Md>{commentary.commentary.match_story}</Md>
            </p>
            <div className="mt-4">
              <div className="kicker mb-2">TURNING POINTS</div>
              <ul className="space-y-1.5">
                {commentary.commentary.turning_points.map((t, i) => (
                  <li key={i} className="text-[13.5px] text-mut flex gap-2">
                    <span style={{ color: "var(--warn)" }}>⚡</span> <span><Md>{t}</Md></span>
                  </li>
                ))}
              </ul>
            </div>
          </Card>
          <div className="grid md:grid-cols-2 gap-4">
            {(["B", "A"] as P[]).map((key) => {
              const rep = commentary.commentary.players.find((x) => x.name === names[key]);
              if (!rep) return null;
              return (
                <Card key={key}>
                  <div className="disp text-[1.15rem] font-semibold mb-2" style={{ color: PCOLOR[key] }}>
                    {rep.name}
                  </div>
                  <p className="text-[13.5px] text-mut leading-relaxed mb-3"><Md>{rep.overview}</Md></p>
                  <NoteList title="🗡 STRENGTHS" items={rep.strengths} />
                  <NoteList title="⚠ WEAKNESSES" items={rep.weaknesses} />
                  <NoteList title="🏋 TRAIN NEXT" items={rep.training_priorities} />
                  <div className="kicker mt-3 mb-1">HOW TO BEAT HIM</div>
                  <p className="text-[13.5px] text-ink/85 leading-relaxed"><Md>{rep.gameplan_against}</Md></p>
                </Card>
              );
            })}
          </div>
        </section>
      )}
    </div>
  );
}

function NoteList({ title, items }: { title: string; items: string[] }) {
  return (
    <div className="mb-3">
      <div className="kicker mb-1">{title}</div>
      <ul className="space-y-1">
        {items.map((s, i) => (
          <li key={i} className="text-[13px] text-mut leading-snug">
            · <Md>{s}</Md>
          </li>
        ))}
      </ul>
    </div>
  );
}
