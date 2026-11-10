"""User config: optional YAML file, parsed with yaml.safe_load (never eval/unsafe loaders).

Path: $BOOKFETCH_CONFIG, else $CLI_ANYTHING_HOME/bookfetch/config.yaml
      (CLI_ANYTHING_HOME defaults to ~/.cli-anything). A missing or corrupt file
silently yields {} — config must never take the tool down.

Keys:
  out_dir: C:\\Books            # default output directory
  disabled_sources: [gutenberg] # sources removed from the registry
"""

from __future__ import annotations

import os
from pathlib import Path

import yaml


def config_path() -> Path:
    override = os.environ.get("BOOKFETCH_CONFIG")
    if override:
        return Path(override)
    home = os.environ.get("CLI_ANYTHING_HOME", str(Path.home() / ".cli-anything"))
    return Path(home) / "bookfetch" / "config.yaml"


def load_config() -> dict:
    path = config_path()
    try:
        if not path.exists():
            return {}
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 - corrupt config degrades to defaults
        return {}
    return data if isinstance(data, dict) else {}
