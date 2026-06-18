"use client";

import { useSearchParams } from "next/navigation";
import { useMemo } from "react";
import type { DoublesViewProps } from "@/components/DoublesDashboard";
import type { DSide, Team } from "@/lib/doubles";
import { TEAM_COLOR, useDoublesReplay } from "@/lib/doubles";
import { DoublesReplay2D, DoublesVideo, FormationTimeline } from "@/components/doubles/court4";
import { Card, Section } from "@/components/ui";
import { fmtClock } from "@/lib/fmt";

export default function DoublesFilm({ d, id, goRally }: DoublesViewProps) {
  const sp = useSearchParams();
  const rallyParam = Number(sp.get("r"));
  const rally = useMemo(() => {
    const ids = d.rallies.map((r) => r.rally);
    return ids.includes(rallyParam) ? rallyParam : (ids[0] ?? 1);
  }, [rallyParam, d.rallies]);

  const { data: rep, error } = useDoublesReplay(id, rally);
  const meta = d.meta;
  const multiSet = meta.nSets > 1;
  const row = d.rallies.find((r) => r.rally === rally);
  // team occupying each court side this rally (geometric near/far → fixed team A/B)
  const teamOf = (side: DSide): Team =>
    side === "near" ? row?.nearPair ?? "A" : row?.farPair ?? "B";

  return (
    <div className="space-y-6 mt-2">
      <Section
        kicker="FILM ROOM"
        title="4-player replay"
        hint="Reconstructed from tracking: each player a dot in true court metres. The FRONT (net) player of each pair is solid; the partner covering the rear is ringed. Front/back is recomputed every frame from geometry, so it survives identity swaps."
      />

      {/* rally picker — grouped by set, scrollable (a full match is 150+ rallies) */}
      <div className="max-h-[168px] overflow-y-auto pr-1 space-y-2 [scrollbar-width:thin]">
        {Array.from({ length: meta.nSets }, (_, i) => i + 1).map((sn) => {
          const setRallies = d.rallies.filter((r) => r.set === sn);
          if (setRallies.length === 0) return null;
          return (
            <div key={sn} className="flex flex-wrap items-center gap-1.5">
              {multiSet && (
                <span className="mono text-[10px] tracking-[0.14em] text-dim w-12 shrink-0">
                  SET {sn}
                </span>
              )}
              {setRallies.map((r) => {
                const on = r.rally === rally;
                return (
                  <button
                    key={r.rally}
                    onClick={() => goRally(r.rally)}
                    title={`rally ${r.rally} · ${fmtClock(r.durS)}`}
                    className="px-2 py-1 rounded text-[11px] border transition-colors mono"
                    style={{
                      borderColor: on ? "var(--ai)" : "var(--line)",
                      color: on ? "var(--ai)" : "var(--mut)",
                      background: on ? "var(--ai-soft)" : "transparent",
                      fontWeight: on ? 600 : 400,
                    }}
                  >
                    {r.rally}
                  </button>
                );
              })}
            </div>
          );
        })}
      </div>

      <div className="grid lg:grid-cols-[minmax(0,380px)_1fr] gap-5 items-start">
        <Card>
          {error && <div className="text-err text-[13px]">Failed to load replay: {error}</div>}
          {!rep && !error && (
            <div className="py-24 text-center text-dim mono text-[12px] animate-pulse">
              LOADING REPLAY…
            </div>
          )}
          {rep && <DoublesReplay2D rep={rep} />}
        </Card>

        <div className="space-y-5">
          {row && <DoublesVideo row={row} youtubeId={meta.youtubeId} />}

          {rep && (
            <Card>
              <div className="kicker mb-3">
                FORMATION TIMELINE{multiSet && row ? ` · SET ${row.set}` : ""}
              </div>
              <div className="space-y-3">
                {(["far", "near"] as DSide[]).map((side) => {
                  const team = teamOf(side);
                  return (
                    <div key={side}>
                      <div className="flex justify-between text-[11px] mono mb-1">
                        <span style={{ color: TEAM_COLOR[team] }}>{meta.teams[team]}</span>
                        <span className="text-dim">
                          {row?.[team]?.attackPct?.toFixed(0) ?? "—"}% attack ·{" "}
                          {Math.max(0, rep.form[side].length - 1)} rotations
                        </span>
                      </div>
                      <FormationTimeline
                        segs={rep.form[side]}
                        f0={rep.f0}
                        f1={rep.f1}
                        color={TEAM_COLOR[team]}
                        marks
                      />
                    </div>
                  );
                })}
              </div>
              <div className="text-[11px] text-dim mono mt-3">
                filled = attack (front/back stack) · faint = defence (side-by-side) ·{" "}
                <span style={{ color: "var(--ink)" }}>│</span> = rotation
              </div>
            </Card>
          )}

          {row && (
            <Card>
              <div className="kicker mb-3">RALLY {row.rally} TACTICS</div>
              <div className="grid grid-cols-2 gap-4">
                {(["near", "far"] as DSide[]).map((side) => {
                  const team = teamOf(side);
                  return (
                    <div key={side}>
                      <div className="font-medium text-[13px] mb-1.5" style={{ color: TEAM_COLOR[team] }}>
                        {meta.teams[team]}
                      </div>
                      <ul className="text-[12.5px] text-mut space-y-1 mono">
                        <li>attack {row[team]?.attackPct?.toFixed(0) ?? "—"}%</li>
                        <li>{row[team]?.rotations ?? 0} rotations</li>
                        <li>{row[team]?.frontSwaps ?? 0} front swaps</li>
                      </ul>
                    </div>
                  );
                })}
              </div>
            </Card>
          )}
        </div>
      </div>
    </div>
  );
}
