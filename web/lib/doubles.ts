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
  /** pre-rendered AI-annotated clip url, or null if none was rendered for this rally */
  clip: string | null;
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

/** per-PLAYER movement for ONE set (four entries per set). `name` is the roster athlete
    for set 1, null otherwise (the pairs swap ends and only set 1 is identity-anchored —
    so later sets show the pair label + a P1/P2 index instead of a guessed name). */
export interface PlayerMovement {
  set: number;
  team: Team;
  idx: number; // within-pair index 0/1
  name: string | null;
  distM: number;
  secs: number;
  speed: number;
  cov: number;
  front: number;
  mid: number;
  back: number;
  heat: Heat;
}

/** one accepted point in the OCR score trajectory */
export interface ScorePoint {
  rally: number;
  a: number;
  b: number;
  winner: Team;
}

export interface PointsSet {
  set: number;
  points: ScorePoint[];
  final: { a: number; b: number };
  winner: Team | null;
}

/** Points / momentum, derived from the per-rally scoreboard OCR */
export interface DoublesPoints {
  topTeam: Team;
  sets: PointsSet[];
  lengthWins: Record<Team, { short: number; mid: number; long: number }>;
  runs: Record<Team, number>;
  rallyWinner: Record<string, Team>;
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

/** court-control (Voronoi dominant region). Raw full-court control carries a static
    far-side bias (far court-y reads ~1.4 m toward the net — see control.py), so the
    tactical read is `nearIndex` = nearControlPct − baseline (deviation cancels the bias). */
export interface ControlRally {
  rally: number;
  set: number;
  f0: number;
  f1: number;
  nearPair: Team;
  farPair: Team;
  nearControlPct: number;
  nearIndex: number;
}

export interface ControlMap {
  step: number;
  w: number;
  l: number;
  nearTeam: string;
  farTeam: string;
  /** [ny][nx]: fraction of set-1 frames the near (team A) side held each court cell */
  grid: number[][];
}

export interface DoublesControl {
  baseline: number; // near% static-bias floor
  summary: Record<Team, number | null>; // frame-weighted control % per team
  rallies: ControlRally[];
  map: ControlMap | null; // set-1 control surface (near = team A)
}

/** stroke-derived shot tactics (null until doubles.strokes has been written + re-exported) */
export interface ShotCount {
  shot: string; // display name (lift/serve/push/block renames already applied)
  n: number;
  pct: number;
}
export interface ShotResponse {
  vs: string; // opponent's shot
  total: number;
  answers: ShotCount[]; // how this team answers it, most common first
}
/** per-player shot mix for one set — keyed (set, team, idx) exactly like PlayerMovement,
    so the two join and share the name / P1-P2 labelling. Within-pair attribution is
    nearest-partner (noisy); the side (= team) is exact. */
export interface PlayerShots {
  set: number;
  team: Team;
  idx: number;
  name: string | null;
  /** score-verified serves only (first stroke + the score says their team served);
      null when no OCR score exists to verify against */
  serves: number | null;
  top: ShotCount[];
}
/** points won serving vs receiving (only rallies with an OCR-accepted winner count) */
export interface ServeReceive {
  servePlayed: number;
  serveWon: number;
  recvPlayed: number;
  recvWon: number;
}
export interface DoublesShots {
  mix: Record<Team, ShotCount[]>;
  responses: Record<Team, ShotResponse[]>;
  players: PlayerShots[];
  serveReceive: Record<Team, ServeReceive> | null;
  /** each scored rally's last stroke: hit by the winner = the finisher; by the loser =
      the shot that didn't come back (error / got punished — CV can't split those) */
  finishers: { won: Record<Team, ShotCount[]>; lost: Record<Team, ShotCount[]> } | null;
  /** rally -> its final detected stroke (worm tooltip) */
  rallyFinish: Record<string, { shot: string; team: Team }>;
}

export interface DoublesMatch {
  meta: DoublesMeta;
  rallies: DoublesRally[];
  formation: Record<Team, FormationSide>;
  formationBySet: FormationBySet[];
  players: PlayerShare[];
  movement: PlayerMovement[];
  flow: DoublesFlow;
  control: DoublesControl | null;
  points: DoublesPoints | null;
  showcase: DoublesShowcase | null;
  notes: CoachNote[];
  shots: DoublesShots | null;
}

/** Display label for a per-player movement entry: the roster athlete name where known
    (set 1), else the pair's display name + P1/P2 (the team is always known; only the
    within-pair identity isn't anchored in later sets — so we don't fake a specific name). */
export function playerLabel(m: PlayerMovement, teams: Record<Team, string>): string {
  return m.name ?? `${teams[m.team]} · P${m.idx + 1}`;
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
  /** CV-detected contacts in order: [frame, hitting slot, display shot name] */
  strokes?: [number, DSlot, string][];
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

/** AI tactical commentary (optional — present only after `doubles.commentary` has run).
    Snake_case mirrors the pydantic `DoublesCommentary` dump written to analysis.json. */
export interface AnalysisPair {
  pair: string;
  overview: string;
  strengths: string[];
  weaknesses: string[];
  training_priorities: string[];
  gameplan_against: string;
}

export interface DoublesAnalysis {
  provider: string;
  model: string;
  generated_at: string;
  commentary: {
    headline: string;
    match_story: string;
    turning_points: string[];
    pairs: AnalysisPair[];
  };
}

/** Returns null when no analysis.json exists for the match (a 404 leaves data null). */
export const useDoublesAnalysis = (id: string) =>
  useJson<DoublesAnalysis>(`/data/${id}/analysis.json`);
