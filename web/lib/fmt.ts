import type { P } from "./types";

export const PCOLOR: Record<P, string> = { A: "var(--pa)", B: "var(--pb)" };
export const PHEX: Record<P, string> = { A: "#ff8a4a", B: "#2fd6c8" };

export const other = (p: P): P => (p === "A" ? "B" : "A");

export const pct = (won: number, n: number) => (n ? Math.round((100 * won) / n) : 0);

export const initials = (name: string) =>
  name.split(" ").map((w) => w[0]).join("");

export function fmtClock(s: number) {
  const m = Math.floor(s / 60);
  return `${m}:${String(Math.round(s % 60)).padStart(2, "0")}`;
}

/** YouTube embed url seeked to a window (2 s of lead-in). */
export function ytEmbed(id: string, t0: number, t1: number) {
  const s = Math.max(0, Math.floor(t0) - 2);
  const e = Math.ceil(t1) + 2;
  return `https://www.youtube-nocookie.com/embed/${id}?start=${s}&end=${e}&autoplay=1&rel=0&modestbranding=1`;
}

export function ytLink(id: string, t0: number) {
  return `https://youtu.be/${id}?t=${Math.max(0, Math.floor(t0) - 2)}`;
}
