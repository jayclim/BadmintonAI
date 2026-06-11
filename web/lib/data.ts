"use client";

import { useEffect, useState } from "react";
import type { IndexData, MatchData, Replay, Showcase, Source } from "./types";

const cache = new Map<string, unknown>();
const inflight = new Map<string, Promise<unknown>>();

async function fetchJson<T>(url: string): Promise<T> {
  if (cache.has(url)) return cache.get(url) as T;
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

export const useIndex = () => useJson<IndexData>("/data/index.json");

export const useMatch = (id: string, src: Source) =>
  useJson<MatchData>(`/data/${id}/${src}.json`);

export const useShowcase = (id: string) => useJson<Showcase>(`/data/${id}/showcase.json`);

export const useReplay = (id: string, src: Source, set: number | null, rally: number | null) =>
  useJson<Replay>(set != null && rally != null ? `/data/${id}/replay/${src}/s${set}r${rally}.json` : null);
