"use client";

import { useMemo, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import type { ViewProps } from "@/components/Dashboard";
import { AiTag, Card, Select } from "@/components/ui";
import { Replay2D, RallyMap } from "@/components/court";
import RallyVideo from "@/components/RallyVideo";
import { useReplay } from "@/lib/data";
import type { Rally } from "@/lib/types";
import { PCOLOR, PHEX, ytLink } from "@/lib/fmt";

export default function Film({ d, id, src }: ViewProps) {
  const { meta, rallies, strokes } = d;
  const names = meta.players;
  const router = useRouter();
  const sp = useSearchParams();

  // evidence preset (?title&keys=1-2.1-7) or direct rally (?r=1-5)
  const preset = useMemo(() => {
    const keys = sp.get("keys");
    if (!keys) return null;
    return {
      title: sp.get("title") ?? "selection",
      keys: new Set(keys.split(".").map((k) => k.trim())),
    };
  }, [sp]);
  const directR = sp.get("r");

  const [setSel, setSetSel] = useState("All");
  const [winSel, setWinSel] = useState("Either player");
  const [catSel, setCatSel] = useState("Anything");
  const [shotSel, setShotSel] = useState("Any");
  const [lenSel, setLenSel] = useState("Any");
  const [sortSel, setSortSel] = useState("Match order");

  const filtered = useMemo(() => {
    let f = [...rallies];
    if (preset) f = f.filter((r) => preset.keys.has(`${r.set}-${r.rally}`));
    else {
      if (setSel !== "All") f = f.filter((r) => r.set === Number(setSel));
      if (winSel !== "Either player") f = f.filter((r) => r.winner && names[r.winner] === winSel);
      if (catSel !== "Anything") f = f.filter((r) => r.category === catSel);
      if (shotSel !== "Any") f = f.filter((r) => r.endShot === shotSel);
      if (lenSel !== "Any") f = f.filter((r) => r.bucket === lenSel);
      if (sortSel === "Longest first") f.sort((a, b) => b.durS - a.durS);
      else if (sortSel === "Most shots") f.sort((a, b) => b.shots - a.shots);
      else if (sortSel === "Clutch first")
        f.sort((a, b) => Number(b.clutch) - Number(a.clutch) || a.set - b.set || a.rally - b.rally);
    }
    return f;
  }, [rallies, preset, setSel, winSel, catSel, shotSel, lenSel, sortSel, names]);

  const [selKey, setSelKey] = useState<string | null>(directR);
  const sel: Rally | undefined =
    filtered.find((r) => `${r.set}-${r.rally}` === selKey) ?? filtered[0];

  const rep = useReplay(id, src, sel?.set ?? null, sel?.rally ?? null);
  const selStrokes = useMemo(
    () =>
      sel
        ? strokes
            .filter((s) => s.set === sel.set && s.rally === sel.rally)
            .sort((a, b) => a.br - b.br)
        : [],
    [strokes, sel],
  );

  const cats = ["Anything", ...new Set(rallies.map((r) => r.category).filter((c) => c !== "—"))];
  const endShots = ["Any", ...new Set(rallies.map((r) => r.endShot))].sort();

  return (
    <div className="space-y-4">
      {preset ? (
        <div className="card rise px-4 py-2.5 flex items-center gap-3 text-[13.5px]">
          <span className="kicker shrink-0">EVIDENCE</span>
          <span className="text-ink/90">
            the <b className="mono">{filtered.length}</b> rallies behind:{" "}
            <i>{preset.title}</i>
          </span>
          <button
            onClick={() => router.push(`/m/${id}/${src}/film/`)}
            className="ml-auto mono text-[11px] px-2.5 py-1 rounded border border-[var(--line)] text-mut hover:text-ink"
          >
            ✕ CLEAR
          </button>
        </div>
      ) : (
        <div className="card rise px-4 py-3 grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3">
          <Select label="SET" value={setSel} onChange={setSetSel}
            options={["All", ...new Set(rallies.map((r) => String(r.set)))]} />
          <Select label="POINT TO" value={winSel} onChange={setWinSel}
            options={["Either player", names.B, names.A]} />
          <Select label="ENDED BY" value={catSel} onChange={setCatSel} options={cats} />
          <Select label="FINAL SHOT" value={shotSel} onChange={setShotSel} options={endShots} />
          <Select label="LENGTH" value={lenSel} onChange={setLenSel}
            options={["Any", "short (≤4)", "mid (5–9)", "long (10+)"]} />
          <Select label="SORT" value={sortSel} onChange={setSortSel}
            options={["Match order", "Longest first", "Most shots", "Clutch first"]} />
        </div>
      )}

      <div className="grid lg:grid-cols-[0.95fr_1.5fr] gap-4 items-start">
        {/* rally list */}
        <Card className="rise-1 !p-0 overflow-hidden">
          <div className="px-4 py-2.5 border-b border-[var(--line-soft)] kicker">
            {filtered.length} RALLIES — SCORE IS A–B AFTER THE RALLY · ❄ CLUTCH
          </div>
          <div className="max-h-[520px] overflow-y-auto">
            {filtered.map((r) => {
              const on = sel && r.set === sel.set && r.rally === sel.rally;
              return (
                <button
                  key={`${r.set}-${r.rally}`}
                  onClick={() => setSelKey(`${r.set}-${r.rally}`)}
                  className="w-full text-left px-4 py-2 grid grid-cols-[64px_1fr_44px_40px] gap-2 items-baseline border-b border-[var(--line-soft)] last:border-0 transition-colors"
                  style={{ background: on ? "var(--panel-solid)" : "transparent" }}
                >
                  <span className="mono text-[13px] font-semibold">
                    {r.a}–{r.b}
                    {r.clutch && <span className="text-[10px]"> ❄</span>}
                  </span>
                  <span className="text-[12.5px] truncate">
                    {r.winner ? (
                      <>
                        <span style={{ color: PCOLOR[r.winner] }}>●</span>{" "}
                        <span className="text-mut">{r.endPhrase}</span>
                      </>
                    ) : (
                      <span className="text-dim">
                        {src === "ai" ? "winner unread (OCR gap)" : "outcome not labeled"}
                      </span>
                    )}
                  </span>
                  <span className="mono text-[11px] text-dim text-right">{r.shots} sh</span>
                  <span className="mono text-[11px] text-dim text-right">{r.durS}s</span>
                </button>
              );
            })}
          </div>
        </Card>

        {/* player + replay */}
        <div className="space-y-4">
          {sel && (
            <Card className="rise-2">
              <div className="flex items-baseline gap-3 flex-wrap mb-3">
                <span className="disp text-[1.2rem] font-semibold">
                  Set {sel.set} · Rally {sel.rally}
                </span>
                <span className="mono text-[13px] text-mut">
                  {sel.pa}–{sel.pb} → <b className="text-ink">{sel.a}–{sel.b}</b>
                </span>
                <span className="text-[13px] text-mut">
                  {sel.winner ? (
                    <>
                      <span style={{ color: PCOLOR[sel.winner] }}>{names[sel.winner]}</span>{" "}
                      takes it — {sel.endPhrase}
                    </>
                  ) : (
                    "winner unknown"
                  )}
                </span>
                {meta.youtubeId && (
                  <a
                    href={ytLink(meta.youtubeId, sel.t0)}
                    target="_blank"
                    className="ml-auto mono text-[11px] text-dim hover:text-mut"
                  >
                    OPEN ON YOUTUBE ↗
                  </a>
                )}
              </div>
              <RallyVideo rally={sel} youtubeId={meta.youtubeId} />

              {/* shot-by-shot strip */}
              <div className="flex gap-1.5 mt-4 overflow-x-auto pb-1">
                {selStrokes.map((s) => {
                  const isEnd = s.br === sel.endRound;
                  const press = s.press ?? 0;
                  return (
                    <div
                      key={s.br}
                      className="shrink-0 w-[74px] rounded border px-1.5 pt-1 pb-1.5 text-center"
                      style={{
                        borderColor: isEnd ? PHEX[s.p] : "var(--line)",
                        background: isEnd ? `${PHEX[s.p]}18` : "transparent",
                      }}
                      title={`#${s.br} ${names[s.p]} — ${s.shot}${press ? ` · reached at ${press} m/s` : ""}`}
                    >
                      <div className="h-7 flex items-end justify-center">
                        <div
                          className="w-2 rounded-t-sm"
                          style={{
                            height: `${Math.min(100, (press / 4.5) * 100)}%`,
                            background: press >= 2.5 ? "var(--warn)" : "var(--dim)",
                            minHeight: press ? 2 : 0,
                          }}
                        />
                      </div>
                      <div className="mono text-[10px] font-semibold" style={{ color: PHEX[s.p] }}>
                        {s.br}
                      </div>
                      <div className="text-[9.5px] text-mut leading-tight truncate">{s.shot}</div>
                      {src === "ai" && s.conf != null && (
                        <div className="mono text-[8.5px]" style={{ color: "var(--ai)" }}>
                          {(s.conf * 100).toFixed(0)}%
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
              <div className="kicker mt-1">
                BAR = SPEED REQUIRED TO REACH THE SHOT (AMBER ≥ 2.5 M/S = FORCED)
              </div>
            </Card>
          )}

          {sel && (
            <div className="grid md:grid-cols-2 gap-4">
              <Card className="rise-3">
                <div className="flex items-center gap-2 mb-2">
                  <span className="kicker">2D REPLAY — CV TRACKS</span>
                  {src === "ai" && <AiTag />}
                </div>
                {rep.data ? (
                  <Replay2D rep={rep.data} ai={src === "ai"} />
                ) : (
                  <div className="text-dim mono text-[12px] py-16 text-center animate-pulse">
                    LOADING TRACKS…
                  </div>
                )}
              </Card>
              <Card className="rise-4">
                <div className="kicker mb-2">RALLY MAP — CONTACTS + LANDING</div>
                <RallyMap
                  strokes={selStrokes.map((s) => ({ ...s, hx: s.hx, hy: s.hy, lx: s.lx, ly: s.ly }))}
                  land={rep.data?.land ?? null}
                  replay={rep.data}
                  smap={rep.data?.smap ?? { A: "near", B: "far" }}
                />
              </Card>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
