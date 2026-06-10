"""Load / save the match registry (config/matches.yaml)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
MATCHES_YAML = REPO_ROOT / "config" / "matches.yaml"


def load_matches(path: Path | str = MATCHES_YAML) -> dict[str, Any]:
    return yaml.safe_load(Path(path).read_text()) or {}


def get_match(match_id: str, path: Path | str = MATCHES_YAML) -> dict[str, Any]:
    matches = load_matches(path)
    if match_id not in matches:
        raise KeyError(f"{match_id!r} not in {path} (have: {list(matches)})")
    return matches[match_id]


def update_match(match_id: str, updates: dict[str, Any], path: Path | str = MATCHES_YAML) -> None:
    """Persist field updates for one match back to the YAML (e.g. fps, homography)."""
    path = Path(path)
    matches = load_matches(path)
    matches.setdefault(match_id, {}).update(updates)
    path.write_text(yaml.safe_dump(matches, sort_keys=False, allow_unicode=True))
