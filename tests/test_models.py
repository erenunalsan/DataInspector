import json
import unittest

from models import MISSING, format_value


class TestMissing(unittest.TestCase):
    def test_missing_is_falsy(self):
        self.assertFalse(MISSING)

    def test_missing_repr(self):
        self.assertEqual(repr(MISSING), "MISSING")

    def test_missing_is_singleton_identity(self):
        self.assertIs(MISSING, MISSING)


class TestFormatValue(unittest.TestCase):
    def test_missing_is_empty_string(self):
        self.assertEqual(format_value(MISSING), "")

    def test_none_is_empty_string(self):
        self.assertEqual(format_value(None), "")

    def test_plain_string_unchanged(self):
        self.assertEqual(format_value("00123"), "00123")

    def test_integer_as_text(self):
        self.assertEqual(format_value(123), "123")

    def test_bool_as_text(self):
        self.assertEqual(format_value(True), "True")

    def test_empty_list(self):
        self.assertEqual(format_value([]), "[]")

    def test_list_of_strings_preserves_quotes(self):
        result = format_value(["a", "b"])
        self.assertEqual(result, json.dumps(["a", "b"], ensure_ascii=False))
        self.assertIn('"a"', result)

    def test_list_with_none_preserves_null(self):
        result = format_value(["a", None, ""])
        self.assertEqual(result, json.dumps(["a", None, ""], ensure_ascii=False))
        self.assertIn("null", result)

    def test_list_with_nested_object_preserved(self):
        value = [{"x": 1}, "y"]
        result = format_value(value)
        self.assertEqual(result, json.dumps(value, ensure_ascii=False))
        self.assertIn('"x"', result)

    def test_empty_dict_shows_as_braces(self):
        self.assertEqual(format_value({}), "{}")

    def test_turkish_characters_preserved_in_scalar(self):
        self.assertEqual(format_value("İstanbul çalışma"), "İstanbul çalışma")

    def test_turkish_characters_preserved_in_list(self):
        result = format_value(["ç", "ş", "İ"])
        self.assertEqual(result, json.dumps(["ç", "ş", "İ"], ensure_ascii=False))
        self.assertIn("ç", result)


if __name__ == "__main__":
    unittest.main()
