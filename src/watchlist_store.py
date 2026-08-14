from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import json


WATCHLIST_FILE = Path("data/watchlists.json")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize_watchlists(raw: object) -> dict[str, list[dict]]:
    if not isinstance(raw, dict):
        return {"Default": []}

    cleaned: dict[str, list[dict]] = {}
    for key, value in raw.items():
        name = str(key).strip()
        if not name:
            continue
        if not isinstance(value, list):
            cleaned[name] = []
            continue
        cleaned[name] = [item for item in value if isinstance(item, dict)]

    if not cleaned:
        cleaned["Default"] = []
    return cleaned


def load_watchlists(path: Path = WATCHLIST_FILE) -> dict[str, list[dict]]:
    if not path.exists():
        return {"Default": []}

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"Default": []}

    return _normalize_watchlists(data)


def save_watchlists(watchlists: dict[str, list[dict]], path: Path = WATCHLIST_FILE) -> None:
    payload = _normalize_watchlists(watchlists)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def list_watchlist_names(watchlists: dict[str, list[dict]]) -> list[str]:
    return sorted(_normalize_watchlists(watchlists).keys())


def create_watchlist(watchlists: dict[str, list[dict]], name: str) -> bool:
    cleaned_name = str(name).strip()
    if not cleaned_name:
        return False
    if cleaned_name in watchlists:
        return False
    watchlists[cleaned_name] = []
    return True


def delete_watchlist(watchlists: dict[str, list[dict]], name: str) -> bool:
    if name not in watchlists:
        return False
    if len(watchlists) <= 1:
        return False
    del watchlists[name]
    return True


def _row_to_entry(row: dict) -> dict:
    quote_symbol = str(row.get("Quote Symbol") or row.get("Ticker") or row.get("Symbol") or "").strip().upper()
    display_symbol = str(row.get("Ticker") or row.get("Symbol") or quote_symbol).strip().upper()
    return {
        "Symbol": display_symbol,
        "Quote Symbol": quote_symbol,
        "Market": str(row.get("Market") or "").strip() or "Unknown",
        "Sector": str(row.get("Sector") or "Unknown").strip() or "Unknown",
        "Industry": str(row.get("Industry") or "Unknown").strip() or "Unknown",
        "Signal": str(row.get("Signal") or "Unknown").strip() or "Unknown",
        "Bar Date": str(row.get("Bar Date") or "").strip(),
        "Added At": _now_iso(),
    }


def add_symbols_to_watchlist(watchlists: dict[str, list[dict]], name: str, rows: list[dict]) -> int:
    if name not in watchlists:
        watchlists[name] = []

    existing = {
        (str(item.get("Quote Symbol") or "").strip().upper(), str(item.get("Market") or "").strip().upper())
        for item in watchlists[name]
    }

    added = 0
    for row in rows:
        if not isinstance(row, dict):
            continue
        entry = _row_to_entry(row)
        key = (entry["Quote Symbol"], entry["Market"].upper())
        if not entry["Quote Symbol"] or key in existing:
            continue
        watchlists[name].append(entry)
        existing.add(key)
        added += 1
    return added


def remove_symbol_from_watchlist(watchlists: dict[str, list[dict]], name: str, quote_symbol: str) -> bool:
    if name not in watchlists:
        return False

    normalized = str(quote_symbol).strip().upper()
    if not normalized:
        return False

    current = watchlists[name]
    retained = [row for row in current if str(row.get("Quote Symbol") or "").strip().upper() != normalized]
    if len(retained) == len(current):
        return False

    watchlists[name] = retained
    return True
