/* Mirrors the JSON emitted by `python -m badminton.doubles.export_web`.

   The doubles dashboard is a SEPARATE surface (route /d/<id>, manifest doubles_index.json)
   so the singles dashboard is untouched and this whole layer stays deletable. Kept
   self-contained — its own small client-fetch hook rather than coupling to lib/data.ts. */

"use client";

import { useEffect, useState } from "react";
import type { Heat } from "@/lib/types";

export type DSide = "near" | "far";
export type DSlot = "near" | "near2" | "far" | "far2";
export type Formation = "attack" | "defence";
/** the two fixed teams: A = whoever started on the near end in set 1, B = the far pair.
    Stats aggregate per team across all sets (the pairs swap ends between games). */
export type Team = "A" | "B";

export interface DoublesIndexMatch {
  id: string;
  discipline: "doubles";
  pairs: Record<DSide, string>;
  tournament: string;
  round: string;
  date: string;
  youtubeId: string | null;
  result: string | null;
  rallies: number;
}

export interface DoublesIndex {
  matches: DoublesIndexMatch[];
}

/** one team's tactics within a rally (null when that team wasn't 2-tracked that rally) */
export interface SideTactics {
  attackPct: number;
  rotations: number;
  frontSwaps: number;
  frames: number;
}

export interface DoublesRally {
  rally: number;
  set: number;
  f0: number;
  f1: number;
  t0: number;
  t1: number;
  durS: number;
  frames: number;
  nearPair: Team;
  farPair: Team;
  A: SideTactics | null;
  B: SideTactics | null;
}

export interface FormationSide {
  frames: number;
  attackPct: number | null;
  defencePct: number | null;
  rotations: number;
  frontSwaps: number;
  medianDepthGapM: number | null;
  medianLateralGapM: number | null;
}

/** per-set formation: a {set} tag plus a FormationSide per team */
export type FormationBySet = { set: number } & Record<Team, FormationSide>;

export interface PlayerShare {
  name: string;
  slot: DSlot;
  side: DSide;
  set: number;
  team: Team;
  frontPct: number;
  frames: number;
}

export interface DoublesMeta {
  id: string;
  discipline: "doubles";
  pairs: Record<DSide, string>;
  teams: Record<Team, string>;
  tournament: string;
  round: string;
  date: string;
  youtubeId: string | null;
  result: string | null;
  fps: number;
  nSets: number;
  sets: { set: number; rallies: number; frames: number }[];
  totals: { rallies: number; frames: number; rallySecs: number };
  span: { f0: number; f1: number };
}

/** per-TEAM movement over the match (both the pair's players combined, heat on one half) */
export interface TeamMovement {
  pair: Team;
  name: string;
  distM: number;
  secs: number;
  speed: number;
  cov: number;
  front: number;
  mid: number;
  back: number;
  heat: Heat;
}

/** per-team formation-flow aggregates over the tracked rallies */
export interface FlowSide {
  rallies: number;
  attackFirst: number;
  defenceFirst: number;
  attackFirstPct: number | null;
  attackPct: number | null;
  attackHoldMedS: number | null;
  rotPerRally: number | null;
  rotPerMin: number | null;
  a2d: number;
  d2a: number;
}

export interface FlowRally {
  rally: number;
  set: number;
  f0: number;
  f1: number;
  durS: number;
  nearPair: Team;
  farPair: Team;
  near: FormSeg[];
  far: FormSeg[];
}

export interface DoublesFlow {
  A: FlowSide;
  B: FlowSide;
  rallies: FlowRally[];
}

/** label-free tracking-quality metrics for the AI-Lab showcase */
export interface ShowcaseSlot {
  slot: DSlot;
  name: string;
  recallPct: number;
  medStepCm: number | null;
  teleports: number;
}

export interface DoublesShowcase {
  coverage: { inRallyPct: number; frames: number; all4: number };
  slots: ShowcaseSlot[];
  segmentation: { rallies: number; spanS: number; minLen: number; maxGap: number };
}

/** one rule-based, doubles-tailored scouting note */
export interface CoachNote {
  kind: "good" | "watch" | "info";
  head: string;
  body: string;
}

export interface DoublesMatch {
  meta: DoublesMeta;
  rallies: DoublesRally[];
  formation: Record<Team, FormationSide>;
  formationBySet: FormationBySet[];
  players: PlayerShare[];
  movement: TeamMovement[];
  flow: DoublesFlow;
  showcase: DoublesShowcase | null;
  notes: CoachNote[];
}

/** run-length [startFrame, endFrame, formation] of the debounced (hysteresis) formation */
export type FormSeg = [number, number, Formation];

export interface DoublesReplay {
  fps: number;
  f0: number;
  f1: number;
  rally: number;
  set: number;
  nearPair: Team;
  farPair: Team;
  pairs: Record<DSide, string>; // near/far -> the team display name occupying that side
  names: Record<DSlot, string> | null;
  tracks: Record<DSlot, [number, number, number][]>; // [frame, court x, court y]
  form: Record<DSide, FormSeg[]>;
}

export const TEAMS: Team[] = ["A", "B"];
/** team colours — reuse the singles player palette (pa/pb) */
export const TEAM_COLOR: Record<Team, string> = { A: "var(--pa)", B: "var(--pb)" };

export const DSLOTS: DSlot[] = ["near", "near2", "far", "far2"];
export const SIDE_OF: Record<DSlot, DSide> = {
  near: "near",
  near2: "near",
  far: "far",
  far2: "far",
};
/** the two slots of a side, in a stable order */
export const SLOTS_OF: Record<DSide, [DSlot, DSlot]> = {
  near: ["near", "near2"],
  far: ["far", "far2"],
};

// ── client fetch (cache + dedupe), mirroring lib/data.ts but standalone ──
const cache = new Map<string, unknown>();
const inflight = new Map<string, Promise<unknown>>();

function fetchJson<T>(url: string): Promise<T> {
  if (cache.has(url)) return Promise.resolve(cache.get(url) as T);
  if (!inflight.has(url)) {
    inflight.set(
      url,
      fetch(url).then(async (r) => {
        if (!r.ok) throw new Error(`${r.status} ${url}`);
        const j = await r.json();
        cache.set(url, j);
        inflight.delete(url);
        return j;
      }),
    );
  }
  return inflight.get(url) as Promise<T>;
}

function useJson<T>(url: string | null): { data: T | null; error: string | null } {
  const [data, setData] = useState<T | null>(url && cache.has(url) ? (cache.get(url) as T) : null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    if (!url) return;
    let on = true;
    fetchJson<T>(url)
      .then((d) => on && setData(d))
      .catch((e) => on && setError(String(e)));
    return () => {
      on = false;
    };
  }, [url]);
  return { data, error };
}

export const useDoublesIndex = () => useJson<DoublesIndex>("/data/doubles_index.json");

export const useDoublesMatch = (id: string) => useJson<DoublesMatch>(`/data/${id}/doubles.json`);

export const useDoublesReplay = (id: string, rally: number | null) =>
  useJson<DoublesReplay>(rally != null ? `/data/${id}/dreplay/r${rally}.json` : null);
