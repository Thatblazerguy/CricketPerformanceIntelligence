"""Auction-name → CPI player identity resolution.

Builds on the existing alias index used by the auction upload endpoints
(canonical names, Cricsheet ``names.csv`` spellings, CPI overrides) and adds:

* the outside-edge ``name_aliases.csv`` mapping (auction spelling → Cricsheet
  spelling) and player registry aliases;
* disambiguation of multiple candidates using *men's T20 activity before the
  auction date* — an auction entrant must be an active men's T20 cricketer, so
  candidates with no men's T20 appearance in the five years before the auction
  are discarded. If more than one candidate survives, the identity stays
  AMBIGUOUS; nothing is merged by guesswork.
"""
from __future__ import annotations

import csv
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path
from typing import Dict, Iterable, Optional, Set, Tuple

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api.routes.auction import _matching_player_ids, _player_name_index, _player_name_key
from app.auction_csv import auction_registry

PROJECT_ROOT = Path(__file__).resolve().parents[3]


class IdentityResolver:
    def __init__(self, db: Session):
        self.db = db
        self.index = _player_name_index(db)
        self.extra_aliases: Dict[str, Set[str]] = defaultdict(set)
        path = PROJECT_ROOT / "data/auction/sources/outside_edge_upstream/name_aliases.csv"
        if path.exists():
            with path.open(newline="", encoding="utf-8-sig") as fh:
                for row in csv.DictReader(fh):
                    a, b = row.get("auction_name"), row.get("performance_name")
                    if a and b:
                        self.extra_aliases[_player_name_key(a)].add(b)
        for names in auction_registry().values():
            keys = {_player_name_key(n) for n in names}
            for k in keys:
                self.extra_aliases[k].update(names)
        self._activity: Dict[Tuple[str, int], bool] = {}

    def candidates(self, name: str) -> Set[str]:
        """Exact alias matches only (no initial-letter fallback)."""
        found = set(self.index.get(_player_name_key(name), ()))
        for alias in self.extra_aliases.get(_player_name_key(name), ()):
            found.update(self.index.get(_player_name_key(alias), ()))
        return found

    # -- broader, evidence-filtered candidate search ----------------------
    def _reverse(self) -> Dict[str, Set[str]]:
        if not hasattr(self, "_rev"):
            self._rev = defaultdict(set)
            for key, pids in self.index.items():
                for pid in pids:
                    self._rev[pid].add(key)
            self._by_surname = defaultdict(set)
            for key in self.index:
                toks = key.split()
                if len(toks) >= 2:
                    self._by_surname[toks[-1]].add(key)
        return self._rev

    def _given_name_conflict(self, pid: str, given: str, surname_keys: Set[str]) -> bool:
        """True when the player's known full given name contradicts ``given``."""
        full_given = set()
        for alias in self._rev.get(pid, ()):
            toks = alias.split()
            if len(toks) >= 2 and toks[-1] in surname_keys:
                for t in toks[:-1]:
                    if len(t) > 2:
                        full_given.add(t)
        return bool(full_given) and given not in full_given

    def broad_candidates(self, name: str) -> Tuple[Set[str], bool]:
        self._reverse()
        key = _player_name_key(name)
        toks = key.split()
        if len(toks) < 2:
            return set(), False
        given, surname = toks[0], toks[-1]
        surnames = {surname} | {s for s in self._by_surname if len(surname) >= 5 and s[:1] == surname[:1]
                                and abs(len(s) - len(surname)) <= 2 and _edit_distance(s, surname) <= 2}
        fuzzy_used = False
        found: Set[str] = set()
        for sn in surnames:
            for alias in self._by_surname.get(sn, ()):
                atoks = alias.split()
                initials = "".join(t[0] for t in atoks[:-1])
                if set(toks[:-1]) <= set(atoks[:-1]) or initials.startswith(given[0]) or given in atoks:
                    found.update(self.index[alias])
                    fuzzy_used |= sn != surname
        found = {pid for pid in found if not self._given_name_conflict(pid, given, surnames)}
        return found, fuzzy_used

    def _active_men_t20(self, ids: Iterable[str], auction_date: date) -> Set[str]:
        ids = list(ids)
        if not ids:
            return set()
        return set(self.db.execute(text("""
            SELECT DISTINCT player_id FROM (
              SELECT player_id FROM scouting_bat_innings
               WHERE player_id = ANY(:ids) AND gender='male' AND match_format IN ('T20','T20I')
                 AND start_date BETWEEN :since AND :until
              UNION
              SELECT player_id FROM scouting_bowl_innings
               WHERE player_id = ANY(:ids) AND gender='male' AND match_format IN ('T20','T20I')
                 AND start_date BETWEEN :since AND :until) x
        """), {"ids": ids, "since": auction_date - timedelta(days=5 * 365),
               "until": auction_date + timedelta(days=200)}).scalars().all())

    def _ipl_active(self, ids: Iterable[str], auction_date: date) -> Set[str]:
        ids = list(ids)
        if not ids:
            return set()
        return set(self.db.execute(text("""
            SELECT DISTINCT x.player_id FROM (
              SELECT player_id, tournament_id, start_date FROM scouting_bat_innings WHERE player_id = ANY(:ids)
              UNION ALL
              SELECT player_id, tournament_id, start_date FROM scouting_bowl_innings WHERE player_id = ANY(:ids)) x
            JOIN tournaments t ON t.id = x.tournament_id
            WHERE t.name = 'Indian Premier League' AND x.start_date BETWEEN :since AND :until
        """), {"ids": ids, "since": auction_date - timedelta(days=3 * 365),
               "until": auction_date + timedelta(days=550)}).scalars().all())

    def _ipl_before(self, ids: Iterable[str], auction_date: date) -> Set[str]:
        ids = list(ids)
        if not ids:
            return set()
        return set(self.db.execute(text("""
            SELECT DISTINCT x.player_id FROM (
              SELECT player_id, tournament_id, start_date FROM scouting_bat_innings WHERE player_id = ANY(:ids)
              UNION ALL
              SELECT player_id, tournament_id, start_date FROM scouting_bowl_innings WHERE player_id = ANY(:ids)) x
            JOIN tournaments t ON t.id = x.tournament_id
            WHERE t.name = 'Indian Premier League' AND x.start_date < :cutoff
        """), {"ids": ids, "cutoff": auction_date}).scalars().all())

    def resolve(self, name: str, auction_date: Optional[date], *, prior_ipl: Optional[bool] = None
                ) -> Tuple[Optional[str], str]:
        """``prior_ipl``: what the auction record itself says about IPL caps before
        the auction (True / False / None = not stated). Candidates contradicting it
        are excluded — e.g. an uncapped debutant cannot be a player with IPL caps."""
        exact = self.candidates(name)
        broad, fuzzy = self.broad_candidates(name)
        exact_surname = set(broad) if not fuzzy else set()
        pool = (exact & broad) or exact or broad
        if prior_ipl is not None and auction_date is not None and pool:
            before = self._ipl_before(pool, auction_date)
            pool = (pool & before) if prior_ipl else (pool - before)
        if len(exact) == 1 and pool == exact:
            return next(iter(exact)), "MATCHED"
        if not pool:
            return None, "UNRESOLVED"
        if len(pool) == 1:
            pid = next(iter(pool))
            return pid, "MATCHED" if exact == pool else ("DISAMBIGUATED" if pid in exact or pid in exact_surname or not fuzzy else "FUZZY")
        if auction_date is not None:
            # Post-auction appearances are used only as identity evidence, never as features.
            for narrowing in (self._ipl_active, self._active_men_t20):
                narrowed = narrowing(pool, auction_date)
                if len(narrowed) == 1:
                    pid = next(iter(narrowed))
                    return pid, "DISAMBIGUATED" if (pid in exact or not fuzzy) else "FUZZY"
                if narrowed:
                    pool = narrowed
        return None, "AMBIGUOUS"


def _edit_distance(a: str, b: str) -> int:
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]
