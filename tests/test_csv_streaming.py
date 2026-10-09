"""Büyük CSV desteğini doğrular:
  - streaming_pilot/csv_source.py (düşük seviye, dosya açmadan CsvStreamSource)
  - streaming_pilot/import_job.py'nin CSV dalı (ImportJob(source_format="csv"))
  - GUI'nin (table_view/main_window) sentetik bir CSV deposuyla sayfalama,
    satıra gitme, arama, sıralama ve Base64 akışı

Gerçek D: diski / harici veri KULLANILMAZ; tamamı sentetik, yerel geçici
dosyalardır.
"""
import base64
import csv as csv_module
import os
import tempfile
import time
import unittest

from streaming_pilot.csv_source import (
    CsvHeaderError,
    CsvStreamSource,
    STOP_BYTE_BUDGET,
    STOP_FIELD_TOO_LARGE,
    STOP_PARSE_ERROR,
    STOP_RECORD_LIMIT,
    STOP_SOURCE_REAL_EOF,
)
from streaming_pilot.disk_store import RecordReader, RecordWriter, read_manifest, write_manifest
from streaming_pilot.import_job import (
    ImportJob,
    OUTCOME_CANCELLED,
    OUTCOME_CSV_HEADER_ERROR,
    OUTCOME_FULL_COMPLETE,
    OUTCOME_LIMIT_REACHED,
    OUTCOME_OUTPUT_IO_ERROR,
    OUTCOME_PARSE_ERROR,
    OUTCOME_PREVIEW,
    OUTCOME_UNEXPECTED_ERROR,
)
import streaming_pilot.disk_store as disk_store_mod


def _write_bytes(tmp, name, data: bytes) -> str:
    path = os.path.join(tmp, name)
    with open(path, "wb") as f:
        f.write(data)
    return path


def _write_text(tmp, name, text: str, encoding: str = "utf-8") -> str:
    return _write_bytes(tmp, name, text.encode(encoding))


def _read_all(path, max_bytes=2 ** 62, max_field_bytes=None):
    """CsvStreamSource'u HER ZAMAN 'with' ile kullanır -- close() (ve
    dolayısıyla csv.field_size_limit'in eski değerine dönmesi) generator'ın
    tüketilip tüketilmediğine ya da GC'ye bırakılmaz, bu yardımcı fonksiyon
    çıkmadan ÖNCE her zaman gerçekleşir."""
    kwargs = {}
    if max_field_bytes is not None:
        kwargs["max_field_bytes"] = max_field_bytes
    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        with CsvStreamSource(f, max_bytes, **kwargs) as source:
            rows = list(source.iter_rows(2 ** 62))
    return source, rows


class TestCsvStreamSourceBasics(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def test_utf8_bom_and_turkish_headers_and_values(self):
        text = "isim,şehir\nEren Ünalsan,İstanbul\n"
        path = _write_bytes(self.tmp.name, "a.csv", b"\xef\xbb\xbf" + text.encode("utf-8"))
        source, rows = _read_all(path)
        self.assertEqual(source.headers, ["isim", "şehir"])
        self.assertEqual(rows, [["Eren Ünalsan", "İstanbul"]])
        self.assertEqual(source.stop_reason, STOP_SOURCE_REAL_EOF)

    def test_utf8_no_bom_still_works(self):
        path = _write_text(self.tmp.name, "a2.csv", "isim,sehir\nAli,Ankara\n")
        source, rows = _read_all(path)
        self.assertEqual(source.headers, ["isim", "sehir"])
        self.assertEqual(rows, [["Ali", "Ankara"]])

    def test_comma_inside_quotes(self):
        path = _write_text(self.tmp.name, "b.csv", 'a,b\n"1,2",3\n')
        _, rows = _read_all(path)
        self.assertEqual(rows, [["1,2", "3"]])

    def test_doubled_quotes(self):
        path = _write_text(self.tmp.name, "c.csv", 'a,b\n"say ""merhaba""",2\n')
        _, rows = _read_all(path)
        self.assertEqual(rows, [['say "merhaba"', "2"]])

    def test_multiline_cell_and_crlf_preserved(self):
        path = _write_bytes(self.tmp.name, "d.csv", b'a,b\r\n"satir1\r\nsatir2",2\r\n')
        _, rows = _read_all(path)
        self.assertEqual(rows, [["satir1\r\nsatir2", "2"]])

    def test_leading_trailing_cell_whitespace_preserved(self):
        path = _write_text(self.tmp.name, "e.csv", "a,b\n  x  , y \n")
        _, rows = _read_all(path)
        self.assertEqual(rows, [["  x  ", " y "]])

    def test_values_like_numbers_and_keywords_stay_as_text(self):
        path = _write_text(self.tmp.name, "f.csv", "a,b,c,d\n00123,null,true,NaN\n")
        _, rows = _read_all(path)
        self.assertEqual(rows, [["00123", "null", "true", "NaN"]])

    def test_empty_file_produces_zero_rows_zero_headers_complete(self):
        path = _write_text(self.tmp.name, "g.csv", "")
        source, rows = _read_all(path)
        self.assertEqual(source.headers, [])
        self.assertEqual(rows, [])
        self.assertEqual(source.stop_reason, STOP_SOURCE_REAL_EOF)

    def test_header_only_file_preserves_headers_zero_rows(self):
        path = _write_text(self.tmp.name, "h.csv", "a,b,c\n")
        source, rows = _read_all(path)
        self.assertEqual(source.headers, ["a", "b", "c"])
        self.assertEqual(rows, [])
        self.assertEqual(source.stop_reason, STOP_SOURCE_REAL_EOF)

    def test_fully_blank_physical_records_skipped(self):
        path = _write_text(self.tmp.name, "i.csv", "a,b\n1,2\n\n3,4\n")
        _, rows = _read_all(path)
        self.assertEqual(rows, [["1", "2"], ["3", "4"]])

    def test_delimiter_marked_empty_cell_row_not_skipped(self):
        path = _write_text(self.tmp.name, "j.csv", "a,b,c\n,,\n\"\",\"\",\"\"\n")
        _, rows = _read_all(path)
        self.assertEqual(rows, [["", "", ""], ["", "", ""]])

    def test_missing_field_rejected_with_physical_line_number(self):
        path = _write_text(self.tmp.name, "k.csv", "a,b,c\n1,2\n")
        source, rows = _read_all(path)
        self.assertEqual(rows, [])
        self.assertEqual(source.stop_reason, STOP_PARSE_ERROR)
        self.assertIn("fiziksel satır", source.row_error_detail)

    def test_extra_field_rejected(self):
        path = _write_text(self.tmp.name, "l.csv", "a,b\n1,2,3\n")
        source, rows = _read_all(path)
        self.assertEqual(rows, [])
        self.assertEqual(source.stop_reason, STOP_PARSE_ERROR)
        self.assertIn("fiziksel satır", source.row_error_detail)

    def test_empty_header_rejected(self):
        path = _write_text(self.tmp.name, "m.csv", "a,,c\n1,2,3\n")
        with self.assertRaises(CsvHeaderError):
            _read_all(path)

    def test_duplicate_header_rejected(self):
        path = _write_text(self.tmp.name, "n.csv", "a,b,a\n1,2,3\n")
        with self.assertRaises(CsvHeaderError):
            _read_all(path)

    def test_unterminated_quote_reported_as_parse_error(self):
        path = _write_text(self.tmp.name, "o.csv", 'a,b\n1,"unterminated\n')
        source, rows = _read_all(path)
        self.assertEqual(rows, [])
        self.assertEqual(source.stop_reason, STOP_PARSE_ERROR)

    def test_invalid_utf8_reported_as_parse_error(self):
        path = _write_bytes(self.tmp.name, "p.csv", b"a,b\n1,\xff\xfe\n")
        source, rows = _read_all(path)
        self.assertEqual(rows, [])
        self.assertEqual(source.stop_reason, STOP_PARSE_ERROR)
        self.assertEqual(source.error_type_name, "UnicodeDecodeError")

    def test_field_size_limit_enforced_and_global_state_restored(self):
        before = csv_module.field_size_limit()
        path = _write_text(self.tmp.name, "q.csv", "a,b\n" + ("x" * 100) + ",2\n")
        source, rows = _read_all(path, max_field_bytes=10)
        self.assertEqual(rows, [])
        self.assertEqual(source.stop_reason, STOP_FIELD_TOO_LARGE)
        # csv.field_size_limit GLOBAL bir modul ayaridir; finally ile onceki
        # degere geri donmus olmali (baska hicbir CSV islemini etkilememeli).
        self.assertEqual(csv_module.field_size_limit(), before)

    def test_preview_record_limit(self):
        text = "a,b\n" + "".join(f"{i},{i}\n" for i in range(100))
        path = _write_text(self.tmp.name, "r.csv", text)
        with open(path, "r", encoding="utf-8-sig", newline="") as f:
            with CsvStreamSource(f, 2 ** 62) as source:
                rows = list(source.iter_rows(10))
        self.assertEqual(len(rows), 10)
        self.assertEqual(source.stop_reason, STOP_RECORD_LIMIT)

    def test_preview_byte_limit(self):
        text = "a,b\n" + "".join(f"{i},{'x' * 50}\n" for i in range(1000))
        path = _write_text(self.tmp.name, "s.csv", text)
        with open(path, "r", encoding="utf-8-sig", newline="") as f:
            with CsvStreamSource(f, 300) as source:
                rows = list(source.iter_rows(2 ** 62))
        self.assertLess(len(rows), 1000)
        self.assertEqual(source.stop_reason, STOP_BYTE_BUDGET)

    def test_field_size_limit_restored_by_close_even_if_generator_kept_alive(self):
        # KRITIK: field_size_limit'in eski degere donmesi artik generator'in
        # kapanmasina/GC'ye ASLA guvenmiyor -- close() acikca cagrildigi anda
        # geri yuklenir, generator TUKETILMEMIS ve hala REFERANSLI olsa bile.
        before = csv_module.field_size_limit()
        text = "a,b\n" + "".join(f"{i},{i}\n" for i in range(50))
        path = _write_text(self.tmp.name, "t.csv", text)
        with open(path, "r", encoding="utf-8-sig", newline="") as f:
            source = CsvStreamSource(f, 2 ** 62, max_field_bytes=999)
            self.assertEqual(csv_module.field_size_limit(), 999)
            gen = source.iter_rows(2 ** 62)
            row0 = next(gen)  # generator baslatildi ama TUKETILMEDI
            self.assertEqual(row0, ["0", "0"])
            source.close()  # generator hala canli/referansli (gen, row0)
            self.assertEqual(csv_module.field_size_limit(), before)
        # generator'a hala referans tutuluyor (asagida kullanilmiyor olsa da,
        # degisken canli kaldigi surece refcount > 0'dir); yine de yukarida
        # close() cagrildigi anda deger zaten geri yuklenmisti.
        self.assertIsNotNone(gen)

    def test_close_is_idempotent(self):
        path = _write_text(self.tmp.name, "t2.csv", "a,b\n1,2\n")
        with open(path, "r", encoding="utf-8-sig", newline="") as f:
            source = CsvStreamSource(f, 2 ** 62, max_field_bytes=999)
            source.close()
            before_second_close = csv_module.field_size_limit()
            source.close()  # ikinci cagri no-op olmali, hata firlatmamali
            self.assertEqual(csv_module.field_size_limit(), before_second_close)


def _write_csv_source(tmp, name, text: str) -> str:
    path = os.path.join(tmp, name)
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(text)
    return path


class TestImportJobCsv(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def test_full_transfer_not_capped_at_1000_records(self):
        n = 5000
        text = "id,deger\n" + "".join(f"{i},deger-{i}\n" for i in range(n))
        src = _write_csv_source(self.tmp.name, "buyuk.csv", text)
        job = ImportJob(src, os.path.join(self.tmp.name, "out"), None, "full", source_format="csv")
        job.run()
        self.assertEqual(job.outcome, OUTCOME_FULL_COMPLETE)
        self.assertEqual(job.completed_count, n)
        self.assertGreater(job.completed_count, 1000)
        manifest = read_manifest(job.manifest_path)
        self.assertTrue(manifest["tamamlandi_mi"])
        self.assertEqual(manifest["kaynak_format"], "csv")
        self.assertEqual(manifest["kolonlar"], ["id", "deger"])
        reader = RecordReader(os.path.join(job.out_dir, "kayitlar.jsonl"), os.path.join(job.out_dir, "kayitlar.idx"))
        self.assertEqual(reader.record_count(), n)
        self.assertEqual(reader.read_record(0), ["0", "deger-0"])
        self.assertEqual(reader.read_record(n - 1), [str(n - 1), f"deger-{n - 1}"])

    def test_preview_never_marked_complete(self):
        text = "id,deger\n" + "".join(f"{i},{i}\n" for i in range(100))
        src = _write_csv_source(self.tmp.name, "onizleme.csv", text)
        job = ImportJob(src, os.path.join(self.tmp.name, "out"), None, "preview", source_format="csv",
                         preview_max_records=10)
        job.run()
        self.assertEqual(job.outcome, OUTCOME_PREVIEW)
        self.assertEqual(job.completed_count, 10)
        self.assertFalse(read_manifest(job.manifest_path)["tamamlandi_mi"])

    def test_header_error_outcome_and_no_data_leak_in_detail(self):
        src = _write_csv_source(self.tmp.name, "kotu_baslik.csv", "a,b,a\ngizli-deger,2,3\n")
        job = ImportJob(src, os.path.join(self.tmp.name, "out"), None, "full", source_format="csv")
        job.run()
        self.assertEqual(job.outcome, OUTCOME_CSV_HEADER_ERROR)
        self.assertEqual(job.completed_count, 0)
        self.assertFalse(read_manifest(job.manifest_path)["tamamlandi_mi"])
        self.assertNotIn("gizli-deger", job.csv_row_error_detail)

    def test_row_field_count_mismatch_outcome_and_no_data_leak(self):
        src = _write_csv_source(self.tmp.name, "eksik_alan.csv", "a,b,c\nsir-deger,2\n")
        job = ImportJob(src, os.path.join(self.tmp.name, "out"), None, "full", source_format="csv")
        job.run()
        self.assertEqual(job.outcome, OUTCOME_PARSE_ERROR)
        self.assertIn("fiziksel satır", job.csv_row_error_detail)
        self.assertNotIn("sir-deger", job.csv_row_error_detail)

    def test_field_size_limit_outcome(self):
        src = _write_csv_source(self.tmp.name, "hucre.csv", "a,b\n" + ("x" * 1000) + ",2\n")
        job = ImportJob(src, os.path.join(self.tmp.name, "out"), None, "full", source_format="csv",
                         max_csv_field_bytes=10)
        job.run()
        self.assertEqual(job.outcome, OUTCOME_LIMIT_REACHED)

    def test_cancel_mid_transfer_keeps_partial_usable_store(self):
        text = "id,deger\n" + "".join(f"{i},{i}\n" for i in range(500))
        src = _write_csv_source(self.tmp.name, "iptal.csv", text)
        job = ImportJob(src, os.path.join(self.tmp.name, "out"), None, "full", source_format="csv")

        original_write = disk_store_mod.RecordWriter.write_record
        calls = {"n": 0}

        def patched(self_writer, value):
            calls["n"] += 1
            if calls["n"] > 20:
                job.request_cancel()
            return original_write(self_writer, value)

        disk_store_mod.RecordWriter.write_record = patched
        try:
            job.run()
        finally:
            disk_store_mod.RecordWriter.write_record = original_write

        self.assertEqual(job.outcome, OUTCOME_CANCELLED)
        self.assertEqual(job.completed_count, 21)
        reader = RecordReader(os.path.join(job.out_dir, "kayitlar.jsonl"), os.path.join(job.out_dir, "kayitlar.idx"))
        self.assertEqual(reader.record_count(), 21)  # yarim kayit/indeks YOK
        self.assertFalse(read_manifest(job.manifest_path)["tamamlandi_mi"])

    def test_write_error_keeps_store_consistent(self):
        text = "id,deger\n" + "".join(f"{i},{i}\n" for i in range(100))
        src = _write_csv_source(self.tmp.name, "hata.csv", text)
        job = ImportJob(src, os.path.join(self.tmp.name, "out"), None, "full", source_format="csv")

        original_write = disk_store_mod.RecordWriter.write_record
        calls = {"n": 0}

        def patched(self_writer, value):
            calls["n"] += 1
            if calls["n"] > 7:
                raise OSError("disk doldu (simülasyon)")
            return original_write(self_writer, value)

        disk_store_mod.RecordWriter.write_record = patched
        try:
            job.run()
        finally:
            disk_store_mod.RecordWriter.write_record = original_write

        self.assertEqual(job.outcome, OUTCOME_OUTPUT_IO_ERROR)
        self.assertEqual(job.completed_count, 7)
        reader = RecordReader(os.path.join(job.out_dir, "kayitlar.jsonl"), os.path.join(job.out_dir, "kayitlar.idx"))
        self.assertEqual(reader.record_count(), 7)
        self.assertFalse(read_manifest(job.manifest_path)["tamamlandi_mi"])

    def test_headers_reopened_from_manifest(self):
        src = _write_csv_source(self.tmp.name, "basliklar.csv", "isim,sehir,puan\nAli,Ankara,5\nAyse,Izmir,9\n")
        job = ImportJob(src, os.path.join(self.tmp.name, "out"), None, "full", source_format="csv")
        job.run()
        manifest = read_manifest(job.manifest_path)
        self.assertEqual(manifest["kolonlar"], ["isim", "sehir", "puan"])
        # Depo kapatilip yeniden acilsa da (RecordReader kapatilip-yeniden-
        # acilabilir oldugu icin) basliklar YALNIZCA manifest'ten okunur.
        reader = RecordReader(os.path.join(job.out_dir, "kayitlar.jsonl"), os.path.join(job.out_dir, "kayitlar.idx"))
        self.assertEqual(reader.read_record(0), ["Ali", "Ankara", "5"])

    def test_old_json_store_manifest_still_opens_without_csv_fields(self):
        # Bu CSV ozelligi eklenmeden ONCEKI bir JSON deposunun manifest'ini
        # simule eder (kaynak_format/kolonlar/csv_hata_detayi alanlari hic
        # yok) -- GUI'nin "manifest.get('kaynak_format') == 'csv'" kontrolu
        # boyle eski bir manifestte hata vermeden False donmeli (bkz.
        # gui/main_window.py._open_disk_store_folder).
        out_dir = os.path.join(self.tmp.name, "eski_json_deposu")
        os.makedirs(out_dir)
        jsonl_path = os.path.join(out_dir, "kayitlar.jsonl")
        index_path = os.path.join(out_dir, "kayitlar.idx")
        manifest_path = os.path.join(out_dir, "manifest.json")
        with RecordWriter(jsonl_path, index_path) as writer:
            writer.write_record({"a": 1})
            writer.write_record({"a": 2})
        write_manifest(
            manifest_path, source_path="eski-kaynak.json",
            selector={"mode": "root_array"}, element_kind_counts={"nesne": 2},
            completed_count=2, bytes_read=123, stop_reason="dizi_tamamlandi",
            error_type_name=None,
        )
        manifest = read_manifest(manifest_path)
        self.assertNotIn("kaynak_format", manifest)
        self.assertIsNone(manifest.get("kaynak_format"))
        known_columns = manifest.get("kolonlar") if manifest.get("kaynak_format") == "csv" else None
        self.assertIsNone(known_columns)
        reader = RecordReader(jsonl_path, index_path)
        self.assertEqual(reader.record_count(), 2)
        self.assertEqual(reader.read_record(0), {"a": 1})


class TestImportJobCsvFieldSizeLimitLifecycle(unittest.TestCase):
    """csv.field_size_limit, ImportJob'un CSV dalının HER çıkış yolunda
    (başarı, kullanıcı iptali, başlık hatası, csv.Error, UnicodeDecodeError,
    yazma hatası, beklenmeyen exception) job.run() BİTTİKTEN HEMEN SONRA
    eski değerine dönmüş olmalı -- bu artık generator'ın kapanmasına ya da
    GC'ye değil, ImportJob._run_csv'nin 'with CsvStreamSource(...) as
    source:' zincirine (bkz. import_job.py, csv_source.py) dayanır."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self._field_size_limit_before_test = csv_module.field_size_limit()
        self.addCleanup(csv_module.field_size_limit, self._field_size_limit_before_test)

    def _assert_restored(self):
        self.assertEqual(csv_module.field_size_limit(), self._field_size_limit_before_test)

    def test_restored_after_success(self):
        text = "a,b\n" + "".join(f"{i},{i}\n" for i in range(30))
        src = _write_csv_source(self.tmp.name, "basari.csv", text)
        job = ImportJob(src, os.path.join(self.tmp.name, "out"), None, "full", source_format="csv",
                         max_csv_field_bytes=777)
        job.run()
        self.assertEqual(job.outcome, OUTCOME_FULL_COMPLETE)
        self._assert_restored()

    def test_restored_after_user_cancel(self):
        text = "a,b\n" + "".join(f"{i},{i}\n" for i in range(200))
        src = _write_csv_source(self.tmp.name, "iptal3.csv", text)
        job = ImportJob(src, os.path.join(self.tmp.name, "out"), None, "full", source_format="csv",
                         max_csv_field_bytes=777)
        job.request_cancel()
        job.run()
        self.assertEqual(job.outcome, OUTCOME_CANCELLED)
        self._assert_restored()

    def test_restored_after_header_error(self):
        src = _write_csv_source(self.tmp.name, "baslik_hata.csv", "a,a\n1,2\n")
        job = ImportJob(src, os.path.join(self.tmp.name, "out"), None, "full", source_format="csv",
                         max_csv_field_bytes=777)
        job.run()
        self.assertEqual(job.outcome, OUTCOME_CSV_HEADER_ERROR)
        self._assert_restored()

    def test_restored_after_csv_error_unterminated_quote(self):
        src = _write_csv_source(self.tmp.name, "csv_hata.csv", 'a,b\n1,"unterminated\n')
        job = ImportJob(src, os.path.join(self.tmp.name, "out"), None, "full", source_format="csv",
                         max_csv_field_bytes=777)
        job.run()
        self.assertEqual(job.outcome, OUTCOME_PARSE_ERROR)
        self._assert_restored()

    def test_restored_after_invalid_utf8(self):
        src = _write_bytes(self.tmp.name, "utf8_hata.csv", b"a,b\n1,\xff\xfe\n")
        job = ImportJob(src, os.path.join(self.tmp.name, "out"), None, "full", source_format="csv",
                         max_csv_field_bytes=777)
        job.run()
        self.assertEqual(job.outcome, OUTCOME_PARSE_ERROR)
        self.assertEqual(job.error_type_name, "UnicodeDecodeError")
        self._assert_restored()

    def test_restored_after_write_error(self):
        text = "a,b\n" + "".join(f"{i},{i}\n" for i in range(50))
        src = _write_csv_source(self.tmp.name, "yazma_hata.csv", text)
        job = ImportJob(src, os.path.join(self.tmp.name, "out"), None, "full", source_format="csv",
                         max_csv_field_bytes=777)

        original_write = disk_store_mod.RecordWriter.write_record

        def patched(self_writer, value):
            raise OSError("disk doldu (simülasyon)")

        disk_store_mod.RecordWriter.write_record = patched
        try:
            job.run()
        finally:
            disk_store_mod.RecordWriter.write_record = original_write

        self.assertEqual(job.outcome, OUTCOME_OUTPUT_IO_ERROR)
        self._assert_restored()

    def test_restored_after_unexpected_exception(self):
        text = "a,b\n" + "".join(f"{i},{i}\n" for i in range(30))
        src = _write_csv_source(self.tmp.name, "beklenmedik.csv", text)
        job = ImportJob(src, os.path.join(self.tmp.name, "out"), None, "full", source_format="csv",
                         max_csv_field_bytes=777)

        original_write = disk_store_mod.RecordWriter.write_record

        def boom(self_writer, value):
            raise RuntimeError("beklenmeyen simülasyon hatası (OSError DEĞİL)")

        disk_store_mod.RecordWriter.write_record = boom
        try:
            job.run()
        finally:
            disk_store_mod.RecordWriter.write_record = original_write

        # RuntimeError hicbir 'except OSError'a/CsvHeaderError'a uymaz;
        # ImportJob.run()'un en disaridaki 'except Exception' bloguna kadar
        # yukselir -- yine de 'with' zinciri (bkz. import_job.py._run_csv)
        # CsvStreamSource.close()'u bu sirada calistirmis olmalidir.
        self.assertEqual(job.outcome, OUTCOME_UNEXPECTED_ERROR)
        self._assert_restored()


def _pump(mw, seconds=8.0):
    end = time.time() + seconds
    while time.time() < end:
        mw.root.update()
        time.sleep(0.02)
        if not mw._busy:
            break


MSG = "CSV disk modu Base64 testi"
ENCODED = base64.b64encode(MSG.encode("utf-8")).decode("ascii")
WRAPPED = f"B64:{ENCODED}:END"


class TestGuiCsvDiskMode(unittest.TestCase):
    """Sentetik (gerçek D: diski KULLANILMAYAN) bir CSV deposuyla GUI'nin
    sayfalama, satıra gitme, arama, sıralama ve seçili satır Base64 akışını
    -- gerçek başlık adlarıyla -- doğrular."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        from gui.main_window import MainWindow
        self.mw = MainWindow()
        self.addCleanup(self.mw.root.destroy)

    def _build_csv_store(self, n=1200):
        headers = ["id", "isim", "not"]
        text = "id,isim,not\n" + "".join(
            f"{i},kisi-{i},{WRAPPED if i == 999 else 'x'}\n" for i in range(n)
        )
        src = _write_csv_source(self.tmp.name, "buyukce.csv", text)
        out_root = os.path.join(self.tmp.name, "cikti")
        job = ImportJob(src, out_root, None, "full", source_format="csv")
        job.run()
        self.assertEqual(job.outcome, OUTCOME_FULL_COMPLETE)
        return job, headers, n

    def test_paging_goto_search_sort_and_decode_with_real_headers(self):
        job, headers, n = self._build_csv_store()

        from gui import dialogs
        original_ask = dialogs.ask_import_config

        def fake_ask(parent):
            return {
                "source": job.source_path, "out_dir": job.out_root_dir, "mode": "full",
                "source_format": "csv", "selector": None,
                "preview_max_records": 1000, "preview_max_bytes": 32 * 1024 * 1024,
            }

        dialogs.ask_import_config = fake_ask
        import gui.main_window as mw_mod
        original_mw_askyesno = mw_mod.messagebox.askyesno
        mw_mod.messagebox.askyesno = lambda *a, **k: True
        try:
            self.mw._on_import_large_json()
            _pump(self.mw, seconds=15.0)
        finally:
            dialogs.ask_import_config = original_ask
            mw_mod.messagebox.askyesno = original_mw_askyesno

        self.assertEqual(self.mw.table_view.mode, "disk")
        self.assertEqual(self.mw.table_view.disk_total_count, n)
        self.assertTrue(self.mw.table_view.disk_is_complete)
        # Gercek basliklar -- "Kolon N" DEGIL -- kolon adi olarak gorunmeli,
        # basliktaki kayit olmasa bile (bkz. table_view.disk_known_columns).
        self.assertEqual(self.mw.table_view.current_page_columns, headers)

        # Sayfalama: 1200 kayit / 500 sayfa boyutu -> 3 sayfa
        self.assertEqual(self.mw.table_view.page_count(), 3)

        # Satira git: son kayit (id=1199)
        self.mw.goto_var.set(str(n))
        self.mw._on_goto()
        _pump(self.mw)
        self.assertEqual(self.mw.table_view.selected_row_id(), n - 1)
        self.assertEqual(self.mw.table_view.current_page_columns, headers)

        # Arama: essiz bir metni arayalim (gercek baslik uzerinden hucreler taraniyor)
        self.mw.search_var.set("kisi-999")
        self.mw._on_search()
        _pump(self.mw, seconds=10.0)
        self.assertIsNotNone(self.mw.match_store)
        self.assertGreaterEqual(self.mw.match_store.count(), 1)

        # Siralama: GERCEK baslik adiyla ("isim") azalan sirala.
        self.mw._refresh_sort_columns()
        self.assertIn("isim", list(self.mw.sort_column_combo["values"]))
        self.mw.sort_column_var.set("isim")
        self.mw.sort_dir_var.set("Azalan")
        self.mw._on_sort()
        _pump(self.mw, seconds=10.0)
        first_children = self.mw.table_view.tree.get_children()
        first_values = self.mw.table_view.tree.item(first_children[0], "values")
        # "isim" kolonunda metin sirasiyla azalan: "kisi-999" > "kisi-998" > ...
        # metin siralamasinda en buyuk "kisi-999" olmalidir (tum "kisi-" on ekli).
        isim_col_index = 1 + headers.index("isim")
        self.assertEqual(first_values[isim_col_index], "kisi-999")

        # Kaynak sirasina don, sonra WRAPPED Base64 hucresini (id=999) coz.
        self.mw._on_return_to_source_order()
        _pump(self.mw)
        self.mw.goto_var.set("1000")  # 1-tabanli konum 1000 -> id 999
        self.mw._on_goto()
        _pump(self.mw)
        self.assertEqual(self.mw.table_view.selected_row_id(), 999)

        captured = {}
        original_ask_b64 = dialogs.ask_base64_config
        original_show = dialogs.show_decode_result

        def fake_ask_b64(parent, columns):
            captured["columns_seen"] = list(columns)
            return {"columns": ["not"], "prefix": "B64:", "postfix": ":END", "apply_to": "joined"}

        def fake_show(parent, decoded_bytes, decoded_text, duration):
            captured["decoded_text"] = decoded_text

        dialogs.ask_base64_config = fake_ask_b64
        dialogs.show_decode_result = fake_show
        try:
            self.mw._on_decode()
            _pump(self.mw)
        finally:
            dialogs.ask_base64_config = original_ask_b64
            dialogs.show_decode_result = original_show

        self.assertEqual(captured["columns_seen"], headers)
        self.assertEqual(captured["decoded_text"], MSG)


if __name__ == "__main__":
    unittest.main()
