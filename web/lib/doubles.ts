/* Mirrors the JSON emitted by `python -m badminton.doubles.export_web`.

   The doubles dashboard is a SEPARATE surface (route /d/<id>, manifest doubles_index.json)
   so the singles dashboard is untouched and this whole layer stays deletable. Kept
   self-contained — its own small client-fetch hook rather than coupling to lib/data.ts. */

"use client";

import { useEffect, useState } from "react";

export type DSide = "near" | "far";
export type DSlot = "near" | "near2" | "far" | "far2";
export type Formation = "attack" | "defence";

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

/** one side's tactics within a rally (null when that side wasn't 2-tracked) */
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
  near: SideTactics | null;
  far: SideTactics | null;
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

export interface PlayerShare {
  name: string;
  slot: DSlot;
  side: DSide;
  frontPct: number;
  frames: number;
}

export interface DoublesMeta {
  id: string;
  discipline: "doubles";
  pairs: Record<DSide, string>;
  names: Record<DSlot, string> | null;
  tournament: string;
  round: string;
  date: string;
  youtubeId: string | null;
  result: string | null;
  fps: number;
  totals: { rallies: number; frames: number; rallySecs: number };
  span: { f0: number; f1: number; set: number };
}

export interface DoublesMatch {
  meta: DoublesMeta;
  rallies: DoublesRally[];
  formation: Record<DSide, FormationSide>;
  players: PlayerShare[];
}

/** run-length [startFrame, endFrame, formation] of the debounced (hysteresis) formation */
export type FormSeg = [number, number, Formation];

export interface DoublesReplay {
  fps: number;
  f0: number;
  f1: number;
  rally: number;
  set: number;
  pairs: Record<DSide, string>;
  names: Record<DSlot, string> | null;
  tracks: Record<DSlot, [number, number, number][]>; // [frame, court x, court y]
  form: Record<DSide, FormSeg[]>;
}

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
