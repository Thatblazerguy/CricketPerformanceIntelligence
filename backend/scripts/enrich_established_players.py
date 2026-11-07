"""Seed verified BCCI profile attributes for the requested established players.

Only sourced identity attributes are stored here. Career statistics remain
derived from delivery data and are not written as biography attributes.
"""
from datetime import date

from sqlalchemy import select

from app.db.session import SessionLocal
from app.models.models import Player, PlayerAttribute

PLAYERS = {
    "6e87d54f-457f-47ca-ad58-98d9153ed2df": {
        "expected_name": "KL Rahul", "full_name": "KL Rahul", "date_of_birth": "1992-04-18",
        "nationality": "India", "primary_role": "Batter", "batting_style": "Right Handed",
        "bowling_style": "Right Arm Off Break",
        "source": "https://www.bcci.tv/players/b0c05c29-721f-4c87-aeba-ba5e3eba9c95/kl-rahul",
    },
    "5dbf3cbf-2274-4b20-8bad-896ec7a98f2d": {
        "expected_name": "Virat Kohli", "full_name": "Virat Kohli", "date_of_birth": "1988-11-05",
        "nationality": "India", "primary_role": "Batter", "batting_style": "Right Handed",
        "bowling_style": "Right Arm Medium",
        "source": "https://www.bcci.tv/players/3c2267a5-45fa-4fac-8a29-9b78947f5f6c/virat-kohli",
    },
    "7ff25fb0-2acd-4c07-8887-e6cd05268743": {
        "expected_name": "Rohit Sharma", "full_name": "Rohit Sharma", "date_of_birth": "1987-04-30",
        "nationality": "India", "primary_role": "Batter", "batting_style": "Right Handed",
        "bowling_style": "Right Arm Off Break",
        "source": "https://www.bcci.tv/players/b78c195f-b149-4136-9803-24209696c4c3/rohit-sharma",
    },
    "d186c9ea-da1d-444c-b541-cd73d719e0fa": {
        "expected_name": "MS Dhoni", "full_name": "Mahendra Singh Dhoni", "date_of_birth": "1981-07-07",
        "nationality": "India", "primary_role": "Wicketkeeper-Batter",
        "source": "https://www.bcci.tv/news/article/ms-dhoni-turns-30",
        "full_name_source": "https://www.bcci.tv/news/article/the-art-of-leadership-by-ms-dhoni",
    },
    "c66feec5-a197-47b1-b134-c69213d7cb77": {
        "expected_name": "Jasprit Bumrah", "full_name": "Jasprit Bumrah", "date_of_birth": "1993-12-06",
        "nationality": "India", "primary_role": "Bowler", "batting_style": "Right Handed",
        "bowling_style": "Right Arm Fast Medium",
        "source": "https://www.bcci.tv/players/352688d9-2f4c-4f66-a8fd-5538d4facaba/jasprit-bumrah",
    },
    "2eb82c43-4f30-4341-88b9-3edc1823dff0": {
        "expected_name": "Ravindra Jadeja", "full_name": "Ravindra Jadeja", "date_of_birth": "1988-12-06",
        "nationality": "India", "primary_role": "All Rounder", "batting_style": "Left Handed",
        "bowling_style": "Left Arm Orthodox",
        "source": "https://www.bcci.tv/players/b2e76c0b-166c-4d7c-97df-a1503726e55c/ravindra-jadeja",
    },
}


def main():
    db = SessionLocal()
    try:
        for player_id, data in PLAYERS.items():
            player = db.get(Player, player_id)
            if player is None or player.canonical_name not in {data["expected_name"], data["full_name"]}:
                raise RuntimeError(f"Stable identity check failed for {data['expected_name']}")
            if player_id.endswith("cd73d719e0fa"):
                player.canonical_name = data["full_name"]
            for attr_type, value in data.items():
                if attr_type in {"expected_name", "source", "full_name_source"}:
                    continue
                source = data.get("full_name_source") if attr_type == "full_name" and data.get("full_name_source") else data["source"]
                existing = db.execute(select(PlayerAttribute).where(
                    PlayerAttribute.player_id == player_id,
                    PlayerAttribute.attribute_type == attr_type,
                )).scalars().all()
                match = next((item for item in existing if item.source == source), None)
                if match:
                    match.attribute_value = value
                    match.confidence = "high"
                else:
                    db.add(PlayerAttribute(player_id=player_id, attribute_type=attr_type,
                                           attribute_value=value, source=source, confidence="high"))
            # Keep the canonical full name in the attribute table with its source.
            full_source = data.get("full_name_source", data["source"])
            full_attr = db.execute(select(PlayerAttribute).where(
                PlayerAttribute.player_id == player_id,
                PlayerAttribute.attribute_type == "full_name",
                PlayerAttribute.source == full_source,
            )).scalar_one_or_none()
            if full_attr is None:
                db.add(PlayerAttribute(player_id=player_id, attribute_type="full_name",
                                       attribute_value=data["full_name"], source=full_source, confidence="high"))
            else:
                full_attr.attribute_value = data["full_name"]
                full_attr.confidence = "high"
        db.commit()
        print(f"Enriched {len(PLAYERS)} players with sourced biography attributes; age remains dynamically calculated.")
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
