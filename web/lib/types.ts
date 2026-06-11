/* Mirrors the JSON emitted by `python -m badminton.export_web`. */

export type P = "A" | "B";
export type Source = "labels" | "ai";
export type Side = "near" | "far";

export interface IndexMatch {
  id: string;
  players: Record<P, string>;
  tournament: string;
  round: string;
  date: string;
  youtubeId: string | null;
  sets: [number, number][];
  rallies: number;
  shots: number;
  sources: Source[];
}

export interface IndexData {
  matches: IndexMatch[];
}

export interface Meta {
  id: string;
  source: Source;
  players: Record<P, string>;
  tournament: string;
  round: string;
  date: string;
  youtubeId: string | null;
  fps: number;
  sets: { set: number; a: number; b: number }[];
  winner: P;
  totals: { rallies: number; shots: number; rallySecs: number; points: Record<P, number> };
  smap: Record<string, Record<P, Side | null>>;
}

export interface Rally {
  clip: string | null;       // AI-annotated MP4 (when rendered), else YouTube fallback
  set: number;
  rally: number;
  f0: number;
  f1: number;
  t0: number;
  t1: number;
  shots: number;
  durS: number;
  server: P;
  serveType: string | null;
  winner: P | null;
  endHitter: P;
  endShot: string;
  endRound: number;
  category: string;          // Winner | Net | Out | Misjudged | Error | —
  endPhrase: string;
  a: number; b: number;      // score after the rally (A–B)
  pa: number; pb: number;    // score before
  clutch: boolean;
  bucket: string;
  pat2: string | null;
  pat3: string | null;
}

export interface Stroke {
  set: number;
  rally: number;
  br: number;
  f: number;
  t: number;
  p: P;
  shot: string;
  conf: number | null;
  hx: number | null; hy: number | null;   // hitter, court metres
  lx: number | null; ly: number | null;   // landing, court metres
  nx: number | null; ny: number | null;   // hitter, normalized (hitter at bottom)
  lnx: number | null; lny: number | null; // landing, normalized
  press: number | null;                   // required speed m/s to reach this shot
}

export interface Note {
  icon: string;
  title: string;
  body: string;
  keys: [number, number][];
}

export interface Pattern {
  pattern: string;
  n: number;
  a_wins: number;
  b_wins: number;
  keys: [number, number][];
}

export interface Insights {
  notes: Note[];
  pointsWon: Record<P, { points: number; winners: number; opp_out: number; opp_net: number; opp_other: number }>;
  lengthBuckets: { bucket: string; player: P; played: number; won: number; win_pct: number }[];
  serveStats: Record<P, { serve_n: number; serve_won: number; recv_n: number; recv_won: number; by_type: Record<string, { n: number; won: number }> }>;
  clutch: Record<P, { n: number; won: number }>;
  longestRun: Record<P, number>;
  patterns2: Pattern[];
  patterns3: Pattern[];
  errorPressure: Record<P, { forced: number; unforced: number; unknown: number; errors: number }>;
  responseMatrix: Record<P, {
    trigger: string;
    n: number;
    replies: { shot: string; n: number; pct: number; winPct: number | null }[];
  }[]>;
  openings: Record<P, Record<string, {
    n: number;
    winPct: number | null;
    returns: { shot: string; n: number; pct: number; srvWinPct: number | null }[];
  }>>;
  backhand: Record<P, { usage_pct: number; err_pct: number; n_err: number }> | null;
  shotOutcomes: { p: P; shot: string; w: number; e: number }[];
  shotMix: { p: P; shot: string; n: number; pct: number }[];
  pressureByShot: Record<string, number>;
  pressureSummary: Record<P, { faced: number; applied: number; n: number }>;
}

export interface Heat {
  nx: number;
  ny: number;
  x1: number;
  y1: number;
  cells: [number, number, number][];
}

export interface Movement {
  distM: number;
  secs: number;
  speed: number;
  cov: number;
  rec: number;
  front: number;
  mid: number;
  back: number;
  heat: Heat;
}

export interface Commentary {
  commentary: {
    headline: string;
    match_story: string;
    turning_points: string[];
    players: {
      name: string;
      overview: string;
      strengths: string[];
      weaknesses: string[];
      training_priorities: string[];
      gameplan_against: string;
    }[];
  };
  model: string | null;
  provider: string | null;
  generatedAt: string | null;
}

export interface MatchData {
  meta: Meta;
  rallies: Rally[];
  strokes: Stroke[];
  insights: Insights;
  movement: Partial<Record<P, Movement>>;
  commentary: Commentary | null;
}

export interface OcrEvent {
  frame: number;
  set_no: number;
  top: number;
  bot: number;
  winner: "top" | "bot" | null;
  new_set: boolean;
}

export interface Showcase {
  heldOut: boolean;
  tracking: { medianM: number; p90M: number; n: number; nearM: number; farM: number };
  agreement: {
    nLabel: number; nPipeline: number; nMatched: number;
    coverage: number; hitterAcc: number; shotAcc: number; e2e: number;
    confusion: { label: string; pred: string; n: number }[];
    recall: { shot: string; recall: number; n: number }[];
  };
  ocr: {
    events: OcrEvent[];
    rowA: "top" | "bot";
    sideA: Record<string, Side>;
    crops: { frame: number; img: string; top: number; bot: number; set: number }[];
  };
  hits?: {
    f1: number; precision: number; recall: number; attribution: number;
    landingMedM: number | null; landingP90M: number | null; nLabel: number;
  };
  segmentation?: { recall: number; precision: number; f1: number; nLabel: number; nDet: number };
}

export interface Replay {
  fps: number;
  f0: number;
  f1: number;
  smap: Record<P, Side | null>;
  near: [number, number, number][];   // [frame, court x, court y]
  far: [number, number, number][];
  shuttle: [number, number, number][]; // [frame, img x, img y]
  hits: { f: number; p: P; shot: string; conf: number | null }[];
  refHits: { f: number; shot: string }[];
  arcs: { f: number; x0: number; y0: number; x1: number; y1: number }[];
  land: { x: number; y: number } | null;
}

export const SHOT_ORDER = [
  "short service", "long service", "clear", "drive", "drop", "lob",
  "net shot", "smash", "push/rush", "defensive shot",
];

export const COURT = { w: 6.1, l: 13.4, net: 6.7 };
