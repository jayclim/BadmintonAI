"""Doubles support — deliberately ISOLATED from the singles pipeline (Phase 0).

Everything doubles-specific lives under badminton.doubles.* so the proven singles
chain (detect.py, pipeline.py, hits.py, shotclass.py, segment.py) is never edited
while we find out whether stable 4-player identity is achievable on broadcast video.
The risky, experimental parts are quarantined here: if doubles doesn't work out,
delete this package and nothing in the singles path regresses.

Reuse goes one direction only: doubles imports shared low-level helpers from the
singles modules (detect.ground_point, court.*, config, db); the singles modules
never import from here.

Modules:
  track  — 4-player detection + tracking with stable slots (near/near2, far/far2)
           and velocity-based ID recovery → `tracks` table.
  roles  — per-frame, geometric front/back + left/right + formation, robust to
           which physical player got which slot.
"""
