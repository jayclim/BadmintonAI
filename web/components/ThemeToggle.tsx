"use client";

/* Theme switch — NIGHT (floodlit court) ↔ SHIRO (白, washi paper).
   The visible label is swapped by CSS on [data-theme] so the rendered
   markup is identical on server and client: no inline script, no
   hydration mismatch, correct from the first paint. */

const KEY = "cs-theme";

export default function ThemeToggle({ className = "" }: { className?: string }) {
  const flip = () => {
    const el = document.documentElement;
    const next = el.getAttribute("data-theme") === "shiro" ? "night" : "shiro";
    el.setAttribute("data-theme", next);
    try {
      localStorage.setItem(KEY, next);
    } catch {}
  };
  return (
    <button
      onClick={flip}
      title="Toggle theme — shiro (paper white) / night"
      className={`mono text-[10.5px] tracking-[0.12em] px-2.5 py-1.5 rounded-md border border-[var(--line)] text-dim hover:text-ink hover:border-[var(--mut)] transition-colors shrink-0 ${className}`}
    >
      <span className="night-only">○ SHIRO</span>
      <span className="shiro-only">● NIGHT</span>
    </button>
  );
}
