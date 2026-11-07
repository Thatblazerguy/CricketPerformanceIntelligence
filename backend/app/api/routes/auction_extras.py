"""Rules uploads, scenario XI generation and basic-data player lookup endpoints."""
from typing import Any, Dict, Literal
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy import Integer, cast, func, select
from sqlalchemy.orm import Session
from app.db.session import get_db
from app.models.models import (AuctionScenario, AuctionRule, AuctionTeam, AuctionRetention,
    AuctionPurchase, AuctionSession, AuctionPlayer, Player, PlayerAttribute, AuctionPredictedXI,
    Match, MatchInnings, Delivery, Wicket, PlayerExternalProfile, Provider)

router = APIRouter(prefix="/auction", tags=["Auction Intelligence"])

class RuleConfirm(BaseModel):
    rules: Dict[str, Any]

class XIRequest(BaseModel):
    team_id: str
    style: Literal["balanced", "batting-heavy", "bowling-heavy", "spin-friendly", "pace-friendly"] = "balanced"

def scenario_or_404(db, scenario_id):
    scenario = db.get(AuctionScenario, scenario_id)
    if not scenario: raise HTTPException(404, "Auction scenario not found")
    return scenario

@router.post("/scenarios/{scenario_id}/rules/parse")
async def parse_rules(scenario_id: str, file: UploadFile = File(...), db: Session = Depends(get_db)):
    scenario_or_404(db, scenario_id)
    filename, content = (file.filename or "").lower(), await file.read()
    try:
        if filename.endswith((".txt", ".csv")): text = content.decode("utf-8-sig")
        elif filename.endswith(".docx"):
            from zipfile import ZipFile
            from xml.etree import ElementTree
            import io
            with ZipFile(io.BytesIO(content)) as z: root = ElementTree.fromstring(z.read("word/document.xml"))
            text = " ".join(node.text or "" for node in root.iter() if node.tag.endswith("}t"))
        elif filename.endswith(".pdf"):
            from pypdf import PdfReader
            import io
            text = "\n".join(p.extract_text() or "" for p in PdfReader(io.BytesIO(content)).pages)
        else: raise HTTPException(415, "Upload PDF, DOCX, CSV, or TXT")
    except HTTPException: raise
    except ImportError as exc: raise HTTPException(503, "PDF extraction library is unavailable; install backend requirements and retry") from exc
    except Exception as exc: raise HTTPException(422, f"Could not extract rules: {exc}")
    from app.auction_intelligence import parse_rules_text
    return {"filename": filename, "extracted_text": text[:30000], "proposed_rules": parse_rules_text(text),
            "note": "Review and edit these extracted limits before confirming them."}

@router.put("/scenarios/{scenario_id}/rules")
def confirm_rules(scenario_id: str, body: RuleConfirm, db: Session = Depends(get_db)):
    scenario_or_404(db, scenario_id)
    rules = body.rules
    try:
        if int(rules["maximum_squad_size"]) < 1 or int(rules["overseas_squad_limit"]) < 0 or int(rules["overseas_xi_limit"]) < 0: raise ValueError()
        if int(rules.get("minimum_squad_size", 0)) > int(rules["maximum_squad_size"]): raise ValueError()
    except (KeyError, TypeError, ValueError): raise HTTPException(422, "Rules contain invalid squad or overseas limits")
    teams = db.scalars(select(AuctionTeam).where(AuctionTeam.scenario_id == scenario_id)).all()
    for team in teams:
        retained = db.scalars(select(AuctionRetention.player_id).where(AuctionRetention.team_id == team.id)).all()
        purchased = db.scalars(select(AuctionPurchase.player_id).join(AuctionSession, AuctionPurchase.session_id == AuctionSession.id)
            .where(AuctionSession.scenario_id == scenario_id, AuctionPurchase.team_id == team.id)).all()
        roster = list(dict.fromkeys(retained + purchased))
        if len(roster) > int(rules["maximum_squad_size"]):
            raise HTTPException(422, f"{team.franchise_name} already exceeds the proposed maximum squad size")
        overseas = 0
        for pid in roster:
            entry = db.scalar(select(AuctionPlayer).where(AuctionPlayer.scenario_id == scenario_id, AuctionPlayer.player_id == pid))
            nationality = db.scalar(select(PlayerAttribute.attribute_value).where(
                PlayerAttribute.player_id == pid, PlayerAttribute.attribute_type == "nationality").limit(1))
            is_overseas = entry.overseas_eligible if entry and entry.overseas_eligible is not None else (nationality.lower() not in {"india", "indian"} if nationality else True)
            overseas += int(bool(is_overseas))
        if overseas > int(rules["overseas_squad_limit"]):
            raise HTTPException(422, f"{team.franchise_name} already exceeds the proposed overseas squad limit")
    latest = db.scalar(select(AuctionRule).where(AuctionRule.scenario_id == scenario_id).order_by(AuctionRule.version.desc()))
    version = (latest.version if latest else 0) + 1
    db.add(AuctionRule(scenario_id=scenario_id, version=version, rules_json=rules)); db.commit()
    return {"rules_version": version, "rules": rules, "confirmed": True}

@router.post("/scenarios/{scenario_id}/predicted-xi")
def generate_xi(scenario_id: str, body: XIRequest, db: Session = Depends(get_db)):
    scenario_or_404(db, scenario_id)
    team = db.scalar(select(AuctionTeam).where(AuctionTeam.id == body.team_id, AuctionTeam.scenario_id == scenario_id))
    if not team: raise HTTPException(404, "Franchise not found")
    latest = db.scalar(select(AuctionRule).where(AuctionRule.scenario_id == scenario_id).order_by(AuctionRule.version.desc()))
    rules = latest.rules_json if latest else {"maximum_squad_size": 25, "overseas_squad_limit": 8, "overseas_xi_limit": 4}
    retentions = db.scalars(select(AuctionRetention).where(AuctionRetention.team_id == team.id)).all()
    purchases = db.scalars(select(AuctionPurchase).where(AuctionPurchase.team_id == team.id)).all()
    ids = list(dict.fromkeys([x.player_id for x in retentions] + [x.player_id for x in purchases]))
    if len(ids) > int(rules.get("maximum_squad_size", 25)): raise HTTPException(422, "Current squad exceeds configured size; resolve before XI generation")
    if not ids: raise HTTPException(422, "No retained or purchased players are available for this franchise")
    players = db.scalars(select(Player).where(Player.id.in_(ids))).all()
    info = {p.id: {"player_id": p.id, "name": p.canonical_name, "overseas": False, "nationality_known": False,
        "role": None, "wicketkeeper": False, "data_complete": False, "confidence": "low",
        "limitations": "No minimum-size CPI performance sample."} for p in players}
    for item in db.scalars(select(AuctionPlayer).where(AuctionPlayer.scenario_id == scenario_id, AuctionPlayer.player_id.in_(ids))).all():
        c = info[item.player_id]; c["role"] = item.primary_role or item.secondary_role
        c["nationality_known"] = item.overseas_eligible is not None or bool(item.nationality)
        c["overseas"] = bool(item.overseas_eligible) if item.overseas_eligible is not None else (item.nationality.lower() not in {"india", "indian"} if item.nationality else False)
        c["wicketkeeper"] = bool(item.wicketkeeper)
    attrs = db.execute(select(PlayerAttribute.player_id, PlayerAttribute.attribute_type, PlayerAttribute.attribute_value)
        .where(PlayerAttribute.player_id.in_(ids), PlayerAttribute.attribute_type.in_(["primary_role", "nationality", "wicketkeeper", "bowling_style"]))).all()
    for pid, attr, val in attrs:
        if attr == "primary_role" and not info[pid]["role"]: info[pid]["role"] = val
        elif attr == "nationality":
            info[pid]["overseas"] = val.lower() not in {"india", "indian"}
            info[pid]["nationality_known"] = True
        elif attr == "wicketkeeper": info[pid]["wicketkeeper"] = "keeper" in val.lower()
        elif attr == "bowling_style":
            spin = any(word in val.lower() for word in ("spin", "break", "orthodox", "leg", "wrist"))
            info[pid]["spin_score"] = 1.0 if spin else 0.0
            info[pid]["pace_score"] = 0.0 if spin else 1.0
    # Query only the current franchise player IDs and aggregate in PostgreSQL.
    bat = db.execute(select(Delivery.batter_id, func.count(Delivery.id), func.sum(Delivery.batter_runs))
        .join(MatchInnings, Delivery.innings_id == MatchInnings.id).join(Match, MatchInnings.match_id == Match.id)
        .where(Delivery.batter_id.in_(ids), Match.match_format == "T20").group_by(Delivery.batter_id)).all()
    for pid, balls, runs in bat:
        runs, balls = int(runs or 0), int(balls or 0)
        info[pid]["bat_score"] = min(1, runs / 1200 + runs / max(balls, 1) / 160)
        info[pid]["data_complete"] = balls >= 100
        info[pid]["reason"] = f"CPI batting: {runs} runs from {balls} recorded deliveries."
        if balls >= 100: info[pid]["confidence"] = "high"
    bowl = db.execute(select(Delivery.bowler_id, func.sum(cast(Delivery.is_legal_ball, Integer)), func.sum(Delivery.bowling_runs))
        .join(MatchInnings, Delivery.innings_id == MatchInnings.id).join(Match, MatchInnings.match_id == Match.id)
        .where(Delivery.bowler_id.in_(ids), Match.match_format == "T20").group_by(Delivery.bowler_id)).all()
    wkts = dict(db.execute(select(Delivery.bowler_id, func.count(Wicket.id)).join(Wicket, Wicket.delivery_id == Delivery.id)
        .join(MatchInnings, Delivery.innings_id == MatchInnings.id).join(Match, MatchInnings.match_id == Match.id)
        .where(Delivery.bowler_id.in_(ids), Match.match_format == "T20", Wicket.is_bowler_wicket.is_(True)).group_by(Delivery.bowler_id)).all())
    for pid, balls, conceded in bowl:
        balls, wickets, conceded = int(balls or 0), int(wkts.get(pid, 0)), int(conceded or 0)
        economy = conceded / max(balls, 1) * 6
        info[pid]["bowl_score"] = min(1, wickets / 80 + max(0, 10 - economy) / 20)
        info[pid]["data_complete"] |= balls >= 60
        info[pid]["reason"] = (info[pid].get("reason", "") + f" Bowling: {wickets} recorded dismissals, {economy:.2f} runs per over.").strip()
        if balls >= 60 and info[pid]["confidence"] == "low": info[pid]["confidence"] = "medium"
    phase_rows = db.execute(select(Delivery.bowler_id, Delivery.phase, func.sum(cast(Delivery.is_legal_ball, Integer)),
                                   func.sum(Delivery.bowling_runs))
        .join(MatchInnings, Delivery.innings_id == MatchInnings.id).join(Match, MatchInnings.match_id == Match.id)
        .where(Delivery.bowler_id.in_(ids), Match.match_format == "T20", Delivery.phase.in_(["powerplay", "middle", "death"]))
        .group_by(Delivery.bowler_id, Delivery.phase)).all()
    phase_wickets = {(pid, phase): count for pid, phase, count in db.execute(select(Delivery.bowler_id, Delivery.phase, func.count(Wicket.id))
        .join(Wicket, Wicket.delivery_id == Delivery.id).join(MatchInnings, Delivery.innings_id == MatchInnings.id)
        .join(Match, MatchInnings.match_id == Match.id)
        .where(Delivery.bowler_id.in_(ids), Match.match_format == "T20", Wicket.is_bowler_wicket.is_(True))
        .group_by(Delivery.bowler_id, Delivery.phase)).all()}
    for pid, phase_name, balls, conceded in phase_rows:
        balls, conceded = int(balls or 0), int(conceded or 0)
        eco = conceded / max(balls, 1) * 6
        phase_score = min(1, int(phase_wickets.get((pid, phase_name), 0)) / 8 + max(0, 10 - eco) / 20)
        info[pid][f"{phase_name}_score"] = phase_score
        info[pid]["phase_profile"] = info[pid].get("phase_profile", []) + [f"{phase_name}: {int(phase_wickets.get((pid, phase_name), 0))} wickets, {eco:.2f} economy"]
        info[pid]["reason"] = (info[pid].get("reason", "") + " T20 phase performance: " + ", ".join(info[pid]["phase_profile"]) + ".").strip()
    for c in info.values(): c.setdefault("bat_score", 0); c.setdefault("bowl_score", 0)
    from app.auction_intelligence import build_predicted_xi
    try: result = build_predicted_xi(list(info.values()), rules, body.style)
    except ValueError as exc: raise HTTPException(422, str(exc))
    missing_nationality = [p["name"] for p in result["players"] if not info[p["player_id"]].get("nationality_known")]
    result["validation_status"] = "INCOMPLETE" if missing_nationality else "VALIDATED"
    result["validation_warnings"] = ([f"Nationality is missing for {len(missing_nationality)} selected player(s); the overseas-player cap cannot be fully verified."] if missing_nationality else [])
    record = AuctionPredictedXI(scenario_id=scenario_id, team_id=team.id, style=body.style,
        rules_version=latest.version if latest else 1, result_json=result)
    db.add(record); db.commit()
    return {**result, "id": record.id, "team_id": team.id, "franchise": team.franchise_name,
            "rules_version": record.rules_version, "validated": not bool(missing_nationality)}
