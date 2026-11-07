"""
Cricsheet File-Based Provider
Wraps the CricsheetParser for use in the ingestion pipeline.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import List, Tuple

from app.domain.entities import CanonicalMatch
from .base import CricketDataProvider
from .cricsheet import CricsheetParser

logger = logging.getLogger(__name__)


class CricsheetFileProvider(CricketDataProvider):
    """
    Discovers and parses Cricsheet JSON files from a local directory.

    Args:
        data_dirs: List of directories containing Cricsheet JSON files.
    """

    def __init__(self, data_dirs: List[Path]):
        self._data_dirs = [Path(d) for d in data_dirs]
        self._parser = CricsheetParser()

    @property
    def name(self) -> str:
        return "cricsheet"

    def discover_matches(self) -> List[str]:
        """Return file stems (source match IDs) for all JSON files found."""
        ids = []
        for d in self._data_dirs:
            if d.exists():
                ids.extend(p.stem for p in sorted(d.glob("*.json")))
        return ids

    def get_path_for_id(self, source_match_id: str) -> Path:
        """Locate the file path for a given source match ID."""
        for d in self._data_dirs:
            candidate = d / f"{source_match_id}.json"
            if candidate.exists():
                return candidate
        raise FileNotFoundError(
            f"No file found for source_match_id={source_match_id} in {self._data_dirs}"
        )

    def parse_match(self, source_path: Path) -> Tuple[CanonicalMatch, List[str]]:
        return self._parser.parse_file(source_path)

    def iter_all(self):
        """
        Iterate over all discoverable match files, yielding (path, CanonicalMatch, warnings).
        Skips files that fail to parse and logs the error.
        """
        for d in self._data_dirs:
            if not d.exists():
                logger.warning("Directory does not exist: %s", d)
                continue
            for path in sorted(d.glob("*.json")):
                try:
                    match, warnings = self._parser.parse_file(path)
                    yield path, match, warnings
                except Exception as exc:
                    logger.error("Failed to parse %s: %s", path.name, exc)

