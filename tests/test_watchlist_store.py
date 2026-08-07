import tempfile
import unittest
from pathlib import Path

from src.watchlist_store import (
    add_symbols_to_watchlist,
    create_watchlist,
    list_watchlist_names,
    load_watchlists,
    remove_symbol_from_watchlist,
    save_watchlists,
)


class TestWatchlistStore(unittest.TestCase):
    def test_create_and_persist_watchlist(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "watchlists.json"
            watchlists = load_watchlists(path)
            self.assertIn("Default", watchlists)

            created = create_watchlist(watchlists, "US Swing")
            self.assertTrue(created)
            save_watchlists(watchlists, path)

            reloaded = load_watchlists(path)
            self.assertIn("US Swing", reloaded)
            self.assertIn("Default", reloaded)

    def test_add_dedup_remove_symbol(self):
        watchlists = {"Default": []}
        rows = [
            {"Quote Symbol": "AAPL", "Market": "USA", "Signal": "WATCH", "Setup Score": 44.0},
            {"Quote Symbol": "AAPL", "Market": "USA", "Signal": "WATCH", "Setup Score": 45.0},
            {"Quote Symbol": "MSFT", "Market": "USA", "Signal": "BREAKOUT BUY", "Setup Score": 61.0},
        ]

        added = add_symbols_to_watchlist(watchlists, "Default", rows)
        self.assertEqual(added, 2)
        self.assertEqual(len(watchlists["Default"]), 2)

        names = list_watchlist_names(watchlists)
        self.assertEqual(names, ["Default"])

        removed = remove_symbol_from_watchlist(watchlists, "Default", "AAPL")
        self.assertTrue(removed)
        self.assertEqual(len(watchlists["Default"]), 1)


if __name__ == "__main__":
    unittest.main()
