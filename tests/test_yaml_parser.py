import unittest

from parsers.common import ParseError
from parsers.yaml_parser import parse


class TestYamlParserRootShapes(unittest.TestCase):
    def test_single_object_root_is_one_record(self):
        records = parse("name: Ali\ntags:\n  - a\n  - b\n")
        self.assertEqual(records, [{"name": "Ali", "tags": ["a", "b"]}])

    def test_object_list_root_is_multiple_records(self):
        records = parse("- a: 1\n- a: 2\n")
        self.assertEqual(records, [{"a": 1}, {"a": 2}])

    def test_empty_list_root_is_zero_records(self):
        self.assertEqual(parse("[]\n"), [])

    def test_scalar_root_rejected(self):
        for text in ["123\n", '"metin"\n', "true\n"]:
            with self.assertRaises(ParseError):
                parse(text)

    def test_completely_empty_document_rejected(self):
        with self.assertRaises(ParseError):
            parse("")

    def test_root_list_with_non_object_element_rejected(self):
        with self.assertRaises(ParseError):
            parse("- a: 1\n- 2\n")

    def test_malformed_yaml_rejected(self):
        with self.assertRaises(ParseError):
            parse("a: [1, 2\n")

    def test_nested_field_and_list_preserved(self):
        records = parse("ad: Ali\nadres:\n  il: Ankara\netiketler:\n  - x\n  - y\n")
        self.assertEqual(
            records, [{"ad": "Ali", "adres": {"il": "Ankara"}, "etiketler": ["x", "y"]}]
        )


class TestYamlParserRejections(unittest.TestCase):
    def test_non_string_key_rejected(self):
        with self.assertRaises(ParseError):
            parse("1: bir\n2: iki\n")

    def test_boolean_key_rejected(self):
        with self.assertRaises(ParseError):
            parse("true: evet\n")

    def test_date_value_rejected(self):
        with self.assertRaises(ParseError):
            parse("tarih: 2024-01-01\n")

    def test_binary_value_rejected(self):
        with self.assertRaises(ParseError):
            parse("veri: !!binary |\n  aGVsbG8=\n")

    def test_set_value_rejected(self):
        with self.assertRaises(ParseError):
            parse("kume: !!set\n  ? a\n  ? b\n")

    def test_circular_alias_rejected(self):
        with self.assertRaises(ParseError):
            parse("a: &anchor\n  b: *anchor\n")


if __name__ == "__main__":
    unittest.main()
