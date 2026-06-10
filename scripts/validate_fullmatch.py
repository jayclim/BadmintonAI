"""Match-wide Phase 0 validation: detect only at the labeled stroke frames
(± a few around the validated offset) across all 54 minutes, then validate.

    python scripts/validate_fullmatch.py india_open_2022_final
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from badminton import db, detect  # noqa: E402

MATCH = sys.argv[1] if len(sys.argv) > 1 else "india_open_2022_final"

# our_frame = ss_frame - offset; validated offset ≈ -6 → our ≈ ss+6.
# detect ss+5, ss+6, ss+7 so validate --search -7..-5 can fine-tune per stroke.
con = db.connect()
ss_frames = [r[0] for r in con.execute(
    "SELECT DISTINCT frame_num FROM strokes WHERE match_id=? AND source='shuttleset' "
    "AND hitter_x IS NOT NULL ORDER BY frame_num", [MATCH]).fetchall()]
con.close()

frames = sorted({f + d for f in ss_frames for d in (5, 6, 7)})
print(f"{len(ss_frames)} labeled strokes -> {len(frames)} frames to detect")
detect.process_frames(MATCH, frames)
