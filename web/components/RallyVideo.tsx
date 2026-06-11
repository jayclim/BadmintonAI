"use client";

import { useOverlayPref } from "@/lib/overlay";
import type { Rally } from "@/lib/types";
import { ytEmbed } from "@/lib/fmt";

/** Rally footage honoring the global AI-overlay preference: the pre-rendered
    annotated clip (pose, shuttle trail, shot calls, OCR score baked in) when ON
    and rendered; the raw YouTube broadcast otherwise. */
export default function RallyVideo({
  rally,
  youtubeId,
}: {
  rally: Rally;
  youtubeId: string | null;
}) {
  const [overlayOn] = useOverlayPref();
  const useClip = overlayOn && !!rally.clip;
  return (
    <div>
      <div className="aspect-video rounded-md overflow-hidden border border-[var(--line)] bg-black">
        {useClip ? (
          <video
            key={rally.clip!}
            src={rally.clip!}
            className="w-full h-full"
            controls
            autoPlay
            muted
            playsInline
          />
        ) : youtubeId ? (
          <iframe
            key={`${rally.set}-${rally.rally}-yt`}
            src={ytEmbed(youtubeId, rally.t0, rally.t1)}
            className="w-full h-full"
            allow="autoplay; encrypted-media; picture-in-picture"
            allowFullScreen
            title="rally clip"
          />
        ) : (
          <div className="w-full h-full flex items-center justify-center text-dim mono text-[12px]">
            NO FOOTAGE
          </div>
        )}
      </div>
      <div className="flex items-center gap-2 mt-1.5">
        {useClip ? (
          <span className="mono text-[10px] tracking-[0.14em]" style={{ color: "var(--ai)" }}>
            ● AI-ANNOTATED — pose · shuttle · shot calls · machine-read score
          </span>
        ) : (
          <span className="mono text-[10px] tracking-[0.14em] text-dim">
            RAW BROADCAST{overlayOn && !rally.clip ? " — no annotated clip rendered for this rally" : ""}
          </span>
        )}
      </div>
    </div>
  );
}
