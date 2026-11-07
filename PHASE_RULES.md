# Format-aware phase rules

Ingestion and the one-time database recalculation use the same format boundaries. `over_number` is zero-indexed in storage.

| Format | Powerplay | Middle | Death |
|---|---|---|---|
| T20, T20I | 0–5 (overs 1–6) | 6–14 (7–15) | 15–19 (16–20) |
| ODI, ODM | 0–9 (1–10) | 10–39 (11–40) | 40–49 (41–50) |
| Test, MDM, Other | Not applicable | Not applicable | Not applicable |

Super overs are labeled separately as `super_over`. Overs outside the limited-overs phase table and non-limited formats receive `unknown`; Test and multi-day records are not given T20 powerplay labels. The Cricsheet feed does not consistently give a revised maximum innings length for every shortened first innings, so these boundaries retain standard ODI/T20 over ranges and only label overs that actually have deliveries. Session metadata is not available in this source; innings-progression bands are not presented as sessions.

The differential phase recalculation has been applied to the imported database: **3,432,250** rows changed; unchanged rows were skipped. Validation confirmed that all Test and MDM deliveries are `unknown`, and ODI/ODM/T20/T20I have the documented phase labels. Phase dependent API results read the persisted `deliveries.phase` value. Run `PYTHONPATH=backend backend/.venv/bin/python backend/scripts/recalculate_delivery_phases.py` after a future full reimport or if raw phase fields are reset.
