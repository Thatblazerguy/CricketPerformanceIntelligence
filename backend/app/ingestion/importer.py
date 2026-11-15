"""
Ingestion Importer
Converts a CanonicalMatch into database records with full idempotency.
Uses upsert logic so running the same file twice is safe.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session
from sqlalchemy import select

from app.domain.entities import (
    CanonicalMatch,
    CanonicalInnings,
    CanonicalDelivery,
    CanonicalWicket,
    CanonicalExtra,
)
from app.models.models import (
    Provider,
    Tournament,
    Team,
    TeamAlias,
    Player,
    PlayerAlias,
    PlayerAttribute,
    Venue,
    VenueAlias,
    Match,
    MatchInnings,
    Delivery,
    DeliveryExtra,
    Wicket,
    RawMatch,
)

logger = logging.getLogger(__name__)


class MatchImporter:
    """
    Imports a single CanonicalMatch into the database.

    Idempotency:
    - Checks for existing match by (provider_id, source_match_id).
    - If checksum unchanged, skips.
    - If checksum changed (revised source), replaces innings/delivery data.
    - Players, teams, venues are upserted by name/source ID.
    """

    def __init__(self, db: Session):
        self.db = db
        self._player_cache: dict = {}   # source_id -> internal player_id
        self._team_cache: dict = {}     # name -> internal team_id
        self._venue_cache: dict = {}    # name -> internal venue_id

    def import_match(self, match: CanonicalMatch, force: bool = False) -> str:
        """
        Import a canonical match. Returns 'inserted', 'updated', or 'skipped'.
        """
        provider = self._get_or_create_provider(match.provider_name)
        raw_match, is_new = self._upsert_raw_match(match, provider.id)

        if not is_new:
            if raw_match.checksum == match.checksum and not force:
                logger.debug("Skipping %s (checksum unchanged)", match.source_match_id)
                return "skipped"
            else:
                logger.info(
                    "Checksum changed for %s — reprocessing", match.source_match_id
                )
                raw_match.checksum = match.checksum
                raw_match.source_revision = match.source_revision
                raw_match.retrieved_at = datetime.utcnow()

        # Resolve references
        tournament_id = self._get_or_create_tournament(match, provider.id)
        venue_id = self._get_or_create_venue(match)
        team_ids = {t: self._get_or_create_team(t, provider.id) for t in match.teams}
        self._upsert_players_from_registry(match.registry, provider.id)

        # Upsert the match record
        db_match, created = self._upsert_match(match, provider.id, tournament_id, venue_id, team_ids)

        if not created:
            # Delete existing innings/deliveries so we can re-insert cleanly
            self._delete_innings_and_deliveries(db_match.id)

        # Insert innings and deliveries
        for inn in match.innings:
            self._insert_innings(inn, db_match.id, team_ids, match.registry)

        self.db.flush()
        # Populate nationality only from a player's represented team in international formats.
        # The hook is scoped to this match, so importing domestic/franchise data adds no inference cost.
        from app.services.nationality import record_match_nationalities
        record_match_nationalities(self.db, db_match.id)
        return "inserted" if created else "updated"

    # ------------------------------------------------------------------ #
    #  Provider                                                            #
    # ------------------------------------------------------------------ #

    def _get_or_create_provider(self, name: str) -> Provider:
        p = self.db.execute(
            select(Provider).where(Provider.name == name)
        ).scalar_one_or_none()
        if not p:
            p = Provider(name=name)
            self.db.add(p)
            self.db.flush()
        return p

    # ------------------------------------------------------------------ #
    #  Raw Match                                                           #
    # ------------------------------------------------------------------ #

    def _upsert_raw_match(self, match: CanonicalMatch, provider_id: str):
        existing = self.db.execute(
            select(RawMatch).where(
                RawMatch.provider_id == provider_id,
                RawMatch.source_match_id == match.source_match_id,
            )
        ).scalar_one_or_none()

        if existing:
            return existing, False

        raw = RawMatch(
            provider_id=provider_id,
            source_match_id=match.source_match_id,
            source_file_name=match.source_file_name,
            checksum=match.checksum,
            source_revision=match.source_revision,
        )
        self.db.add(raw)
        self.db.flush()
        return raw, True

    # ------------------------------------------------------------------ #
    #  Tournament                                                          #
    # ------------------------------------------------------------------ #

    def _get_or_create_tournament(
        self, match: CanonicalMatch, provider_id: str
    ) -> Optional[str]:
        if not match.competition_name:
            return None

        existing = self.db.execute(
            select(Tournament).where(
                Tournament.provider_id == provider_id,
                Tournament.name == match.competition_name,
            )
        ).scalar_one_or_none()

        if existing:
            return existing.id

        t = Tournament(
            provider_id=provider_id,
            name=match.competition_name,
            format=match.match_format.value if match.match_format else None,
            gender=match.gender.value if match.gender else None,
        )
        self.db.add(t)
        self.db.flush()
        return t.id

    # ------------------------------------------------------------------ #
    #  Venue                                                               #
    # ------------------------------------------------------------------ #

    def _get_or_create_venue(self, match: CanonicalMatch) -> Optional[str]:
        name = match.venue_name
        if not name:
            return None
        if name in self._venue_cache:
            return self._venue_cache[name]

        if match.venue_source_id:
            by_registry_id = self.db.execute(
                select(Venue).where(Venue.source_venue_id == match.venue_source_id)
            ).scalars().first()
            if by_registry_id:
                self._venue_cache[name] = by_registry_id.id
                if name.casefold() != by_registry_id.canonical_name.casefold():
                    alias_exists = self.db.execute(select(VenueAlias.id).where(
                        VenueAlias.source_venue_id == match.venue_source_id,
                        VenueAlias.source_name == name,
                    )).first()
                    if not alias_exists:
                        self.db.add(VenueAlias(venue_id=by_registry_id.id, source_venue_id=match.venue_source_id, source_name=name))
                return by_registry_id.id

        existing = self.db.execute(
            select(Venue).where(Venue.name == name)
        ).scalar_one_or_none()

        if existing:
            self._venue_cache[name] = existing.id
            return existing.id

        v = Venue(
            name=name,
            canonical_name=name,
            source_venue_id=match.venue_source_id,
            city=match.city,
        )
        self.db.add(v)
        self.db.flush()
        self._venue_cache[name] = v.id
        return v.id

    # ------------------------------------------------------------------ #
    #  Teams                                                               #
    # ------------------------------------------------------------------ #

    def _get_or_create_team(self, name: str, provider_id: str) -> str:
        if name in self._team_cache:
            return self._team_cache[name]

        existing = self.db.execute(
            select(Team).where(Team.name == name)
        ).scalar_one_or_none()

        if existing:
            self._team_cache[name] = existing.id
            return existing.id

        t = Team(name=name, canonical_name=name)
        self.db.add(t)
        self.db.flush()
        self._team_cache[name] = t.id
        return t.id

    # ------------------------------------------------------------------ #
    #  Players                                                             #
    # ------------------------------------------------------------------ #

    def _upsert_players_from_registry(self, registry: dict, provider_id: str):
        """
        Ensure every player in the registry has a canonical Player record
        with a PlayerAlias linking their Cricsheet source ID.
        """
        affected_ids = set()
        for name, source_id in registry.items():
            if source_id in self._player_cache:
                affected_ids.add(self._player_cache[source_id])
                continue

            # Look up by source ID first (most reliable)
            alias = self.db.execute(
                select(PlayerAlias).where(
                    PlayerAlias.provider_id == provider_id,
                    PlayerAlias.source_player_id == source_id,
                )
            ).scalar_one_or_none()

            if alias:
                self._player_cache[source_id] = alias.player_id
                affected_ids.add(alias.player_id)
                continue

            # Check if canonical player already exists by name
            player = self.db.execute(
                select(Player).where(Player.canonical_name == name)
            ).scalars().first()

            if not player:
                player = Player(canonical_name=name)
                self.db.add(player)
                self.db.flush()

            alias = PlayerAlias(
                player_id=player.id,
                provider_id=provider_id,
                source_player_id=source_id,
                source_name=name,
            )
            self.db.add(alias)
            self.db.flush()
            self._player_cache[source_id] = player.id
            affected_ids.add(player.id)

        # New/imported players without known nationality are explicitly reviewable.
        # International match evidence is applied after innings are inserted.
        if affected_ids:
            has_nationality = set(self.db.execute(select(PlayerAttribute.player_id).where(
                PlayerAttribute.player_id.in_(affected_ids),
                PlayerAttribute.attribute_type == "nationality",
            )).scalars().all())
            for player_id in affected_ids - has_nationality:
                self.db.add(PlayerAttribute(player_id=player_id, attribute_type="nationality",
                    attribute_value="Unknown", source="nationality_review_required", confidence="low"))
            self.db.flush()

    def _resolve_player_id(self, source_id: Optional[str]) -> Optional[str]:
        if not source_id:
            return None
        return self._player_cache.get(source_id)

    # ------------------------------------------------------------------ #
    #  Match                                                               #
    # ------------------------------------------------------------------ #

    def _upsert_match(
        self,
        match: CanonicalMatch,
        provider_id: str,
        tournament_id: Optional[str],
        venue_id: Optional[str],
        team_ids: dict,
    ):
        teams = match.teams
        team1_id = team_ids.get(teams[0]) if len(teams) > 0 else None
        team2_id = team_ids.get(teams[1]) if len(teams) > 1 else None
        toss_winner_id = team_ids.get(match.toss_winner)
        winner_id = team_ids.get(match.winner) if match.winner else None

        existing = self.db.execute(
            select(Match).where(
                Match.provider_id == provider_id,
                Match.source_match_id == match.source_match_id,
            )
        ).scalar_one_or_none()

        if existing:
            existing.tournament_id = tournament_id
            existing.venue_id = venue_id
            existing.start_date = match.start_date
            existing.gender = match.gender.value
            existing.match_format = match.match_format.value
            existing.season = match.season
            existing.team1_id = team1_id
            existing.team2_id = team2_id
            existing.toss_winner_id = toss_winner_id
            existing.toss_decision = match.toss_decision.value if match.toss_decision else None
            existing.raw_source_checksum = match.checksum
            existing.source_revision = match.source_revision
            existing.winner_id = winner_id
            existing.result_type = match.result_type.value if match.result_type else None
            existing.result_margin_runs = match.result_margin_runs
            existing.result_margin_wickets = match.result_margin_wickets
            existing.source_data_version = match.data_version
            self.db.flush()
            return existing, False

        db_match = Match(
            provider_id=provider_id,
            source_match_id=match.source_match_id,
            tournament_id=tournament_id,
            venue_id=venue_id,
            start_date=match.start_date,
            gender=match.gender.value,
            match_format=match.match_format.value,
            season=match.season,
            team1_id=team1_id,
            team2_id=team2_id,
            toss_winner_id=toss_winner_id,
            toss_decision=match.toss_decision.value if match.toss_decision else None,
            winner_id=winner_id,
            result_type=match.result_type.value if match.result_type else None,
            result_margin_runs=match.result_margin_runs,
            result_margin_wickets=match.result_margin_wickets,
            raw_source_checksum=match.checksum,
            source_revision=match.source_revision,
            source_data_version=match.data_version,
        )
        self.db.add(db_match)
        self.db.flush()
        return db_match, True

    # ------------------------------------------------------------------ #
    #  Innings and Deliveries                                              #
    # ------------------------------------------------------------------ #

    def _delete_innings_and_deliveries(self, match_id: str):
        """Delete all innings and child records for a match (for reprocessing)."""
        from sqlalchemy import delete as sql_delete
        innings_ids = [
            row[0] for row in self.db.execute(
                select(MatchInnings.id).where(MatchInnings.match_id == match_id)
            ).fetchall()
        ]
        if not innings_ids:
            return

        delivery_ids = [
            row[0] for row in self.db.execute(
                select(Delivery.id).where(Delivery.innings_id.in_(innings_ids))
            ).fetchall()
        ]

        if delivery_ids:
            self.db.execute(sql_delete(DeliveryExtra).where(DeliveryExtra.delivery_id.in_(delivery_ids)))
            self.db.execute(sql_delete(Wicket).where(Wicket.delivery_id.in_(delivery_ids)))
            self.db.execute(sql_delete(Delivery).where(Delivery.id.in_(delivery_ids)))

        self.db.execute(sql_delete(MatchInnings).where(MatchInnings.id.in_(innings_ids)))
        self.db.flush()

    def _insert_innings(
        self,
        inn: CanonicalInnings,
        match_id: str,
        team_ids: dict,
        registry: dict,
    ):
        batting_team_id = team_ids.get(inn.batting_team)
        db_innings = MatchInnings(
            match_id=match_id,
            innings_number=inn.innings_number,
            batting_team_id=batting_team_id,
            target_runs=inn.target_runs,
            target_overs=inn.target_overs,
            is_super_over=inn.is_super_over,
        )
        self.db.add(db_innings)
        self.db.flush()

        for dl in inn.deliveries:
            self._insert_delivery(dl, db_innings.id)

    def _insert_delivery(self, dl: CanonicalDelivery, innings_id: str):
        batter_id = self._resolve_player_id(dl.batter_source_id)
        bowler_id = self._resolve_player_id(dl.bowler_source_id)
        non_striker_id = self._resolve_player_id(dl.non_striker_source_id)

        db_dl = Delivery(
            innings_id=innings_id,
            over_number=dl.over_number,
            delivery_sequence=dl.delivery_sequence,
            source_delivery_label=dl.source_delivery_label,
            batter_id=batter_id,
            bowler_id=bowler_id,
            non_striker_id=non_striker_id,
            batter_runs=dl.batter_runs,
            extras_runs=dl.extras_runs,
            total_runs=dl.total_runs,
            bowling_runs=dl.bowling_runs,
            is_legal_ball=dl.is_legal_ball,
            is_ball_faced_by_batter=dl.is_ball_faced_by_batter,
            is_boundary_four=dl.is_boundary_four,
            is_boundary_six=dl.is_boundary_six,
            phase=dl.phase.value,
            has_replacement=dl.has_replacement,
        )
        self.db.add(db_dl)
        self.db.flush()

        for extra in dl.extras:
            self.db.add(DeliveryExtra(
                delivery_id=db_dl.id,
                extra_type=extra.extra_type,
                runs=extra.runs,
            ))

        for wk in dl.wickets:
            player_out_id = self._resolve_player_id(wk.player_out_source_id)
            fielder_id = self._resolve_player_id(wk.fielder_source_id)
            self.db.add(Wicket(
                delivery_id=db_dl.id,
                player_out_id=player_out_id,
                dismissal_type=wk.kind,
                is_bowler_wicket=wk.is_bowler_wicket,
                is_batter_dismissed=wk.is_batter_dismissed,
                fielder_id=fielder_id,
            ))

        self.db.flush()
