# Cricsheet JSON Data Dictionary
## CPI: Cricket Performance Intelligence

**Generated from:** Actual Cricsheet JSON files (IPL + Men's T20I)  
**Data version:** 1.3.0  
**Last updated:** 2026-11-06

---

## 1. File Structure

Each Cricsheet JSON file represents one match and has three top-level keys:

```
{
  "meta":    { data_version, created, revision },
  "info":    { match metadata },
  "innings": [ { innings data }, ... ]
}
```

---

## 2. `meta` Object

| Field          | Type   | Notes                                           |
|----------------|--------|-------------------------------------------------|
| `data_version` | string | Cricsheet schema version. Observed: `"1.3.0"`.  |
| `created`      | string | ISO date file was created by Cricsheet.         |
| `revision`     | int    | Increments when file is re-released/corrected.  |

> **Important:** `revision` and `created` together allow detection of updated source files. Store both for idempotent reprocessing.

---

## 3. `info` Object

| Field              | Type            | Required | Notes                                                              |
|--------------------|-----------------|----------|--------------------------------------------------------------------|
| `balls_per_over`   | int             | Yes      | Standard T20 = 6.                                                  |
| `city`             | string          | No       | City name, may be absent.                                          |
| `dates`            | array[string]   | Yes      | ISO dates. Multi-day matches have multiple entries.                |
| `event`            | object          | No       | Contains `name` (competition) and `match_number`.                  |
| `gender`           | string          | Yes      | `"male"` or `"female"`.                                            |
| `match_type`       | string          | Yes      | `"T20"`, `"ODI"`, `"Test"`, etc.                                   |
| `officials`        | object          | No       | Umpires, TV umpires, match referees, reserve umpires.              |
| `outcome`          | object          | Yes      | See Outcome section.                                               |
| `overs`            | int             | Yes      | Maximum overs per innings.                                         |
| `player_of_match`  | array[string]   | No       | Player names (not IDs).                                            |
| `players`          | object          | Yes      | `{team_name: [player_name, ...]}`. Names match `registry.people`. |
| `registry`         | object          | Yes      | `{people: {name: id}, venues: {name: id}}`.                        |
| `season`           | string/int      | Yes      | Season identifier. Can be `"2024"` or `"2020/21"`.                |
| `team_type`        | string          | Yes      | `"club"` (IPL) or `"international"` (T20I).                        |
| `teams`            | array[string]   | Yes      | Exactly two team names.                                            |
| `toss`             | object          | Yes      | `{winner: team_name, decision: "bat"/"field"}`.                    |
| `venue`            | string          | Yes      | Full venue name. Registry may contain venue ID.                    |

### `info.outcome` Object

| Field      | Type   | Notes                                                                       |
|------------|--------|-----------------------------------------------------------------------------|
| `winner`   | string | Team name. **Absent** if no winner (tie or no result).                      |
| `by`       | object | `{"runs": N}` or `{"wickets": N}`. Present only when there is a winner.    |
| `result`   | string | `"tie"` or `"no result"`. Present only when no winner.                      |

> **Handling:** Check for `outcome.winner` first. If absent, check `outcome.result`.

---

## 4. `innings` Array

Each element is one innings object.

| Field               | Type    | Required | Notes                                                              |
|---------------------|---------|----------|--------------------------------------------------------------------|
| `team`              | string  | Yes      | Batting team name.                                                 |
| `overs`             | array   | Yes      | Ordered list of over objects.                                      |
| `powerplays`        | array   | No       | Powerplay period definitions from source. Present in most matches. |
| `target`            | object  | No       | `{runs: N, overs: N}`. Present in second innings (and DLS).       |
| `super_over`        | bool    | No       | `true` when this innings is a super over.                          |
| `absent_hurt`       | array   | No       | Player names who are absent hurt (not available to bat).           |
| `miscounted_overs`  | object  | No       | Rare; flags scoring inconsistencies in the source.                 |

> **Phase assignment for T20:** Over index 0–5 = Powerplay, 6–14 = Middle, 15–19 = Death. Use `over` field (zero-based) from each over object.

---

## 5. Over Object

```json
{
  "over": 0,
  "deliveries": [ ... ]
}
```

| Field         | Type  | Notes                                                     |
|---------------|-------|-----------------------------------------------------------|
| `over`        | int   | Zero-based over number (0–19 for 20-over T20).            |
| `deliveries`  | array | All deliveries in this over, including wides and no-balls.|

> **Important:** An over can contain more than 6 deliveries because wides and no-balls are re-bowled. `over` is an integer, not a decimal.

---

## 6. Delivery Object

```json
{
  "actual_delivery": "0.1",
  "batter": "DA Warner",
  "bowler": "TS Mills",
  "non_striker": "S Dhawan",
  "runs": {"batter": 0, "extras": 0, "total": 0},
  "extras": {"wides": 1},
  "wickets": [...],
  "replacements": {...},
  "review": {...}
}
```

| Field              | Type   | Required | Notes                                                         |
|--------------------|--------|----------|---------------------------------------------------------------|
| `actual_delivery`  | string | Yes      | `"over.ball"` notation, e.g. `"0.1"`. Parse as string only.  |
| `batter`           | string | Yes      | Facing batter name.                                           |
| `bowler`           | string | Yes      | Bowling player name.                                          |
| `non_striker`      | string | Yes      | Non-striking batter name.                                     |
| `runs`             | object | Yes      | See Runs section.                                             |
| `extras`           | object | No       | Absent when no extras on this delivery.                       |
| `wickets`          | array  | No       | Absent when no dismissal. Can contain multiple wicket events. |
| `replacements`     | object | No       | Impact player substitutions (IPL rule).                       |
| `review`           | object | No       | DRS review information.                                       |

---

## 7. Runs Object

```json
{ "batter": 2, "extras": 0, "total": 2 }
```

| Field     | Type | Notes                                                         |
|-----------|------|---------------------------------------------------------------|
| `batter`  | int  | Runs credited to the batter off the bat.                      |
| `extras`  | int  | Total extras on this delivery (sum of all extra types).       |
| `total`   | int  | `batter + extras`. Validation: assert `batter + extras == total`. |

---

## 8. Extras Object

Absent when no extras. Present keys depend on what occurred.

| Key        | Type | Legal Ball? | Counted in Batter's Balls Faced? | Bowling Runs Conceded? |
|------------|------|-------------|----------------------------------|------------------------|
| `wides`    | int  | **No**      | No                               | Yes                    |
| `noballs`  | int  | **No**      | Yes (by convention)              | Yes                    |
| `byes`     | int  | Yes         | Yes                              | **No**                 |
| `legbyes`  | int  | Yes         | Yes                              | **No**                 |
| `penalty`  | int  | Yes         | Yes                              | Depends on context     |

> **Legal ball rule:** A delivery is **not** a legal ball if `extras` contains `wides` OR `noballs`. Byes and leg-byes on legal deliveries do not affect legality.

---

## 9. Wickets Array

Each element is one dismissal event. Multiple wickets on one delivery are possible (e.g. obstructing + run-out).

```json
[
  {
    "kind": "caught",
    "player_out": "DA Warner",
    "fielders": [{"name": "Mandeep Singh"}]
  }
]
```

| Field        | Type   | Notes                                     |
|--------------|--------|-------------------------------------------|
| `kind`       | string | Dismissal type. See table below.          |
| `player_out` | string | Name of the dismissed batter.             |
| `fielders`   | array  | Optional. `[{"name": "...", "substitute": bool}]`. |

### Dismissal Types and Bowler Credit

| Kind                  | Bowler Credited? | Notes                               |
|-----------------------|------------------|-------------------------------------|
| `bowled`              | ✅ Yes           |                                     |
| `caught`              | ✅ Yes           | Includes caught and bowled.         |
| `caught and bowled`   | ✅ Yes           |                                     |
| `lbw`                 | ✅ Yes           |                                     |
| `stumped`             | ✅ Yes           |                                     |
| `hit wicket`          | ✅ Yes           |                                     |
| `run out`             | ❌ No            | No bowler credit. Fielder credited. |
| `obstructing the field` | ❌ No          | Unusual. No bowler credit.          |
| `retired hurt`        | ❌ No            | Not a dismissal for average purposes.|
| `retired out`         | ✅ Yes (avg)     | Counts as a dismissal for batting average. |

> **Batting average denominator:** Count dismissals where batter is out (`kind != "retired hurt"`). Retired hurt is not a dismissal.

---

## 10. `registry.people`

Maps player **name** (as used in delivery records) to a stable Cricsheet **person ID** (8-character hex string).

```json
{
  "DA Warner": "dcce6f09",
  "MS Dhoni": "7d47e3c3"
}
```

> **Use these IDs as the canonical player identifier.** Names alone are insufficient — the same player may appear with slightly different names across matches. The registry ID is stable across matches.

---

## 11. Known Edge Cases

| Case                       | Handling Required                                                              |
|----------------------------|--------------------------------------------------------------------------------|
| Wide with runs             | `extras.wides` can be > 1 (e.g., 2 for a wide + overthrows). Not legal.       |
| No-ball with runs          | `extras.noballs = 1`, batter may also score runs. Not a legal ball.            |
| Byes on a wide             | Possible. Both `wides` and `byes` can appear together.                         |
| Multiple wickets           | `wickets` array may have length > 1.                                           |
| Run-out off a wide/no-ball | Wicket on a non-legal ball. Dismissed batter is out but no bowler credit.      |
| Super over                 | `innings.super_over = true`. Treat separately from main innings aggregates.    |
| Impact player (IPL)        | `replacements.match` with `reason: "impact_player"`. Affects playing XI.      |
| Absent hurt                | Player listed in `innings.absent_hurt` did not bat. Not a dismissal.           |
| `season` format            | Can be `2024` (int) or `"2020/21"` (string). Normalise to string.             |
| DRS review                 | `review` on delivery. Does not change run/wicket attribution.                  |
| Penalty runs               | `extras.penalty`. Rare. Attributed to batting team, not bowler's economy.      |
| Miscounted overs           | `innings.miscounted_overs`. Flag but do not block ingestion.                   |

---

## 12. Dataset Coverage

### IPL

| Season   | Matches |
|----------|---------|
| 2007/08  | 58      |
| 2009     | 57      |
| 2009/10  | 60      |
| 2011     | 73      |
| 2012     | 74      |
| 2013     | 76      |
| 2014     | 60      |
| 2015     | 59      |
| 2016     | 60      |
| 2017     | 59      |
| 2018     | 60      |
| 2019     | 60      |
| 2020/21  | 60      |
| 2021     | 60      |
| 2022     | 74      |
| 2023     | 74      |
| 2024     | 71      |
| 2025     | 74      |
| 2026     | 74      |
| **Total**| **1,243**|

- Total deliveries: **295,732**
- Total wickets: **14,705**
- Deliveries with extras: **16,227**
- Boundaries (4s): **34,447** | Boundaries (6s): **15,779**

### Men's T20I

- **5,851 match files** extracted from Cricsheet T20s archive.

---

## 13. Missing / Unavailable Attributes

| Attribute           | Available? | Notes                                           |
|---------------------|------------|-------------------------------------------------|
| Bowling style       | ❌ No      | Not in Cricsheet JSON. Must come from external source (OpenCricket or manual). |
| Batting hand        | ❌ No      | Not in Cricsheet JSON.                          |
| Nationality         | ❌ No      | Not in Cricsheet JSON.                          |
| Player age/DOB      | ❌ No      | Not in Cricsheet JSON.                          |
| Shot type/location  | ❌ No      | No wagon-wheel data.                            |
| Ball speed/swing    | ❌ No      | No ball-tracking data.                          |
| Player role (bat/bowl) | ❌ No   | Inferable from match data, not guaranteed.      |
| Player photo/bio    | ❌ No      | Not in Cricsheet JSON.                          |

> **Consequence:** Pace vs. spin analysis requires a separately sourced bowler-style mapping, stored with provenance and confidence in `player_attributes`.

---

## 14. Scoring Convention Decisions

These conventions are adopted for CPI and documented here:

1. **Legal ball:** A delivery is legal if and only if `extras` does not contain `wides` or `noballs`.
2. **Balls faced by batter:** Legal balls + no-balls faced. Wides are excluded.
3. **Bowling runs conceded:** `batter_runs + wides_runs + noballs_runs`. Byes and leg-byes are excluded.
4. **Bowler wicket credit:** Only for: bowled, caught, caught and bowled, lbw, stumped, hit wicket.
5. **Batting dismissal (for average):** All `kind` values except `retired hurt`. `retired out` counts as dismissed.
6. **Boundary event:** `batter_runs == 4` or `batter_runs == 6` on the delivery record. Not inferred from total runs.
7. **Phase (T20):** Over index (zero-based): Powerplay 0–5, Middle 6–14, Death 15–19.
8. **Super over:** Excluded from all standard aggregate statistics unless explicitly requested.
9. **Over number:** Integer (zero-based). Never treated as a decimal. `delivery_sequence` tracks position within the over.

