"""Recompute persisted delivery phase labels from format-aware phase rules."""
from sqlalchemy import text
from app.db.session import engine


def main():
    sql = text("""
        UPDATE deliveries d SET phase = CASE
          WHEN i.is_super_over THEN 'super_over'
          WHEN m.match_format IN ('T20','T20I') AND d.over_number BETWEEN 0 AND 5 THEN 'powerplay'
          WHEN m.match_format IN ('T20','T20I') AND d.over_number BETWEEN 6 AND 14 THEN 'middle'
          WHEN m.match_format IN ('T20','T20I') AND d.over_number BETWEEN 15 AND 19 THEN 'death'
          WHEN m.match_format IN ('ODI','ODM') AND d.over_number BETWEEN 0 AND 9 THEN 'powerplay'
          WHEN m.match_format IN ('ODI','ODM') AND d.over_number BETWEEN 10 AND 39 THEN 'middle'
          WHEN m.match_format IN ('ODI','ODM') AND d.over_number BETWEEN 40 AND 49 THEN 'death'
          ELSE 'unknown' END
        FROM match_innings i JOIN matches m ON m.id=i.match_id
        WHERE d.innings_id=i.id AND d.phase IS DISTINCT FROM CASE
          WHEN i.is_super_over THEN 'super_over'
          WHEN m.match_format IN ('T20','T20I') AND d.over_number BETWEEN 0 AND 5 THEN 'powerplay'
          WHEN m.match_format IN ('T20','T20I') AND d.over_number BETWEEN 6 AND 14 THEN 'middle'
          WHEN m.match_format IN ('T20','T20I') AND d.over_number BETWEEN 15 AND 19 THEN 'death'
          WHEN m.match_format IN ('ODI','ODM') AND d.over_number BETWEEN 0 AND 9 THEN 'powerplay'
          WHEN m.match_format IN ('ODI','ODM') AND d.over_number BETWEEN 10 AND 39 THEN 'middle'
          WHEN m.match_format IN ('ODI','ODM') AND d.over_number BETWEEN 40 AND 49 THEN 'death'
          ELSE 'unknown' END
    """)
    with engine.begin() as conn:
        result = conn.execute(sql)
        print(f"Recomputed phase labels for {result.rowcount:,} deliveries")


if __name__ == "__main__": main()
