"""Scenario-scoped auction data and validated auction operations."""
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List, Optional, Literal
from uuid import uuid4
import csv
import re

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.models import (
    AuctionScenario, AuctionRule, AuctionTeam, AuctionPlayer, AuctionImport,
    AuctionSession, AuctionEvent, AuctionBid, AuctionPurchase, AuctionRetention,
    Player, PlayerNameAlias, PlayerAlias, AuctionHistoryRecord, AuctionHistoryImport, AuctionModelRun,
    PlayerAttribute, Match, MatchInnings, Delivery, Wicket, AuctionPredictedXI,
)
from app.auction_rules import validate_bid
from app.auction_csv import auction_registry, history_row, pool_row, read_csv_rows, _first, _decimal

router = APIRouter(prefix="/auction", tags=["Auction Intelligence"])


class ScenarioCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    season: str = Field(min_length=4, max_length=16)
    auction_type: Literal["MEGA", "MINI", "CUSTOM"] = "CUSTOM"
    competition: str = "Indian Premier League"
    rules: Dict[str, Any] = Field(default_factory=lambda: {
        "total_purse": 120, "minimum_squad_size": 18, "maximum_squad_size": 25,
        "overseas_squad_limit": 8, "minimum_bid_increment": 0.2,
        "overseas_xi_limit": 4, "retention_limit": 6,
    })


class TeamInput(BaseModel):
    franchise_name: str
    franchise_code: str
    initial_purse: Decimal = Field(gt=0)
    minimum_squad_size: int = Field(default=18, ge=0)
    maximum_squad_size: int = Field(default=25, ge=1)
    overseas_squad_limit: int = Field(default=8, ge=0)


class PoolRow(BaseModel):
    player_id: Optional[str] = None
    player_name: Optional[str] = None
    base_price: Decimal = Field(gt=0)
    primary_role: Optional[str] = None
    secondary_role: Optional[str] = None
    nationality: Optional[str] = None
    overseas_eligible: Optional[bool] = None
    wicketkeeper: Optional[bool] = None
    auction_category: Optional[str] = None
    auction_order: Optional[int] = None


class PoolUpload(BaseModel):
    filename: str = "player-pool.json"
    rows: List[PoolRow]


class BidInput(BaseModel):
    team_id: str
    player_id: str
    amount: Decimal = Field(gt=0)


class SessionCreate(BaseModel):
    simulation_mode: Literal["INTERACTIVE", "AUTOMATED"] = "INTERACTIVE"


class RuleConfirm(BaseModel):
    rules: Dict[str, Any]


class XIRequest(BaseModel):
    team_id: str
    style: Literal["balanced", "batting-heavy", "bowling-heavy", "spin-friendly", "pace-friendly"] = "balanced"


def _scenario(db: Session, scenario_id: str) -> AuctionScenario:
    value = db.get(AuctionScenario, scenario_id)
    if value is None:
        raise HTTPException(404, "Auction scenario not found")
    return value


@router.get("/scenarios")
def list_scenarios(db: Session = Depends(get_db)):
    rows = db.scalars(select(AuctionScenario).order_by(AuctionScenario.updated_at.desc())).all()
    return [{"id": x.id, "name": x.name, "season": x.season, "auction_type": x.auction_type,
             "competition": x.competition, "status": x.status} for x in rows]


@router.post("/scenarios")
def create_scenario(payload: ScenarioCreate, db: Session = Depends(get_db)):
    rules = payload.rules
    if Decimal(str(rules.get("total_purse", 0))) <= 0:
        raise HTTPException(422, "Rules must include a positive total_purse")
    if int(rules.get("minimum_squad_size", 0)) > int(rules.get("maximum_squad_size", 0)):
        raise HTTPException(422, "Minimum squad size cannot exceed maximum squad size")
    scenario = AuctionScenario(name=payload.name, season=payload.season,
                               auction_type=payload.auction_type, competition=payload.competition)
    db.add(scenario)
    db.flush()
    db.add(AuctionRule(scenario_id=scenario.id, version=1, rules_json=rules))
    db.commit()
    return {"id": scenario.id, "name": scenario.name, "season": scenario.season,
            "auction_type": scenario.auction_type, "status": scenario.status, "rules_version": 1}


@router.get("/scenarios/{scenario_id}")
def get_scenario(scenario_id: str, db: Session = Depends(get_db)):
    scenario = _scenario(db, scenario_id)
    rule = db.scalar(select(AuctionRule).where(AuctionRule.scenario_id == scenario_id)
                      .order_by(AuctionRule.version.desc()))
    teams = db.scalars(select(AuctionTeam).where(AuctionTeam.scenario_id == scenario_id)
                       .order_by(AuctionTeam.franchise_name)).all()
    pool_count = db.scalar(select(func.count()).select_from(AuctionPlayer)
                            .where(AuctionPlayer.scenario_id == scenario_id)) or 0
    return {"id": scenario.id, "name": scenario.name, "season": scenario.season,
            "auction_type": scenario.auction_type, "competition": scenario.competition,
            "status": scenario.status, "rules_version": rule.version if rule else None,
            "rules": rule.rules_json if rule else {}, "teams": [
                {"id": t.id, "name": t.franchise_name, "code": t.franchise_code,
                 "initial_purse": float(t.initial_purse), "remaining_purse": float(t.remaining_purse)}
                for t in teams], "available_players": pool_count}


@router.post("/scenarios/{scenario_id}/run")
def run_auction_scenario(scenario_id: str, db: Session = Depends(get_db)):
    scenario = _scenario(db, scenario_id)
    from app.analytics.auction_scenario import run_scenario
    try:
        return run_scenario(db, scenario)
    except (ValueError, KeyError, OSError) as exc:
        raise HTTPException(422, f"Could not run scenario: {exc}")


@router.post("/scenarios/{scenario_id}/teams")
def add_team(scenario_id: str, payload: TeamInput, db: Session = Depends(get_db)):
    _scenario(db, scenario_id)
    if payload.minimum_squad_size > payload.maximum_squad_size:
        raise HTTPException(422, "Minimum squad size cannot exceed maximum squad size")
    team = AuctionTeam(scenario_id=scenario_id, franchise_name=payload.franchise_name,
                       franchise_code=payload.franchise_code.upper(), initial_purse=payload.initial_purse,
                       remaining_purse=payload.initial_purse, minimum_squad_size=payload.minimum_squad_size,
                       maximum_squad_size=payload.maximum_squad_size,
                       overseas_squad_limit=payload.overseas_squad_limit)
    db.add(team)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "This franchise code already exists in the scenario")
    return {"id": team.id, "franchise_name": team.franchise_name, "franchise_code": team.franchise_code}


def _resolve_player(db: Session, row: PoolRow, name_index=None):
    if row.player_id:
        player = db.get(Player, row.player_id)
        if player:
            return [player]
        source_matches = db.scalars(select(Player).join(PlayerAlias, PlayerAlias.player_id == Player.id)
                                    .where(PlayerAlias.source_player_id == row.player_id)).unique().all()
        if source_matches:
            return source_matches
    name = (row.player_name or "").strip()
    if not name:
        return []
    ids = _matching_player_ids(name_index if name_index is not None else _player_name_index(db), name)
    return db.scalars(select(Player).where(Player.id.in_(ids))).all() if ids else []


def _player_name_index(db: Session):
    """Load canonical names and aliases once for bulk identity resolution."""
    index = {}
    queries = [select(Player.id, Player.canonical_name),
               select(PlayerNameAlias.player_id, PlayerNameAlias.alias),
               select(PlayerAlias.player_id, PlayerAlias.source_name)]
    for query in queries:
        for player_id, name in db.execute(query).all():
            if name:
                index.setdefault(_player_name_key(name), set()).add(player_id)
    # names.csv connects every Cricsheet spelling to a stable identifier. Join
    # those IDs to CPI's existing Cricsheet aliases without creating players.
    source_ids = {}
    for player_id, source_player_id in db.execute(select(PlayerAlias.player_id, PlayerAlias.source_player_id)).all():
        source_ids.setdefault(str(source_player_id).casefold(), set()).add(player_id)
    reference_dir = Path(__file__).resolve().parents[4] / "data/reference/cricsheet"
    for names_file in (reference_dir / "names.csv", reference_dir / "cpi_alias_overrides.csv"):
        if names_file.exists():
            with names_file.open(newline="", encoding="utf-8-sig") as stream:
                for row in csv.DictReader(stream):
                    player_ids = source_ids.get(str(row.get("identifier", "")).casefold(), set())
                    key = _player_name_key(row.get("name", ""))
                    if key and player_ids:
                        index.setdefault(key, set()).update(player_ids)
    return index


def _player_name_key(value):
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").casefold()).strip()


def _matching_player_ids(index, name):
    key = _player_name_key(name)
    matched = set(index.get(key, set()))
    if matched or not key:
        return matched
    # Handle long names against Cricsheet initials (e.g. Spencer Johnson ↔
    # SH Johnson) only when the resulting CPI identity is unique.
    tokens = key.split()
    if len(tokens) < 2:
        return set()
    surname = tokens[-1]
    initial = tokens[0][0]
    candidates = set()
    for alias, player_ids in index.items():
        alias_tokens = alias.split()
        if len(alias_tokens) < 2 or alias_tokens[-1] != surname:
            continue
        given = "".join(t[0] for t in alias_tokens[:-1] if t)
        if given.startswith(initial):
            candidates.update(player_ids)
    return candidates


def _history_csv_preview(db: Session, filename: str, content: bytes, source_name: str):
    try:
        raw_rows = read_csv_rows(filename, content)
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    index = _player_name_index(db)
    accepted, rejected, seen = [], [], set()
    duplicate_rows = 0
    for line, source_row in raw_rows:
        item, errors = history_row(source_name, line, source_row)
        if errors:
            rejected.append({"row": line, "player_name": item["source_player_name"], "reasons": errors})
            continue
        aliases = [item["source_player_name"]]
        aliases.extend(auction_registry().get(item["source_player_id"], []))
        matched = set()
        for alias in aliases:
            matched.update(_matching_player_ids(index, alias))
        item["player_id"] = next(iter(matched)) if len(matched) == 1 else None
        item["identity_match_status"] = "MATCHED" if len(matched) == 1 else "AMBIGUOUS" if matched else "UNRESOLVED"
        if item["source_record_key"] in seen:
            duplicate_rows += 1
            continue
        seen.add(item["source_record_key"])
        accepted.append(item)
    if not raw_rows:
        rejected.append({"row": 1, "player_name": None, "reasons": ["CSV contains no data rows"]})
    existing = set(db.scalars(select(AuctionHistoryRecord.source_record_key)
                              .where(AuctionHistoryRecord.source_name == source_name)).all())
    duplicates = [r for r in accepted if r["source_record_key"] in existing]
    if duplicates:
        duplicate_rows += len(duplicates)
        dupkeys = {r["source_record_key"] for r in duplicates}
        accepted = [r for r in accepted if r["source_record_key"] not in dupkeys]
    identity_summary = {
        "matched": sum(r["identity_match_status"] == "MATCHED" for r in accepted),
        "unresolved": sum(r["identity_match_status"] == "UNRESOLVED" for r in accepted),
        "ambiguous": sum(r["identity_match_status"] == "AMBIGUOUS" for r in accepted),
    }
    return {"filename": filename, "source_name": source_name, "accepted_rows": len(accepted),
            "duplicate_rows": duplicate_rows, "rejected_rows": len(rejected),
            "identity_summary": identity_summary, "accepted": accepted, "rejected": rejected}


@router.post("/scenarios/{scenario_id}/player-pool/preview")
def preview_player_pool(scenario_id: str, payload: PoolUpload, db: Session = Depends(get_db)):
    _scenario(db, scenario_id)
    accepted, rejected, warnings = [], [], []
    name_index = _player_name_index(db)
    seen = set()
    for index, row in enumerate(payload.rows, 1):
        matches = _resolve_player(db, row, name_index)
        if len(matches) != 1:
            rejected.append({"row": index, "player_name": row.player_name,
                             "reason": "unresolved player" if not matches else "ambiguous player identity"})
            continue
        player = matches[0]
        if player.id in seen:
            rejected.append({"row": index, "player_name": row.player_name or player.canonical_name,
                             "reason": "duplicate player in upload"})
            continue
        seen.add(player.id)
        accepted.append({"row": index, "player_id": player.id, "player_name": player.canonical_name,
                         "base_price": str(row.base_price), "primary_role": row.primary_role})
    existing = set(db.scalars(select(AuctionPlayer.player_id)
                              .where(AuctionPlayer.scenario_id == scenario_id)).all())
    for candidate in accepted:
        if candidate["player_id"] in existing:
            rejected.append({"row": candidate["row"], "player_name": candidate["player_name"],
                             "reason": "player is already in this scenario"})
    rejected_rows = {item["row"] for item in rejected}
    accepted = [item for item in accepted if item["row"] not in rejected_rows]
    if not payload.rows:
        warnings.append("Upload contains no rows")
    return {"filename": payload.filename, "accepted_rows": len(accepted), "rejected_rows": len(rejected),
            "accepted": accepted, "rejected": rejected, "warnings": warnings,
            "note": "Preview only; no auction records were written."}


@router.post("/scenarios/{scenario_id}/player-pool/import")
def import_player_pool(scenario_id: str, payload: PoolUpload, db: Session = Depends(get_db)):
    _scenario(db, scenario_id)
    preview = preview_player_pool(scenario_id, payload, db)
    report = {k: preview[k] for k in ("accepted", "rejected", "warnings")}
    batch = AuctionImport(scenario_id=scenario_id, filename=payload.filename, data_type="PLAYER_POOL",
                          status="IMPORTED" if preview["accepted_rows"] else "REJECTED",
                          accepted_rows=preview["accepted_rows"], rejected_rows=preview["rejected_rows"],
                          report_json=report)
    db.add(batch)
    rows_by_number = {index: row for index, row in enumerate(payload.rows, 1)}
    for candidate in preview["accepted"]:
        row = rows_by_number[candidate["row"]]
        player = db.get(Player, candidate["player_id"])
        db.add(AuctionPlayer(scenario_id=scenario_id, player_id=player.id, base_price=row.base_price,
                             auction_category=row.auction_category, auction_order=row.auction_order,
                             primary_role=row.primary_role, secondary_role=row.secondary_role,
                             nationality=row.nationality, overseas_eligible=row.overseas_eligible,
                             wicketkeeper=row.wicketkeeper, identity_match_status="MATCHED"))
    db.commit()
    return {"import_id": batch.id, "accepted_rows": batch.accepted_rows,
            "rejected_rows": batch.rejected_rows, "report": report}


@router.get("/scenarios/{scenario_id}/teams")
def team_analysis(scenario_id: str, db: Session = Depends(get_db)):
    _scenario(db, scenario_id)
    teams = db.scalars(select(AuctionTeam).where(AuctionTeam.scenario_id == scenario_id)
                       .order_by(AuctionTeam.franchise_name)).all()
    output = []
    for team in teams:
        purchases = db.scalars(select(AuctionPurchase).where(AuctionPurchase.team_id == team.id)).all()
        retentions = db.scalars(select(AuctionRetention).where(AuctionRetention.team_id == team.id)).all()
        player_ids = [x.player_id for x in purchases] + [x.player_id for x in retentions]
        roles = {}
        for player_id in player_ids:
            auction_player = db.scalar(select(AuctionPlayer).where(
                AuctionPlayer.scenario_id == scenario_id, AuctionPlayer.player_id == player_id))
            if auction_player and auction_player.primary_role:
                roles[auction_player.primary_role] = roles.get(auction_player.primary_role, 0) + 1
        output.append({"team_id": team.id, "franchise": team.franchise_name,
                       "remaining_purse": float(team.remaining_purse), "squad_count": len(player_ids),
                       "role_counts": roles,
                       "analysis_status": "scenario data only; performance-informed fit is unavailable until player pool and requirements are supplied"})
    return output


@router.post("/scenarios/{scenario_id}/sessions")
def create_session(scenario_id: str, payload: SessionCreate, db: Session = Depends(get_db)):
    scenario = _scenario(db, scenario_id)
    if scenario.status not in ("DRAFT", "READY"):
        raise HTTPException(409, "Scenario is not available to start an auction")
    active = db.scalar(select(AuctionSession).where(AuctionSession.scenario_id == scenario_id,
                                                    AuctionSession.session_status.in_(("READY", "RUNNING"))))
    if active:
        raise HTTPException(409, "This scenario already has an active auction session")
    if not db.scalar(select(func.count()).select_from(AuctionTeam).where(AuctionTeam.scenario_id == scenario_id)):
        raise HTTPException(422, "Add at least one franchise before creating an auction session")
    session = AuctionSession(scenario_id=scenario_id, simulation_mode=payload.simulation_mode)
    scenario.status = "RUNNING"
    db.add(session)
    db.commit()
    return {"id": session.id, "status": session.session_status, "simulation_mode": session.simulation_mode}


@router.post("/sessions/{session_id}/call-next")
def call_next_player(session_id: str, db: Session = Depends(get_db)):
    session = db.get(AuctionSession, session_id)
    if not session:
        raise HTTPException(404, "Auction session not found")
    if session.session_status not in ("READY", "RUNNING"):
        raise HTTPException(409, "Auction session is not active")
    player = db.scalar(select(AuctionPlayer).where(AuctionPlayer.scenario_id == session.scenario_id,
                                                  AuctionPlayer.availability_status == "AVAILABLE")
                       .order_by(AuctionPlayer.auction_order.nulls_last(), AuctionPlayer.id).with_for_update(skip_locked=True))
    if not player:
        session.session_status = "COMPLETED"
        scenario = db.get(AuctionScenario, session.scenario_id)
        if scenario:
            scenario.status = "COMPLETED"
        db.commit()
        return {"status": "COMPLETED", "message": "No available players remain."}
    player.availability_status = "IN_AUCTION"
    rules = db.scalar(select(AuctionRule).where(AuctionRule.scenario_id == session.scenario_id)
                      .order_by(AuctionRule.version.desc()))
    last = db.scalar(select(func.max(AuctionEvent.sequence_number)).where(AuctionEvent.session_id == session_id)) or 0
    event = AuctionEvent(session_id=session_id, sequence_number=last + 1, event_type="PLAYER_CALLED",
                         player_id=player.player_id, bid_amount=player.base_price,
                         event_payload={"base_price": str(player.base_price), "rules_version": rules.version if rules else None})
    session.active_player_id = player.player_id
    session.current_bid = player.base_price
    session.session_status = "RUNNING"
    db.add(event)
    db.commit()
    return {"player_id": player.player_id, "base_price": str(player.base_price), "event_id": event.id}


@router.post("/sessions/{session_id}/bid")
def place_bid(session_id: str, payload: BidInput, db: Session = Depends(get_db)):
    session = db.scalar(select(AuctionSession).where(AuctionSession.id == session_id).with_for_update())
    if not session:
        raise HTTPException(404, "Auction session not found")
    if session.session_status != "RUNNING" or not session.active_player_id:
        raise HTTPException(409, "There is no active player to bid on")
    if payload.player_id != session.active_player_id:
        raise HTTPException(409, "Bid player does not match the active auction player")
    team = db.scalar(select(AuctionTeam).where(AuctionTeam.id == payload.team_id,
                                                AuctionTeam.scenario_id == session.scenario_id).with_for_update())
    if not team:
        raise HTTPException(404, "Franchise is not part of this scenario")
    rule = db.scalar(select(AuctionRule).where(AuctionRule.scenario_id == session.scenario_id)
                     .order_by(AuctionRule.version.desc()))
    increment = Decimal(str((rule.rules_json if rule else {}).get("minimum_bid_increment", "0.2")))
    purchased_count = db.scalar(select(func.count()).select_from(AuctionPurchase)
                            .where(AuctionPurchase.session_id == session_id, AuctionPurchase.team_id == team.id)) or 0
    retained_count = db.scalar(select(func.count()).select_from(AuctionRetention).where(AuctionRetention.team_id == team.id)) or 0
    squad_size = purchased_count + retained_count
    active_pool_player = db.scalar(select(AuctionPlayer).where(
        AuctionPlayer.scenario_id == session.scenario_id, AuctionPlayer.player_id == payload.player_id))
    if not active_pool_player or active_pool_player.availability_status != "IN_AUCTION":
        raise HTTPException(409, "The active player is no longer available for bidding")
    rules = rule.rules_json if rule else {}
    incoming_overseas = bool(active_pool_player.overseas_eligible) if active_pool_player.overseas_eligible is not None else (active_pool_player.nationality.lower() not in {"india", "indian"} if active_pool_player.nationality else True)
    if incoming_overseas:
        retained_ids = db.scalars(select(AuctionRetention.player_id).where(AuctionRetention.team_id == team.id)).all()
        foreign_retained = 0
        for retained_id in retained_ids:
            retained_pool = db.scalar(select(AuctionPlayer).where(AuctionPlayer.scenario_id == session.scenario_id,
                                                                  AuctionPlayer.player_id == retained_id))
            nationality = db.scalar(select(PlayerAttribute.attribute_value).where(
                PlayerAttribute.player_id == retained_id, PlayerAttribute.attribute_type == "nationality").limit(1))
            overseas = retained_pool.overseas_eligible if retained_pool and retained_pool.overseas_eligible is not None else (nationality.lower() not in {"india", "indian"} if nationality else True)
            foreign_retained += int(bool(overseas))
        foreign_purchased = db.scalar(select(func.count()).select_from(AuctionPurchase).join(AuctionPlayer,
            (AuctionPlayer.player_id == AuctionPurchase.player_id) & (AuctionPlayer.scenario_id == session.scenario_id)).where(
            AuctionPurchase.session_id == session_id, AuctionPurchase.team_id == team.id, AuctionPlayer.overseas_eligible.is_(True))) or 0
        if (foreign_retained or 0) + foreign_purchased >= int(rules.get("overseas_squad_limit", team.overseas_squad_limit)):
            raise HTTPException(422, "Franchise overseas-player squad limit would be exceeded")
    # Opening bid may equal base price. Later bids must clear the configured increment.
    prior_accepted_bid = (session.current_bid if session.current_team_id else
                          Decimal(str(active_pool_player.base_price)) - increment)
    try:
        validate_bid(current_bid=prior_accepted_bid, offered_bid=payload.amount, minimum_increment=increment,
                     remaining_purse=team.remaining_purse, squad_count=squad_size,
                     maximum_squad_size=min(team.maximum_squad_size, int(rules.get("maximum_squad_size", team.maximum_squad_size))))
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    last = db.scalar(select(func.max(AuctionEvent.sequence_number)).where(AuctionEvent.session_id == session_id)) or 0
    bid = AuctionBid(session_id=session_id, player_id=payload.player_id, team_id=team.id,
                     bid_amount=payload.amount, bid_source="USER", accepted=True)
    event = AuctionEvent(session_id=session_id, sequence_number=last + 1, event_type="BID_PLACED",
                         player_id=payload.player_id, team_id=team.id, bid_amount=payload.amount,
                         event_payload={"source": "USER"})
    session.current_bid = payload.amount
    session.current_team_id = team.id
    db.add_all([bid, event])
    db.commit()
    return {"accepted": True, "team_id": team.id, "amount": str(payload.amount), "event_id": event.id}


@router.post("/sessions/{session_id}/close-player")
def close_player(session_id: str, db: Session = Depends(get_db)):
    session = db.scalar(select(AuctionSession).where(AuctionSession.id == session_id).with_for_update())
    if not session:
        raise HTTPException(404, "Auction session not found")
    if session.session_status != "RUNNING" or not session.active_player_id:
        raise HTTPException(409, "There is no active player to close")
    last = db.scalar(select(func.max(AuctionEvent.sequence_number)).where(AuctionEvent.session_id == session_id)) or 0
    active = db.scalar(select(AuctionPlayer).where(AuctionPlayer.scenario_id == session.scenario_id,
                                                   AuctionPlayer.player_id == session.active_player_id).with_for_update())
    if not active or active.availability_status != "IN_AUCTION":
        raise HTTPException(409, "The active player is no longer available")
    if session.current_team_id:
        team = db.scalar(select(AuctionTeam).where(AuctionTeam.id == session.current_team_id).with_for_update())
        price = Decimal(str(session.current_bid))
        if price > Decimal(str(team.remaining_purse)):
            raise HTTPException(409, "Winning team no longer has sufficient purse")
        team.remaining_purse = Decimal(str(team.remaining_purse)) - price
        active.availability_status = "SOLD"
        sold_event = AuctionEvent(session_id=session_id, sequence_number=last + 1, event_type="PLAYER_SOLD",
                                  player_id=session.active_player_id, team_id=team.id, bid_amount=price,
                                  event_payload={})
        db.add(sold_event)
        db.flush()
        db.add(AuctionPurchase(session_id=session_id, player_id=session.active_player_id, team_id=team.id,
                               purchase_price=price, acquisition_type="AUCTION", auction_event_id=sold_event.id))
        result = {"status": "SOLD", "team": team.franchise_name, "price": str(price)}
    else:
        active.availability_status = "UNSOLD"
        db.add(AuctionEvent(session_id=session_id, sequence_number=last + 1, event_type="PLAYER_UNSOLD",
                            player_id=session.active_player_id, event_payload={}))
        result = {"status": "UNSOLD"}
    session.active_player_id = None
    session.current_team_id = None
    session.current_bid = None
    db.commit()
    return result


@router.get("/sessions/{session_id}/events")
def session_events(session_id: str, db: Session = Depends(get_db)):
    if not db.get(AuctionSession, session_id):
        raise HTTPException(404, "Auction session not found")
    events = db.scalars(select(AuctionEvent).where(AuctionEvent.session_id == session_id)
                        .order_by(AuctionEvent.sequence_number)).all()
    return [{"sequence_number": e.sequence_number, "event_type": e.event_type, "player_id": e.player_id,
             "team_id": e.team_id, "bid_amount": str(e.bid_amount) if e.bid_amount is not None else None,
             "payload": e.event_payload, "created_at": e.created_at.isoformat()} for e in events]


@router.post("/history/preview-csv")
async def preview_history_csv(file: UploadFile = File(...), source_name: str = Form("custom-upload"),
                              db: Session = Depends(get_db)):
    report = _history_csv_preview(db, file.filename or "upload.csv", await file.read(), source_name[:256])
    return {**report, "accepted": report["accepted"][:100],
            "note": "Preview only. The first 100 valid rows are shown; upload again to import."}


@router.post("/history/import-csv")
async def import_history_csv(file: UploadFile = File(...), source_name: str = Form("custom-upload"),
                             source_url: Optional[str] = Form(None), db: Session = Depends(get_db)):
    report = _history_csv_preview(db, file.filename or "upload.csv", await file.read(), source_name[:256])
    source_name = source_name[:256]
    for row in report["accepted"]:
        db.add(AuctionHistoryRecord(
            player_id=row["player_id"], source_player_id=row["source_player_id"],
            source_player_name=row["source_player_name"], identity_match_status=row["identity_match_status"],
            auction_year=row["auction_year"], franchise_name=row["franchise_name"], role=row["role"],
            nationality=row["nationality"], base_price_lakh=row["base_price_lakh"],
            final_price_lakh=row["final_price_lakh"], status=row["status"],
            acquisition_type=row["acquisition_type"], source_name=source_name,
            source_url=source_url, source_record_key=row["source_record_key"],
        ))
    upload = AuctionHistoryImport(filename=(file.filename or "upload.csv")[:512], source_name=source_name,
                                  source_url=source_url, accepted_rows=report["accepted_rows"],
                                  duplicate_rows=report["duplicate_rows"], rejected_rows=report["rejected_rows"],
                                  report_json={"identity_summary": report["identity_summary"],
                                               "rejected": report["rejected"][:100]})
    db.add(upload)
    db.commit()
    return {"import_id": upload.id, "filename": upload.filename, "source_name": source_name,
            "accepted_rows": upload.accepted_rows, "duplicate_rows": upload.duplicate_rows,
            "rejected_rows": upload.rejected_rows, "identity_summary": report["identity_summary"],
            "rejected": report["rejected"][:100]}


@router.post("/history/import-bundled-sources")
def import_bundled_auction_sources(db: Session = Depends(get_db)):
    project_root = Path(__file__).resolve().parents[4]
    sources = [
        ("outside-edge/ipl_auction", "data/auction/sources/outside_edge_auction_all_years.csv",
         "https://github.com/outside-edge/ipl_auction"),
        ("rixabhh/IPL-Auction-Analysis", "data/auction/sources/rixabhh_cleaned_ipl_auction_2013_2022.csv",
         "https://github.com/rixabhh/IPL-Auction-Analysis"),
    ]
    results = []
    for source_name, relative, source_url in sources:
        path = project_root / relative
        if not path.exists():
            raise HTTPException(404, f"Bundled auction source file is missing: {relative}")
        report = _history_csv_preview(db, path.name, path.read_bytes(), source_name)
        for row in report["accepted"]:
            db.add(AuctionHistoryRecord(
                player_id=row["player_id"], source_player_id=row["source_player_id"],
                source_player_name=row["source_player_name"], identity_match_status=row["identity_match_status"],
                auction_year=row["auction_year"], franchise_name=row["franchise_name"], role=row["role"],
                nationality=row["nationality"], base_price_lakh=row["base_price_lakh"],
                final_price_lakh=row["final_price_lakh"], status=row["status"],
                acquisition_type=row["acquisition_type"], source_name=source_name,
                source_url=source_url, source_record_key=row["source_record_key"],
            ))
        db.add(AuctionHistoryImport(
            filename=path.name, source_name=source_name, source_url=source_url,
            accepted_rows=report["accepted_rows"], duplicate_rows=report["duplicate_rows"],
            rejected_rows=report["rejected_rows"],
            report_json={"identity_summary": report["identity_summary"], "rejected": report["rejected"][:100]},
        ))
        results.append({"source_name": source_name, "accepted_rows": report["accepted_rows"],
                        "duplicate_rows": report["duplicate_rows"], "rejected_rows": report["rejected_rows"],
                        "identity_summary": report["identity_summary"]})
    db.commit()
    return {"sources": results, "note": "Rows are stored with source provenance; retained and unsold outcomes remain distinct."}


@router.get("/history/summary")
def auction_history_summary(db: Session = Depends(get_db)):
    total = db.scalar(select(func.count()).select_from(AuctionHistoryRecord)) or 0
    sold = db.scalar(select(func.count()).select_from(AuctionHistoryRecord).where(
        AuctionHistoryRecord.status == "SOLD", AuctionHistoryRecord.acquisition_type == "auction",
        AuctionHistoryRecord.final_price_lakh.is_not(None))) or 0
    years = db.execute(select(AuctionHistoryRecord.auction_year, func.count())
                       .group_by(AuctionHistoryRecord.auction_year).order_by(AuctionHistoryRecord.auction_year)).all()
    sources = db.execute(select(AuctionHistoryRecord.source_name, func.count())
                         .group_by(AuctionHistoryRecord.source_name).order_by(AuctionHistoryRecord.source_name)).all()
    imports = db.scalars(select(AuctionHistoryImport).order_by(AuctionHistoryImport.created_at.desc()).limit(20)).all()
    latest = db.scalar(select(AuctionModelRun).where(AuctionModelRun.task == "price_regression")
                       .order_by(AuctionModelRun.created_at.desc()))
    return {"records": total, "sold_auction_rows": sold,
            "years": [{"year": y, "count": count} for y, count in years],
            "sources": [{"source": s, "count": count} for s, count in sources],
            "imports": [{"id": i.id, "filename": i.filename, "source_name": i.source_name,
                         "accepted_rows": i.accepted_rows, "duplicate_rows": i.duplicate_rows,
                         "rejected_rows": i.rejected_rows, "created_at": i.created_at.isoformat()} for i in imports],
            "latest_price_model": _model_run_json(latest) if latest else None}


def _model_run_json(run):
    return {"id": run.id, "version": run.model_version, "training_rows": run.training_rows,
            "validation_rows": run.validation_rows, "evaluation": run.evaluation_json,
            "created_at": run.created_at.isoformat()}


@router.post("/models/train-price")
def train_auction_price_model(db: Session = Depends(get_db)):
    from app.ml.auction_price import train_price_model
    try:
        return _model_run_json(train_price_model(db))
    except ValueError as exc:
        raise HTTPException(422, str(exc))


@router.get("/models/price/status")
def auction_price_model_status(db: Session = Depends(get_db)):
    run = db.scalar(select(AuctionModelRun).where(AuctionModelRun.task == "price_regression")
                     .order_by(AuctionModelRun.created_at.desc()))
    return _model_run_json(run) if run else {"trained": False, "message": "Import auction history and train the price baseline."}


def _pool_csv_upload(scenario_id: str, filename: str, content: bytes, db: Session):
    _scenario(db, scenario_id)
    try:
        raw_rows = read_csv_rows(filename, content)
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    parsed, malformed = [], []
    for line, row in raw_rows:
        item, errors = pool_row(line, row)
        if errors:
            malformed.append({"row": line, "reasons": errors})
        else:
            parsed.append((line, item))
    preview = preview_player_pool(scenario_id, PoolUpload(filename=filename, rows=[r for _, r in parsed]), db)
    # Translate its 1-based data-row positions back to original CSV line numbers.
    for item in preview["accepted"]:
        item["row"] = parsed[item["row"] - 1][0]
    for item in preview["rejected"]:
        item["row"] = parsed[item["row"] - 1][0]
    preview["rejected"].extend(malformed)
    preview["rejected_rows"] += len(malformed)
    return preview, parsed


@router.post("/scenarios/{scenario_id}/retentions/preview-csv")
async def preview_retentions_csv(scenario_id: str, file: UploadFile = File(...), db: Session = Depends(get_db)):
    _scenario(db, scenario_id)
    try:
        rows = read_csv_rows(file.filename or "retentions.csv", await file.read())
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    index = _player_name_index(db)
    accepted, rejected, seen = [], [], set()
    for line, row in rows:
        name = _first(row, "player_name", "player", "name", "cricketer")
        team = _first(row, "franchise_name", "franchise", "team", "team_name", "buyer")
        ids = _matching_player_ids(index, name)
        if not name or not team:
            rejected.append({"row": line, "player_name": name, "reason": "player and franchise/team are required"})
            continue
        if len(ids) != 1:
            rejected.append({"row": line, "player_name": name,
                             "reason": "unresolved player identity" if not ids else "ambiguous player identity"})
            continue
        player_id = next(iter(ids))
        if player_id in seen:
            rejected.append({"row": line, "player_name": name, "reason": "duplicate retained player in upload"})
            continue
        seen.add(player_id)
        team_row = db.scalar(select(AuctionTeam).where(
            AuctionTeam.scenario_id == scenario_id,
            func.lower(AuctionTeam.franchise_name) == team.casefold()))
        retained = db.scalar(select(AuctionRetention).where(
            AuctionRetention.scenario_id == scenario_id, AuctionRetention.player_id == player_id))
        if retained:
            rejected.append({"row": line, "player_name": name, "reason": "player is already in this scenario's retention list"})
            continue
        price = _decimal(_first(row, "retention_price_lakh", "retention_price", "price_lakh", "price"))
        accepted.append({"row": line, "player_id": player_id, "player_name": name,
                         "canonical_name": db.get(Player, player_id).canonical_name,
                         "franchise": team, "franchise_exists": bool(team_row),
                         "retention_price": str(price) if price is not None else None,
                         "retention_category": _first(row, "retention_category", "category", "retention_order"),
                         "retention_order": _first(row, "retention_order", "order")})
    return {"filename": file.filename, "accepted_rows": len(accepted), "rejected_rows": len(rejected),
            "accepted": accepted[:100], "rejected": rejected[:100],
            "note": "Player aliases are resolved through CPI and Cricsheet names.csv; ambiguous matches are rejected."}


@router.post("/scenarios/{scenario_id}/retentions/import-csv")
async def import_retentions_csv(scenario_id: str, file: UploadFile = File(...), db: Session = Depends(get_db)):
    _scenario(db, scenario_id)
    filename = file.filename or "retentions.csv"
    try:
        rows = read_csv_rows(filename, await file.read())
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    index = _player_name_index(db)
    accepted, rejected, seen = [], [], set()
    for line, row in rows:
        name = _first(row, "player_name", "player", "name", "cricketer")
        team_name = _first(row, "franchise_name", "franchise", "team", "team_name", "buyer")
        ids = _matching_player_ids(index, name)
        enrichment_status = None
        if name and team_name and not ids:
            from app.services.cricket_database import enrich_player
            profile, source, enrichment_status = await enrich_player(db, name, {"nationality": _first(row, "nationality"), "primary_role": _first(row, "role")})
            ids = {profile.id}
            index.setdefault(_player_name_key(name), set()).add(profile.id)
        if not name or not team_name or len(ids) != 1:
            reason = "player and franchise/team are required" if not name or not team_name else (
                "unresolved player identity" if not ids else "ambiguous player identity")
            rejected.append({"row": line, "player_name": name, "reason": reason})
            continue
        player_id = next(iter(ids))
        if player_id in seen or db.scalar(select(AuctionRetention.id).where(
                AuctionRetention.scenario_id == scenario_id, AuctionRetention.player_id == player_id)):
            rejected.append({"row": line, "player_name": name, "reason": "duplicate retained player"})
            continue
        seen.add(player_id)
        team = db.scalar(select(AuctionTeam).where(
            AuctionTeam.scenario_id == scenario_id,
            func.lower(AuctionTeam.franchise_name) == team_name.casefold()))
        if team is None:
            code = re.sub(r"[^A-Z0-9]", "", team_name.upper())[:32] or f"TEAM{len(accepted)+1}"
            if db.scalar(select(AuctionTeam.id).where(AuctionTeam.scenario_id == scenario_id,
                                                       AuctionTeam.franchise_code == code)):
                code = f"{code[:26]}{len(accepted)+1:05d}"
            team = AuctionTeam(scenario_id=scenario_id, franchise_name=team_name[:128], franchise_code=code,
                               initial_purse=0, remaining_purse=0, minimum_squad_size=0,
                               maximum_squad_size=25, overseas_squad_limit=8)
            db.add(team)
            db.flush()
        active_rule = db.scalar(select(AuctionRule).where(AuctionRule.scenario_id == scenario_id).order_by(AuctionRule.version.desc()))
        active_rules = active_rule.rules_json if active_rule else {}
        existing_size = db.scalar(select(func.count()).select_from(AuctionRetention).where(AuctionRetention.team_id == team.id)) or 0
        incoming_size = sum(1 for x in accepted if x.get("franchise", "").casefold() == team_name.casefold())
        if existing_size + incoming_size >= int(active_rules.get("maximum_squad_size", team.maximum_squad_size)):
            rejected.append({"row": line, "player_name": name, "reason": "maximum squad size would be exceeded"})
            continue
        nationality = _first(row, "nationality", "country")
        overseas_flag = _first(row, "overseas_eligible", "overseas")
        incoming_overseas = (str(overseas_flag).strip().lower() in {"1", "true", "yes", "y"}) if overseas_flag else (nationality.lower() not in {"india", "indian"} if nationality else True)
        if incoming_overseas:
            existing_ids = db.scalars(select(AuctionRetention.player_id).where(AuctionRetention.team_id == team.id)).all()
            already_foreign = 0
            for existing_id in existing_ids:
                existing_nat = db.scalar(select(PlayerAttribute.attribute_value).where(
                    PlayerAttribute.player_id == existing_id, PlayerAttribute.attribute_type == "nationality").limit(1))
                already_foreign += int(bool(existing_nat and existing_nat.lower() not in {"india", "indian"}))
            already_foreign += sum(1 for x in accepted if x.get("franchise", "").casefold() == team_name.casefold() and x.get("overseas"))
            if already_foreign >= int(active_rules.get("overseas_squad_limit", team.overseas_squad_limit)):
                rejected.append({"row": line, "player_name": name, "reason": "overseas squad limit would be exceeded"})
                continue
        price = _decimal(_first(row, "retention_price_lakh", "retention_price", "price_lakh", "price"))
        order = _first(row, "retention_order", "order")
        try:
            order = int(order) if order else None
        except ValueError:
            order = None
        accepted.append({"row": line, "player_id": player_id, "player_name": db.get(Player, player_id).canonical_name,
                         "franchise": team.franchise_name, "overseas": incoming_overseas})
        db.add(AuctionRetention(scenario_id=scenario_id, team_id=team.id, player_id=player_id,
                                retention_price=price, retention_category=_first(row, "retention_category", "category"),
                                retention_order=order))
    batch = AuctionImport(scenario_id=scenario_id, filename=filename, data_type="RETENTIONS",
                          status="IMPORTED" if accepted else "REJECTED", accepted_rows=len(accepted),
                          rejected_rows=len(rejected), report_json={"accepted": accepted[:100], "rejected": rejected[:100]})
    db.add(batch)
    db.commit()
    return {"import_id": batch.id, "accepted_rows": len(accepted), "rejected_rows": len(rejected),
            "accepted": accepted[:100], "rejected": rejected[:100]}


@router.post("/scenarios/{scenario_id}/player-pool/preview-csv")
async def preview_player_pool_csv(scenario_id: str, file: UploadFile = File(...), db: Session = Depends(get_db)):
    preview, _ = _pool_csv_upload(scenario_id, file.filename or "player-pool.csv", await file.read(), db)
    return {**preview, "accepted": preview["accepted"][:100], "note": "Preview only."}


@router.post("/scenarios/{scenario_id}/player-pool/import-csv")
async def import_player_pool_csv(scenario_id: str, file: UploadFile = File(...), db: Session = Depends(get_db)):
    filename = file.filename or "player-pool.csv"
    preview, parsed = _pool_csv_upload(scenario_id, filename, await file.read(), db)
    line_to_item = {line: item for line, item in parsed}
    import_rows = []
    import_player_ids = {item["player_id"] for item in preview["accepted"]}
    for item in preview["accepted"]:
        row = line_to_item[item["row"]]
        import_rows.append({"player_id": item["player_id"], "base_price": str(row.base_price),
                            "auction_category": row.auction_category, "auction_order": row.auction_order,
                            "primary_role": row.primary_role, "secondary_role": row.secondary_role,
                            "nationality": row.nationality, "overseas_eligible": row.overseas_eligible,
                            "wicketkeeper": row.wicketkeeper})
    # Unknown identities get a conservative exact-match provider lookup; when the
    # provider has no verified match, preserve the uploaded name as a minimal record.
    unresolved = {r["row"]: r for r in preview["rejected"] if r.get("reason") == "unresolved player"}
    if unresolved:
        from app.services.cricket_database import enrich_player
        for line, rejected in unresolved.items():
            row = line_to_item.get(line)
            if not row or not row.player_name: continue
            player, source, status = await enrich_player(db, row.player_name, {
                "nationality": row.nationality, "primary_role": row.primary_role,
                "batting_style": None, "bowling_style": None,
            })
            if player.id in import_player_ids:
                rejected["reason"] = "duplicate player in upload"
                continue
            import_player_ids.add(player.id)
            import_rows.append({"player_id": player.id, "base_price": str(row.base_price),
                "auction_category": row.auction_category, "auction_order": row.auction_order,
                "primary_role": row.primary_role, "secondary_role": row.secondary_role,
                "nationality": row.nationality, "overseas_eligible": row.overseas_eligible,
                "wicketkeeper": row.wicketkeeper})
            rejected["reason"] = f"Added as {status} profile ({source})"
        # These rows are now valid minimal/basic CPI records, not rejections.
        imported_unresolved = sum(r.get("reason", "").startswith("Added as ") for r in unresolved.values())
        preview["rejected_rows"] -= imported_unresolved
        preview["accepted_rows"] += len(import_rows) - len(preview["accepted"])
    for row in import_rows:
        db.add(AuctionPlayer(scenario_id=scenario_id, identity_match_status="MATCHED", **row))
    batch = AuctionImport(scenario_id=scenario_id, filename=filename, data_type="PLAYER_POOL",
                          status="IMPORTED" if import_rows else "REJECTED",
                          accepted_rows=len(import_rows), rejected_rows=preview["rejected_rows"],
                          report_json={"rejected": preview["rejected"][:100]})
    db.add(batch)
    db.commit()
    return {"import_id": batch.id, "accepted_rows": batch.accepted_rows,
            "rejected_rows": batch.rejected_rows, "rejected": preview["rejected"][:100]}
