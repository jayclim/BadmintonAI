import type { ReactNode } from "react";

/** Minimal inline-markdown renderer for LLM text: **bold**, *italic*, `code`.
    The commentary strings are single paragraphs/bullets — no block syntax needed. */
export function Md({ children }: { children: string }) {
  return <>{parse(children)}</>;
}

function parse(s: string): ReactNode[] {
  const out: ReactNode[] = [];
  // tokenize on **…**, *…*, `…`
  const re = /(\*\*[^*]+\*\*|\*[^*\n]+\*|`[^`]+`)/g;
  let last = 0;
  let m: RegExpExecArray | null;
  let k = 0;
  while ((m = re.exec(s))) {
    if (m.index > last) out.push(s.slice(last, m.index));
    const t = m[0];
    if (t.startsWith("**"))
      out.push(
        <strong key={k++} className="text-ink font-semibold">
          {t.slice(2, -2)}
        </strong>,
      );
    else if (t.startsWith("`"))
      out.push(
        <code key={k++} className="mono text-[0.92em]">
          {t.slice(1, -1)}
        </code>,
      );
    else out.push(<em key={k++}>{t.slice(1, -1)}</em>);
    last = m.index + t.length;
  }
  if (last < s.length) out.push(s.slice(last));
  return out;
}
