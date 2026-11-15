"""
Player directory search: fuzzy name matching, scoped career statistics, filters and sorting.

Everything is derived from data already in the database:

* Names come from ``players.canonical_name``, the ``full_name`` attribute,
  ``player_aliases`` (provider spellings) and ``player_name_aliases`` (reference
  names such as Cricsheet ``names.csv``), so initials, full names and alternate
  spellings all resolve to the same player.
* Statistics come from the persisted per-innings tables ``scouting_bat_innings``
  / ``scouting_bowl_innings`` (see ``app.analytics.scouting_aggregates``), which
  already apply the cricket rules (super overs excluded, legal balls, bowler
  wickets, ...). One grouped query per scope (format x gender x competition x
  team) aggregates every player; the result is cached in-process and cleared by
  ``app.services.data_version`` when new matches are imported.
* Nothing is estimated: a player without data in a scope has no stats there, and
  attributes that are not recorded (batting style, images, ...) stay empty.
"""
from __future__ import annotations

import bisect
import difflib
import re
import threading
import unicodedata
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Dict, Iterable, List, Optional, Set, Tuple

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.analytics.player_roles import classify_player_role

# A player is "active" when they appeared within this window of the latest match
# recorded for their gender. Relative to the data, not today's date, so a stale
# import never marks everybody inactive.
ACTIVE_WINDOW_DAYS = 365

# Minimum sample before a player is ranked on a rate statistic. Counting
# statistics (runs, wickets, matches) are never thresholded.
# Thresholds scale with format length (balls faced / legal balls bowled).
QUALIFIER_BALLS = {
    "T20": (100, 120), "T20I": (100, 120),
    "ODI": (250, 300), "ODM": (250, 300),
    "Test": (500, 600), "MDM": (500, 600),
    None: (250, 300),  # all formats combined
}
RATE_STATS = {
    "batting_average": "balls_faced", "batting_strike_rate": "balls_faced",
    "bowling_average": "legal_balls", "economy": "legal_balls", "bowling_strike_rate": "legal_balls",
}


def rate_qualifier(sort: str, match_format: Optional[str]) -> Optional[Tuple[str, int]]:
    stat = RATE_STATS.get(sort)
    if not stat:
        return None
    bat, bowl = QUALIFIER_BALLS.get(match_format, QUALIFIER_BALLS[None])
    return stat, (bat if stat == "balls_faced" else bowl)

SORT_FIELDS = {
    "relevance", "name", "matches", "runs", "batting_average", "batting_strike_rate", "highest_score",
    "hundreds", "fifties", "sixes", "wickets", "bowling_average", "economy", "bowling_strike_rate",
    "five_wickets", "last_played",
}
# Lower is better for these; "desc" (the UI's "best first") therefore sorts ascending.
LOWER_IS_BETTER = {"bowling_average", "economy", "bowling_strike_rate"}

ROLE_FILTERS = {
    "batter": {"Specialist Batter", "Wicketkeeper-Batter"},
    "bowler": {"Specialist Bowler"},
    "all_rounder": {"Batting All-Rounder", "Bowling All-Rounder"},
    "wicketkeeper": {"Wicketkeeper-Batter"},
    "unclassified": {"Unclassified"},
}

# Query words that describe a role or bowling type rather than a name.
CONTEXT_SYNONYMS = {
    "batter": "batter", "batsman": "batter", "batters": "batter", "batsmen": "batter", "bat": "batter",
    "bowler": "bowler", "bowlers": "bowler",
    "allrounder": "allrounder", "allrounders": "allrounder", "all-rounder": "allrounder", "ar": "allrounder",
    "spinner": "spin", "spinners": "spin", "spin": "spin",
    "pacer": "pace", "pacers": "pace", "pace": "pace", "seamer": "pace", "seamers": "pace", "seam": "pace",
    "quick": "pace", "fast": "fast",
    "keeper": "wicketkeeper", "wicketkeeper": "wicketkeeper", "wk": "wicketkeeper",
}

_cache_lock = threading.Lock()
_directory: Optional["Directory"] = None
_scopes: "OrderedDict[tuple, Scope]" = OrderedDict()
_MAX_SCOPES = 24


def clear_cache() -> None:
    global _directory
    with _cache_lock:
        _directory = None
        _scopes.clear()


# --------------------------------------------------------------------------- text helpers

_NON_WORD = re.compile(r"[^a-z0-9\s]")


def normalize(value: str) -> str:
    value = unicodedata.normalize("NFKD", value or "")
    value = "".join(ch for ch in value if not unicodedata.combining(ch)).lower()
    value = value.replace("-", " ").replace("'", "").replace(".", " ")
    return " ".join(_NON_WORD.sub(" ", value).split())


def tokens(value: str) -> List[str]:
    return normalize(value).split()


class TokenIndex:
    """Inverted index token -> ids with exact, prefix and fuzzy lookups."""

    def __init__(self) -> None:
        self.postings: Dict[str, Set[str]] = {}
        self._sorted: List[str] = []

    def add(self, token: str, ident: str) -> None:
        if token:
            self.postings.setdefault(token, set()).add(ident)

    def freeze(self) -> None:
        self._sorted = sorted(self.postings)

    def lookup(self, token: str, fuzzy: bool = True) -> Dict[str, float]:
        """Return id -> match strength (1 exact, 0.85 prefix, <=0.75 fuzzy) for one query token."""
        out: Dict[str, float] = {}

        def put(ids: Iterable[str], score: float) -> None:
            for ident in ids:
                if score > out.get(ident, 0.0):
                    out[ident] = score

        if token in self.postings:
            put(self.postings[token], 1.0)
        start = bisect.bisect_left(self._sorted, token)
        for i in range(start, len(self._sorted)):
            cand = self._sorted[i]
            if not cand.startswith(token):
                break
            if cand != token:
                put(self.postings[cand], 0.85)
        if fuzzy and len(token) >= 4:
            cutoff = 0.8 if len(token) <= 5 else 0.75
            for cand in difflib.get_close_matches(token, self._sorted, n=12, cutoff=cutoff):
                if cand != token:
                    ratio = difflib.SequenceMatcher(None, token, cand).ratio()
                    put(self.postings[cand], round(0.75 * ratio, 3))
        return out


# --------------------------------------------------------------------------- directory (bio + names)

@dataclass
class PlayerEntry:
    id: str
    name: str
    full_name: Optional[str] = None
    names_norm: List[str] = field(default_factory=list)
    nationality: Optional[str] = None
    primary_role: Optional[str] = None
    batting_style: Optional[str] = None
    bowling_style: Optional[str] = None
    bowling_type: Optional[str] = None
    bowling_arm: Optional[str] = None
    bowling_speed_category: Optional[str] = None
    player_image: Optional[str] = None
    date_of_birth: Optional[date] = None


@dataclass
class Directory:
    players: Dict[str, PlayerEntry]
    name_index: TokenIndex
    context_index: TokenIndex
    teams: Dict[str, str]                      # team id -> name
    team_index: TokenIndex                     # team name tokens / initials -> team ids
    latest_by_gender: Dict[str, date]


BIO_TYPES = ("full_name", "nationality", "primary_role", "batting_style", "bowling_style", "bowling_type",
             "bowling_arm", "bowling_speed_category", "player_image", "date_of_birth")


def _initials(name_tokens: List[str]) -> str:
    return "".join(t[0] for t in name_tokens if t)


def _build_directory(db: Session) -> Directory:
    players: Dict[str, PlayerEntry] = {
        pid: PlayerEntry(id=pid, name=name)
        for pid, name in db.execute(text("SELECT id, canonical_name FROM players")).all()
    }
    # Highest-confidence, most recent value per attribute (same precedence as the profile endpoint).
    attr_rows = db.execute(text("""
        SELECT DISTINCT ON (player_id, attribute_type) player_id, attribute_type, attribute_value
        FROM player_attributes
        WHERE attribute_type = ANY(:types)
        ORDER BY player_id, attribute_type,
                 CASE confidence WHEN 'high' THEN 3 WHEN 'medium' THEN 2 WHEN 'low' THEN 1 ELSE 0 END DESC,
                 updated_at DESC
    """), {"types": list(BIO_TYPES)}).all()
    for pid, attr, value in attr_rows:
        entry = players.get(pid)
        if entry is None or value in (None, ""):
            continue
        if attr == "nationality" and value == "Unknown":
            continue
        if attr == "bowling_style" and value.lower().startswith("other"):
            continue
        if attr == "date_of_birth":
            try:
                entry.date_of_birth = date.fromisoformat(value)
            except ValueError:
                pass
            continue
        setattr(entry, attr, value)

    alias_names: Dict[str, Set[str]] = {}
    for pid, alias in db.execute(text(
        "SELECT player_id, source_name FROM player_aliases UNION SELECT player_id, alias FROM player_name_aliases"
    )).all():
        alias_names.setdefault(pid, set()).add(alias)

    name_index, context_index = TokenIndex(), TokenIndex()
    for pid, entry in players.items():
        raw_names = {entry.name, *(alias_names.get(pid) or ())}
        if entry.full_name:
            raw_names.add(entry.full_name)
        normed = []
        for raw in raw_names:
            norm = normalize(raw)
            if not norm or norm in normed:
                continue
            normed.append(norm)
            toks = norm.split()
            for tok in toks:
                name_index.add(tok, pid)
            if len(toks) >= 2:
                # "Mahendra Singh Dhoni" -> "msd", "ms"; also joined surname-less forms like "abde".
                name_index.add(_initials(toks), pid)
                name_index.add(_initials(toks[:-1]), pid)
                name_index.add("".join(toks), pid)
        entry.names_norm = normed
        for value in (entry.nationality, entry.bowling_style, entry.bowling_type, entry.bowling_arm,
                      entry.bowling_speed_category, entry.batting_style):
            for tok in tokens(value or ""):
                context_index.add(tok, pid)
        role_tok = normalize(entry.primary_role or "")
        if "keeper" in role_tok or "wk" in role_tok.split():
            context_index.add("wicketkeeper", pid)
    name_index.freeze()
    context_index.freeze()

    teams = {tid: name for tid, name in db.execute(text("SELECT id, name FROM teams")).all()}
    team_index = TokenIndex()
    team_names: Dict[str, Set[str]] = {tid: {name} for tid, name in teams.items()}
    for tid, alias in db.execute(text("SELECT team_id, source_name FROM team_aliases")).all():
        team_names.setdefault(tid, set()).add(alias)
    for tid, names in team_names.items():
        for raw in names:
            toks = [t for t in tokens(raw) if t not in {"women", "men"}]
            for tok in toks:
                team_index.add(tok, tid)
            if len(toks) >= 2:
                team_index.add(_initials(toks), tid)  # "Chennai Super Kings" -> "csk"
    team_index.freeze()

    latest = {g: d for g, d in db.execute(text(
        "SELECT lower(gender), max(start_date) FROM matches WHERE start_date IS NOT NULL GROUP BY 1"
    )).all() if g}
    return Directory(players=players, name_index=name_index, context_index=context_index,
                     teams=teams, team_index=team_index, latest_by_gender=latest)


def get_directory(db: Session) -> Directory:
    global _directory
    with _cache_lock:
        if _directory is not None:
            return _directory
    built = _build_directory(db)
    with _cache_lock:
        _directory = built
    return built


# --------------------------------------------------------------------------- scoped statistics

@dataclass
class ScopeRow:
    player_id: str
    gender: Optional[str]
    matches: int
    bat_innings: int
    runs: int
    balls_faced: int
    dismissals: int
    not_outs: int
    highest_score: Optional[int]
    highest_not_out: bool
    fours: int
    sixes: int
    fifties: int
    hundreds: int
    bowl_innings: int
    legal_balls: int
    runs_conceded: int
    wickets: int
    five_wickets: int
    best_wickets: Optional[int]
    best_runs: Optional[int]
    first_played: Optional[date]
    last_played: Optional[date]
    team_ids: List[str]
    formats: List[str]
    role: str = "Unclassified"

    @property
    def batting_average(self) -> Optional[float]:
        return round(self.runs / self.dismissals, 2) if self.dismissals else None

    @property
    def batting_strike_rate(self) -> Optional[float]:
        return round(self.runs * 100.0 / self.balls_faced, 2) if self.balls_faced else None

    @property
    def bowling_average(self) -> Optional[float]:
        return round(self.runs_conceded / self.wickets, 2) if self.wickets else None

    @property
    def economy(self) -> Optional[float]:
        return round(self.runs_conceded * 6.0 / self.legal_balls, 2) if self.legal_balls else None

    @property
    def bowling_strike_rate(self) -> Optional[float]:
        return round(self.legal_balls / self.wickets, 2) if self.wickets else None


@dataclass
class Scope:
    rows: Dict[str, ScopeRow]


_SCOPE_SQL = """
WITH bat AS (
    SELECT player_id,
           count(*) AS inns, sum(runs) AS runs, sum(balls) AS balls,
           sum(dismissed::int) AS outs, sum(fours) AS fours, sum(sixes) AS sixes,
           sum((runs >= 50 AND runs < 100)::int) AS fifties, sum((runs >= 100)::int) AS hundreds,
           -- highest score, preferring a not-out innings on ties: key = runs*2 + not_out
           max(runs * 2 + (NOT dismissed)::int) AS hs_key
    FROM scouting_bat_innings s
    WHERE {where}
    GROUP BY player_id
), bowl AS (
    SELECT player_id,
           count(*) AS inns, sum(legal_balls) AS lb, sum(runs) AS rc, sum(wickets) AS wkts,
           sum((wickets >= 5)::int) AS five_w,
           -- best figures: most wickets, then fewest runs
           max(wickets * 10000 + (9999 - LEAST(runs, 9999))) AS best_key
    FROM scouting_bowl_innings s
    WHERE {where}
    GROUP BY player_id
), app_rows AS (
    SELECT player_id, match_id, gender, start_date, team_id, match_format FROM scouting_bat_innings s WHERE {where}
    UNION ALL
    SELECT player_id, match_id, gender, start_date, team_id, match_format FROM scouting_bowl_innings s WHERE {where}
), per_match AS (
    -- one row per player per match (hash aggregate; avoids sorting the whole table for count DISTINCT)
    SELECT player_id, match_id, min(gender) AS gender, min(start_date) AS d, min(match_format) AS f
    FROM app_rows GROUP BY player_id, match_id
), per_team AS (
    SELECT player_id, team_id FROM app_rows WHERE team_id IS NOT NULL GROUP BY player_id, team_id
), per_format AS (
    SELECT player_id, f FROM per_match GROUP BY player_id, f
), team_lists AS (
    SELECT player_id, array_agg(team_id) AS teams FROM per_team GROUP BY player_id
), format_lists AS (
    SELECT player_id, array_agg(f) AS formats FROM per_format GROUP BY player_id
), apps AS (
    SELECT pm.player_id, min(pm.gender) AS gender, count(*) AS matches, min(pm.d) AS first_d, max(pm.d) AS last_d
    FROM per_match pm GROUP BY pm.player_id
)
SELECT a.player_id, a.gender, a.matches,
       COALESCE(b.inns, 0), COALESCE(b.runs, 0), COALESCE(b.balls, 0), COALESCE(b.outs, 0),
       b.hs_key, NULL, COALESCE(b.fours, 0), COALESCE(b.sixes, 0),
       COALESCE(b.fifties, 0), COALESCE(b.hundreds, 0),
       COALESCE(w.inns, 0), COALESCE(w.lb, 0), COALESCE(w.rc, 0), COALESCE(w.wkts, 0), COALESCE(w.five_w, 0),
       w.best_key, NULL,
       a.first_d, a.last_d, tl.teams, fl.formats
FROM apps a
LEFT JOIN team_lists tl ON tl.player_id = a.player_id
LEFT JOIN format_lists fl ON fl.player_id = a.player_id
LEFT JOIN bat b ON b.player_id = a.player_id
LEFT JOIN bowl w ON w.player_id = a.player_id
"""


def _build_scope(db: Session, directory: Directory, match_format: Optional[str], gender: Optional[str],
                 competition: Optional[str], team_id: Optional[str]) -> Scope:
    where, params = ["1=1"], {}
    if match_format:
        where.append("s.match_format = :fmt")
        params["fmt"] = match_format
    if gender:
        where.append("s.gender = :gender")
        params["gender"] = gender
    if competition:
        where.append("s.tournament_id IN (SELECT id FROM tournaments WHERE name = :competition)")
        params["competition"] = competition
    if team_id:
        where.append("s.team_id = :team_id")
        params["team_id"] = team_id
    rows: Dict[str, ScopeRow] = {}
    # The grouped aggregates spill to disk at the default 4MB work_mem (~3.5s vs ~1s).
    # SET LOCAL only lasts for the current transaction.
    db.execute(text("SET LOCAL work_mem = '256MB'"))
    for r in db.execute(text(_SCOPE_SQL.format(where=" AND ".join(where))), params).all():
        row = ScopeRow(
            player_id=r[0], gender=r[1], matches=int(r[2] or 0), bat_innings=int(r[3]), runs=int(r[4]),
            balls_faced=int(r[5]), dismissals=int(r[6]), not_outs=max(0, int(r[3]) - int(r[6])),
            highest_score=(r[7] // 2) if r[7] is not None else None,
            highest_not_out=bool(r[7] is not None and r[7] % 2 == 1), fours=int(r[9]), sixes=int(r[10]),
            fifties=int(r[11]), hundreds=int(r[12]), bowl_innings=int(r[13]), legal_balls=int(r[14]),
            runs_conceded=int(r[15]), wickets=int(r[16]), five_wickets=int(r[17]),
            best_wickets=(r[18] // 10000) if r[18] is not None else None,
            best_runs=(9999 - r[18] % 10000) if r[18] is not None else None, first_played=r[20], last_played=r[21], team_ids=list(r[22] or []),
            formats=list(r[23] or []),
        )
        entry = directory.players.get(row.player_id)
        row.role = classify_player_role(row.balls_faced, row.bat_innings, row.legal_balls, row.bowl_innings,
                                        entry.primary_role if entry else None)[0]
        rows[row.player_id] = row
    return Scope(rows=rows)


def get_scope(db: Session, directory: Directory, match_format: Optional[str], gender: Optional[str],
              competition: Optional[str], team_id: Optional[str]) -> Scope:
    key = (match_format or "", gender or "", competition or "", team_id or "")
    with _cache_lock:
        if key in _scopes:
            _scopes.move_to_end(key)
            return _scopes[key]
    scope = _build_scope(db, directory, match_format, gender, competition, team_id)
    with _cache_lock:
        _scopes[key] = scope
        while len(_scopes) > _MAX_SCOPES:
            _scopes.popitem(last=False)
    return scope


# --------------------------------------------------------------------------- query matching

def match_query(directory: Directory, scope: Scope, query: str) -> Tuple[Dict[str, float], Dict[str, str]]:
    """Return (player id -> relevance, player id -> why it matched).

    Every query word must match the player somewhere: a name (exact, prefix,
    initials or fuzzy), a team they played for in scope, their nationality,
    bowling style or role. Name hits weigh more than context hits.
    """
    q_norm = normalize(query)
    q_tokens = q_norm.split()
    if not q_tokens:
        return {}, {}
    scores: Optional[Dict[str, float]] = None
    reasons: Dict[str, str] = {}
    team_rows: Dict[str, Set[str]] = {}

    def players_in_teams(team_ids: Set[str]) -> Set[str]:
        key = ",".join(sorted(team_ids))
        if key not in team_rows:
            team_rows[key] = {pid for pid, row in scope.rows.items() if team_ids.intersection(row.team_ids)}
        return team_rows[key]

    for tok in q_tokens:
        per: Dict[str, float] = dict(directory.name_index.lookup(tok))
        synonym = CONTEXT_SYNONYMS.get(tok)
        if synonym in {"batter", "bowler", "allrounder"}:
            wanted = {"batter": ROLE_FILTERS["batter"], "bowler": ROLE_FILTERS["bowler"],
                      "allrounder": ROLE_FILTERS["all_rounder"]}[synonym]
            for pid, row in scope.rows.items():
                if row.role in wanted and per.get(pid, 0) < 0.5:
                    per[pid] = 0.5
                    reasons.setdefault(pid, "role")
        else:
            ctx_tok = synonym or tok
            for pid, strength in directory.context_index.lookup(ctx_tok, fuzzy=False).items():
                if strength * 0.5 > per.get(pid, 0):
                    per[pid] = strength * 0.5
                    reasons.setdefault(pid, "attribute")
        if len(tok) >= 2:
            team_hits = directory.team_index.lookup(tok, fuzzy=len(tok) >= 5)
            strong = {tid for tid, s in team_hits.items() if s >= 0.85}
            if strong:
                for pid in players_in_teams(strong):
                    if per.get(pid, 0) < 0.45:
                        per[pid] = 0.45
                        reasons.setdefault(pid, "team")
        if scores is None:
            scores = per
        else:
            scores = {pid: s + per[pid] for pid, s in scores.items() if pid in per}
        if not scores:
            return {}, {}

    assert scores is not None
    # Whole-phrase bonuses on any recorded name.
    for pid in list(scores):
        entry = directory.players.get(pid)
        if not entry:
            continue
        best = 0.0
        for name in entry.names_norm:
            if name == q_norm:
                best = max(best, 2.0)
            elif name.startswith(q_norm):
                best = max(best, 1.0)
            elif q_norm in name:
                best = max(best, 0.5)
        if best:
            scores[pid] += best
            reasons[pid] = "name"
        elif pid not in reasons:
            reasons[pid] = "name"
    # When there is a strong hit, drop the weak fuzzy tail (e.g. "dhoni" should not list "Dhani").
    top = max(scores.values(), default=0)
    if top >= 1.2:
        floor = top * 0.5
        scores = {pid: s for pid, s in scores.items() if s >= floor}
    return scores, reasons


# --------------------------------------------------------------------------- public search

def _age(dob: Optional[date]) -> Optional[int]:
    if not dob:
        return None
    today = date.today()
    return today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))


def _status(directory: Directory, row: Optional[ScopeRow]) -> Optional[str]:
    if not row or not row.last_played:
        return None
    latest = directory.latest_by_gender.get(row.gender or "") or max(directory.latest_by_gender.values(), default=None)
    if not latest:
        return None
    return "active" if row.last_played >= latest - timedelta(days=ACTIVE_WINDOW_DAYS) else "inactive"


def _card(directory: Directory, entry: PlayerEntry, row: Optional[ScopeRow], reason: Optional[str]) -> dict:
    teams = []
    if row:
        teams = sorted((directory.teams.get(t) for t in row.team_ids if directory.teams.get(t)))
    best = f"{row.best_wickets}/{row.best_runs}" if row and row.best_wickets is not None and row.legal_balls else None
    hs = None
    if row and row.highest_score is not None and row.bat_innings:
        hs = f"{row.highest_score}{'*' if row.highest_not_out else ''}"
    return {
        "id": entry.id,
        "name": entry.name,
        "full_name": entry.full_name if entry.full_name and entry.full_name != entry.name else None,
        "nationality": entry.nationality,
        "gender": row.gender if row else None,
        "age": _age(entry.date_of_birth),
        "player_image": entry.player_image,
        "role": row.role if row else (classify_player_role(0, 0, 0, 0, entry.primary_role)[0]),
        "batting_style": entry.batting_style,
        "bowling_style": entry.bowling_style,
        "bowling_type": entry.bowling_type,
        "bowling_arm": entry.bowling_arm,
        "teams": teams,
        "team_count": len(teams),
        "formats": sorted(row.formats) if row else [],
        "status": _status(directory, row),
        "first_played": row.first_played if row else None,
        "last_played": row.last_played if row else None,
        "match_reason": reason,
        "stats": None if not row else {
            "matches": row.matches,
            "bat_innings": row.bat_innings,
            "runs": row.runs,
            "balls_faced": row.balls_faced,
            "not_outs": row.not_outs,
            "highest_score": hs,
            "batting_average": row.batting_average,
            "batting_strike_rate": row.batting_strike_rate,
            "fifties": row.fifties,
            "hundreds": row.hundreds,
            "fours": row.fours,
            "sixes": row.sixes,
            "bowl_innings": row.bowl_innings,
            "legal_balls": row.legal_balls,
            "overs": f"{row.legal_balls // 6}.{row.legal_balls % 6}",
            "wickets": row.wickets,
            "runs_conceded": row.runs_conceded,
            "bowling_average": row.bowling_average,
            "economy": row.economy,
            "bowling_strike_rate": row.bowling_strike_rate,
            "five_wickets": row.five_wickets,
            "best_bowling": best,
        },
    }


def _sort_value(field_name: str, entry: PlayerEntry, row: Optional[ScopeRow]):
    if field_name == "name":
        return normalize(entry.name)
    if row is None:
        return None
    if field_name == "highest_score":
        return row.highest_score if row.bat_innings else None
    return getattr(row, field_name, None)


def search(db: Session, *, q: Optional[str] = None, match_format: Optional[str] = None,
           gender: Optional[str] = None, competition: Optional[str] = None, team_id: Optional[str] = None,
           nationality: Optional[str] = None, batting_style: Optional[str] = None,
           bowling_type: Optional[str] = None, bowling_style: Optional[str] = None,
           bowling_arm: Optional[str] = None, role: Optional[str] = None, status: Optional[str] = None,
           min_matches: Optional[int] = None, sort: str = "relevance", direction: str = "desc",
           page: int = 1, page_size: int = 24) -> dict:
    directory = get_directory(db)
    scope = get_scope(db, directory, match_format, gender, competition, team_id)
    scoped = bool(match_format or gender or competition or team_id)

    reasons: Dict[str, str] = {}
    if q and normalize(q):
        relevance, reasons = match_query(directory, scope, q)
        candidates = list(relevance)
    else:
        relevance = {}
        candidates = list(scope.rows)
    if scoped:
        # Inside a scope only players who actually appeared in it are listed.
        candidates = [pid for pid in candidates if pid in scope.rows]

    def keep(pid: str) -> bool:
        entry = directory.players.get(pid)
        if entry is None:
            return False
        row = scope.rows.get(pid)
        if nationality and entry.nationality != nationality:
            return False
        if batting_style and entry.batting_style != batting_style:
            return False
        if bowling_type and (entry.bowling_type or "").lower() != bowling_type.lower():
            return False
        if bowling_style and entry.bowling_style != bowling_style:
            return False
        if bowling_arm and (entry.bowling_arm or "").lower() != bowling_arm.lower():
            return False
        if role:
            current = row.role if row else "Unclassified"
            if current not in ROLE_FILTERS.get(role, {role}):
                return False
        if status and _status(directory, row) != status:
            return False
        if min_matches and (row is None or row.matches < min_matches):
            return False
        return True

    filtered = [pid for pid in candidates if keep(pid)]

    sort = sort if sort in SORT_FIELDS else "relevance"
    if sort == "relevance" and not relevance:
        sort = "runs"
    qualifier = rate_qualifier(sort, match_format)
    unqualified = 0
    if qualifier:
        attr, minimum = qualifier
        before = len(filtered)
        filtered = [pid for pid in filtered if scope.rows.get(pid) and getattr(scope.rows[pid], attr) >= minimum]
        unqualified = before - len(filtered)

    def matches_of(pid: str) -> int:
        row = scope.rows.get(pid)
        return row.matches if row else 0

    if sort == "relevance":
        filtered.sort(key=lambda pid: (-relevance.get(pid, 0), -matches_of(pid), directory.players[pid].name))
    else:
        best_first = direction != "asc"
        ascending = (not best_first) if sort not in LOWER_IS_BETTER else best_first
        if sort == "name":
            ascending = direction != "desc"
        with_value = [(pid, _sort_value(sort, directory.players[pid], scope.rows.get(pid))) for pid in filtered]
        present = [(pid, v) for pid, v in with_value if v is not None]
        missing = [pid for pid, v in with_value if v is None]
        present.sort(key=lambda item: (item[1], -matches_of(item[0])) if ascending else (item[1], matches_of(item[0])),
                     reverse=not ascending)
        filtered = [pid for pid, _ in present] + sorted(missing, key=lambda pid: directory.players[pid].name)

    total = len(filtered)
    start = (page - 1) * page_size
    page_ids = filtered[start:start + page_size]
    players = [_card(directory, directory.players[pid], scope.rows.get(pid), reasons.get(pid)) for pid in page_ids]
    return {
        "players": players,
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": (total + page_size - 1) // page_size if total else 0,
        "sort": sort,
        "qualifier": ({"stat": qualifier[0], "minimum": qualifier[1], "excluded": unqualified}
                      if qualifier else None),
        "active_window_days": ACTIVE_WINDOW_DAYS,
    }


def suggest(db: Session, q: str, limit: int = 8) -> List[dict]:
    """Lightweight typeahead: best name matches across all players plus matching teams."""
    directory = get_directory(db)
    scope = get_scope(db, directory, None, None, None, None)
    relevance, reasons = match_query(directory, scope, q)
    ranked = sorted(relevance, key=lambda pid: (-relevance[pid], -(scope.rows[pid].matches if pid in scope.rows else 0)))
    out = []
    for pid in ranked[:limit]:
        entry = directory.players[pid]
        row = scope.rows.get(pid)
        out.append({
            "type": "player", "id": pid, "name": entry.name,
            "full_name": entry.full_name if entry.full_name and entry.full_name != entry.name else None,
            "nationality": entry.nationality, "role": row.role if row else None,
            "gender": row.gender if row else None, "matches": row.matches if row else 0,
            "match_reason": reasons.get(pid),
        })
    team_hits: Dict[str, float] = {}
    q_tokens = normalize(q).split()
    if len(normalize(q)) >= 2:
        for i, tok in enumerate(q_tokens):
            hits = directory.team_index.lookup(tok, fuzzy=False)
            team_hits = hits if i == 0 else {t: s + hits[t] for t, s in team_hits.items() if t in hits}
    for tid in sorted(team_hits, key=lambda t: (-team_hits[t], directory.teams.get(t, "")))[:3]:
        if tid in directory.teams:
            out.append({"type": "team", "id": tid, "name": directory.teams[tid]})
    return out


def options(db: Session, match_format: Optional[str], gender: Optional[str]) -> dict:
    """Filter values that exist in the data for this format/gender, with player counts."""
    directory = get_directory(db)
    scope = get_scope(db, directory, match_format, gender, None, None)

    def counted(values: Iterable[Optional[str]]) -> List[dict]:
        counts: Dict[str, int] = {}
        for value in values:
            if value:
                counts[value] = counts.get(value, 0) + 1
        return [{"value": v, "count": c} for v, c in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))]

    entries = [directory.players[pid] for pid in scope.rows if pid in directory.players]
    team_counts: Dict[str, int] = {}
    for row in scope.rows.values():
        for tid in row.team_ids:
            team_counts[tid] = team_counts.get(tid, 0) + 1

    where, params = ["1=1"], {}
    if match_format:
        where.append("m.match_format = :fmt")
        params["fmt"] = match_format
    if gender:
        where.append("lower(m.gender) = :gender")
        params["gender"] = gender
    competitions = [{"value": name, "count": int(n), "formats": list(fmts or [])} for name, n, fmts in db.execute(text(f"""
        SELECT t.name, count(*) AS n, array_agg(DISTINCT m.match_format) AS fmts
        FROM matches m JOIN tournaments t ON t.id = m.tournament_id
        WHERE {' AND '.join(where)}
        GROUP BY t.name ORDER BY n DESC, t.name
    """), params).all()]

    return {
        "players_in_scope": len(scope.rows),
        "nationalities": counted(e.nationality for e in entries),
        "batting_styles": counted(e.batting_style for e in entries),
        "bowling_types": counted(e.bowling_type for e in entries),
        "bowling_styles": counted(e.bowling_style for e in entries),
        "bowling_arms": counted(e.bowling_arm for e in entries),
        "roles": counted(row.role for row in scope.rows.values()),
        "teams": [{"value": tid, "label": directory.teams[tid], "count": c}
                  for tid, c in sorted(team_counts.items(), key=lambda kv: directory.teams.get(kv[0], ""))
                  if tid in directory.teams],
        "competitions": competitions,
        "status_counts": counted(_status(directory, row) for row in scope.rows.values()),
        "latest_match_by_gender": {g: d.isoformat() for g, d in directory.latest_by_gender.items()},
        "active_window_days": ACTIVE_WINDOW_DAYS,
        "rate_qualifiers": {k: {"stat": q[0], "minimum": q[1]}
                            for k in RATE_STATS for q in [rate_qualifier(k, match_format)]},
    }


def warm_cache(session_factory) -> None:
    """Build the directory and the default (all players) scope so the first search is fast."""
    db = session_factory()
    try:
        directory = get_directory(db)
        get_scope(db, directory, None, None, None, None)
    except Exception:  # pragma: no cover - warming is best effort
        import logging
        logging.getLogger(__name__).debug("player search warm-up failed", exc_info=True)
    finally:
        db.close()
