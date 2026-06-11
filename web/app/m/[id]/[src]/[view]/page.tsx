import fs from "node:fs";
import path from "node:path";
import { Suspense } from "react";
import Dashboard from "@/components/Dashboard";
import type { IndexData, Source } from "@/lib/types";

const VIEWS = ["overview", "points", "court", "patterns", "film", "lab"] as const;

export function generateStaticParams() {
  const p = path.join(process.cwd(), "public", "data", "index.json");
  const idx: IndexData = JSON.parse(fs.readFileSync(p, "utf-8"));
  const params: { id: string; src: string; view: string }[] = [];
  for (const m of idx.matches)
    for (const src of m.sources)
      for (const view of VIEWS) params.push({ id: m.id, src, view });
  return params;
}

export default async function Page({
  params,
}: {
  params: Promise<{ id: string; src: string; view: string }>;
}) {
  const { id, src, view } = await params;
  return (
    <Suspense>
      <Dashboard id={id} src={src as Source} view={view} />
    </Suspense>
  );
}
