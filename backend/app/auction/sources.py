"""Deterministic parsers that turn raw auction sources into one normalized schema.

Every parser returns plain dict rows with the columns in ``NORMALIZED_COLUMNS``.
Nothing is inferred here: a field that a source does not carry is ``None``.

Sources handled
---------------
* Wikipedia "List of <season> Indian Premier League personnel changes" pages,
  stored as the MediaWiki parse API JSON (wikitext + revision id) so the exact
  revision used is reproducible. Sold-player tables carry set, lot number,
  base price, sale price, RTM marker and previous franchise; retention tables
  carry retention salaries; the 2024 page also carries purse remaining.
* Official IPL auction list copies redistributed via outside-edge/ipl_auction
  (Kaggle mirrors): the 2022 full list (sold and unsold, reserve prices, sets)
  and the 2023 player pool / sold list.
"""
from __future__ import annotations

import csv
import json
import re
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

NORMALIZED_COLUMNS = [
    "season", "player_name", "country", "role", "bowling_style", "capped_status",
    "set_code", "lot_number", "base_price_lakh", "final_price_lakh", "status",
    "acquisition_type", "franchise", "previous_franchise", "is_rtm",
    "ipl_matches_before", "age_at_auction", "date_of_birth",
    "source_name", "source_url", "source_revision", "source_tier",
]

# Canonical franchise codes. Renamed franchises keep one code because the
# franchise (purse, retention rights, RTM rights) carried over.
FRANCHISE_CODES = {
    "chennai super kings": "CSK", "csk": "CSK",
    "mumbai indians": "MI", "mi": "MI",
    "kolkata knight riders": "KKR", "kkr": "KKR",
    "royal challengers bangalore": "RCB", "royal challengers bengaluru": "RCB", "rcb": "RCB",
    "rajasthan royals": "RR", "rr": "RR",
    "delhi capitals": "DC", "delhi daredevils": "DC", "dc": "DC", "dd": "DC",
    "sunrisers hyderabad": "SRH", "srh": "SRH",
    "punjab kings": "PBKS", "kings xi punjab": "PBKS", "pbks": "PBKS", "kxip": "PBKS",
    "gujarat titans": "GT", "gt": "GT",
    "lucknow super giants": "LSG", "lsg": "LSG",
    "deccan chargers": "DCH", "dch": "DCH", "dcp": "DCH",
    "kochi tuskers kerala": "KTK", "ktk": "KTK",
    "pune warriors india": "PWI", "pune warriors": "PWI", "pwi": "PWI",
    "rising pune supergiant": "RPS", "rising pune supergiants": "RPS", "rps": "RPS", "rpsg": "RPS",
    "gujarat lions": "GL", "gl": "GL",
}
FRANCHISE_NAMES = {
    "CSK": "Chennai Super Kings", "MI": "Mumbai Indians", "KKR": "Kolkata Knight Riders",
    "RCB": "Royal Challengers Bengaluru", "RR": "Rajasthan Royals", "DC": "Delhi Capitals",
    "SRH": "Sunrisers Hyderabad", "PBKS": "Punjab Kings", "GT": "Gujarat Titans",
    "LSG": "Lucknow Super Giants", "DCH": "Deccan Chargers", "KTK": "Kochi Tuskers Kerala",
    "PWI": "Pune Warriors India", "RPS": "Rising Pune Supergiant", "GL": "Gujarat Lions",
}

COUNTRY_CODES = {
    "IND": "India", "ENG": "England", "AUS": "Australia", "SA": "South Africa", "RSA": "South Africa",
    "NZ": "New Zealand", "WIN": "West Indies", "WI": "West Indies", "SL": "Sri Lanka",
    "AFG": "Afghanistan", "BAN": "Bangladesh", "PAK": "Pakistan", "ZIM": "Zimbabwe",
    "IRE": "Ireland", "NED": "Netherlands", "SCO": "Scotland", "NAM": "Namibia", "NEP": "Nepal",
    "UAE": "United Arab Emirates", "USA": "United States", "CAN": "Canada", "OMA": "Oman",
}


def franchise_code(value) -> Optional[str]:
    if value is None:
        return None
    key = re.sub(r"\s+", " ", str(value)).strip().casefold()
    if not key or key in {"n/a", "na", "-", "none", "do no play", "do not play", "unsold"}:
        return None
    return FRANCHISE_CODES.get(key)


def normalize_role(value) -> Optional[str]:
    """Map source role vocabularies onto BAT / BOWL / AR / WK."""
    key = re.sub(r"[^a-z]", "", str(value or "").casefold())
    if not key or key == "unknown":
        return None
    if key in ("bat", "bowl", "ar", "wk"):  # already-normalised codes
        return key.upper()
    if "keeper" in key or key.startswith("wk"):
        return "WK"
    if "allround" in key:
        return "AR"
    if "bowl" in key:
        return "BOWL"
    if "bat" in key:
        return "BAT"
    return None


def role_from_set(set_code: Optional[str]) -> Optional[str]:
    """IPL auction set codes encode specialism: BA, AL, WK, FA, SP (U-prefixed if uncapped)."""
    m = re.match(r"^U?(BA|AL|WK|FA|SP)\d*$", (set_code or "").upper())
    return {"BA": "BAT", "AL": "AR", "WK": "WK", "FA": "BOWL", "SP": "BOWL"}[m.group(1)] if m else None


def bowling_kind(style: Optional[str], set_code: Optional[str] = None) -> Optional[str]:
    """Pace / spin from an explicit bowling style or an FA/SP auction set code."""
    code = (set_code or "").upper()
    if re.match(r"^U?FA\d*$", code):
        return "pace"
    if re.match(r"^U?SP\d*$", code):
        return "spin"
    text = str(style or "").casefold()
    if not text or text in {"nan", "-", "none"}:
        return None
    if any(w in text for w in ("spin", "break", "orthodox", "chinaman", "googly", "leg ", "legbreak", "off ")):
        return "spin"
    if any(w in text for w in ("fast", "medium", "seam", "pace")):
        return "pace"
    return None


# --------------------------------------------------------------------------
# Wikitext helpers
# --------------------------------------------------------------------------

_REF_RE = re.compile(r"<ref[^>/]*/>|<ref[^>]*>.*?</ref>", re.S | re.I)
_TAG_RE = re.compile(r"<[^>]+>")


def _template_args(body: str) -> List[str]:
    parts, depth, cur = [], 0, ""
    for ch in body:
        if ch in "{[":
            depth += 1
        elif ch in "}]":
            depth -= 1
        if ch == "|" and depth == 0:
            parts.append(cur)
            cur = ""
        else:
            cur += ch
    parts.append(cur)
    return parts


def inr_convert_lakh(text: str) -> Optional[float]:
    """``{{INRConvert|16|c}}`` → 1600 lakh; ``{{INRConvert|70|l}}`` → 70 lakh."""
    m = re.search(r"\{\{\s*INRConvert\s*\|([^}]*)\}\}", text, re.I)
    if not m:
        return None
    args = [a.strip() for a in _template_args(m.group(1))]
    try:
        amount = float(args[0].replace(",", ""))
    except (ValueError, IndexError):
        return None
    unit = (args[1] if len(args) > 1 else "").casefold()
    if unit.startswith("c"):
        return round(amount * 100, 2)
    if unit.startswith("l"):
        return round(amount, 2)
    return round(amount / 100000, 2)


def clean_cell(raw: str) -> Tuple[str, Dict]:
    """Return display text plus structured hints (country code, RTM, INR amount)."""
    hints: Dict = {}
    text = _REF_RE.sub("", raw)
    if re.search(r"\{\{\s*dagger\s*\}\}", text, re.I):
        hints["rtm"] = True
    lakh = inr_convert_lakh(text)
    if lakh is not None:
        hints["lakh"] = lakh
    m = re.search(r"\{\{\s*(?:cr|cricon|flagicon)\s*\|\s*([A-Za-z]{2,4})", text)
    if m:
        hints["country_code"] = m.group(1).upper()
    if re.search(r"\{\{\s*N/?A\s*\}\}", text, re.I):
        hints["na"] = True

    def sortname(match):
        args = [a.strip() for a in _template_args(match.group(1)) if "=" not in a]
        return " ".join(a for a in args[:2] if a)

    text = re.sub(r"\{\{\s*sortname\s*\|([^}]*)\}\}", sortname, text, flags=re.I)
    text = re.sub(r"\{\{[^{}]*\}\}", "", text)
    text = re.sub(r"\[\[(?:[^|\]]*\|)?([^\]]*)\]\]", r"\1", text)
    text = _TAG_RE.sub(" ", text).replace("'''", "").replace("''", "")
    return re.sub(r"\s+", " ", text).strip(), hints


def _split_attr(cell: str) -> str:
    """Drop a leading ``attr=... |`` prefix (pipe outside links/templates)."""
    depth = 0
    for i, ch in enumerate(cell):
        if ch in "{[":
            depth += 1
        elif ch in "}]":
            depth -= 1
        elif ch == "|" and depth == 0:
            head = cell[:i]
            if "=" in head or head.strip() == "":
                return cell[i + 1:]
            return cell
    return cell


def _split_cells(line: str, sep: str) -> List[str]:
    parts, depth, cur, i = [], 0, "", 0
    while i < len(line):
        ch = line[i]
        if ch in "{[":
            depth += 1
        elif ch in "}]":
            depth -= 1
        if depth == 0 and line.startswith(sep, i):
            parts.append(cur)
            cur = ""
            i += len(sep)
            continue
        cur += ch
        i += 1
    parts.append(cur)
    return parts


def wikitables(wikitext: str) -> List[Dict]:
    """Parse every top-level wikitable into caption, header row and data rows."""
    text = _REF_RE.sub("", wikitext)
    tables = []
    for m in re.finditer(r"^\{\|(.*?)^\|\}", text, re.S | re.M):
        body = m.group(1)
        caption, header, rows, section = None, None, [], None
        position = m.start()
        for chunk in re.split(r"^\|-[^\n]*$", body, flags=re.M):
            cells = []
            is_header = True
            for line in chunk.split("\n"):
                line = line.rstrip()
                if line.startswith("|+"):
                    caption = clean_cell(_split_attr(line[2:]))[0]
                    continue
                if line.startswith("!"):
                    for c in _split_cells(line[1:], "!!"):
                        # Row headers use ``! scope="row" | value || next || ...``.
                        sub = _split_cells(c, "||")
                        cells.append(_split_attr(sub[0]))
                        cells.extend(sub[1:])
                        if 'scope="row"' in c:
                            is_header = False
                elif line.startswith("|") and not line.startswith("|}"):
                    is_header = False
                    for c in _split_cells(line[1:], "||"):
                        cells.append(_split_attr(c))
                elif cells and line.strip():
                    cells[-1] += " " + line
            if not cells:
                continue
            if is_header:
                labels = [clean_cell(c)[0] for c in cells]
                if len(labels) == 1 or "colspan" in chunk:
                    section = labels[0]
                elif header is None or len(labels) >= 3:
                    header = labels
                continue
            rows.append({"cells": [clean_cell(c) for c in cells], "section": section})
        tables.append({"caption": caption, "header": header, "rows": rows, "offset": position})
    return tables


def _col(header: List[str], *needles) -> Optional[int]:
    for i, h in enumerate(header or []):
        low = h.casefold()
        if all(n in low for n in needles):
            return i
    return None


def _num(text) -> Optional[float]:
    if text is None:
        return None
    t = str(text).replace(",", "").strip()
    try:
        return float(t)
    except ValueError:
        return None


def _set_code(caption: Optional[str], section: Optional[str]) -> Optional[str]:
    for label in (caption, section):
        m = re.search(r"\(([A-Z]{1,4}\d{0,2})\)", label or "")
        if m:
            return m.group(1)
        if label and "accelerated" in label.casefold():
            return "ACC"
    return None


def parse_wikipedia_page(path: Path, season: int) -> Dict[str, List[Dict]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    parse = payload["parse"]
    wikitext = parse["wikitext"]
    revision = str(parse.get("revid") or "")
    title = parse.get("title") or f"List of {season} Indian Premier League personnel changes"
    url = "https://en.wikipedia.org/wiki/" + title.replace(" ", "_") + (f"?oldid={revision}" if revision else "")
    base = {"season": season, "source_name": "wikipedia/ipl-personnel-changes", "source_url": url,
            "source_revision": revision, "source_tier": "reference"}
    stripped = _REF_RE.sub("", wikitext)  # table offsets refer to ref-stripped text
    m_ret = re.search(r"^===\s*Retained players\s*===", stripped, re.M)
    retention_start = m_ret.start() if m_ret else len(stripped)
    m_end = re.search(r"^==[^=\n]*==\s*$|^===\s*Purse remaining", stripped[retention_start + 5:], re.M)
    auction_start = retention_start + 5 + m_end.start() if m_end else len(stripped)
    sold, retained, purse = [], [], []
    for table in wikitables(wikitext):
        header = table["header"] or []
        cap = table["caption"] or ""
        price_col = _col(header, "auctioned price")
        if price_col is not None:
            name_c = _col(header, "name")
            team_c = _col(header, str(season), "team")
            prev_c = _col(header, str(season - 1), "team")
            base_c = _col(header, "base price")
            for row in table["rows"]:
                cells = list(row["cells"])
                set_no_c = _col(header, "set no")
                if set_no_c is not None and len(cells) == len(header) - 1:
                    cells.insert(set_no_c, ("", {}))  # accelerated rows omit the set number
                if len(cells) < len(header) - 1:
                    continue
                get = lambda i: cells[i] if i is not None and i < len(cells) else ("", {})
                name, name_hints = get(name_c)
                if not name:
                    continue
                set_c = next((i for i, h in enumerate(header) if h.strip().casefold() == "set"), None)
                set_code = get(set_c)[0] or None if set_c is not None else None
                set_code = set_code if set_code and re.match(r"^[A-Z]{1,4}\d{0,2}$", set_code) else _set_code(cap, row["section"])
                country_hint = get(_col(header, "country"))[1].get("country_code")
                matches_text = get(_col(header, "ipl matches") or _col(header, "no. of ipl"))
                sold.append({**base,
                    "player_name": name, "country": COUNTRY_CODES.get(country_hint, country_hint),
                    "role": normalize_role(get(_col(header, "role"))[0]) or role_from_set(set_code),
                    "capped_status": (get(_col(header, "capped"))[0] or get(_col(header, "category"))[0] or None),
                    "set_code": set_code,
                    "lot_number": _lot(get(_col(header, "no.") if _col(header, "s.no") is None else _col(header, "s.no"))[0]),
                    "base_price_lakh": _num(get(base_c)[0]),
                    "final_price_lakh": _num(get(price_col)[0]),
                    "status": "SOLD", "acquisition_type": "auction",
                    "franchise": franchise_code(get(team_c)[0]),
                    "previous_franchise": franchise_code(re.split(r"\s{2,}|<br", get(prev_c)[0] or "")[0]) if prev_c is not None else None,
                    "is_rtm": bool(name_hints.get("rtm")),
                    "ipl_matches_before": 0 if matches_text[1].get("na") else _num(matches_text[0]),
                })
            continue
        if _col(header, "salary") is not None and _col(header, "player") is not None \
                and retention_start <= table["offset"] < (auction_start if auction_start > 0 else len(wikitext)):
            team = franchise_code(cap)
            if not team:
                continue
            pc, nc, sc = _col(header, "player"), _col(header, "nationality"), _col(header, "salary")
            for row in table["rows"]:
                cells = row["cells"]
                # Row-header layouts put the player first; numbered layouts shift by one.
                offset = len(header) - len(cells)
                get = lambda i: cells[i - offset] if i is not None and 0 <= i - offset < len(cells) else ("", {})
                name = get(pc)[0]
                if not name:
                    continue
                country = get(nc)[1].get("country_code")
                retained.append({**base, "player_name": name,
                                 "country": COUNTRY_CODES.get(country, country),
                                 "final_price_lakh": get(sc)[1].get("lakh"),
                                 "status": "RETAINED", "acquisition_type": "retained",
                                 "franchise": team})
            continue
        if _col(header, "purse") is not None and _col(header, "team") is not None:
            for row in table["rows"]:
                cells = row["cells"]
                team = franchise_code(cells[0][0]) if cells else None
                slots = cells[2][0] if len(cells) > 2 else ""
                m = re.match(r"(\d+)\s*\((\d+)\s*overseas", slots)
                if team:
                    purse.append({"season": season, "franchise": team,
                                  "purse_remaining_lakh": cells[1][1].get("lakh") if len(cells) > 1 else None,
                                  "slots_left": int(m.group(1)) if m else None,
                                  "overseas_slots_left": int(m.group(2)) if m else None,
                                  "source_name": base["source_name"], "source_url": url,
                                  "source_revision": revision})
    for row in sold + retained:
        for col in NORMALIZED_COLUMNS:
            row.setdefault(col, None)
    return {"sold": sold, "retained": retained, "purse": purse}


# --------------------------------------------------------------------------
# Official auction list copies (CSV)
# --------------------------------------------------------------------------

def _read_csv(path: Path) -> List[Dict]:
    with path.open(newline="", encoding="utf-8-sig") as fh:
        return [{(k or "").strip(): (v.strip() if isinstance(v, str) else v) for k, v in r.items()}
                for r in csv.DictReader(fh)]


def _age_from_dob(dob: Optional[str], on: date) -> Tuple[Optional[str], Optional[int]]:
    if not dob:
        return None, None
    for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y"):
        try:
            born = datetime.strptime(dob, fmt).date()
            return born.isoformat(), on.year - born.year - ((on.month, on.day) < (born.month, born.day))
        except ValueError:
            continue
    return None, None


def parse_official_2022(path: Path) -> List[Dict]:
    rows = []
    url = "https://github.com/outside-edge/ipl_auction/blob/main/data/acquisitions/sources/kaggle_2022/IPL_Auction_2022_FullList.csv"
    for r in _read_csv(path):
        name = r.get("Players")
        if not name:
            continue
        sold = (r.get("Bid") or "").casefold() == "sold"
        paid = _num(r.get("Price Paid"))
        age = _num(r.get("Age"))
        rows.append({c: None for c in NORMALIZED_COLUMNS} | {
            "season": 2022, "player_name": name, "country": r.get("Country") or None,
            "role": normalize_role(r.get("Specialism")), "bowling_style": r.get("Bowling Style") or None,
            "capped_status": r.get("C/U/A") or None, "set_code": r.get("2022 Set") or None,
            "base_price_lakh": _num(r.get("Reserve Price Rs Lakh")),
            "final_price_lakh": round(paid / 100000, 2) if sold and paid else None,
            "status": "SOLD" if sold else "UNSOLD", "acquisition_type": "auction",
            "franchise": franchise_code(r.get("Team")) if sold else None,
            "previous_franchise": franchise_code(r.get("2021 Team")),
            "ipl_matches_before": _num(r.get("IPL")), "age_at_auction": int(age) if age else None,
            "is_rtm": False,
            "source_name": "official-list/ipl-2022-auction", "source_url": url,
            "source_revision": "outside-edge HEAD", "source_tier": "official_copy",
        })
    return rows


def parse_official_2023(pool_path: Path, sold_path: Path) -> List[Dict]:
    url = "https://github.com/outside-edge/ipl_auction/tree/main/data/acquisitions/sources/kaggle_2023"
    sold = {}
    for r in _read_csv(sold_path):
        key = (r.get("First Name", "").strip(), r.get("Surname", "").strip())
        price = _num(r.get("Auction_Price"))
        team = franchise_code(r.get("TEAM"))
        if price and team:
            sold[key] = (team, price)
    rows = []
    auction_day = date(2022, 12, 23)
    for r in _read_csv(pool_path):
        key = (r.get("First Name", "").strip(), r.get("Surname", "").strip())
        name = " ".join(k for k in key if k)
        if not name:
            continue
        dob, age = _age_from_dob(r.get("DOB"), auction_day)
        outcome = sold.get(key)
        rows.append({c: None for c in NORMALIZED_COLUMNS} | {
            "season": 2023, "player_name": name, "country": r.get("Country") or None,
            "role": normalize_role(r.get("Specialism")), "bowling_style": r.get("Bowling_Style") or None,
            "capped_status": r.get("C/U/A") or None, "set_code": r.get("2023 Set") or None,
            "lot_number": None,
            "base_price_lakh": _num(r.get("Reserve_Price")),
            "final_price_lakh": outcome[1] if outcome else None,
            "status": "SOLD" if outcome else "UNSOLD", "acquisition_type": "auction",
            "franchise": outcome[0] if outcome else None,
            "previous_franchise": franchise_code(r.get("2022 Team")),
            "ipl_matches_before": _num(r.get("IPL")), "age_at_auction": age, "date_of_birth": dob,
            "is_rtm": False,
            "source_name": "official-list/ipl-2023-auction", "source_url": url,
            "source_revision": "outside-edge HEAD", "source_tier": "official_copy",
        })
    return rows


def load_all_normalized(project_root: Path) -> Dict[str, List[Dict]]:
    src = project_root / "data" / "auction" / "sources"
    out = {"lots": [], "purse": []}
    for path in sorted((src / "wikipedia").glob("wiki_*.json")):
        season = int(re.search(r"(\d{4})", path.name).group(1))
        parsed = parse_wikipedia_page(path, season)
        out["lots"].extend(parsed["sold"] + parsed["retained"])
        out["purse"].extend(parsed["purse"])
    up = src / "outside_edge_upstream"
    if (up / "IPL_Auction_2022_FullList.csv").exists():
        out["lots"].extend(parse_official_2022(up / "IPL_Auction_2022_FullList.csv"))
    if (up / "IPL_2023_Auction_Pool.csv").exists():
        out["lots"].extend(parse_official_2023(up / "IPL_2023_Auction_Pool.csv", up / "IPL_2023_Auction_Sold.csv"))
    return out


def retrieved_at(path: Path) -> str:
    return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat()


def _lot(text) -> Optional[int]:
    m = re.match(r"\s*(\d+)", str(text or ""))
    return int(m.group(1)) if m else None
