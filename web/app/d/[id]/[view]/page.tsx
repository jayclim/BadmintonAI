import fs from "node:fs";
import path from "node:path";
import { Suspense } from "react";
import DoublesDashboard from "@/components/DoublesDashboard";
import type { DoublesIndex } from "@/lib/doubles";

const VIEWS = ["overview", "court", "patterns", "film", "lab"] as const;

export function generateStaticParams() {
  const p = path.join(process.cwd(), "public", "data", "doubles_index.json");
  if (!fs.existsSync(p)) return [];
  const idx: DoublesIndex = JSON.parse(fs.readFileSync(p, "utf-8"));
  const params: { id: string; view: string }[] = [];
  for (const m of idx.matches) for (const view of VIEWS) params.push({ id: m.id, view });
  return params;
}

export default async function Page({
  params,
}: {
  params: Promise<{ id: string; view: string }>;
}) {
  const { id, view } = await params;
  return (
    <Suspense>
      <DoublesDashboard id={id} view={view} />
    </Suspense>
  );
}
