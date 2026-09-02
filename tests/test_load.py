import os
import tempfile
import unittest

import parsers
from models import MISSING
from parsers.common import ParseError


class TestLoad(unittest.TestCase):
    def test_unsupported_extension_raises(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "veri.csv")
            with open(path, "w", encoding="utf-8") as f:
                f.write("a,b\n1,2\n")
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


if __name__ == "__main__":
    unittest.main()
