import os
import tempfile
import unittest

from models import MISSING
from parsers.common import ParseError, normalize, read_text_file


class TestNormalize(unittest.TestCase):
    def test_single_flat_record(self):
        ds = normalize([{"name": "Ali", "age": 30}])
        self.assertEqual(ds.columns, ["name", "age"])
        self.assertEqual(len(ds.rows), 1)
        self.assertEqual(ds.rows[0].row_id, 0)
        self.assertEqual(ds.rows[0].raw, {"name": "Ali", "age": 30})

    def test_missing_field_filled_across_records(self):
        ds = normalize([{"a": 1, "b": 2}, {"a": 3}])
        self.assertEqual(ds.columns, ["a", "b"])
        self.assertEqual(ds.rows[0].raw["b"], 2)
        self.assertIs(ds.rows[1].raw["b"], MISSING)

    def test_column_order_is_first_seen(self):
        ds = normalize([{"z": 1, "a": 2}, {"a": 2, "m": 3}])
        self.assertEqual(ds.columns, ["z", "a", "m"])

    def test_row_id_assigned_in_load_order(self):
        ds = normalize([{"a": 1}, {"a": 2}, {"a": 3}])
        self.assertEqual([r.row_id for r in ds.rows], [0, 1, 2])

    def test_nested_field_flattened_with_dot(self):
        ds = normalize([{"address": {"city": "Ankara", "no": 5}}])
        self.assertIn("address.city", ds.columns)
        self.assertIn("address.no", ds.columns)
        self.assertEqual(ds.rows[0].raw["address.city"], "Ankara")

    def test_list_field_kept_as_list_not_exploded(self):
        ds = normalize([{"name": "Ali", "tags": ["a", "b", "c"]}])
        self.assertEqual(ds.columns, ["name", "tags"])
        self.assertEqual(ds.rows[0].raw["tags"], ["a", "b", "c"])

    def test_list_of_objects_preserved_raw(self):
        ds = normalize([{"items": [{"x": 1}, {"y": 2}]}])
        self.assertEqual(ds.rows[0].raw["items"], [{"x": 1}, {"y": 2}])

    def test_empty_nested_object_preserved(self):
        ds = normalize([{"meta": {}}])
        self.assertEqual(ds.rows[0].raw["meta"], {})

    def test_entirely_empty_record_produces_no_columns(self):
        ds = normalize([{}])
        self.assertEqual(ds.columns, [])
        self.assertEqual(ds.rows[0].raw, {})

    def test_null_missing_and_empty_string_are_distinct(self):
        ds = normalize([{"a": None, "b": ""}, {"a": 1}])
        self.assertIsNone(ds.rows[0].raw["a"])
        self.assertEqual(ds.rows[0].raw["b"], "")
        self.assertIs(ds.rows[1].raw["b"], MISSING)

    def test_numeric_like_string_not_converted(self):
        ds = normalize([{"code": "00123"}])
        self.assertEqual(ds.rows[0].raw["code"], "00123")
        self.assertIsInstance(ds.rows[0].raw["code"], str)

    def test_empty_records_list_produces_empty_dataset(self):
        ds = normalize([])
        self.assertEqual(ds.columns, [])
        self.assertEqual(ds.rows, [])

    def test_collision_within_same_record(self):
        with self.assertRaises(ParseError):
            normalize([{"a.b": "x", "a": {"b": "y"}}])

    def test_collision_across_records(self):
        with self.assertRaises(ParseError):
            normalize([{"a.b": "x"}, {"a": {"b": "y"}}])

    def test_same_path_repeating_across_records_is_not_a_collision(self):
        ds = normalize([{"a": {"b": 1}}, {"a": {"b": 2}}])
        self.assertEqual(ds.columns, ["a.b"])
        self.assertEqual(ds.rows[0].raw["a.b"], 1)
        self.assertEqual(ds.rows[1].raw["a.b"], 2)


class TestReadTextFile(unittest.TestCase):
    def test_file_not_found_raises_parse_error(self):
        missing_path = os.path.join(tempfile.gettempdir(), "olmayan_dataınspector_test.json")
        with self.assertRaises(ParseError):
            read_text_file(missing_path)

    def test_reads_utf8_bom_file(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "bom.json")
            with open(path, "w", encoding="utf-8-sig") as f:
                f.write('{"il": "İstanbul"}')
            text = read_text_file(path)
            self.assertEqual(text, '{"il": "İstanbul"}')
            bom = chr(0xFEFF)
            self.assertFalse(text.startswith(bom))

    def test_reads_plain_utf8_file(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "plain.json")
            with open(path, "w", encoding="utf-8") as f:
                f.write('{"sehir": "çanakkale"}')
            text = read_text_file(path)
            self.assertEqual(text, '{"sehir": "çanakkale"}')

    def test_invalid_utf8_bytes_raise_parse_error(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "gecersiz.json")
            with open(path, "wb") as f:
                f.write(b'{"a": "\xff\xfe bozuk baytlar"}')
            with self.assertRaises(ParseError):
                read_text_file(path)


if __name__ == "__main__":
    unittest.main()
