import fs from "node:fs";
import path from "node:path";
import Link from "next/link";
import type { IndexData } from "@/lib/types";
import type { DoublesIndex } from "@/lib/doubles";
import ThemeToggle from "@/components/ThemeToggle";
import GitHubLink, { GitHubMark, PROFILE_URL, REPO_URL } from "@/components/GitHubLink";

/* Landing page: one pre-selected rally, already playing, with the measured numbers
   next to it. The match picker lives at /matches, linked below the fold. */

function readCounts(): { matches: number; rallies: number } {
  const p = path.join(process.cwd(), "public", "data");
  const idx: IndexData = JSON.parse(fs.readFileSync(path.join(p, "index.json"), "utf-8"));
  const dblPath = path.join(p, "doubles_index.json");
  const dbl: DoublesIndex = fs.existsSync(dblPath)
    ? JSON.parse(fs.readFileSync(dblPath, "utf-8"))
    : { matches: [] };
  const all = [...idx.matches, ...dbl.matches];
  return {
    matches: all.length,
    rallies: all.reduce((n, m) => n + (m.rallies ?? 0), 0),
  };
}

/** The hero rally: All England Open 2022 SF, game 2, a 39-shot exchange rendered
    by the pipeline itself (scripts/render_web_clips.py). Deep-links to the same
    rally in the film room. */
const HERO_RALLY = "/m/all_england_2022_sf/labels/film/?r=2-6";

const METRICS: [string, string][] = [
  ["0.86 F1", "hit detection"],
  ["0.94", "rally segmentation"],
  ["~97%", "score OCR accuracy"],
  ["~0.64 m", "court position precision"],
];

const STACK: [string, string][] = [
  ["Players", "Ultralytics YOLO11x-pose + ByteTrack, 17-keypoint pose per frame"],
  ["Court geometry", "hand-calibrated 4-corner homography (OpenCV), positions in true metres"],
  ["Shuttle", "TrackNetV3, vendored unmodified and patched to run on Apple-silicon MPS"],
  ["Hits & landings", "velocity-kink / direction-reversal / serve-onset detectors over the shuttle track"],
  ["Shot types", "pretrained BST-0 (CVPRW'26) run on our own CV inputs, zero fine-tuning"],
  ["Rally windows", "camera-run detection with dead-shuttle restart splitting"],
  ["Score & sets", "template-matched digit OCR on the broadcast scoreboard graphic"],
  ["Storage / analytics", "DuckDB keyed by match · pandas · NumPy · scikit-learn"],
  ["Dashboard", "Next.js 16 static export, TypeScript, Tailwind 4, hand-written SVG charts"],
  ["Runtime", "Python 3.12, PyTorch on Apple-silicon MPS"],
];

export default function Home() {
  const { matches, rallies } = readCounts();
  return (
    <main className="max-w-[1180px] mx-auto px-5 sm:px-6 w-full">
      {/* ── top bar ── */}
      <nav className="flex items-center gap-3 py-3.5">
        <span className="disp font-bold text-[1.15rem] tracking-tight">
          COURT<span style={{ color: "var(--ai)" }}>SIDE</span>
        </span>
        <div className="ml-auto flex items-center gap-2">
          <GitHubLink />
          <ThemeToggle />
        </div>
      </nav>

      {/* ── headline ── */}
      <h1 className="rise text-[clamp(1.15rem,2.5vw,1.7rem)] font-semibold leading-[1.3] tracking-tight max-w-3xl mt-1 mb-2">
        Per-shot badminton match data, extracted from broadcast video alone with no manual
        labelling at inference time.
      </h1>
      <p className="rise rise-1 mono text-[10.5px] tracking-[0.1em] uppercase text-dim mb-4 leading-relaxed">
        player + shuttle tracking · hit detection · shot classification · scoreboard OCR
      </p>

      {/* ── hero: the rally, already playing, with the numbers beside it. On a phone
             the metrics come straight after the video; the caption drops below them. ── */}
      <section className="grid lg:grid-cols-12 lg:grid-rows-[auto_1fr] gap-4 lg:gap-5 items-start">
        <div className="order-1 lg:col-span-8 lg:col-start-1 lg:row-start-1 rise rise-1">
          <div className="rounded-md overflow-hidden border border-[var(--line)] bg-black">
            <video
              className="w-full h-auto block"
              src="/hero/rally.mp4"
              poster="/hero/rally.jpg"
              width={960}
              height={540}
              autoPlay
              muted
              loop
              playsInline
              preload="auto"
              disableRemotePlayback
              aria-label="Annotated badminton rally: player boxes and pose skeletons, shuttle trajectory trail, shot-type calls and a machine-read scoreboard, with a top-down court map."
            />
          </div>
          <div className="flex flex-wrap items-baseline gap-x-2.5 gap-y-0.5 mt-1.5">
            <span className="mono text-[10px] tracking-[0.14em]" style={{ color: "var(--ai)" }}>
              ● EVERY OVERLAY IS PIPELINE OUTPUT
            </span>
            <span className="text-dim text-[11.5px]">
              boxes + pose · shuttle trajectory · shot call · court map · machine-read score
            </span>
          </div>
        </div>

        <div className="order-3 lg:col-span-8 lg:col-start-1 lg:row-start-2">
          <p className="text-mut text-[13px] leading-relaxed max-w-2xl">
            All England Open 2022 semi-final, Lakshya Sen vs Lee Zii Jia, a 39-shot rally from
            game 2. Nothing in this clip is hand-annotated.{" "}
            <Link href={HERO_RALLY} className="underline underline-offset-2 hover:text-ink">
              Open this rally in the dashboard →
            </Link>
          </p>
        </div>

        <div className="order-2 lg:col-span-4 lg:col-start-9 lg:row-start-1 lg:row-span-2 card rise rise-2 p-4 sm:p-5">
          <div className="kicker mb-0.5">MEASURED ON A</div>
          <div className="mono text-[12px] tracking-[0.12em] mb-4" style={{ color: "var(--ai)" }}>
            HELD-OUT TEST SET
          </div>
          <dl className="grid grid-cols-2 lg:grid-cols-1 gap-x-4 gap-y-4">
            {METRICS.map(([value, label]) => (
              <div key={label} className="border-t border-[var(--line-soft)] pt-2.5">
                <dt className="bignum text-[clamp(1.5rem,4.2vw,1.9rem)]">{value}</dt>
                <dd className="text-mut text-[12.5px] mt-1 leading-snug">{label}</dd>
              </div>
            ))}
          </dl>
          <p className="text-dim text-[11.5px] leading-relaxed mt-5 pt-4 border-t border-[var(--line-soft)]">
            Denmark Open 2022 semi-final, scored against ShuttleSet22 human annotations. Every
            threshold was tuned on a different match and left untouched.
          </p>
        </div>
      </section>

      {/* ── below the fold ── */}
      <div className="rule mt-14 mb-8" />

      <section className="mb-14">
        <Link
          href="/matches/"
          className="card p-5 flex items-center gap-4 hover:border-[var(--mut)] transition-colors group block sm:inline-flex"
        >
          <div>
            <div className="text-[1.05rem] font-semibold">Explore other matches</div>
            <div className="text-mut text-[13px] mt-0.5">
              {matches} matches · {rallies} rallies · six analysis views, ground truth vs AI
              side by side
            </div>
          </div>
          <span className="text-dim group-hover:text-ink transition-colors ml-auto sm:ml-6 shrink-0">
            →
          </span>
        </Link>
      </section>

      <section className="mb-16 max-w-3xl">
        <h2 className="text-[1.15rem] font-semibold mb-4">Stack</h2>
        <dl className="text-[13.5px] leading-relaxed">
          {STACK.map(([k, v]) => (
            <div
              key={k}
              className="grid sm:grid-cols-[10.5rem_1fr] gap-x-4 py-2 border-t border-[var(--line-soft)]"
            >
              <dt className="mono text-[10.5px] tracking-[0.1em] uppercase text-dim pt-1">{k}</dt>
              <dd className="text-mut">{v}</dd>
            </div>
          ))}
        </dl>
      </section>

      <footer className="pb-16">
        <div className="flex flex-wrap gap-2.5 mb-5">
          <a
            href={REPO_URL}
            target="_blank"
            rel="noopener noreferrer"
            className="card px-4 py-2.5 inline-flex items-center gap-2.5 text-[13.5px] hover:border-[var(--mut)] transition-colors"
          >
            <GitHubMark />
            <span className="font-semibold">jayclim/BadmintonAI</span>
            <span className="text-dim">source code</span>
          </a>
          <a
            href={PROFILE_URL}
            target="_blank"
            rel="noopener noreferrer"
            className="card px-4 py-2.5 inline-flex items-center gap-2.5 text-[13.5px] hover:border-[var(--mut)] transition-colors"
          >
            <GitHubMark />
            <span className="font-semibold">@jayclim</span>
            <span className="text-dim">GitHub profile</span>
          </a>
        </div>
        <p className="text-dim text-[12px] mono leading-relaxed">
          YOLO11 pose · TrackNetV3 · BST-0 (CVPRW&apos;26) · template-matched score OCR.
          Validated against ShuttleSet22 human labels, including a fully held-out match.
        </p>
      </footer>
    </main>
  );
}
