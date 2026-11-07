"""Explainable team needs and franchise-specific auction bid estimates."""
from collections import Counter, defaultdict
from pathlib import Path

import joblib
import numpy as np
from sqlalchemy import bindparam, select, text

from app.ml.auction_price import predict_team_bids, _team_key, role_key
from app.analytics.auction_competition import (
    competition_adjusted_price, demand_score, percentile_quality, team_willingness_lakh,
)
from app.analytics.auction_form import FORM_FEATURES, load_recent_form
from app.models.models import (
    AuctionHistoryRecord, AuctionModelRun, AuctionPlayer, AuctionPurchase, AuctionRetention,
    AuctionRule, AuctionSession, AuctionTeam, Player, PlayerAttribute,
)

DEFAULT_ROLE_TARGETS = {"Batter": 6, "Bowler": 6, "All-Rounder": 4, "Wicketkeeper": 2}
SERIOUS_BIDDER_DEMAND_THRESHOLD = 20.0


def role_needs(retained_roles, targets=None):
    targets = targets or DEFAULT_ROLE_TARGETS
    gaps = {role: max(0, int(target) - int(retained_roles.get(role, 0)))
            for role, target in targets.items() if int(target) > 0}
    return {role: gap for role, gap in gaps.items() if gap > 0}


def _load_player_roles(db, player_ids):
    if not player_ids:
        return {}
    rows = db.execute(select(PlayerAttribute.player_id, PlayerAttribute.attribute_value)
                      .where(PlayerAttribute.player_id.in_(player_ids),
                             PlayerAttribute.attribute_type == "primary_role")
                      .order_by(PlayerAttribute.updated_at.desc())).all()
    result = {}
    for player_id, value in rows:
        role = role_key(value)
        if role != "Unknown":
            result.setdefault(player_id, role)
    historical_roles = db.execute(select(AuctionHistoryRecord.player_id, AuctionHistoryRecord.role)
                                  .where(AuctionHistoryRecord.player_id.in_(player_ids),
                                         AuctionHistoryRecord.role.is_not(None))
                                  .order_by(AuctionHistoryRecord.auction_year.desc())).all()
    for player_id, value in historical_roles:
        role = role_key(value)
        if role != "Unknown":
            result.setdefault(player_id, role)
    return result


def _history_priors(db, player_ids, year):
    rows = db.scalars(select(AuctionHistoryRecord).where(
        AuctionHistoryRecord.player_id.in_(player_ids),
        AuctionHistoryRecord.status == "SOLD",
        AuctionHistoryRecord.acquisition_type == "auction",
        AuctionHistoryRecord.auction_year < year,
        AuctionHistoryRecord.final_price_lakh.is_not(None),
    ).order_by(AuctionHistoryRecord.auction_year.desc())).all() if player_ids else []
    priors = {}
    for row in rows:
        values = priors.setdefault(row.player_id, [float(row.final_price_lakh), 0])
        values[1] += 1
    return priors


def _t20_player_metrics(db, player_ids):
    """Read cached/indexed T20 delivery aggregates once for the active player pool."""
    if not player_ids:
        return {}
    ids = list(player_ids)
    metrics = {pid: {} for pid in ids}
    bat_sql = text("""
        SELECT d.batter_id AS player_id,
               COUNT(DISTINCT mi.match_id) AS matches,
               SUM(CASE WHEN d.is_ball_faced_by_batter THEN 1 ELSE 0 END) AS balls,
               SUM(d.batter_runs) AS runs,
               SUM(CASE WHEN d.is_boundary_four THEN 1 ELSE 0 END) AS fours,
               SUM(CASE WHEN d.is_boundary_six THEN 1 ELSE 0 END) AS sixes,
               SUM(CASE WHEN d.is_legal_ball AND d.batter_runs=0 THEN 1 ELSE 0 END) AS dots
        FROM deliveries d JOIN match_innings mi ON mi.id=d.innings_id
        JOIN matches m ON m.id=mi.match_id
        WHERE d.batter_id IN :player_ids AND m.match_format='T20' AND mi.is_super_over=FALSE
        GROUP BY d.batter_id
    """).bindparams(bindparam("player_ids", expanding=True))
    for row in db.execute(bat_sql, {"player_ids": ids}).mappings():
        pid = row["player_id"]
        metrics[pid].update({
            "batting_balls": int(row["balls"] or 0), "matches": int(row["matches"] or 0),
            "batting_average": None, "strike_rate": None, "boundary_percentage": None,
            "batting_dot_percentage": None,
        })
        balls, runs = int(row["balls"] or 0), int(row["runs"] or 0)
        metrics[pid].update({"batting_runs": runs, "batting_balls": balls,
            "boundary_percentage": round((int(row["fours"] or 0)+int(row["sixes"] or 0))*100.0/balls, 3) if balls else None,
            "strike_rate": round(runs*100.0/balls, 3) if balls else None,
            "batting_dot_percentage": round(int(row["dots"] or 0)*100.0/balls, 3) if balls else None})
    bat_wickets = text("""
        SELECT d.batter_id AS player_id, COUNT(*) AS wickets
        FROM wickets w JOIN deliveries d ON d.id=w.delivery_id
        JOIN match_innings mi ON mi.id=d.innings_id JOIN matches m ON m.id=mi.match_id
        WHERE d.batter_id IN :player_ids AND w.player_out_id=d.batter_id
          AND w.is_batter_dismissed=TRUE AND m.match_format='T20' AND mi.is_super_over=FALSE
        GROUP BY d.batter_id
    """).bindparams(bindparam("player_ids", expanding=True))
    for row in db.execute(bat_wickets, {"player_ids": ids}).mappings():
        runs = metrics[row["player_id"]].get("batting_runs", 0)
        metrics[row["player_id"]]["batting_average"] = round(runs / int(row["wickets"]), 3) if row["wickets"] else None

    bowl_sql = text("""
        SELECT d.bowler_id AS player_id,
               COUNT(DISTINCT mi.match_id) AS matches,
               SUM(CASE WHEN d.is_legal_ball THEN 1 ELSE 0 END) AS balls,
               SUM(d.bowling_runs) AS runs,
               SUM(CASE WHEN d.is_legal_ball AND d.batter_runs=0 THEN 1 ELSE 0 END) AS dots
        FROM deliveries d JOIN match_innings mi ON mi.id=d.innings_id
        JOIN matches m ON m.id=mi.match_id
        WHERE d.bowler_id IN :player_ids AND m.match_format='T20' AND mi.is_super_over=FALSE
        GROUP BY d.bowler_id
    """).bindparams(bindparam("player_ids", expanding=True))
    for row in db.execute(bowl_sql, {"player_ids": ids}).mappings():
        pid, balls, runs = row["player_id"], int(row["balls"] or 0), int(row["runs"] or 0)
        metrics[pid].update({"bowling_balls": balls, "bowling_runs": runs,
            "bowling_matches": int(row["matches"] or 0), "wickets_per_match": None,
            "economy": round(runs*6.0/balls, 3) if balls else None,
            "bowling_average": None, "bowling_strike_rate": None,
            "dot_percentage": round(int(row["dots"] or 0)*100.0/balls, 3) if balls else None})
    bowl_wickets = text("""
        SELECT d.bowler_id AS player_id, COUNT(*) AS wickets
        FROM wickets w JOIN deliveries d ON d.id=w.delivery_id
        JOIN match_innings mi ON mi.id=d.innings_id JOIN matches m ON m.id=mi.match_id
        WHERE d.bowler_id IN :player_ids AND w.is_bowler_wicket=TRUE
          AND m.match_format='T20' AND mi.is_super_over=FALSE
        GROUP BY d.bowler_id
    """).bindparams(bindparam("player_ids", expanding=True))
    for row in db.execute(bowl_wickets, {"player_ids": ids}).mappings():
        pid, wickets = row["player_id"], int(row["wickets"] or 0)
        balls = metrics[pid].get("bowling_balls", 0)
        runs = metrics[pid].get("bowling_runs", 0)
        matches = metrics[pid].get("bowling_matches", 0)
        metrics[pid].update({"wickets": wickets,
            "wickets_per_match": round(wickets / matches, 3) if matches else None,
            "bowling_average": round(runs / wickets, 3) if wickets else None,
            "bowling_strike_rate": round(balls / wickets, 3) if wickets else None})
    return metrics


def _role_markup_priors(db, year):
    rows = db.scalars(select(AuctionHistoryRecord).where(
        AuctionHistoryRecord.auction_year < year,
        AuctionHistoryRecord.status == "SOLD",
        AuctionHistoryRecord.acquisition_type == "auction",
        AuctionHistoryRecord.final_price_lakh.is_not(None),
        AuctionHistoryRecord.base_price_lakh.is_not(None),
        AuctionHistoryRecord.base_price_lakh > 0,
    )).all()
    by_role, all_markups = defaultdict(list), []
    for row in rows:
        markup = max(0.0, float(row.final_price_lakh) / float(row.base_price_lakh) - 1.0)
        if markup > 0:
            all_markups.append(markup)
        key = role_key(row.role)
        if key != "Unknown" and markup > 0:
            by_role[key].append(markup)
    def robust(values):
        # Positive sale premiums capture observed bidding beyond reserve/base.
        # Log compression keeps unusually large reserve-price multiples from
        # dominating estimates while retaining their direction and rank.
        return float(np.log1p(np.median(values))) if len(values) >= 5 else None
    overall = robust(all_markups) or 0.0
    return {role: robust(values) if robust(values) is not None else overall for role, values in by_role.items()}, overall


def run_scenario(db, scenario):
    teams = db.scalars(select(AuctionTeam).where(AuctionTeam.scenario_id == scenario.id)
                       .order_by(AuctionTeam.franchise_name)).all()
    retentions = db.scalars(select(AuctionRetention).where(AuctionRetention.scenario_id == scenario.id)).all()
    candidates = db.execute(select(AuctionPlayer, Player).join(Player, Player.id == AuctionPlayer.player_id)
                            .where(AuctionPlayer.scenario_id == scenario.id,
                                   AuctionPlayer.availability_status == "AVAILABLE")).all()
    if not teams or not retentions:
        return {"ready": False, "message": "Import the full retention-list CSV before running the scenario.",
                "teams": [], "model": None}
    if not candidates:
        return {"ready": False, "message": "Import the player-pool CSV before running the scenario.",
                "teams": [], "model": None}
    model_run = db.scalar(select(AuctionModelRun).where(AuctionModelRun.task == "price_regression")
                          .order_by(AuctionModelRun.created_at.desc()))
    if not model_run:
        return {"ready": False, "message": "Train the previous-auction price model before running this scenario.",
                "teams": [], "model": None}
    backend_root = Path(__file__).resolve().parents[2]
    artifact = (backend_root / model_run.artifact_path).resolve()
    if not artifact.is_relative_to(backend_root.resolve()) or not artifact.exists():
        return {"ready": False, "message": "The latest price-model artifact is missing; train the model again.",
                "teams": [], "model": None}
    model_payload = joblib.load(artifact)
    if "franchise" not in model_payload.get("features", []):
        return {"ready": False, "message": "Retrain the auction model to enable franchise-specific bid estimates.",
                "teams": [], "model": {"version": model_run.model_version}}
    if not model_payload.get("form_features") or not model_payload.get("form_adjusters"):
        return {"ready": False, "message": "Retrain the auction price model once to enable recent-form valuation.",
                "teams": [], "model": {"version": model_run.model_version}}
    rule = db.scalar(select(AuctionRule).where(AuctionRule.scenario_id == scenario.id)
                     .order_by(AuctionRule.version.desc()))
    rules = rule.rules_json if rule else {}
    targets = rules.get("role_targets") or DEFAULT_ROLE_TARGETS
    targets = {role_key(role): int(target) for role, target in targets.items() if int(target) > 0}

    year = int(str(scenario.season)[:4])
    retained_ids = {item.player_id for item in retentions}
    pool_ids = {pool.player_id for pool, _ in candidates}
    purchase_rows = db.execute(select(AuctionPurchase, AuctionSession).join(
        AuctionSession, AuctionPurchase.session_id == AuctionSession.id
    ).where(AuctionSession.scenario_id == scenario.id)).all()
    purchased_ids = {purchase.player_id for purchase, _ in purchase_rows}
    all_ids = retained_ids | pool_ids | purchased_ids
    roles = _load_player_roles(db, all_ids)
    roster_pool_entries = db.scalars(select(AuctionPlayer).where(
        AuctionPlayer.scenario_id == scenario.id,
        AuctionPlayer.player_id.in_(all_ids),
    )).all() if all_ids else []
    roster_pool_by_player = {entry.player_id: entry for entry in roster_pool_entries}
    for entry in roster_pool_entries:
        role = role_key(entry.primary_role or entry.secondary_role)
        if role != "Unknown":
            roles.setdefault(entry.player_id, role)
    for pool, player in candidates:
        candidate_role = role_key(pool.primary_role or roles.get(player.id))
        if candidate_role != "Unknown":
            roles[player.id] = candidate_role
    history_priors = _history_priors(db, pool_ids, year)
    role_markups, overall_markup = _role_markup_priors(db, year)
    perf = _t20_player_metrics(db, pool_ids)

    # Relative quality is calculated within each role cohort using CPI T20
    # delivery aggregates. All-rounders receive equal batting and bowling weight.
    candidates_by_role = defaultdict(list)
    pool_by_id = {}
    for pool, player in candidates:
        role = role_key(pool.primary_role or roles.get(player.id))
        pool_by_id[player.id] = (pool, player, role)
        candidates_by_role[role].append(player.id)
    form_by_player = load_recent_form(
        db, pool_ids, {pid: role for pid, (_pool, _player, role) in pool_by_id.items()}
    )
    qualities = {}
    for role, player_ids in candidates_by_role.items():
        cohort = {pid: perf.get(pid, {}) for pid in player_ids}
        for pid, score in percentile_quality(cohort, role).items():
            qualities[pid] = score

    team_retention = defaultdict(list)
    for row in retentions:
        team_retention[row.team_id].append(row)
    team_purchases = defaultdict(list)
    for purchase, _session in purchase_rows:
        team_purchases[purchase.team_id].append(purchase)

    # Reconcile nationality and current squad composition once for all franchises.
    roster_ids = retained_ids | purchased_ids
    attrs = db.execute(select(PlayerAttribute.player_id, PlayerAttribute.attribute_type,
                              PlayerAttribute.attribute_value).where(
        PlayerAttribute.player_id.in_(roster_ids),
        PlayerAttribute.attribute_type.in_(("nationality", "primary_role")),
    )).all() if roster_ids else []
    roster_attrs = defaultdict(dict)
    for pid, kind, value in attrs:
        roster_attrs[pid].setdefault(kind, value)
    pool_by_player = {pool.player_id: pool for pool, _ in candidates}

    # Franchise role-purchase experience is used as a small suitability input;
    # franchise price behaviour remains learned by the existing ML pipeline.
    history_rows = db.scalars(select(AuctionHistoryRecord).where(
        AuctionHistoryRecord.auction_year < year,
        AuctionHistoryRecord.status == "SOLD",
        AuctionHistoryRecord.acquisition_type == "auction",
        AuctionHistoryRecord.franchise_name.is_not(None),
    )).all()
    team_role_sales = Counter()
    team_role_max = Counter()
    for row in history_rows:
        key = (_team_key(row.franchise_name), role_key(row.role))
        if key[1] != "Unknown":
            team_role_sales[key] += 1
            team_role_max[key[1]] = max(team_role_max[key[1]], team_role_sales[key])

    historical_by_team = model_run.evaluation_json.get("records_by_franchise", {})
    total_purse_cr = float(rules.get("total_purse", 120) or 120)
    max_squad = int(rules.get("maximum_squad_size", 25))
    overseas_limit = int(rules.get("overseas_squad_limit", 8))
    team_states = {}
    output_teams = []
    for team in teams:
        roster = set(row.player_id for row in team_retention.get(team.id, []))
        roster.update(row.player_id for row in team_purchases.get(team.id, []))
        role_counts = Counter(roles.get(pid, role_key(
            (roster_pool_by_player.get(pid).primary_role if roster_pool_by_player.get(pid) else None) or
            roster_attrs[pid].get("primary_role"))) for pid in roster)
        gaps = role_needs(role_counts, targets)
        team_max = min(max_squad, int(team.maximum_squad_size or max_squad))
        slots_left = max(0, team_max - len(roster))
        retention_spend_lakh = sum(float(row.retention_price or 0) for row in team_retention.get(team.id, []))
        purchase_spend_cr = sum(float(row.purchase_price or 0) for row in team_purchases.get(team.id, []))
        if float(team.initial_purse or 0) > 0:
            purse_lakh = max(0.0, float(team.remaining_purse or 0) * 100.0 - retention_spend_lakh)
        else:
            purse_lakh = max(0.0, total_purse_cr * 100.0 - retention_spend_lakh - purchase_spend_cr * 100.0)
        overseas_count = 0
        for pid in roster:
            player_pool = roster_pool_by_player.get(pid)
            nationality = (player_pool.nationality if player_pool else None) or roster_attrs[pid].get("nationality")
            overseas = (player_pool.overseas_eligible if player_pool and player_pool.overseas_eligible is not None else None)
            if overseas is None and nationality:
                overseas = nationality.strip().casefold() not in {"india", "indian", "unknown"}
            overseas_count += int(bool(overseas))
        state = {"purse_lakh": purse_lakh, "slots_left": slots_left,
                 "overseas_slots": max(0, overseas_limit - overseas_count),
                 "role_counts": role_counts, "gaps": gaps, "role_targets": targets,
                 "roster_count": len(roster)}
        team_states[team.id] = state
        team_history_count = historical_by_team.get(_team_key(team.franchise_name), 0)
        needs = [{"role": role, "target": targets[role], "retained": role_counts.get(role, 0),
                  "players_needed": gap} for role, gap in sorted(gaps.items(), key=lambda pair: -pair[1])]
        output_teams.append({
            "team_id": team.id, "franchise": team.franchise_name,
            "retained_count": len(team_retention.get(team.id, [])),
            "retained_role_counts": dict(role_counts), "needs": needs,
            "remaining_purse_cr": round(purse_lakh / 100.0, 2),
            "squad_slots_remaining": slots_left,
            "overseas_slots_remaining": state["overseas_slots"],
            "historical_team_sales": int(team_history_count),
            "recommendations": [],
        })

    # Preserve the historical model as the player/franchise valuation anchor.
    # Predict each candidate against every franchise; feasible bidders are later
    # filtered by squad, purse, overseas capacity and role urgency.
    prediction_requests, prediction_keys = [], []
    for player_id, (pool, player, candidate_role) in pool_by_id.items():
        prior, count = history_priors.get(player_id, [np.nan, 0])
        if not count:
            prior = np.nan
        for team in teams:
            prediction_keys.append((player_id, team.id))
            prediction_requests.append({
                "auction_year": year, "base_price_lakh": float(pool.base_price) * 100.0,
                "prior_price_lakh": prior, "prior_auction_count": count,
                "role": candidate_role, "nationality": pool.nationality,
                "franchise": team.franchise_name,
                **form_by_player.get(player_id, {}),
            })
    historical_estimates = predict_team_bids(model_payload, prediction_requests)
    historical_by_player = defaultdict(dict)
    for (player_id, team_id), value in zip(prediction_keys, historical_estimates):
        historical_by_player[player_id][team_id] = value

    # Count only comparable players still available in the pool. With missing
    # quality data, same-role players remain alternatives rather than being
    # silently treated as poor quality.
    alternatives = {}
    for player_id, (_pool, _player, role) in pool_by_id.items():
        quality = qualities.get(player_id)
        alternatives[player_id] = sum(
            1 for other_id, (_op, _oplayer, other_role) in pool_by_id.items()
            if other_id != player_id and other_role == role and
            (quality is None or qualities.get(other_id) is None or qualities.get(other_id) >= quality - 10.0)
        )

    output_players = []
    mae_lakh = float(model_run.evaluation_json.get("mae_lakh") or 0.0)
    minimum_increment_lakh = float(rules.get("minimum_bid_increment", 0.2)) * 100.0
    for player_id, (pool, player, candidate_role) in pool_by_id.items():
        base_lakh = float(pool.base_price) * 100.0
        role_markup = role_markups.get(candidate_role, overall_markup)
        team_prices = historical_by_player[player_id]
        individual_value = float(np.median(list(team_prices.values()))) if team_prices else base_lakh
        quality = qualities.get(player_id)
        bidder_records = []
        for team in teams:
            state = team_states[team.id]
            gap = int(state["gaps"].get(candidate_role, 0))
            is_overseas = pool.overseas_eligible
            if is_overseas is None and pool.nationality:
                is_overseas = pool.nationality.strip().casefold() not in {"india", "indian", "unknown"}
            predicted = float(team_prices.get(team.id, base_lakh))
            score, reasons = demand_score(
                gap, state["role_targets"].get(candidate_role, 1), quality,
                state["purse_lakh"], predicted, base_lakh, state["slots_left"],
                state["overseas_slots"], bool(is_overseas),
            )
            if score <= 0:
                continue
            hist_role_count = team_role_sales.get((_team_key(team.franchise_name), candidate_role), 0)
            max_role_count = team_role_max.get(candidate_role, 0)
            franchise_fit = 0.85 + 0.15 * (hist_role_count / max_role_count if max_role_count else 0.0)
            score = round(score * franchise_fit, 1)
            # Keep affordability separate from willingness: the purse only
            # caps the franchise-specific model estimate and must never become
            # the bid shown to the user just because demand is high.
            willingness = team_willingness_lakh(
                predicted, base_lakh, state["purse_lakh"])
            reasons.append("Prior franchise role acquisitions: {}".format(hist_role_count))
            bidder_records.append({
                "team_id": team.id, "franchise": team.franchise_name,
                "demand_score": score, "role_gap": gap,
                "historical_value_lakh": round(predicted, 2),
                "willingness_lakh": round(willingness, 2),
                "reasons": reasons,
            })

        serious = [row for row in bidder_records if row["demand_score"] >= SERIOUS_BIDDER_DEMAND_THRESHOLD]
        price = competition_adjusted_price(
            base_lakh, individual_value,
            [row["willingness_lakh"] for row in serious],
            alternatives[player_id], role_markup, mae_lakh,
        )
        # A real increment is applied after the second-highest feasible bid,
        # bounded by the strongest bidder's estimated willingness to pay.
        if len(serious) >= 2:
            bid_values = sorted((row["willingness_lakh"] for row in serious), reverse=True)
            price["expected_lakh"] = round(min(bid_values[0], max(price["expected_lakh"], bid_values[1] + minimum_increment_lakh)), 2)
            price["low_lakh"] = round(max(base_lakh, min(price["low_lakh"], price["expected_lakh"])), 2)
            price["high_lakh"] = round(max(price["high_lakh"], price["expected_lakh"]), 2)
        serious.sort(key=lambda row: (-row["demand_score"], -row["willingness_lakh"], row["franchise"]))
        total_demand = min(100.0, sum(row["demand_score"] for row in serious))
        model_rows = int(model_run.training_rows or 0)
        confidence = "high" if quality is not None and len(serious) >= 3 and model_rows >= 500 else (
            "medium" if (quality is not None or len(serious) >= 2) and model_rows >= 100 else "low")
        output_players.append({
            "player_id": player_id, "player_name": player.canonical_name,
            "role": candidate_role, "base_price_cr": round(float(pool.base_price), 2),
            "individual_valuation_cr": round(individual_value / 100.0, 2),
            "predicted_final_price_lakh": price["expected_lakh"],
            "predicted_final_price_cr": round(price["expected_lakh"] / 100.0, 2),
            "confidence_interval_lakh": {"low": price["low_lakh"], "high": price["high_lakh"]},
            "confidence_interval_cr": {"low": round(price["low_lakh"] / 100.0, 2),
                                       "high": round(price["high_lakh"] / 100.0, 2)},
            "confidence": confidence,
            "realistic_competing_franchises": len(serious),
            "demand_score": round(total_demand, 1),
            "scarcity_score": price["scarcity_score"],
            "comparable_alternatives": price["comparable_alternatives"],
            "competition_level": price["competition_level"],
            "competition_pressure": price["competition_pressure"],
            "most_likely_competitors": [{
                "team_id": row["team_id"], "franchise": row["franchise"],
                "demand_score": row["demand_score"],
                "role_gap": row["role_gap"],
                "willingness_to_pay_cr": round(row["willingness_lakh"] / 100.0, 2),
                "reasons": row["reasons"],
            } for row in serious[:5]],
            "price_basis": "Historical franchise-aware estimate adjusted for feasible bidder competition, role urgency and comparable-player scarcity.",
            "quality_sample": "T20 CPI deliveries" if quality is not None else "insufficient T20 sample",
            "recent_form": {
                "sample_matches": int(form_by_player.get(player_id, {}).get("form_sample_matches") or 0),
                "assessment": _form_assessment(candidate_role, form_by_player.get(player_id, {})),
                "features": {key.removeprefix("form_"): form_by_player.get(player_id, {}).get(key)
                             for key in FORM_FEATURES if form_by_player.get(player_id, {}).get(key) is not None},
                "influenced_price_model": True,
            },
        })

        # Team recommendations reuse the same player-specific willing bids and
        # expose why each franchise is or is not a realistic rival.
        for row in bidder_records:
            team_result = next(item for item in output_teams if item["team_id"] == row["team_id"])
            team_history_count = historical_by_team.get(_team_key(row["franchise"]), 0)
            team_result["recommendations"].append({
                "player_id": player_id, "player_name": player.canonical_name,
                "role": candidate_role, "base_price_cr": round(float(pool.base_price), 2),
                "estimated_bid_lakh": row["willingness_lakh"],
                "estimated_bid_cr": round(row["willingness_lakh"] / 100.0, 2),
                "estimated_team_willingness_cr": round(row["willingness_lakh"] / 100.0, 2),
                "need_priority": row["demand_score"], "demand_score": row["demand_score"],
                "confidence": confidence, "historical_team_sales": int(team_history_count),
                "price_basis": "Historical team valuation adjusted for role shortage, available purse and historical role suitability.",
                "demand_reasons": row["reasons"],
            })

    for team_result in output_teams:
        team_result["recommendations"].sort(
            key=lambda x: (-x["need_priority"], -x["estimated_team_willingness_cr"], x["player_name"]))
        team_result["recommendations"] = team_result["recommendations"][:10]
    output_players.sort(key=lambda x: (-x["realistic_competing_franchises"],
                                       -x["demand_score"], -x["predicted_final_price_lakh"]))
    return {
        "ready": True,
        "scenario": {"id": scenario.id, "name": scenario.name, "season": scenario.season},
        "model": {"version": model_run.model_version,
                  "holdout_mae_lakh": model_run.evaluation_json.get("mae_lakh"),
                  "holdout_start_year": model_run.evaluation_json.get("validation_start_year")},
        "assumptions": {
            "role_targets": targets,
            "target_note": "Default target squad balance is 6 batters, 6 bowlers, 4 all-rounders and 2 wicketkeepers; override in scenario rules when desired.",
            "price_note": "The historical model learns recent, role-specific batting and bowling form from pre-auction match snapshots. Expected closes add feasible bidder competition, role urgency and role-relative auction scarcity; purse and roster constraints exclude unrealistic bidders.",
            "price_unit": "INR crore and lakh",
        },
        "teams": output_teams,
        "player_predictions": output_players,
    }


def _form_assessment(role, features):
    """Short transparent summary; no assessment is emitted for thin samples."""
    if int(features.get("form_sample_matches") or 0) < 3:
        return "Insufficient recent match data"
    role_text = str(role or "").casefold()
    parts = []
    if "bowl" not in role_text or "all" in role_text:
        runs = features.get("form_bat_runs_per_match")
        strike = features.get("form_bat_strike_rate")
        if runs is not None:
            parts.append("batting {:.1f} runs per recent appearance".format(runs))
        if strike is not None:
            parts.append("SR {:.1f}".format(strike))
    if "bowl" in role_text or "all" in role_text:
        wickets = features.get("form_bowl_wickets_per_match")
        economy = features.get("form_bowl_economy")
        if wickets is not None:
            parts.append("bowling {:.2f} wickets per recent appearance".format(wickets))
        if economy is not None:
            parts.append("economy {:.2f}".format(economy))
    if "wicket" in role_text:
        stumpings = features.get("form_keeper_stumpings_per_match")
        if stumpings is not None:
            parts.append("{:.2f} stumpings per recent appearance".format(stumpings))
    trend = features.get("form_recent_trend")
    if trend is not None:
        parts.append("recent trend {}".format("up" if trend > 0 else "down" if trend < 0 else "steady"))
    return "; ".join(parts) if parts else "Insufficient role-specific performance data"
