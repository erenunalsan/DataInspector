import os
import tempfile
import unittest

import parsers
from models import MISSING
from parsers.common import ParseError


class TestLoad(unittest.TestCase):
    def test_unsupported_extension_raises(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "veri.txt")
            with open(path, "w", encoding="utf-8") as f:
                f.write("a: 1\n")
            with self.assertRaises(ParseError):
                parsers.load(path)

    def test_missing_file_raises(self):
        missing_path = os.path.join(tempfile.gettempdir(), "olmayan_dataınspector.json")
        with self.assertRaises(ParseError):
            parsers.load(missing_path)

    def test_invalid_utf8_bytes_raises(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "gecersiz_utf8.json")
            with open(path, "wb") as f:
                f.write(b'{"a": "\xff\xfe bozuk baytlar"}')
            with self.assertRaises(ParseError):
                parsers.load(path)

    def test_malformed_json_file_raises(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "bozuk.json")
            with open(path, "w", encoding="utf-8") as f:
                f.write("{bozuk")
            with self.assertRaises(ParseError):
                parsers.load(path)

    def test_utf8_bom_and_turkish_characters(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "veri.json")
            with open(path, "w", encoding="utf-8-sig") as f:
                f.write('[{"sehir": "İstanbul", "aciklama": "çalışma ğüşiöı"}]')
            ds = parsers.load(path)
            self.assertEqual(ds.rows[0].raw["sehir"], "İstanbul")
            self.assertEqual(ds.rows[0].raw["aciklama"], "çalışma ğüşiöı")

    def test_empty_list_root_produces_empty_dataset(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "bos.json")
            with open(path, "w", encoding="utf-8") as f:
                f.write("[]")
            ds = parsers.load(path)
            self.assertEqual(ds.columns, [])
            self.assertEqual(ds.rows, [])

    def test_full_pipeline_nested_list_and_missing(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "kayit.json")
            content = (
                '[{"ad": "Ali", "adres": {"il": "Ankara"}, "etiketler": ["a", "b"]},'
                ' {"ad": "Ayse"}]'
            )
            with open(path, "w", encoding="utf-8") as f:
                f.write(content)
            ds = parsers.load(path)
            self.assertEqual(ds.columns, ["ad", "adres.il", "etiketler"])
            self.assertEqual(ds.rows[0].raw["etiketler"], ["a", "b"])
            self.assertIs(ds.rows[1].raw["adres.il"], MISSING)
            self.assertIs(ds.rows[1].raw["etiketler"], MISSING)


class TestLoadCsv(unittest.TestCase):
    def test_basic_csv_load(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "veri.csv")
            with open(path, "w", encoding="utf-8", newline="") as f:
                f.write("ad,yas\nAli,30\nAyse,25\n")
            ds = parsers.load(path)
            self.assertEqual(ds.columns, ["ad", "yas"])
            self.assertEqual(ds.rows[0].raw, {"ad": "Ali", "yas": "30"})
            self.assertEqual(ds.rows[1].raw, {"ad": "Ayse", "yas": "25"})

    def test_uppercase_csv_extension_supported(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "VERI.CSV")
            with open(path, "w", encoding="utf-8", newline="") as f:
                f.write("a,b\n1,2\n")
            ds = parsers.load(path)
            self.assertEqual(ds.columns, ["a", "b"])

    def test_csv_utf8_bom_and_turkish_characters(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "veri.csv")
            with open(path, "w", encoding="utf-8-sig", newline="") as f:
                f.write("sehir,aciklama\nİstanbul,çalışma ğüşiöı\n")
            ds = parsers.load(path)
            self.assertEqual(ds.rows[0].raw["sehir"], "İstanbul")
            self.assertEqual(ds.rows[0].raw["aciklama"], "çalışma ğüşiöı")

    def test_csv_header_only_file_produces_columns_with_zero_rows(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "sadece_baslik.csv")
            with open(path, "w", encoding="utf-8", newline="") as f:
                f.write("ad,yas\n")
            ds = parsers.load(path)
            self.assertEqual(ds.columns, ["ad", "yas"])
            self.assertEqual(ds.rows, [])

    def test_csv_empty_file_produces_empty_dataset(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "bos.csv")
            with open(path, "w", encoding="utf-8", newline="") as f:
                f.write("")
            ds = parsers.load(path)
            self.assertEqual(ds.columns, [])
            self.assertEqual(ds.rows, [])

    def test_csv_field_count_mismatch_raises(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "uyumsuz.csv")
            with open(path, "w", encoding="utf-8", newline="") as f:
                f.write("a,b,c\n1,2\n")
            with self.assertRaises(ParseError):
                parsers.load(path)

    def test_csv_duplicate_header_raises(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "tekrar.csv")
            with open(path, "w", encoding="utf-8", newline="") as f:
                f.write("a,b,a\n1,2,3\n")
            with self.assertRaises(ParseError):
                parsers.load(path)

    def test_csv_unclosed_quote_raises(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "bozuk.csv")
            with open(path, "w", encoding="utf-8", newline="") as f:
                f.write('a,b\n"acik tirnak,2\n')
            with self.assertRaises(ParseError):
                parsers.load(path)

    def test_csv_multiline_crlf_preserved_end_to_end(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "coksatirli.csv")
            with open(path, "wb") as f:
                f.write(b'a,b\r\n"satir1\r\nsatir2",2\r\n')
            ds = parsers.load(path)
            self.assertEqual(ds.rows[0].raw["a"], "satir1\r\nsatir2")

    def test_csv_numeric_like_values_not_converted(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "sayisal.csv")
            with open(path, "w", encoding="utf-8", newline="") as f:
                f.write('kod,aktif\n"00123",true\n')
            ds = parsers.load(path)
            self.assertEqual(ds.rows[0].raw["kod"], "00123")
            self.assertIsInstance(ds.rows[0].raw["kod"], str)
            self.assertEqual(ds.rows[0].raw["aktif"], "true")


if __name__ == "__main__":
    unittest.main()
