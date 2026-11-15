"""CSV adapters for CPI auction player pools and historical outcome files."""
import csv
from functools import lru_cache
import hashlib
import io
import math
import re
from pathlib import Path
from decimal import Decimal, InvalidOperation

MAX_BYTES = 10 * 1024 * 1024
MAX_ROWS = 10000


def _key(value):
    return re.sub(r"[^a-z0-9]", "", str(value or "").lower())


def _first(row, *names):
    for name in names:
        value = row.get(_key(name))
        if value is not None and str(value).strip() != "":
            return str(value).strip()
    return None


def _decimal(value):
    if value is None:
        return None
    cleaned = re.sub(r"[₹,$\s]", "", str(value)).replace(",", "")
    if cleaned.lower() in ("nan", "none", "null", "-"):
        return None
    try:
        number = Decimal(cleaned)
        return number if number.is_finite() else None
    except InvalidOperation:
        return None


def read_csv_rows(filename, content):
    if len(content) > MAX_BYTES:
        raise ValueError("CSV file exceeds the 10 MB upload limit")
    if not filename.lower().endswith(".csv"):
        raise ValueError("Upload a .csv file")
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise ValueError("CSV must be encoded as UTF-8")
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        raise ValueError("CSV needs a header row")
    if len(reader.fieldnames) > 100:
        raise ValueError("CSV has too many columns")
    rows = []
    for line_number, source in enumerate(reader, 2):
        if len(rows) >= MAX_ROWS:
            raise ValueError(f"CSV exceeds the {MAX_ROWS:,} row limit")
        rows.append((line_number, {_key(k): v for k, v in source.items() if k is not None}))
    return rows


def history_row(source, line_number, row):
    name = _first(row, "player_name", "player", "name", "cricketer")
    year_raw = _first(row, "auction_year", "year", "season")
    team = _first(row, "franchise_name", "team", "franchise", "buyer")
    role = _first(row, "role", "primary_role", "player_role")
    origin = _first(row, "nationality", "player_origin", "origin", "nationality_status")
    status = (_first(row, "status", "sold_status") or "SOLD").upper()
    acquisition = (_first(row, "acquisition_type", "acquisition", "type") or "auction").lower()
    source_player_id = _first(row, "source_player_id", "player_id")

    errors = []
    try:
        year = int(year_raw) if year_raw else 0
        if year < 2000 or year > 2100:
            errors.append("year is missing or outside 2000–2100")
    except ValueError:
        year = 0
        errors.append("year is not an integer")
    if not name:
        errors.append("player name is required")
    if status not in ("SOLD", "UNSOLD", "RETAINED"):
        errors.append("status must be SOLD, UNSOLD, or RETAINED")
    if acquisition not in ("auction", "retained", "retention", "rtm"):
        acquisition = "auction"
    if status == "RETAINED":
        acquisition = "retained"

    # Canonical source format is INR lakh. The 2013–2022 source stores INR and
    # crore; prefer Amount_Cr, then convert Amount (rupees) to lakh.
    final_lakh = _decimal(_first(row, "final_price_lakh", "price_lakh", "sold_price_lakh"))
    amount_cr = _decimal(_first(row, "amount_cr", "price_cr", "final_price_cr"))
    amount_rupees = _decimal(_first(row, "amount", "price", "sold_price"))
    if final_lakh is None and amount_cr is not None:
        final_lakh = amount_cr * 100
    if final_lakh is None and amount_rupees is not None:
        final_lakh = amount_rupees / 100000

    base_lakh = _decimal(_first(row, "base_price_lakh", "base_lakh"))
    base_cr = _decimal(_first(row, "base_price_cr", "base_cr"))
    if base_lakh is None and base_cr is not None:
        base_lakh = base_cr * 100
    if status == "SOLD" and (final_lakh is None or final_lakh <= 0):
        errors.append("sold record needs a positive final price")
    if status == "UNSOLD":
        final_lakh = None
    if final_lakh is not None and final_lakh < 0:
        errors.append("final price cannot be negative")

    nationality = origin
    if origin and origin.lower() in ("overseas", "international", "foreign"):
        nationality = "Overseas"
    elif origin and origin.lower() in ("indian", "domestic"):
        nationality = "Indian"

    normalized_name = re.sub(r"\s+", " ", name or "").strip().casefold()
    normalized_team = re.sub(r"\s+", " ", team or "").strip().casefold()
    key_values = "|".join((str(year), normalized_name, normalized_team, acquisition, status,
                            str(final_lakh if final_lakh is not None else "")))
    record_key = hashlib.sha256(key_values.encode("utf-8")).hexdigest()
    return {
        "line": line_number, "source_player_name": name, "source_player_id": source_player_id,
        "auction_year": year, "franchise_name": team, "role": role, "nationality": nationality,
        "base_price_lakh": base_lakh, "final_price_lakh": final_lakh, "status": status,
        "acquisition_type": acquisition, "source_name": source, "source_record_key": record_key,
    }, errors


def pool_row(line_number, row):
    from app.api.routes.auction import PoolRow
    name = _first(row, "player_name", "player", "name", "canonical_name")
    player_id = _first(row, "player_id", "cpi_player_id")
    base_cr = _decimal(_first(row, "base_price", "base_price_cr"))
    base_lakh = _decimal(_first(row, "base_price_lakh"))
    base = base_cr if base_cr is not None else (base_lakh / 100 if base_lakh is not None else None)
    errors = []
    if not name and not player_id:
        errors.append("player name or CPI player ID is required")
    if base is None or base <= 0:
        errors.append("base price must be positive")
    if errors:
        return None, errors
    try:
        parsed = PoolRow(
            player_name=name, player_id=player_id, base_price=base,
            primary_role=_first(row, "primary_role", "role"),
            secondary_role=_first(row, "secondary_role"), nationality=_first(row, "nationality", "player_origin"),
            overseas_eligible=(_first(row, "overseas_eligible") or "").lower() in ("true", "1", "yes", "y")
                if _first(row, "overseas_eligible") is not None else None,
            wicketkeeper=(_first(row, "wicketkeeper", "is_wicketkeeper") or "").lower() in ("true", "1", "yes", "y")
                if _first(row, "wicketkeeper", "is_wicketkeeper") is not None else None,
            auction_category=_first(row, "auction_category", "set"),
            auction_order=int(_first(row, "auction_order", "order")) if _first(row, "auction_order", "order") else None,
        )
        return parsed, []
    except (ValueError, TypeError) as exc:
        return None, [str(exc)]


@lru_cache(maxsize=1)
def auction_registry():
    """Source P-IDs and aliases from the downloaded repository registry."""
    path = Path(__file__).resolve().parents[2] / "data" / "auction" / "sources" / "outside_edge_player_registry.csv"
    if not path.exists():
        return {}
    result = {}
    with path.open(newline="", encoding="utf-8-sig") as stream:
        for row in csv.DictReader(stream):
            player_id = str(row.get("player_id", "")).strip()
            names = [row.get("canonical_name", "")]
            names.extend(str(row.get("aliases", "")).split("|"))
            result[player_id] = [re.sub(r"\s+", " ", name).strip() for name in names if name and name.strip()]
    return result
