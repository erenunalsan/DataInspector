import unittest

from parsers.common import ParseError
from parsers.json_parser import parse


class TestJsonParserRootShapes(unittest.TestCase):
    def test_single_object_root_is_one_record(self):
        records = parse('{"name": "Ali", "tags": ["a", "b"]}')
        self.assertEqual(records, [{"name": "Ali", "tags": ["a", "b"]}])

    def test_object_list_root_is_multiple_records(self):
        records = parse('[{"a": 1}, {"a": 2}]')
        self.assertEqual(records, [{"a": 1}, {"a": 2}])

    def test_empty_list_root_is_zero_records(self):
        self.assertEqual(parse('[]'), [])

    def test_scalar_root_rejected(self):
        for text in ['123', '"metin"', 'true', 'null']:
            with self.assertRaises(ParseError):
                parse(text)

    def test_root_list_with_non_object_element_rejected(self):
        with self.assertRaises(ParseError):
            parse('[{"a": 1}, 2]')
        with self.assertRaises(ParseError):
            parse('[1, 2, 3]')

    def test_malformed_json_rejected(self):
        with self.assertRaises(ParseError):
            parse('{"a": }')

    def test_duplicate_key_top_level_rejected(self):
        with self.assertRaises(ParseError):
            parse('{"a": 1, "a": 2}')

    def test_duplicate_key_nested_rejected(self):
        with self.assertRaises(ParseError):
            parse('{"outer": {"a": 1, "a": 2}}')

    def test_duplicate_key_inside_list_element_rejected(self):
        with self.assertRaises(ParseError):
            parse('[{"a": 1, "a": 2}]')

    def test_wrapper_object_with_inner_list_stays_one_record(self):
        records = parse('{"records": [{"a": 1}, {"a": 2}], "meta": "x"}')
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["records"], [{"a": 1}, {"a": 2}])
        self.assertEqual(records[0]["meta"], "x")


class TestJsonParserSpecialNumbers(unittest.TestCase):
    def test_nan_rejected(self):
        with self.assertRaises(ParseError):
            parse('{"a": NaN}')

    def test_infinity_rejected(self):
        with self.assertRaises(ParseError):
            parse('{"a": Infinity}')

    def test_negative_infinity_rejected(self):
        with self.assertRaises(ParseError):
            parse('{"a": -Infinity}')

    def test_nan_rejected_when_nested_in_list_and_object(self):
        with self.assertRaises(ParseError):
            parse('[{"a": [1, NaN, 2]}]')

    def test_infinity_rejected_when_nested(self):
        with self.assertRaises(ParseError):
            parse('{"outer": {"a": Infinity}}')

    def test_positive_overflow_rejected(self):
        with self.assertRaises(ParseError):
            parse('{"a": 1e400}')

    def test_negative_overflow_rejected(self):
        with self.assertRaises(ParseError):
            parse('{"a": -1e400}')

    def test_overflow_rejected_when_nested_in_list(self):
        with self.assertRaises(ParseError):
            parse('{"a": [1, 1e400]}')

    def test_normal_decimal_and_exponent_numbers_still_parse(self):
        records = parse('{"a": 3.14, "b": 1.5e10, "c": -2.5e-3}')
        self.assertEqual(records, [{"a": 3.14, "b": 1.5e10, "c": -2.5e-3}])

    def test_quoted_nan_and_infinity_strings_are_preserved(self):
        records = parse('{"a": "NaN", "b": "Infinity", "c": "-Infinity"}')
        self.assertEqual(
            records, [{"a": "NaN", "b": "Infinity", "c": "-Infinity"}]
        )


if __name__ == "__main__":
    unittest.main()
