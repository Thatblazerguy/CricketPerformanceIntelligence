"""Playing XI upload, OCR, and roster resolution APIs.

Enables users across any CPI section to upload an entire Playing XI (via text,
CSV, or team-sheet / scorecard screenshot), resolve all 11 players against the
canonical CPI database with roles, styles, and team balance, and use that XI
for simulation, matchups, comparisons, scouting, and venue analysis.
"""
from __future__ import annotations

import csv
import difflib
import io
import re
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.models import Player, PlayerAlias, PlayerAttribute, PlayerNameAlias

router = APIRouter()
OCR_SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "ocr_match_screenshot.swift"


class ResolveXiRequest(BaseModel):
    team_name: Optional[str] = "Uploaded Playing XI"
    names: Optional[List[str]] = None
    text: Optional[str] = None
    format: Optional[str] = "T20"


class PlayerXiItem(BaseModel):
    order: int
    input_name: str
    id: Optional[str] = None
    name: Optional[str] = None
    matched: bool = False
    confidence: str = "unmatched"  # exact, alias, initial_surname, fuzzy, unmatched
    primary_role: Optional[str] = None
    batting_style: Optional[str] = None
    bowling_type: Optional[str] = None
    bowling_style: Optional[str] = None
    is_captain: bool = False
    is_wicketkeeper: bool = False
    alternatives: List[Dict[str, Any]] = Field(default_factory=list)


class TeamBalance(BaseModel):
    batters: int = 0
    all_rounders: int = 0
    bowlers: int = 0
    wicketkeepers: int = 0
    pace_bowlers: int = 0
    spin_bowlers: int = 0
    left_hand_batters: int = 0
    right_hand_batters: int = 0


class ResolveXiResponse(BaseModel):
    team_name: str
    total_players: int
    matched_count: int
    players: List[PlayerXiItem]
    balance: TeamBalance
    message: Optional[str] = None


_CAPTAIN_TAGS = {"c", "capt", "captain"}
_KEEPER_TAGS = {"wk", "w/k", "w", "keeper", "wicketkeeper", "wicket-keeper"}


def clean_player_name(raw: str) -> tuple[str, bool, bool]:
    """Strip order numbers, captain/wk tags, and excess punctuation.

    Tags are only recognised inside brackets, e.g. ``(c)``, ``[wk]``, ``(c/wk)``,
    or as scorecard symbols (``*`` captain, ``†`` keeper), so names such as
    "Chris Woakes" are never mistaken for tags.
    """
    item = raw.strip()
    is_capt = is_wk = False
    for tag in re.findall(r"[\(\[]([^\)\]]*)[\)\]]", item):
        folded = tag.strip().casefold()
        parts = {p for p in re.split(r"[\s,&+]+|/(?!k\b)", folded) if p}
        if parts & _CAPTAIN_TAGS:
            is_capt = True
        if parts & _KEEPER_TAGS or "w/k" in folded:
            is_wk = True
    if "†" in item:
        is_wk = True
    if re.search(r"\*\s*$|^\s*\*|\w\*", item):
        is_capt = True

    # Strip numbers at start: '1.', '1)', '1 -', '#1'
    cleaned = re.sub(r"^[#\d]+[\.\)\-\:\s]+", "", item)
    # Strip bracketed tags only when they are captain/keeper/vice-captain markers.
    def _strip(match):
        inner = {p for p in re.split(r"[\s,&+/]+", match.group(1).strip().casefold()) if p}
        return "" if inner and inner <= (_CAPTAIN_TAGS | _KEEPER_TAGS | {"k", "vc"}) else match.group(0)
    cleaned = re.sub(r"[\(\[]([^\)\]]*)[\)\]]", _strip, cleaned)
    cleaned = cleaned.replace("†", "").replace("*", "")
    # Clean whitespace and trailing punctuation
    cleaned = re.sub(r"[\,\;\:\-]+$", "", cleaned)
    cleaned = re.sub(r"\s{2,}", " ", cleaned).strip()
    return cleaned, is_capt, is_wk


def _fetch_player_attributes(player_ids: set[str], db: Session) -> Dict[str, Dict[str, Any]]:
    """Batch fetch all attributes for a set of player IDs."""
    if not player_ids:
        return {}
    rows = db.execute(
        select(PlayerAttribute.player_id, PlayerAttribute.attribute_type, PlayerAttribute.attribute_value)
        .where(
            PlayerAttribute.player_id.in_(player_ids),
            PlayerAttribute.attribute_type.in_([
                "primary_role", "batting_style", "batting_hand",
                "bowling_type", "bowling_style", "bowling_category",
                "bowling_arm", "nationality"
            ])
        )
    ).all()
    attr_map: Dict[str, Dict[str, Any]] = {pid: {} for pid in player_ids}
    for pid, atype, avalue in rows:
        if atype in ("batting_style", "batting_hand") and "batting_style" not in attr_map[pid]:
            attr_map[pid]["batting_style"] = avalue
        elif atype in ("bowling_type", "bowling_category") and "bowling_type" not in attr_map[pid]:
            attr_map[pid]["bowling_type"] = avalue
        elif atype == "bowling_style" and "bowling_style" not in attr_map[pid]:
            attr_map[pid]["bowling_style"] = avalue
        elif atype == "primary_role" and "primary_role" not in attr_map[pid]:
            attr_map[pid]["primary_role"] = avalue
        elif atype == "nationality" and "nationality" not in attr_map[pid]:
            attr_map[pid]["nationality"] = avalue

    # For any matched player without an explicit primary_role, deduce from delivery workload
    from app.models.models import Delivery
    from app.analytics.player_roles import classify_player_role
    from sqlalchemy import func

    for pid in player_ids:
        if not attr_map[pid].get("primary_role"):
            b_balls = db.scalar(select(func.count(Delivery.id)).where(Delivery.batter_id == pid)) or 0
            w_balls = db.scalar(select(func.count(Delivery.id)).where(Delivery.bowler_id == pid)) or 0
            role, _, _ = classify_player_role(b_balls, max(1, b_balls // 20), w_balls, max(1, w_balls // 20))
            if role and role != "Unclassified":
                attr_map[pid]["primary_role"] = role
            elif attr_map[pid].get("bowling_type"):
                attr_map[pid]["primary_role"] = "Specialist Bowler" if w_balls > b_balls else "Specialist Batter"
            else:
                attr_map[pid]["primary_role"] = "Specialist Batter" if b_balls >= w_balls else "Specialist Bowler"

    return attr_map


def _resolve_single_player(
    raw_name: str,
    db: Session,
    alias_dict: Optional[Dict[str, tuple[str, str]]] = None,
) -> tuple[Optional[str], Optional[str], str, List[Dict[str, Any]]]:
    """Resolve a single cleaned player name to a CPI player ID, name, confidence, and alternatives."""
    name, _, _ = clean_player_name(raw_name)
    if not name or len(name) < 2:
        return None, None, "unmatched", []

    folded = name.casefold()

    # 1. Exact canonical name match
    p_exact = db.execute(select(Player.id, Player.canonical_name).where(Player.canonical_name.ilike(name))).first()
    if p_exact:
        return p_exact[0], p_exact[1], "exact", []

    # 2. Exact alias match from memory cache if provided
    if alias_dict and folded in alias_dict:
        pid, pname = alias_dict[folded]
        return pid, pname, "alias", []

    # Check alias in DB
    p_alias = db.execute(
        select(PlayerAlias.player_id, Player.canonical_name)
        .join(Player, Player.id == PlayerAlias.player_id)
        .where(PlayerAlias.source_name.ilike(name))
    ).first()
    if p_alias:
        return p_alias[0], p_alias[1], "alias", []

    p_name_alias = db.execute(
        select(PlayerNameAlias.player_id, Player.canonical_name)
        .join(Player, Player.id == PlayerNameAlias.player_id)
        .where(PlayerNameAlias.alias.ilike(name))
    ).first()
    if p_name_alias:
        return p_name_alias[0], p_name_alias[1], "alias", []

    # 3. Surname + Initial matching (handles "Ruturaj Gaikwad" -> "RD Gaikwad", "Suryakumar Yadav" -> "SA Yadav")
    parts = name.split()
    if len(parts) >= 2:
        first, last = parts[0], parts[-1]
        first_init = first[0].upper()
        # Query players whose canonical or alias contains the surname using fast indexed queries
        candidates = db.execute(
            select(Player.id, Player.canonical_name)
            .where(Player.canonical_name.ilike(f"%{last}%"))
            .limit(10)
        ).all()
        if not candidates:
            candidates = db.execute(
                select(PlayerNameAlias.player_id, Player.canonical_name)
                .join(Player, Player.id == PlayerNameAlias.player_id)
                .where(PlayerNameAlias.alias.ilike(f"%{last}%"))
                .limit(10)
            ).all()

        for cid, cname in candidates:
            # Check initial matches first letter of first name
            cparts = cname.split()
            if cname.upper().startswith(first_init) or (len(cparts) > 1 and cparts[0].upper().startswith(first_init)):
                alts = [{"id": x[0], "name": x[1]} for x in candidates if x[0] != cid][:3]
                return cid, cname, "initial_surname", alts

        if candidates:
            cid, cname = candidates[0]
            alts = [{"id": x[0], "name": x[1]} for x in candidates[1:4]]
            return cid, cname, "surname", alts

    # 4. Fast fuzzy candidate search on prefix/substring candidates only
    prefix = name[:4] if len(name) >= 4 else name
    fuzzy_candidates = db.execute(
        select(Player.id, Player.canonical_name)
        .where(Player.canonical_name.ilike(f"%{prefix}%"))
        .limit(25)
    ).all()
    best_matches = []
    for pid, cname in fuzzy_candidates:
        ratio = difflib.SequenceMatcher(None, folded, cname.casefold()).ratio()
        if ratio >= 0.65:
            best_matches.append((ratio, pid, cname))

    best_matches.sort(key=lambda x: x[0], reverse=True)
    if best_matches and best_matches[0][0] >= 0.75:
        top = best_matches[0]
        alts = [{"id": x[1], "name": x[2]} for x in best_matches[1:4]]
        return top[1], top[2], "fuzzy", alts

    return None, None, "unmatched", [{"id": x[1], "name": x[2]} for x in best_matches[:3]]


def _ocr_file(file_path: str) -> str:
    """Run native OCR script if available."""
    try:
        import subprocess
        cache = Path("/private/tmp/cpi-swift-cache")
        cache.mkdir(parents=True, exist_ok=True)
        result = subprocess.run(
            ["swift", "-module-cache-path", str(cache), str(OCR_SCRIPT), file_path],
            capture_output=True,
            text=True,
            timeout=90,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    except Exception:
        pass
    return ""


@router.post("/xi/resolve", response_model=ResolveXiResponse)
def resolve_xi(req: ResolveXiRequest, db: Session = Depends(get_db)):
    """Resolve a list or text of player names to canonical CPI players and calculate Playing XI balance."""
    raw_lines: List[str] = []
    if req.names:
        raw_lines.extend(req.names)
    elif req.text:
        # Split by newlines, commas, or semicolons
        text = req.text.strip()
        if "\n" in text:
            raw_lines.extend([line.strip() for line in text.splitlines() if line.strip()])
        elif "," in text:
            raw_lines.extend([part.strip() for part in text.split(",") if part.strip()])
        elif ";" in text:
            raw_lines.extend([part.strip() for part in text.split(";") if part.strip()])
        else:
            raw_lines.append(text)

    # Filter out common header lines like 'Playing XI', 'Team Sheet', 'Lineup:'
    filtered_lines: List[str] = []
    for line in raw_lines:
        line_clean = line.strip()
        if not line_clean:
            continue
        if re.search(r"^(playing\s*xi|team\s*(sheet|lineup|xi)|lineup|squad|substitutes|bench)\b", line_clean, re.I):
            continue
        filtered_lines.append(line_clean)

    if not filtered_lines:
        raise HTTPException(400, "Provide at least 1 player name in 'names' or 'text'")

    resolved_items: List[PlayerXiItem] = []
    matched_ids: set[str] = set()

    for idx, raw in enumerate(filtered_lines[:15]):  # Process up to 15 (XI + up to 4 subs)
        cleaned, is_capt, is_wk = clean_player_name(raw)
        pid, pname, conf, alts = _resolve_single_player(cleaned, db)
        if pid:
            matched_ids.add(pid)

        resolved_items.append(
            PlayerXiItem(
                order=idx + 1,
                input_name=raw,
                id=pid,
                name=pname or cleaned,
                matched=bool(pid),
                confidence=conf,
                is_captain=is_capt,
                is_wicketkeeper=is_wk,
                alternatives=alts,
            )
        )

    # Fetch attributes for all matched players
    attr_map = _fetch_player_attributes(matched_ids, db)
    for item in resolved_items:
        if item.id and item.id in attr_map:
            attrs = attr_map[item.id]
            item.primary_role = attrs.get("primary_role")
            item.batting_style = attrs.get("batting_style")
            item.bowling_type = attrs.get("bowling_type")
            item.bowling_style = attrs.get("bowling_style")
            # If role indicates keeper, mark wicketkeeper
            if item.primary_role and "keeper" in item.primary_role.lower():
                item.is_wicketkeeper = True

    # Calculate Playing XI Balance (for the top 11 players)
    top_11 = resolved_items[:11]
    batters = sum(1 for p in top_11 if p.primary_role in ("Batter", "Specialist Batter", "Wicketkeeper-Batter"))
    all_rounders = sum(1 for p in top_11 if p.primary_role in ("All-Rounder", "Batting All-Rounder", "Bowling All-Rounder"))
    bowlers = sum(1 for p in top_11 if p.primary_role in ("Bowler", "Specialist Bowler"))
    keepers = sum(1 for p in top_11 if p.is_wicketkeeper or (p.primary_role and "keeper" in p.primary_role.lower()))
    paces = sum(1 for p in top_11 if p.bowling_type and "pace" in p.bowling_type.lower())
    spins = sum(1 for p in top_11 if p.bowling_type and "spin" in p.bowling_type.lower())
    left_bats = sum(1 for p in top_11 if p.batting_style and "left" in p.batting_style.lower())
    right_bats = sum(1 for p in top_11 if p.batting_style and "right" in p.batting_style.lower())

    balance = TeamBalance(
        batters=batters,
        all_rounders=all_rounders,
        bowlers=bowlers,
        wicketkeepers=keepers,
        pace_bowlers=paces,
        spin_bowlers=spins,
        left_hand_batters=left_bats,
        right_hand_batters=right_bats,
    )

    matched_count = sum(1 for p in resolved_items if p.matched)
    return ResolveXiResponse(
        team_name=req.team_name or "Uploaded Playing XI",
        total_players=len(resolved_items),
        matched_count=matched_count,
        players=resolved_items,
        balance=balance,
        message=f"Resolved {matched_count} of {len(resolved_items)} players against the CPI database.",
    )


@router.post("/xi/upload-file", response_model=ResolveXiResponse)
async def upload_xi_file(file: UploadFile = File(...), db: Session = Depends(get_db)):
    """Upload a team-sheet image (OCR) or CSV/TXT file to extract and resolve a Playing XI."""
    name = (file.filename or "").casefold()
    suffix = Path(name).suffix
    content = await file.read()
    if not content or len(content) > 10 * 1024 * 1024:
        raise HTTPException(413, "Uploaded file must be under 10 MB")

    extracted_lines: List[str] = []

    if suffix in (".png", ".jpg", ".jpeg", ".webp"):
        with tempfile.NamedTemporaryFile(suffix=suffix) as tmp:
            tmp.write(content)
            tmp.flush()
            ocr_text = _ocr_file(tmp.name)
        if not ocr_text:
            raise HTTPException(
                422,
                "Could not extract text from this image. Please paste or enter the player names directly."
            )
        extracted_lines = [line.strip() for line in ocr_text.splitlines() if line.strip()]
    elif suffix in (".csv", ".txt"):
        try:
            decoded = content.decode("utf-8", errors="replace")
            reader = csv.reader(io.StringIO(decoded))
            for row in reader:
                if row and row[0].strip():
                    extracted_lines.append(row[0].strip())
        except Exception as exc:
            raise HTTPException(400, f"Failed to parse text file: {exc}")
    else:
        raise HTTPException(415, "Upload an image (.png, .jpg, .webp) or text/CSV (.csv, .txt)")

    team_title = Path(file.filename or "Uploaded XI").stem.replace("_", " ").title()
    resolve_req = ResolveXiRequest(team_name=team_title, names=extracted_lines)
    return resolve_xi(resolve_req, db)


@router.get("/xi/search-player")
def search_player_for_xi(q: str = Query(..., min_length=2), db: Session = Depends(get_db)):
    """Fast search for replacing or picking a player for the Playing XI."""
    alias_match = select(PlayerNameAlias.player_id).where(PlayerNameAlias.alias.ilike(f"%{q}%")).subquery()
    rows = db.execute(
        select(Player.id, Player.canonical_name)
        .where(or_(Player.canonical_name.ilike(f"%{q}%"), Player.id.in_(select(alias_match))))
        .limit(20)
    ).all()
    pids = [r[0] for r in rows]
    attr_map = _fetch_player_attributes(set(pids), db)
    results = []
    for pid, cname in rows:
        attrs = attr_map.get(pid, {})
        results.append({
            "id": pid,
            "name": cname,
            "primary_role": attrs.get("primary_role", "Player"),
            "batting_style": attrs.get("batting_style"),
            "bowling_type": attrs.get("bowling_type"),
            "bowling_style": attrs.get("bowling_style"),
        })
    return {"query": q, "results": results}


_PRESETS_CACHE: Optional[List[Dict[str, Any]]] = None


@router.get("/xi/presets")
def get_xi_presets(db: Session = Depends(get_db)):
    """Return pre-configured, verified international and franchise Playing XIs."""
    global _PRESETS_CACHE
    if _PRESETS_CACHE is not None:
        return {"presets": _PRESETS_CACHE}
    presets = [
        {
            "id": "ind-t20-wc-2024",
            "name": "India — T20 World Cup 2024 Champions",
            "format": "T20",
            "description": "Final XI vs South Africa at Bridgetown, Barbados (June 29, 2024)",
            "names": [
                "Rohit Sharma (c)", "Virat Kohli", "Rishabh Pant (wk)", "SA Yadav",
                "Shivam Dube", "Hardik Pandya", "Ravindra Jadeja", "Axar Patel",
                "Kuldeep Yadav", "Arshdeep Singh", "Jasprit Bumrah"
            ],
        },
        {
            "id": "aus-cwc-2023",
            "name": "Australia — ODI World Cup 2023 Champions",
            "format": "ODI",
            "description": "Final XI vs India at Ahmedabad (November 19, 2023)",
            "names": [
                "Travis Head", "David Warner", "Mitchell Marsh", "Steven Smith",
                "Marnus Labuschagne", "Glenn Maxwell", "Josh Inglis (wk)",
                "Pat Cummins (c)", "Mitchell Starc", "Adam Zampa", "Josh Hazlewood"
            ],
        },
        {
            "id": "kkr-ipl-2024",
            "name": "Kolkata Knight Riders — IPL 2024 Champions",
            "format": "T20",
            "description": "Final XI vs Sunrisers Hyderabad at Chennai (May 26, 2024)",
            "names": [
                "Philip Salt (wk)", "Sunil Narine", "Venkatesh Iyer", "Shreyas Iyer (c)",
                "Rinku Singh", "Andre Russell", "Ramandeep Singh", "Mitchell Starc",
                "Harshit Rana", "VG Arora", "V Chakravarthy"
            ],
        },
        {
            "id": "csk-ipl-2023",
            "name": "Chennai Super Kings — IPL 2023 Champions",
            "format": "T20",
            "description": "Final XI vs Gujarat Titans at Ahmedabad (May 29, 2023)",
            "names": [
                "RD Gaikwad", "Devon Conway", "Ajinkya Rahane", "AT Rayudu",
                "Shivam Dube", "Moeen Ali", "Ravindra Jadeja", "MS Dhoni (c/wk)",
                "DL Chahar", "TU Deshpande", "M Theekshana"
            ],
        },
        {
            "id": "eng-t20-wc-2022",
            "name": "England — T20 World Cup 2022 Champions",
            "format": "T20",
            "description": "Final XI vs Pakistan at Melbourne (November 13, 2022)",
            "names": [
                "Jos Buttler (c/wk)", "Alex Hales", "Philip Salt", "Ben Stokes",
                "HC Brook", "Liam Livingstone", "Moeen Ali", "Sam Curran",
                "Chris Woakes", "Chris Jordan", "Adil Rashid"
            ],
        },
    ]

    # Pre-resolve each preset with DB attributes for instant front-end consumption
    all_names = [name for p in presets for name in p["names"]]
    # Run resolution for each preset
    resolved_presets = []
    for pr in presets:
        req = ResolveXiRequest(team_name=pr["name"], names=pr["names"], format=pr["format"])
        resp = resolve_xi(req, db)
        resolved_presets.append({
            "id": pr["id"],
            "name": pr["name"],
            "format": pr["format"],
            "description": pr["description"],
            "team_name": resp.team_name,
            "total_players": resp.total_players,
            "matched_count": resp.matched_count,
            "players": [p.model_dump() for p in resp.players],
            "balance": resp.balance.model_dump(),
        })

    _PRESETS_CACHE = resolved_presets
    return {"presets": resolved_presets}
