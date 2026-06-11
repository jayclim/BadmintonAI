"use client";

import { useEffect, useState } from "react";

const KEY = "cs-ai-overlay";
let current = true;
const subs = new Set<(v: boolean) => void>();

/** Global, persisted "AI overlay" preference: when ON, every rally video plays the
    AI-annotated clip (where rendered) instead of the raw broadcast embed. */
export function useOverlayPref(): [boolean, (v: boolean) => void] {
  const [on, setOn] = useState(current);
  useEffect(() => {
    const stored = localStorage.getItem(KEY);
    if (stored !== null && stored !== String(current)) {
      current = stored === "true";
    }
    setOn(current);
    const fn = (v: boolean) => setOn(v);
    subs.add(fn);
    return () => {
      subs.delete(fn);
    };
  }, []);
  const set = (v: boolean) => {
    current = v;
    localStorage.setItem(KEY, String(v));
    subs.forEach((fn) => fn(v));
  };
  return [on, set];
}
