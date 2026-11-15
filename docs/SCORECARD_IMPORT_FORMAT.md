# Verified scorecard import format

CPI imports historical scorecards (matches without ball-by-ball data) as a JSON
bundle, through **Data Health → Ingestion → Import verified scorecards** or
`POST /api/v1/data-health/scorecards/import`.

Only import data you are licensed or permitted to use. CPI does not scrape
websites to produce bundles. A bundle without `source.licence` is rejected.

## Rules

* Leave unknown fields out (or `null`). CPI never fills them in. Balls faced,
  fours, sixes, maidens and minutes are commonly missing in old scorecards.
* Give player IDs whenever you have them, as `"<scheme>:<id>"`:
  `cricinfo:35320`, `cricketarchive:1933`, `bcci:…`, `cricsheet:d2c2b2d5`.
  Cricsheet's people register maps these schemes to CPI players. Without an
  ID, a name is accepted only if exactly one CPI player has it **and** has played
  for that team. Otherwise the row is kept but left unresolved, and it shows up in Data Health.
* `balls_per_over` is needed before overs are converted to balls (8-ball overs
  were used in Australia, New Zealand and South Africa at times). Without it,
  bowling economy and strike rate stay unavailable for that match.
* Each innings is checked for consistency: batting runs plus extras must equal
  the total, dismissals must equal wickets, and bowler runs plus byes and leg
  byes must equal the total. An innings that fails is stored but marked
  `inconsistent`, and it never counts towards career statistics.
* A match that CPI already holds (ball-by-ball or from another bundle) is linked
  to the existing canonical match, never duplicated. Values that disagree are
  flagged for reconciliation, and both values are kept.
* Re-importing a bundle with the same `source.key` and `source_match_id`
  replaces that source's scorecard for the match.

## Schema

```json
{
  "source": {
    "key": "cricketarchive_licensed",
    "name": "CricketArchive (licensed extract)",
    "licence": "Data licence agreement #1234, 2026",
    "url": "https://cricketarchive.com/"
  },
  "matches": [
    {
      "source_match_id": "12345",
      "start_date": "1990-08-09",
      "end_date": "1990-08-14",
      "gender": "male",
      "format_class": "TEST",
      "competition": "India tour of England",
      "season": "1990",
      "venue": "Old Trafford, Manchester",
      "country": "England",
      "teams": ["England", "India"],
      "balls_per_over": 6,
      "toss": {"winner": "England", "decision": "bat"},
      "result": {"type": "draw", "winner": null},
      "innings": [
        {
          "number": 1, "team": "England", "total": 519, "wickets": 10, "overs": "169.4",
          "declared": false,
          "extras": {"total": 19, "byes": 2, "leg_byes": 9, "wides": 0, "no_balls": 8, "penalty": 0},
          "batting": [
            {"name": "GA Gooch", "id": "cricinfo:13399", "position": 1, "runs": 116, "balls": null,
             "fours": 15, "sixes": null, "dismissal": "caught", "how_out": "c X b Y"},
            {"name": "Twelfth Player", "dnb": true}
          ],
          "bowling": [
            {"name": "Kapil Dev", "id": "cricinfo:30028", "overs": "13", "maidens": 2, "runs": 67, "wickets": 0}
          ]
        }
      ]
    }
  ]
}
```

The values in this example only show the shape of the format. They are not reference data.

| Field | Values |
|---|---|
| `format_class` | `TEST`, `ODI`, `T20I`, `FIRST_CLASS`, `LIST_A`, `T20_DOMESTIC`, `MULTI_DAY`, `ONE_DAY` |
| `result.type` | `win`, `draw`, `tie`, `no result` |
| `dismissal` | e.g. `caught`, `bowled`, `lbw`, `run out`, `stumped`, `not out`, `retired hurt`, `retired out` (or give `"out": true/false`) |
