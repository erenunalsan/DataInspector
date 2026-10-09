import io
import os
import tempfile
import unittest
from decimal import Decimal

from streaming_pilot.budgeted_reader import BudgetedBinaryReader
from streaming_pilot.disk_store import RecordReader, read_manifest
from streaming_pilot.run_pilot import run_pilot
from streaming_pilot.streaming_source import (
    STOP_ARRAY_COMPLETE,
    STOP_BYTE_BUDGET,
    STOP_PARSE_ERROR,
    STOP_RECORD_LIMIT,
    STOP_SOURCE_REAL_EOF,
)

OBJECT_FIXTURE = """{
  "meta_a": 42,
  "meta_b": "surum bilgisi",
  "kayitlar": [
    {"ad": "Ali \\"Kaptan\\" Veli", "notlar": "satir1\\nsatir2\\ttab", "il": "İstanbul, Çanakkale", "sayi": 123456789012345678901234567890, "oran": 2.50, "bos": null},
    {"ad": "Ayse", "il": "Ankara"},
    {"ad": "Deneme { parantez } [koseli]", "il": "Izmir"}
  ]
}"""

POSITIONAL_FIXTURE = """{
  "a": 1,
  "b": 2,
  "satirlar": [
    [1, "iki", 3.5, null],
    ["dort", 5, [6, 7]],
    [8]
  ]
}"""

FIRST_ARRAY_FIXTURE = """{
  "sayi_alani": 7,
  "nesne_alani": {"ic1": 1, "ic2": {"daha_ic": 2}},
  "hedef_dizi": [{"x": 1}, {"x": 2}]
}"""

MALFORMED_FIXTURE = """{
  "a": 1,
  "b": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, garbage_token_not_valid_json]
}"""


def write_fixture(tmpdir, name, text):
    path = os.path.join(tmpdir, name)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    return path


class TestBudgetedBinaryReader(unittest.TestCase):
    def test_never_exceeds_budget(self):
        data = b"x" * 10000
        reader = BudgetedBinaryReader(io.BytesIO(data), budget_bytes=100)
        total = 0
        while True:
            chunk = reader.read(37)
            if not chunk:
                break
            total += len(chunk)
        self.assertLessEqual(total, 100)
        self.assertLessEqual(reader.bytes_read, 100)
        self.assertTrue(reader.budget_hit)
        self.assertFalse(reader.real_eof)

    def test_real_eof_before_budget(self):
        data = b"short"
        reader = BudgetedBinaryReader(io.BytesIO(data), budget_bytes=1000)
        out = b""
        while True:
            chunk = reader.read(4)
            if not chunk:
                break
            out += chunk
        self.assertEqual(out, data)
        self.assertTrue(reader.real_eof)
        self.assertFalse(reader.budget_hit)


class TestObjectElements(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.src = write_fixture(self.tmp.name, "obj.json", OBJECT_FIXTURE)
        self.out_dir = os.path.join(self.tmp.name, "out")

    def test_full_round_trip_object_records(self):
        result = run_pilot(
            self.src, self.out_dir, {"mode": "name", "value": "kayitlar"},
            max_bytes=1024 * 1024, max_records=1000,
        )
        self.assertEqual(result["completed_count"], 3)
        self.assertIn(result["stop_reason"], (STOP_ARRAY_COMPLETE, STOP_SOURCE_REAL_EOF))
        self.assertEqual(result["element_kind_counts"], {"nesne": 3})

        manifest = read_manifest(result["manifest_path"])
        self.assertTrue(manifest["tamamlandi_mi"])

        reader = RecordReader(result["jsonl_path"], result["index_path"])
        self.assertEqual(reader.record_count(), 3)

        r0 = reader.read_record(0)
        self.assertEqual(r0["ad"], 'Ali "Kaptan" Veli')
        self.assertEqual(r0["notlar"], "satir1\nsatir2\ttab")
        self.assertEqual(r0["il"], "İstanbul, Çanakkale")
        self.assertEqual(r0["sayi"], 123456789012345678901234567890)
        self.assertIsInstance(r0["sayi"], int)
        self.assertEqual(r0["oran"], Decimal("2.50"))
        self.assertIsInstance(r0["oran"], Decimal)
        self.assertIsNone(r0["bos"])
        self.assertIn("bos", r0)  # acik null: anahtar var, degeri None

        r1 = reader.read_record(1)
        self.assertNotIn("bos", r1)  # eksik alan: anahtar hic yok (None ile karistirilmadi)
        self.assertNotIn("sayi", r1)
        self.assertNotIn("oran", r1)

        r2 = reader.read_record(2)
        self.assertEqual(r2["ad"], "Deneme { parantez } [koseli]")

    def test_reopen_after_close_and_page_read(self):
        result = run_pilot(
            self.src, self.out_dir, {"mode": "index", "value": 3},
            max_bytes=1024 * 1024, max_records=1000,
        )
        # Yeni bir RecordReader ornegi -- onceki calisirken acilan hicbir
        # tutamaci paylasmiyor; "kapatip yeniden acma" senaryosunu temsil eder.
        fresh_reader = RecordReader(result["jsonl_path"], result["index_path"])
        self.assertEqual(fresh_reader.record_count(), 3)
        page = fresh_reader.read_page(0, 500)
        self.assertEqual(len(page), 3)
        self.assertEqual(page[0]["ad"], 'Ali "Kaptan" Veli')

    def test_page_size_over_limit_rejected(self):
        result = run_pilot(
            self.src, self.out_dir, {"mode": "index", "value": 3},
            max_bytes=1024 * 1024, max_records=1000,
        )
        reader = RecordReader(result["jsonl_path"], result["index_path"])
        with self.assertRaises(ValueError):
            reader.read_page(0, 501)

    def test_record_index_out_of_range_raises(self):
        result = run_pilot(
            self.src, self.out_dir, {"mode": "index", "value": 3},
            max_bytes=1024 * 1024, max_records=1000,
        )
        reader = RecordReader(result["jsonl_path"], result["index_path"])
        with self.assertRaises(IndexError):
            reader.read_record(999)


class TestPositionalArrayElements(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.src = write_fixture(self.tmp.name, "pos.json", POSITIONAL_FIXTURE)
        self.out_dir = os.path.join(self.tmp.name, "out")

    def test_positional_records_no_auto_header(self):
        result = run_pilot(
            self.src, self.out_dir, {"mode": "name", "value": "satirlar"},
            max_bytes=1024 * 1024, max_records=1000,
        )
        self.assertEqual(result["completed_count"], 3)
        self.assertEqual(result["element_kind_counts"], {"dizi_pozisyonel": 3})

        reader = RecordReader(result["jsonl_path"], result["index_path"])
        r0 = reader.read_record(0)
        # ILK kayit da normal bir veri satiridir; baslik olarak yutulmadi.
        self.assertEqual(r0, [1, "iki", Decimal("3.5"), None])
        r1 = reader.read_record(1)
        self.assertEqual(r1, ["dort", 5, [6, 7]])
        r2 = reader.read_record(2)
        self.assertEqual(r2, [8])


class TestSelectorModes(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def test_index_selector(self):
        src = write_fixture(self.tmp.name, "a.json", OBJECT_FIXTURE)
        result = run_pilot(src, os.path.join(self.tmp.name, "o1"),
                            {"mode": "index", "value": 3}, max_bytes=1 << 20, max_records=100)
        self.assertEqual(result["completed_count"], 3)

    def test_name_selector(self):
        src = write_fixture(self.tmp.name, "b.json", OBJECT_FIXTURE)
        result = run_pilot(src, os.path.join(self.tmp.name, "o2"),
                            {"mode": "name", "value": "kayitlar"}, max_bytes=1 << 20, max_records=100)
        self.assertEqual(result["completed_count"], 3)

    def test_first_array_skips_scalar_and_nested_object(self):
        src = write_fixture(self.tmp.name, "c.json", FIRST_ARRAY_FIXTURE)
        result = run_pilot(src, os.path.join(self.tmp.name, "o3"),
                            {"mode": "first_array"}, max_bytes=1 << 20, max_records=100)
        self.assertEqual(result["completed_count"], 2)
        reader = RecordReader(result["jsonl_path"], result["index_path"])
        self.assertEqual(reader.read_record(0), {"x": 1})
        self.assertEqual(reader.read_record(1), {"x": 2})


class TestStopReasons(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def test_record_limit_stops_before_array_closes(self):
        src = write_fixture(self.tmp.name, "obj.json", OBJECT_FIXTURE)
        result = run_pilot(src, os.path.join(self.tmp.name, "o1"),
                            {"mode": "name", "value": "kayitlar"},
                            max_bytes=1 << 20, max_records=2)
        self.assertEqual(result["completed_count"], 2)
        self.assertEqual(result["stop_reason"], STOP_RECORD_LIMIT)
        manifest = read_manifest(result["manifest_path"])
        self.assertFalse(manifest["tamamlandi_mi"])

    def test_byte_budget_cuts_off_mid_record_no_partial_written(self):
        src = write_fixture(self.tmp.name, "obj.json", OBJECT_FIXTURE)
        # Butceyi, dizinin ilk elemaninin ORTASINDA bitecek kadar kucuk tut.
        with open(src, "rb") as f:
            full = f.read()
        idx_first_record_start = full.index(b'"kayitlar"')
        tiny_budget = idx_first_record_start + 40  # ilk kaydin ortasinda bir yerde
        result = run_pilot(src, os.path.join(self.tmp.name, "o2"),
                            {"mode": "name", "value": "kayitlar"},
                            max_bytes=tiny_budget, max_records=1000)
        self.assertEqual(result["stop_reason"], STOP_BYTE_BUDGET)
        self.assertEqual(result["completed_count"], 0)  # ilk kayit yariminda kesildi, YAZILMADI
        self.assertLessEqual(result["bytes_read"], tiny_budget)
        manifest = read_manifest(result["manifest_path"])
        self.assertFalse(manifest["tamamlandi_mi"])
        # cikti dosyasinda hicbir satir olmamali (yarim kayit yazilmadi)
        reader = RecordReader(result["jsonl_path"], result["index_path"])
        self.assertEqual(reader.record_count(), 0)

    def test_no_records_completed_within_tiny_budget_is_reported(self):
        src = write_fixture(self.tmp.name, "obj.json", OBJECT_FIXTURE)
        result = run_pilot(src, os.path.join(self.tmp.name, "o3"),
                            {"mode": "name", "value": "kayitlar"},
                            max_bytes=8, max_records=1000)
        self.assertEqual(result["completed_count"], 0)
        self.assertEqual(result["stop_reason"], STOP_BYTE_BUDGET)

    def test_full_completion_within_generous_limits(self):
        src = write_fixture(self.tmp.name, "obj.json", OBJECT_FIXTURE)
        result = run_pilot(src, os.path.join(self.tmp.name, "o4"),
                            {"mode": "name", "value": "kayitlar"},
                            max_bytes=1 << 20, max_records=1000)
        self.assertIn(result["stop_reason"], (STOP_ARRAY_COMPLETE, STOP_SOURCE_REAL_EOF))
        manifest = read_manifest(result["manifest_path"])
        self.assertTrue(manifest["tamamlandi_mi"])

    def test_malformed_json_with_ample_budget_reports_parse_error(self):
        src = write_fixture(self.tmp.name, "bozuk.json", MALFORMED_FIXTURE)
        result = run_pilot(src, os.path.join(self.tmp.name, "o5"),
                            {"mode": "name", "value": "b"},
                            max_bytes=1 << 20, max_records=1000)
        self.assertEqual(result["stop_reason"], STOP_PARSE_ERROR)
        manifest = read_manifest(result["manifest_path"])
        self.assertFalse(manifest["tamamlandi_mi"])
        # hata siniif adi disinda ham JSON/veri parcasi rapora sizmamali
        self.assertIsNotNone(result["error_type_name"])
        self.assertNotIn("garbage_token_not_valid_json", str(result["error_type_name"]))


if __name__ == "__main__":
    unittest.main()
