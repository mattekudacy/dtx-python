"""Settings the game saves by itself: the learned note map and calibration.

They live in a JSON file beside the user's config.toml, which the game never
rewrites (so hand-written comments there survive). Saved values take
precedence over config.toml; `drumgame --reset-saved` removes them.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


def saved_path() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "drumgame" / "saved.json"


def load_saved(path: Path | None = None) -> dict[str, Any]:
    """Saved settings in the same nested shape as the config, or {}.

    A missing or unreadable file is not an error: the game falls back to the
    config.
    """
    path = path or saved_path()
    try:
        data = json.loads(path.read_text("utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def save(patch: dict[str, Any], path: Path | None = None) -> Path:
    """Merge `patch` into the saved settings. Top-level sections are replaced
    whole, so saving a learned note map discards the previous one."""
    path = path or saved_path()
    data = load_saved(path)
    data.update(patch)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=1, sort_keys=True) + "\n", "utf-8")
    os.replace(tmp, path)  # never leave a half-written file behind
    return path


def reset(path: Path | None = None) -> bool:
    """Delete the saved settings. Returns whether there was anything to delete."""
    path = path or saved_path()
    try:
        path.unlink()
        return True
    except FileNotFoundError:
        return False
