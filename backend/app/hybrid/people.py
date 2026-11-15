"""Player identity across providers, from Cricsheet's people register (people.csv).

people.csv maps each Cricsheet person identifier to the same person's ID at
ESPNcricinfo, CricketArchive, BCCI, Cricbuzz and others. Those keys let a
scorecard from another provider resolve to the canonical CPI player without
guessing from names.
"""
from __future__ import annotations

import csv
from pathlib import Path
from typing import Dict, Optional, Tuple

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.core.config import resolve_backend_path
from app.models.models import Player, PlayerAlias, PlayerExternalId, PlayerNameAlias, Provider

PEOPLE_CSV = "../data/reference/cricsheet/people.csv"

RESOLVED, NAME_TEAM, UNRESOLVED = "resolved", "name_team", "unresolved"


def scheme_of(column: str) -> str:
    s = column[4:] if column.startswith("key_") else column
    return s[:-2] if s.endswith(("_2", "_3")) else s


def import_external_ids(db: Session, path: Optional[Path] = None) -> Dict[str, int]:
    path = path or resolve_backend_path(PEOPLE_CSV)
    if not path.exists():
        return {"error": 1}
    cricsheet = dict(db.execute(text("""SELECT pa.source_player_id, pa.player_id FROM player_aliases pa
                                        JOIN providers p ON p.id = pa.provider_id WHERE p.name = 'cricsheet'""")).all())
    rows = []
    with open(path, newline="", encoding="utf-8") as fh:
        for rec in csv.DictReader(fh):
            pid = cricsheet.get(rec["identifier"])
            if not pid:
                continue
            for col, val in rec.items():
                if col.startswith("key_") and val:
                    rows.append({"pid": pid, "scheme": scheme_of(col), "ext": val.strip()})
    for i in range(0, len(rows), 10000):
        db.execute(text("""INSERT INTO player_external_ids (id, player_id, id_scheme, external_id, source)
                           VALUES (gen_random_uuid()::text, :pid, :scheme, :ext, 'Cricsheet people.csv')
                           ON CONFLICT (id_scheme, external_id) DO NOTHING"""), rows[i:i + 10000])
    return {"external_ids": len(rows), "players": len({r["pid"] for r in rows})}


def resolve_player(db: Session, *, source_player_id: Optional[str], name: str,
                   team_name: Optional[str] = None) -> Tuple[Optional[str], str]:
    """Resolve a scorecard participant to a CPI player id.

    ``source_player_id`` is ``"<scheme>:<id>"`` (e.g. ``cricinfo:35320`` or
    ``cricsheet:d2c2b2d5``). Without an ID, a name is only accepted when exactly
    one CPI player has it AND that player is recorded playing for ``team_name``;
    otherwise the row stays unresolved rather than risk mis-attribution.
    """
    if source_player_id and ":" in source_player_id:
        scheme, ext = source_player_id.split(":", 1)
        if scheme == "cricsheet":
            pid = db.scalar(select(PlayerAlias.player_id).join(Provider, Provider.id == PlayerAlias.provider_id)
                            .where(Provider.name == "cricsheet", PlayerAlias.source_player_id == ext))
        else:
            pid = db.scalar(select(PlayerExternalId.player_id).where(PlayerExternalId.id_scheme == scheme,
                                                                     PlayerExternalId.external_id == ext))
        if pid:
            return pid, RESOLVED
    clean = name.strip()
    ids = set(db.scalars(select(Player.id).where(func.lower(Player.canonical_name) == clean.lower())))
    ids |= set(db.scalars(select(PlayerNameAlias.player_id).where(func.lower(PlayerNameAlias.alias) == clean.lower())))
    if len(ids) == 1 and team_name:
        pid = next(iter(ids))
        played_for = db.scalar(text("""SELECT 1 FROM match_appearances WHERE player_id = :p
                                       AND lower(team_name) = lower(:t) LIMIT 1"""), {"p": pid, "t": team_name})
        if played_for:
            return pid, NAME_TEAM
    return None, UNRESOLVED
