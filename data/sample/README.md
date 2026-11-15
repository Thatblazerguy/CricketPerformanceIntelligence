# CPI Sample Dataset

A representative, lightweight sample of **204 real Cricsheet match files** (24.50 MB uncompressed) for local development, fast onboarding, testing, and Docker evaluation without needing the full 11.7M delivery database.

## Composition Breakdown

| Format | Category | Gender | Matches |
|---|---|---|---:|
| MDM | Domestic / Franchise | Male | 6 |
| ODI | International | Female | 13 |
| ODI | International | Male | 35 |
| ODM | Domestic / Franchise | Female | 1 |
| ODM | Domestic / Franchise | Male | 11 |
| T20 | Domestic / Franchise | Female | 22 |
| T20 | Domestic / Franchise | Male | 70 |
| T20I | International | Female | 8 |
| T20I | International | Male | 33 |
| Test | International | Female | 0 |
| Test | International | Male | 5 |
| **Total** | | | **204** |

## Usage

This sample dataset is loaded automatically during Docker container initialization (`docker compose up`) or manually via:

```bash
cd backend
.venv/bin/python scripts/ingest_gamedata.py --data-dir ../data/sample/matches
```

To re-generate this sample from the full local `gamedata/` archive:
```bash
python3 scripts/make_sample_dataset.py
```

## Attribution & License

All match records in this sample are provided by [Cricsheet](https://cricsheet.org/) and licensed under the [Open Data Commons Open Database License (ODbL) 1.0](https://opendatacommons.org/licenses/odbl/1.0/).
See [data/ATTRIBUTION.md](../ATTRIBUTION.md) for full licensing terms.
