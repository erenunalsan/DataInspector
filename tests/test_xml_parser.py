import unittest

from parsers.common import ParseError
from parsers.xml_parser import parse


class TestXmlParserBasic(unittest.TestCase):
    def test_root_direct_children_are_records(self):
        records = parse(
            "<root><item><ad>Ali</ad></item><item><ad>Ayse</ad></item></root>"
        )
        self.assertEqual(records, [{"ad": "Ali"}, {"ad": "Ayse"}])

    def test_attribute_becomes_at_prefixed_field(self):
        records = parse('<root><item id="1"><ad>Ali</ad></item></root>')
        self.assertEqual(records, [{"@id": "1", "ad": "Ali"}])

    def test_repeated_child_elements_become_list(self):
        records = parse(
            "<root><item><etiket>a</etiket><etiket>b</etiket></item></root>"
        )
        self.assertEqual(records, [{"etiket": ["a", "b"]}])

    def test_empty_root_produces_no_records(self):
        self.assertEqual(parse("<root></root>"), [])

    def test_nested_element_becomes_dict(self):
        records = parse(
            "<root><item><adres><il>Ankara</il></adres></item></root>"
        )
        self.assertEqual(records, [{"adres": {"il": "Ankara"}}])


class TestXmlParserRejections(unittest.TestCase):
    def test_mixed_content_rejected(self):
        with self.assertRaises(ParseError):
            parse("<root><item>metin<alt>1</alt></item></root>")

    def test_text_and_attribute_together_rejected(self):
        with self.assertRaises(ParseError):
            parse('<root><item id="1">metin</item></root>')

    def test_malformed_xml_rejected(self):
        with self.assertRaises(ParseError):
            parse("<root><item></root>")

    def test_record_without_fields_rejected(self):
        with self.assertRaises(ParseError):
            parse("<root><item/></root>")


if __name__ == "__main__":
    unittest.main()
