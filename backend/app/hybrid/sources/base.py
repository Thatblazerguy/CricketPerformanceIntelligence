"""Source adapter contract.

Every adapter declares what it really provides (ball-by-ball, scorecard or
metadata) and the access terms it operates under. Adapters are independent:
adding a provider never requires touching another adapter or the ingestion core.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from sqlalchemy.orm import Session


@dataclass
class SourceInfo:
    key: str
    name: str
    data_level: str                     # ball_by_ball / scorecard / metadata / none
    access: str                         # open / user_supplied / licence_required / restricted / unavailable
    licence: str
    url: Optional[str] = None
    coverage: str = ""
    integrated: bool = False
    notes: List[str] = field(default_factory=list)

    def as_dict(self) -> Dict:
        return self.__dict__.copy()


class SourceAdapter(ABC):
    info: SourceInfo

    @abstractmethod
    def refresh_inventory(self, db: Session) -> Dict[str, int]:
        """Record what the source says exists and compare it with CPI."""

    def import_missing(self, db: Session, limit: Optional[int] = None) -> Dict[str, int]:
        return {"not_supported": 1}
