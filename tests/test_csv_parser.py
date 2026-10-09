import unittest

from parsers.common import ParseError
from parsers.csv_parser import parse


class TestCsvParserBasic(unittest.TestCase):
    def test_basic_headers_and_records(self):
        records, headers = parse("ad,yas\nAli,30\nAyse,25\n")
        self.assertEqual(headers, ["ad", "yas"])
        self.assertEqual(records, [{"ad": "Ali", "yas": "30"}, {"ad": "Ayse", "yas": "25"}])

    def test_header_order_preserved(self):
        records, headers = parse("z,a,m\n1,2,3\n")
        self.assertEqual(headers, ["z", "a", "m"])
        self.assertEqual(list(records[0].keys()), ["z", "a", "m"])

    def test_values_stay_as_text_no_conversion(self):
        records, headers = parse('kod,aktif,sabit\n"00123",true,NaN\n')
        row = records[0]
        self.assertEqual(row["kod"], "00123")
        self.assertIsInstance(row["kod"], str)
        self.assertEqual(row["aktif"], "true")
        self.assertEqual(row["sabit"], "NaN")

    def test_empty_cell_stays_empty_string(self):
        records, headers = parse("a,b\n1,\n")
        self.assertEqual(records[0]["b"], "")

    def test_leading_trailing_whitespace_in_cell_preserved(self):
        records, headers = parse("a,b\n  x  ,y\n")
        self.assertEqual(records[0]["a"], "  x  ")

    def test_quoted_comma_preserved(self):
        records, headers = parse('a,b\n"iki, parca",2\n')
        self.assertEqual(records[0]["a"], "iki, parca")

    def test_doubled_quote_becomes_single_quote(self):
        records, headers = parse('a,b\n"o ""dedi""",2\n')
        self.assertEqual(records[0]["a"], 'o "dedi"')

    def test_multiline_quoted_cell_with_crlf_preserved(self):
        records, headers = parse('a,b\r\n"satir1\r\nsatir2",2\r\n')
        self.assertEqual(records[0]["a"], "satir1\r\nsatir2")

    def test_multiline_quoted_cell_with_lf_preserved(self):
        records, headers = parse('a,b\n"satir1\nsatir2",2\n')
        self.assertEqual(records[0]["a"], "satir1\nsatir2")


class TestCsvParserHeaderValidation(unittest.TestCase):
    def test_duplicate_header_rejected(self):
        with self.assertRaises(ParseError):
            parse("a,b,a\n1,2,3\n")

    def test_empty_header_rejected(self):
        with self.assertRaises(ParseError):
            parse("a,,c\n1,2,3\n")

    def test_whitespace_only_header_rejected(self):
        with self.assertRaises(ParseError):
            parse("a,   ,c\n1,2,3\n")

    def test_valid_header_with_surrounding_whitespace_not_trimmed(self):
        records, headers = parse(" ad ,yas\n1,2\n")
        self.assertEqual(headers, [" ad ", "yas"])
        self.assertIn(" ad ", records[0])


class TestCsvParserRecordShape(unittest.TestCase):
    def test_blank_physical_lines_skipped(self):
        records, headers = parse("a,b\n\n1,2\n\n3,4\n")
        self.assertEqual(records, [{"a": "1", "b": "2"}, {"a": "3", "b": "4"}])

    def test_delimited_empty_cells_not_treated_as_blank_row(self):
        records, headers = parse("a,b,c\n,,\n")
        self.assertEqual(records, [{"a": "", "b": "", "c": ""}])

    def test_quoted_empty_cells_not_treated_as_blank_row(self):
        records, headers = parse('a,b,c\n"","",""\n')
        self.assertEqual(records, [{"a": "", "b": "", "c": ""}])

    def test_too_few_fields_rejected(self):
        with self.assertRaises(ParseError):
            parse("a,b,c\n1,2\n")

    def test_too_many_fields_rejected(self):
        with self.assertRaises(ParseError):
            parse("a,b\n1,2,3\n")


class TestCsvParserEmptyFiles(unittest.TestCase):
    def test_completely_empty_file(self):
        records, headers = parse("")
        self.assertEqual(records, [])
        self.assertEqual(headers, [])

    def test_only_blank_lines_file(self):
        records, headers = parse("\n\n\n")
        self.assertEqual(records, [])
        self.assertEqual(headers, [])

    def test_header_only_file_returns_empty_records_with_headers(self):
        records, headers = parse("ad,yas\n")
        self.assertEqual(headers, ["ad", "yas"])
        self.assertEqual(records, [])


class TestCsvParserMalformed(unittest.TestCase):
    def test_unclosed_quote_rejected(self):
        with self.assertRaises(ParseError):
            parse('a,b\n"acik tirnak,2\n')


if __name__ == "__main__":
    unittest.main()
