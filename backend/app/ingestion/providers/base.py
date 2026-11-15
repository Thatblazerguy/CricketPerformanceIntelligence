"""
Provider Base Interface
Defines the abstract contract all data providers must implement.
"""
from __future__ import annotations
from abc import ABC, abstractmethod
from pathlib import Path
from typing import List, Tuple
from app.domain.entities import CanonicalMatch


class CricketDataProvider(ABC):
    """Abstract base for all cricket data providers."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Provider identifier (e.g., 'cricsheet')."""
        ...

    @abstractmethod
    def discover_matches(self) -> List[str]:
        """
        Discover available source match identifiers.

        Returns:
            List of source match IDs (e.g., file stems for Cricsheet).
        """
        ...

    @abstractmethod
    def parse_match(self, source_path: Path) -> Tuple[CanonicalMatch, List[str]]:
        """
        Parse a source match file into canonical form.

        Args:
            source_path: Path to the source file.

        Returns:
            Tuple of (CanonicalMatch, warnings list).
        """
        ...

