# CPI Cricket Rules Reference
## Cricket Performance Intelligence

**Document:** `docs/cricket-rules.md`  
**Version:** 1.0  
**Companion:** `docs/data-dictionary.md`

---

## 1. Legal Ball Definition

A delivery is **legal** if and only if neither `wides` nor `noballs` appears in the delivery's `extras` object.

```python
def is_legal_delivery(extras: dict) -> bool:
    """
    Returns True if the delivery is a legal ball.
    Wides and no-balls are not legal deliveries.
    Byes, leg-byes and penalties on otherwise-legal deliveries do not change legality.
    """
    return "wides" not in extras and "noballs" not in extras
```

**Reference:** Standard scorecard conventions, MCC Laws of Cricket.

---

## 2. Balls Faced (Batting)

A batter's **balls faced** count is the number of deliveries where:
- The batter is the facing batter (`delivery.batter == player_name`)
- AND the delivery is **not** a wide (i.e., `wides` NOT in extras)

> No-balls **do** count as balls faced. Wides do **not** count as balls faced.

```
balls_faced = count(deliveries where batter == player AND "wides" not in extras)
```

---

## 3. Batting Average

```
batting_average = total_batter_runs / times_dismissed
```

- **Numerator:** Sum of `delivery.runs.batter` for all deliveries where `batter == player`.
- **Denominator:** Count of innings where the batter was **dismissed** (see Section 7 for dismissal rules).
- **Not-out handling:** If denominator is 0 (all innings are not-outs), batting average is undefined (`null`).

---

## 4. Batting Strike Rate

```
strike_rate = (batter_runs / balls_faced) × 100
```

- If `balls_faced == 0`, strike rate is `null`.

---

## 5. Boundary Counts

A boundary event is determined by the **batter's runs** on the delivery:
- **Four:** `delivery.runs.batter == 4`
- **Six:** `delivery.runs.batter == 6`

> Do **not** use `delivery.runs.total == 4` or `6` — total includes extras which may coincidentally sum to 4.

---

## 6. Dot Ball (Batting)

A dot ball for the batter is a legal delivery where `delivery.runs.batter == 0`.

```
dot_ball_percentage = (dot_deliveries / balls_faced) × 100
```

Where `dot_deliveries` = legal balls where batter scored 0 runs.

---

## 7. Dismissal Types and Batting Average

| Kind                  | Counts as Dismissed? | Notes                               |
|-----------------------|----------------------|-------------------------------------|
| `bowled`              | ✅ Yes               |                                     |
| `caught`              | ✅ Yes               |                                     |
| `caught and bowled`   | ✅ Yes               |                                     |
| `lbw`                 | ✅ Yes               |                                     |
| `stumped`             | ✅ Yes               |                                     |
| `hit wicket`          | ✅ Yes               |                                     |
| `run out`             | ✅ Yes               | Dismissed, but no bowler credit.    |
| `obstructing the field` | ✅ Yes             | Unusual.                            |
| `retired out`         | ✅ Yes               | Counts as dismissed for average.    |
| `retired hurt`        | ❌ No                | Not a dismissal.                    |

---

## 8. Bowling Runs Conceded

```
bowling_runs_conceded = batter_runs + wides_runs + noballs_runs
```

- **Include:** `delivery.runs.batter`, any `extras.wides`, any `extras.noballs`.
- **Exclude:** `extras.byes`, `extras.legbyes`, `extras.penalty`.

> Byes and leg-byes go against the extras total but are **not** charged to the bowler.

---

## 9. Bowling Legal Balls and Overs

```
legal_balls = count(deliveries where bowler == player AND is_legal_delivery)
overs_display = f"{legal_balls // 6}.{legal_balls % 6}"
```

> **Never** store overs as a decimal (e.g., 4.3 meaning 4 overs and 3 balls). Store as `legal_balls` integer and format for display only.

---

## 10. Economy Rate

```
economy_rate = (bowling_runs_conceded / legal_balls) × 6
```

- If `legal_balls == 0`, economy rate is `null`.

---

## 11. Bowling Average

```
bowling_average = bowling_runs_conceded / bowler_wickets
```

- If `bowler_wickets == 0`, bowling average is `null`.

---

## 12. Bowling Strike Rate

```
bowling_strike_rate = legal_balls / bowler_wickets
```

- If `bowler_wickets == 0`, bowling strike rate is `null`.

---

## 13. Bowler Wicket Credit

A bowler receives wicket credit **only** for:

| Dismissal Kind        | Credit? |
|-----------------------|---------|
| `bowled`              | ✅      |
| `caught`              | ✅      |
| `caught and bowled`   | ✅      |
| `lbw`                 | ✅      |
| `stumped`             | ✅      |
| `hit wicket`          | ✅      |
| `run out`             | ❌      |
| `obstructing the field` | ❌    |
| `retired hurt`        | ❌      |
| `retired out`         | ❌      |

---

## 14. Phase Assignment (T20)

Phases are determined by the zero-based `over` integer from each over object:

| Phase    | Over indices (0-based) | Over numbers (display) |
|----------|------------------------|------------------------|
| Powerplay| 0 – 5                  | 1 – 6                  |
| Middle   | 6 – 14                 | 7 – 15                 |
| Death    | 15 – 19                | 16 – 20                |

> **Super overs** are excluded from phase calculations.  
> **Shortened innings:** Phases are still assigned by over index, not by total overs. A match reduced to 10 overs has overs 0–5 as powerplay and 6–9 as middle (no death phase).

---

## 15. Extras Classification

| Extra Type | Legal Ball? | Balls Faced? | Bowling Runs? | Notes            |
|------------|-------------|--------------|---------------|------------------|
| `wides`    | ❌ No       | No           | Yes           | Re-bowled        |
| `noballs`  | ❌ No       | Yes          | Yes           | Free hit follows |
| `byes`     | ✅ Yes      | Yes          | No            | Missed by keeper |
| `legbyes`  | ✅ Yes      | Yes          | No            | Off pads         |
| `penalty`  | ✅ Yes      | Yes          | Situational   | Rare             |

---

## 16. Known Edge Cases

### Wide + Byes on Same Delivery
Both `wides` and `byes` can appear together. The wide makes it non-legal. Byes portion goes to extras (not bowling runs). Wide portion is bowling runs.

### No-ball + Batter Scores Runs
Both `extras.noballs = 1` and `runs.batter > 0` can be present. Not a legal ball. All batter runs count toward batter's total. No-ball run counts toward bowling runs conceded.

### Run-out Off a Wide
A batter can be run out on a wide delivery. The delivery is not legal. The dismissal is `run out` — no bowler credit. The batter is dismissed for average purposes.

### Multiple Wickets on One Delivery
`wickets` array can have length > 1. Each wicket event must be processed independently. This is rare but valid (e.g., obstructing the field + run out).

### Super Over
Innings with `super_over: true` are excluded from all standard aggregates (batting, bowling, phase, etc.). Super overs should be tracked separately and surfaced only when explicitly requested.

### Absent Hurt
Players listed in `innings.absent_hurt` did not bat. They should not appear in batting statistics for that innings. This is distinct from a not-out — they simply did not bat.

### Impact Player (IPL)
Deliveries may contain `replacements.match` with `reason: "impact_player"`. This is an IPL-specific rule allowing a player substitution at a defined point. The replacement player statistics count normally. The substituted player's statistics up to that point count normally.

### Retired Hurt vs. Retired Out
- `retired hurt`: Not dismissed. Does not count toward dismissal tally. Can return to bat.
- `retired out`: Dismissed. Counts toward batting average denominator.

---

## 17. Validation Checks

The ingestion pipeline must validate:

1. `runs.batter + runs.extras == runs.total` for every delivery.
2. Sum of innings total runs == sum of all delivery `runs.total`.
3. No duplicate delivery keys within an innings.
4. Player names in deliveries resolve to registry IDs.
5. Each over's `over` field is sequential and unique within the innings.
6. `wickets[i].player_out` matches a batter in the registry.

