import unittest

from algorithms.search import build_failure_table, kmp_contains, find_matches
from parsers.common import normalize


class TestKmpPrimitives(unittest.TestCase):
    def test_simple_match(self):
        pattern = "aba"
        table = build_failure_table(pattern)
        self.assertTrue(kmp_contains("xxabaxx", pattern, table))

    def test_no_match(self):
        pattern = "xyz"
        table = build_failure_table(pattern)
        self.assertFalse(kmp_contains("abcdef", pattern, table))

    def test_pattern_longer_than_text(self):
        pattern = "abcdef"
        table = build_failure_table(pattern)
        self.assertFalse(kmp_contains("ab", pattern, table))

    def test_repeating_characters_pattern(self):
        # Naif aramanin kotu davrandigi klasik durum: tekrarli karakterler.
        pattern = "aaab"
        text = "aaaaaaaaab"
        table = build_failure_table(pattern)
        self.assertTrue(kmp_contains(text, pattern, table))

    def test_case_sensitive(self):
        pattern = "Ali"
        table = build_failure_table(pattern)
        self.assertFalse(kmp_contains("ali veli", pattern, table))
        self.assertTrue(kmp_contains("Ali veli", pattern, table))

    def test_empty_pattern_no_match(self):
        table = build_failure_table("")
        self.assertFalse(kmp_contains("herhangi bir metin", "", table))


class TestFindMatches(unittest.TestCase):
    def setUp(self):
        self.dataset = normalize([
            {"ad": "Ali", "sehir": "Ankara"},
            {"ad": "Ayse", "sehir": "Istanbul"},
            {"ad": "Veli", "sehir": "Ankara"},
        ])
        self.view_order = [row.row_id for row in self.dataset.rows]

    def test_matches_across_all_columns(self):
        matches = find_matches(self.dataset, self.view_order, "Ankara")
        self.assertEqual(matches, [0, 2])

    def test_matches_follow_view_order(self):
        reversed_order = list(reversed(self.view_order))
        matches = find_matches(self.dataset, reversed_order, "Ankara")
        self.assertEqual(matches, [2, 0])

    def test_no_match_returns_empty(self):
        self.assertEqual(find_matches(self.dataset, self.view_order, "Izmir"), [])

    def test_empty_query_returns_empty(self):
        self.assertEqual(find_matches(self.dataset, self.view_order, ""), [])

    def test_row_matched_once_even_with_multiple_hits(self):
        ds = normalize([{"a": "Ankara", "b": "Ankara"}])
        vo = [row.row_id for row in ds.rows]
        self.assertEqual(find_matches(ds, vo, "Ankara"), [0])


if __name__ == "__main__":
    unittest.main()
