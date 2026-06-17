"use client";

import { useSearchParams } from "next/navigation";
import { useMemo } from "react";
import type { DoublesViewProps } from "@/components/DoublesDashboard";
import type { DSide } from "@/lib/doubles";
import { useDoublesReplay } from "@/lib/doubles";
import { DoublesReplay2D, FormationTimeline } from "@/components/doubles/court4";
import { Card, Section } from "@/components/ui";
import { fmtClock, ytEmbed } from "@/lib/fmt";

const SIDE_COLOR: Record<DSide, string> = { near: "var(--pa)", far: "var(--pb)" };

export default function DoublesFilm({ d, id, goRally }: DoublesViewProps) {
  const sp = useSearchParams();
  const rallyParam = Number(sp.get("r"));
  const rally = useMemo(() => {
    const ids = d.rallies.map((r) => r.rally);
    return ids.includes(rallyParam) ? rallyParam : (ids[0] ?? 1);
  }, [rallyParam, d.rallies]);

  const { data: rep, error } = useDoublesReplay(id, rally);
  const meta = d.meta;
  const row = d.rallies.find((r) => r.rally === rally);

  return (
    <div className="space-y-6 mt-2">
      <Section
        kicker="FILM ROOM"
        title="4-player replay"
        hint="Reconstructed from tracking: each player a dot in true court metres. The FRONT (net) player of each pair is solid; the partner covering the rear is ringed. Front/back is recomputed every frame from geometry, so it survives identity swaps."
      />

      {/* rally picker */}
      <div className="flex flex-wrap gap-1.5">
        {d.rallies.map((r) => {
          const on = r.rally === rally;
          return (
            <button
              key={r.rally}
              onClick={() => goRally(r.rally)}
              className="px-3 py-1.5 rounded-md text-[12.5px] border transition-colors mono"
              style={{
                borderColor: on ? "var(--ai)" : "var(--line)",
                color: on ? "var(--ai)" : "var(--mut)",
                background: on ? "var(--ai-soft)" : "transparent",
                fontWeight: on ? 600 : 400,
              }}
            >
              R{r.rally} · {fmtClock(r.durS)}
            </button>
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
          {meta.youtubeId && row && (
            <div className="aspect-video rounded-md overflow-hidden border border-[var(--line)] bg-black">
              <iframe
                key={`${rally}-yt`}
                src={ytEmbed(meta.youtubeId, row.t0, row.t1)}
                className="w-full h-full"
                allow="autoplay; encrypted-media; picture-in-picture"
                allowFullScreen
                title="rally clip"
              />
            </div>
          )}

          {rep && (
            <Card>
              <div className="kicker mb-3">FORMATION TIMELINE</div>
              <div className="space-y-3">
                {(["far", "near"] as DSide[]).map((side) => (
                  <div key={side}>
                    <div className="flex justify-between text-[11px] mono mb-1">
                      <span style={{ color: SIDE_COLOR[side] }}>{meta.pairs[side]}</span>
                      <span className="text-dim">
                        {row?.[side]?.attackPct?.toFixed(0) ?? "—"}% attack
                      </span>
                    </div>
                    <FormationTimeline
                      segs={rep.form[side]}
                      f0={rep.f0}
                      f1={rep.f1}
                      color={SIDE_COLOR[side]}
                    />
                  </div>
                ))}
              </div>
              <div className="text-[11px] text-dim mono mt-3">
                filled = attack (front/back stack) · faint = defence (side-by-side)
              </div>
            </Card>
          )}

          {row && (
            <Card>
              <div className="kicker mb-3">RALLY {row.rally} TACTICS</div>
              <div className="grid grid-cols-2 gap-4">
                {(["near", "far"] as DSide[]).map((side) => (
                  <div key={side}>
                    <div className="font-medium text-[13px] mb-1.5" style={{ color: SIDE_COLOR[side] }}>
                      {meta.pairs[side]}
                    </div>
                    <ul className="text-[12.5px] text-mut space-y-1 mono">
                      <li>attack {row[side]?.attackPct?.toFixed(0) ?? "—"}%</li>
                      <li>{row[side]?.rotations ?? 0} rotations</li>
                      <li>{row[side]?.frontSwaps ?? 0} front swaps</li>
                    </ul>
                  </div>
                ))}
              </div>
            </Card>
          )}
        </div>
      </div>
    </div>
  );
}
