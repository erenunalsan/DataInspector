import math
import unittest

from algorithms.sorting import merge_sort_view
from models import MISSING
from parsers.common import normalize


class TestMergeSortView(unittest.TestCase):
    def test_ascending_numbers(self):
        ds = normalize([{"n": 3}, {"n": 1}, {"n": 2}])
        vo = [row.row_id for row in ds.rows]
        result = merge_sort_view(ds, vo, "n", ascending=True)
        values = [ds.rows[r].raw["n"] for r in result]
        self.assertEqual(values, [1, 2, 3])

    def test_descending_numbers(self):
        ds = normalize([{"n": 3}, {"n": 1}, {"n": 2}])
        vo = [row.row_id for row in ds.rows]
        result = merge_sort_view(ds, vo, "n", ascending=False)
        values = [ds.rows[r].raw["n"] for r in result]
        self.assertEqual(values, [3, 2, 1])

    def test_stability_preserves_relative_order_of_equal_values(self):
        ds = normalize([
            {"n": 1, "tag": "birinci"},
            {"n": 1, "tag": "ikinci"},
            {"n": 1, "tag": "ucuncu"},
        ])
        vo = [row.row_id for row in ds.rows]
        result = merge_sort_view(ds, vo, "n", ascending=True)
        tags = [ds.rows[r].raw["tag"] for r in result]
        self.assertEqual(tags, ["birinci", "ikinci", "ucuncu"])

    def test_stability_holds_in_descending_too(self):
        ds = normalize([
            {"n": 1, "tag": "birinci"},
            {"n": 1, "tag": "ikinci"},
        ])
        vo = [row.row_id for row in ds.rows]
        result = merge_sort_view(ds, vo, "n", ascending=False)
        tags = [ds.rows[r].raw["tag"] for r in result]
        self.assertEqual(tags, ["birinci", "ikinci"])

    def test_type_group_order_bool_number_text_complex(self):
        ds = normalize([
            {"v": "metin"},
            {"v": [1, 2]},
            {"v": True},
            {"v": 5},
        ])
        vo = [row.row_id for row in ds.rows]
        result = merge_sort_view(ds, vo, "v", ascending=True)
        values = [ds.rows[r].raw["v"] for r in result]
        self.assertEqual(values, [True, 5, "metin", [1, 2]])

    def test_missing_none_nan_always_last_ascending(self):
        # "other" alanini tasiyan kayitta "v" alani hic yok -> MISSING uretir.
        ds = normalize([{"v": 2}, {"other": 1}, {"v": 1}, {"v": float("nan")}])
        vo = [row.row_id for row in ds.rows]
        result = merge_sort_view(ds, vo, "v", ascending=True)
        values = [ds.rows[r].raw["v"] for r in result]
        self.assertEqual(values[:2], [1, 2])
        tail = values[2:]
        self.assertEqual(len(tail), 2)
        self.assertTrue(all(v is MISSING or v is None or (isinstance(v, float) and math.isnan(v)) for v in tail))

    def test_missing_none_nan_always_last_descending(self):
        ds = normalize([{"v": 2}, {"other": 1}, {"v": 1}, {"v": float("nan")}])
        vo = [row.row_id for row in ds.rows]
        result = merge_sort_view(ds, vo, "v", ascending=False)
        values = [ds.rows[r].raw["v"] for r in result]
        self.assertEqual(values[:2], [2, 1])

    def test_numeric_like_strings_sorted_as_text(self):
        ds = normalize([{"kod": "10"}, {"kod": "2"}, {"kod": "1"}])
        vo = [row.row_id for row in ds.rows]
        result = merge_sort_view(ds, vo, "kod", ascending=True)
        values = [ds.rows[r].raw["kod"] for r in result]
        # metin sirasinda "1" < "10" < "2"
        self.assertEqual(values, ["1", "10", "2"])

    def test_original_rows_never_reordered(self):
        ds = normalize([{"n": 3}, {"n": 1}, {"n": 2}])
        original_ids = [row.row_id for row in ds.rows]
        vo = list(original_ids)
        merge_sort_view(ds, vo, "n", ascending=True)
        self.assertEqual([row.row_id for row in ds.rows], original_ids)


if __name__ == "__main__":
    unittest.main()
