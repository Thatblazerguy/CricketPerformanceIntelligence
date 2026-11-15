#!/usr/bin/env python3
"""
scripts/make_sample_dataset.py
Extracts a diverse, representative sample of exactly 300 real Cricsheet matches
from local gamedata/ covering all formats (T20, T20I, ODI, ODM, Test, MDM)
and both men's and women's cricket, staying strictly under 25 MB.
"""
import json
import os
import shutil
import sys
from collections import defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
GAMEDATA_DIR = REPO_ROOT / "gamedata"
SAMPLE_DIR = REPO_ROOT / "data" / "sample"
SAMPLE_MATCHES_DIR = SAMPLE_DIR / "matches"

# Exact target quotas for 300 matches
TARGET_QUOTAS = {
    ("T20", "male"): 70,
    ("T20", "female"): 35,
    ("T20I", "male"): 60,
    ("T20I", "female"): 35,
    ("ODI", "male"): 35,
    ("ODI", "female"): 15,
    ("ODM", "male"): 15,
    ("ODM", "female"): 10,
    ("Test", "male"): 12,
    ("Test", "female"): 3,
    ("MDM", "male"): 10,
}

def determine_format(info: dict) -> str:
    raw_format = info.get("match_type", "")
    team_type = info.get("team_type", "").lower()
    if team_type == "international" and raw_format in ("T20", "IT20"):
        return "T20I"
    elif raw_format == "T20":
        return "T20"
    elif raw_format == "IT20":
        return "T20I"
    elif raw_format == "ODI":
        return "ODI"
    elif raw_format == "Test":
        return "Test"
    elif raw_format in ("ODM", "One Day"):
        return "ODM"
    elif raw_format in ("MDM", "Multi-day"):
        return "MDM"
    return raw_format

def make_sample():
    if not GAMEDATA_DIR.exists():
        print(f"Error: gamedata directory not found at {GAMEDATA_DIR}")
        sys.exit(1)

    SAMPLE_MATCHES_DIR.mkdir(parents=True, exist_ok=True)
    
    # Clean existing sample files if any
    for existing in SAMPLE_MATCHES_DIR.glob("*.json"):
        existing.unlink()

    counts = defaultdict(int)
    selected_files = []
    total_bytes = 0

    all_files = sorted(GAMEDATA_DIR.glob("*.json"))
    print(f"Scanning {len(all_files)} matches in {GAMEDATA_DIR}...")

    # We also sort files by size so for multi-day/test we pick clean compact matches
    for fpath in all_files:
        try:
            with open(fpath, "r", encoding="utf-8") as fp:
                data = json.load(fp)
            info = data.get("info", {})
            fmt = determine_format(info)
            gender = info.get("gender", "male").lower()
            key = (fmt, gender)

            target = TARGET_QUOTAS.get(key, 0)
            if counts[key] < target:
                file_size = fpath.stat().st_size
                # Guard against single oversized matches
                if fmt in ("Test", "MDM") and file_size > 500 * 1024:
                    continue
                if total_bytes + file_size < 24.5 * 1024 * 1024:
                    counts[key] += 1
                    total_bytes += file_size
                    selected_files.append((fpath, fmt, gender, file_size))
        except Exception:
            continue

        if all(counts[k] >= target for k, target in TARGET_QUOTAS.items()):
            break

    total_mb = total_bytes / (1024 * 1024)
    print(f"Selected {len(selected_files)} matches ({total_mb:.2f} MB):")
    for (fmt, gender), cnt in sorted(counts.items()):
        print(f"  - {fmt} ({gender}): {cnt} matches")

    if total_mb >= 25.0:
        print(f"Error: Total size {total_mb:.2f} MB exceeds 25 MB limit!")
        sys.exit(1)

    # Copy files
    for fpath, _, _, _ in selected_files:
        shutil.copy2(fpath, SAMPLE_MATCHES_DIR / fpath.name)

    # Write data/sample/README.md
    readme_path = SAMPLE_DIR / "README.md"
    readme_content = f"""# CPI Sample Dataset

A representative, lightweight sample of **{len(selected_files)} real Cricsheet match files** ({total_mb:.2f} MB uncompressed) for local development, fast onboarding, testing, and Docker evaluation without needing the full 11.7M delivery database.

## Composition Breakdown

| Format | Category | Gender | Matches |
|---|---|---|---:|
"""
    for (fmt, gender), cnt in sorted(counts.items()):
        cat_desc = "International" if "I" in fmt or fmt == "Test" else "Domestic / Franchise"
        readme_content += f"| {fmt} | {cat_desc} | {gender.capitalize()} | {cnt} |\n"

    readme_content += f"""| **Total** | | | **{len(selected_files)}** |

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
"""
    readme_path.write_text(readme_content, encoding="utf-8")
    print(f"Wrote {readme_path}")
    print("Sample dataset creation complete!")

if __name__ == "__main__":
    make_sample()
