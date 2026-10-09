"""Büyük JSON aktarım özelliğini doğrular: kök dizi, kök nesnede dizi
(alan adı/sırası), nesne/pozisyonel kayıtlar, boş dizi, yanlış seçici,
Türkçe karakterler, Decimal, iptal, boyut/derinlik sınırları, "dizi
kapandı ama belgenin devamı bozuk" ve yazma hatasında depo tutarlılığı.
Üretilen depoyla sayfalama/arama/sıralamayı birlikte de test eder.

Gerçek D: diski / harici veri KULLANILMAZ; tamamı sentetik, yerel geçici
dosyalardır.
"""
import json
import os
import tempfile
import time
import unittest
from decimal import Decimal

import streaming_pilot.disk_store as disk_store_mod
from gui.dialogs import build_import_config
from streaming_pilot.disk_store import RecordReader, read_manifest
from streaming_pilot.import_job import (
    ImportJob,
    OUTCOME_CANCELLED,
    OUTCOME_FULL_COMPLETE,
    OUTCOME_LIMIT_REACHED,
    OUTCOME_OUTPUT_IO_ERROR,
    OUTCOME_PARSE_ERROR,
    OUTCOME_PREVIEW,
    OUTCOME_SELECTOR_ERROR,
    OUTCOME_TARGET_NOT_FOUND,
)


def _write(tmp, name, obj_or_text):
    path = os.path.join(tmp, name)
    with open(path, "w", encoding="utf-8") as f:
        if isinstance(obj_or_text, str):
            f.write(obj_or_text)
        else:
            json.dump(obj_or_text, f, ensure_ascii=False)
    return path


class TestImportJobSelectors(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def test_root_array_direct(self):
        src = _write(self.tmp.name, "a.json", [{"x": i} for i in range(10)])
        job = ImportJob(src, os.path.join(self.tmp.name, "out"), {"mode": "root_array"}, "full")
        job.run()
        self.assertEqual(job.outcome, OUTCOME_FULL_COMPLETE)
        self.assertEqual(job.completed_count, 10)
        self.assertTrue(read_manifest(job.manifest_path)["tamamlandi_mi"])

    def test_root_object_field_by_name(self):
        src = _write(self.tmp.name, "b.json", {"meta": 1, "kayitlar": [{"x": i} for i in range(7)]})
        job = ImportJob(src, os.path.join(self.tmp.name, "out"),
                        {"mode": "name", "value": "kayitlar"}, "full")
        job.run()
        self.assertEqual(job.outcome, OUTCOME_FULL_COMPLETE)
        self.assertEqual(job.completed_count, 7)

    def test_root_object_field_by_1based_index(self):
        src = _write(self.tmp.name, "c.json", {"meta": 1, "kayitlar": [{"x": i} for i in range(4)]})
        job = ImportJob(src, os.path.join(self.tmp.name, "out"),
                        {"mode": "index", "value": 2}, "full")  # 1-tabanli: 2. alan = "kayitlar"
        job.run()
        self.assertEqual(job.outcome, OUTCOME_FULL_COMPLETE)
        self.assertEqual(job.completed_count, 4)

    def test_wrong_selector_field_not_found(self):
        src = _write(self.tmp.name, "d.json", {"meta": 1, "kayitlar": [{"x": 1}]})
        job = ImportJob(src, os.path.join(self.tmp.name, "out"),
                        {"mode": "name", "value": "olmayan"}, "full")
        job.run()
        self.assertEqual(job.outcome, OUTCOME_TARGET_NOT_FOUND)
        self.assertFalse(read_manifest(job.manifest_path)["tamamlandi_mi"])

    def test_empty_array(self):
        src = _write(self.tmp.name, "e.json", {"kayitlar": []})
        job = ImportJob(src, os.path.join(self.tmp.name, "out"),
                        {"mode": "name", "value": "kayitlar"}, "full")
        job.run()
        self.assertEqual(job.outcome, OUTCOME_FULL_COMPLETE)
        self.assertEqual(job.completed_count, 0)
        reader = RecordReader(os.path.join(job.out_dir, "kayitlar.jsonl"), os.path.join(job.out_dir, "kayitlar.idx"))
        self.assertEqual(reader.record_count(), 0)


class TestBuildImportConfig(unittest.TestCase):
    """gui.dialogs.build_import_config: widget'lardan okunan HAM (string)
    degerlerden ImportJob yapilandirmasi uretme mantigi -- gercek Tk
    diyalogu ACILMADAN dogrudan test edilir. Bu, "kullanici alan sirasi
    kutusuna deger yazdi ama radyo dugmesini tiklamadigi icin secici
    sessizce 'kok zaten dizi'ye dustu" hatasinin kok nedenini kapsar."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def test_field_order_selector_via_real_gui_config_path_extracts_two_records(self):
        # Bildirilen gercek senaryo: kok nesnenin ucuncu alani bir kayit
        # dizisi; kullanici alan sirasi olarak "3" girdi.
        src = _write(self.tmp.name, "sentetik.json",
                     {"birinci": 1, "ikinci": 2, "ucuncu": [[1, 2, 3], [4, 5, 6]]})
        out_root = os.path.join(self.tmp.name, "cikti")

        config = build_import_config(
            source=src, out_dir=out_root, mode="full",
            selector_mode="index", name_value="", index_raw="3",
            max_records_raw="1000", max_mib_raw="32",
        )
        self.assertEqual(config["selector"], {"mode": "index", "value": 3})

        job = ImportJob(config["source"], config["out_dir"], config["selector"], config["mode"],
                         preview_max_records=config["preview_max_records"],
                         preview_max_bytes=config["preview_max_bytes"])
        job.run()
        self.assertEqual(job.outcome, OUTCOME_FULL_COMPLETE)
        self.assertEqual(job.completed_count, 2)

    def test_name_selector_still_works(self):
        config = build_import_config(
            source="kaynak.json", out_dir="cikti", mode="full",
            selector_mode="name", name_value="kayitlar", index_raw="",
            max_records_raw="1000", max_mib_raw="32",
        )
        self.assertEqual(config["selector"], {"mode": "name", "value": "kayitlar"})

    def test_root_array_selector_still_works(self):
        config = build_import_config(
            source="kaynak.json", out_dir="cikti", mode="full",
            selector_mode="root_array", name_value="", index_raw="",
            max_records_raw="1000", max_mib_raw="32",
        )
        self.assertEqual(config["selector"], {"mode": "root_array"})

    def test_no_selector_choice_raises_clear_error_instead_of_silently_defaulting(self):
        # Onceki hatali davranis: hicbir secim yapilmazsa sessizce
        # {"mode": "root_array"} uretiliyordu. Artik acik bir hata verilir.
        with self.assertRaises(ValueError) as ctx:
            build_import_config(
                source="kaynak.json", out_dir="cikti", mode="full",
                selector_mode="", name_value="", index_raw="",
                max_records_raw="1000", max_mib_raw="32",
            )
        self.assertIn("Kayıt dizisi seçimi yapılmalı", str(ctx.exception))

    def test_invalid_index_raises_clear_error(self):
        with self.assertRaises(ValueError):
            build_import_config(
                source="kaynak.json", out_dir="cikti", mode="full",
                selector_mode="index", name_value="", index_raw="0",
                max_records_raw="1000", max_mib_raw="32",
            )
        with self.assertRaises(ValueError):
            build_import_config(
                source="kaynak.json", out_dir="cikti", mode="full",
                selector_mode="index", name_value="", index_raw="abc",
                max_records_raw="1000", max_mib_raw="32",
            )

    def test_empty_name_raises_clear_error(self):
        with self.assertRaises(ValueError):
            build_import_config(
                source="kaynak.json", out_dir="cikti", mode="full",
                selector_mode="name", name_value="   ", index_raw="",
                max_records_raw="1000", max_mib_raw="32",
            )

    def test_missing_source_or_out_dir_raises_clear_error(self):
        with self.assertRaises(ValueError):
            build_import_config(
                source="", out_dir="cikti", mode="full",
                selector_mode="root_array", name_value="", index_raw="",
                max_records_raw="1000", max_mib_raw="32",
            )

    def test_invalid_preview_limits_raise_clear_error(self):
        with self.assertRaises(ValueError):
            build_import_config(
                source="kaynak.json", out_dir="cikti", mode="preview",
                selector_mode="root_array", name_value="", index_raw="",
                max_records_raw="0", max_mib_raw="32",
            )

    def test_csv_source_ignores_selector_entirely(self):
        # CSV'de "secici" kavrami yoktur; selector_mode/name_value/index_raw
        # BOS/gecersiz olsa bile (JSON icin hata sayilacak degerler) CSV
        # icin hicbir hataya yol acmamali, selector=None donmeli.
        config = build_import_config(
            source="veri.csv", out_dir="cikti", mode="full",
            selector_mode="", name_value="", index_raw="",
            max_records_raw="1000", max_mib_raw="32",
        )
        self.assertEqual(config["source_format"], "csv")
        self.assertIsNone(config["selector"])

    def test_unsupported_extension_raises_clear_error(self):
        with self.assertRaises(ValueError) as ctx:
            build_import_config(
                source="veri.txt", out_dir="cikti", mode="full",
                selector_mode="root_array", name_value="", index_raw="",
                max_records_raw="1000", max_mib_raw="32",
            )
        self.assertIn(".json", str(ctx.exception))
        self.assertIn(".csv", str(ctx.exception))


class TestImportJobSelectorErrorDetail(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def test_root_array_selector_against_object_root_gives_descriptive_error(self):
        # Bu, bildirilen hatanin motor tarafi: yanlislikla "root_array"
        # secilirse (kok aslinda bir nesne), aciklayici bir detay
        # (gercek alan adi/degeri icermeyen, yalnizca yapisal bir mesaj)
        # hem job uzerinde hem manifest'te bulunmali.
        src = _write(self.tmp.name, "n.json", {"birinci": 1, "ikinci": 2, "ucuncu": [[1], [2]]})
        job = ImportJob(src, os.path.join(self.tmp.name, "out"), {"mode": "root_array"}, "full")
        job.run()
        self.assertEqual(job.outcome, OUTCOME_SELECTOR_ERROR)
        self.assertEqual(job.completed_count, 0)
        self.assertIsNotNone(job.selector_error_detail)
        manifest = read_manifest(job.manifest_path)
        self.assertEqual(manifest["sonuc"], OUTCOME_SELECTOR_ERROR)
        self.assertIsNotNone(manifest["secici_hata_detayi"])


class TestImportJobRecordKinds(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def test_object_and_positional_records_and_turkish_and_decimal(self):
        src = _write(self.tmp.name, "f.json", {
            "kayitlar": [
                {"il": "İstanbul", "not": "çalışma ğüşiöı", "tutar": 2.50, "buyuk": 123456789012345678901234567890, "bos": None},
                ["pozisyonel", 1, True, None],
            ]
        })
        job = ImportJob(src, os.path.join(self.tmp.name, "out"),
                        {"mode": "name", "value": "kayitlar"}, "full")
        job.run()
        self.assertEqual(job.outcome, OUTCOME_FULL_COMPLETE)
        self.assertEqual(job.element_kind_counts, {"nesne": 1, "dizi_pozisyonel": 1})

        reader = RecordReader(os.path.join(job.out_dir, "kayitlar.jsonl"), os.path.join(job.out_dir, "kayitlar.idx"))
        r0 = reader.read_record(0)
        self.assertEqual(r0["il"], "İstanbul")
        self.assertEqual(r0["not"], "çalışma ğüşiöı")
        self.assertIsInstance(r0["tutar"], Decimal)
        self.assertEqual(r0["tutar"], Decimal("2.50"))
        self.assertIsInstance(r0["buyuk"], int)
        self.assertEqual(r0["buyuk"], 123456789012345678901234567890)
        self.assertIsNone(r0["bos"])
        r1 = reader.read_record(1)
        self.assertEqual(r1, ["pozisyonel", 1, True, None])


class TestImportJobCompleteness(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def test_array_closed_but_document_continuation_broken(self):
        # Dizi DUZGUN kapaniyor (2 kayit basariyla yazilir) ama belgenin
        # devami (kok nesnenin sonraki alani) bozuk -- bu YALNIZ dizinin
        # kapanmasinin "tamamlandi" saymaya YETMEDIGINI kanitlar.
        src = _write(self.tmp.name, "g.json",
                     '{"kayitlar": [{"a": 1}, {"a": 2}], "sonra": garbage_token}')
        job = ImportJob(src, os.path.join(self.tmp.name, "out"),
                        {"mode": "name", "value": "kayitlar"}, "full")
        job.run()
        self.assertEqual(job.outcome, OUTCOME_PARSE_ERROR)
        self.assertEqual(job.completed_count, 2)  # kayitlar yazildi, kullanilabilir
        self.assertFalse(read_manifest(job.manifest_path)["tamamlandi_mi"])
        reader = RecordReader(os.path.join(job.out_dir, "kayitlar.jsonl"), os.path.join(job.out_dir, "kayitlar.idx"))
        self.assertEqual(reader.record_count(), 2)

    def test_extra_field_after_array_still_completes(self):
        src = _write(self.tmp.name, "h.json",
                     {"meta": 1, "kayitlar": [{"a": i} for i in range(3)], "sonra_alan": "gecerli"})
        job = ImportJob(src, os.path.join(self.tmp.name, "out"),
                        {"mode": "name", "value": "kayitlar"}, "full")
        job.run()
        self.assertEqual(job.outcome, OUTCOME_FULL_COMPLETE)
        self.assertTrue(read_manifest(job.manifest_path)["tamamlandi_mi"])

    def test_five_thousand_records_not_capped_at_pilot_limits(self):
        n = 5200
        src = _write(self.tmp.name, "buyuk.json",
                     {"kayitlar": [{"i": i} for i in range(n)], "kuyruk_alani": "son"})
        job = ImportJob(src, os.path.join(self.tmp.name, "out"),
                        {"mode": "name", "value": "kayitlar"}, "full")
        job.run()
        self.assertEqual(job.outcome, OUTCOME_FULL_COMPLETE)
        self.assertEqual(job.completed_count, n)
        self.assertGreater(job.completed_count, 1000)  # pilotun eski sinirinin cok uzerinde
        reader = RecordReader(os.path.join(job.out_dir, "kayitlar.jsonl"), os.path.join(job.out_dir, "kayitlar.idx"))
        self.assertEqual(reader.record_count(), n)


class TestImportJobPreview(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def test_preview_never_marked_complete_even_if_array_would_close(self):
        # Dizi yalnizca 3 eleman iceriyor ve onizleme siniri (5) bunu asmiyor
        # olsa bile -- onizleme HER ZAMAN "tamamlandi=False" olmali.
        src = _write(self.tmp.name, "i.json", {"kayitlar": [{"a": i} for i in range(3)]})
        job = ImportJob(src, os.path.join(self.tmp.name, "out"),
                        {"mode": "name", "value": "kayitlar"}, "preview",
                        preview_max_records=5)
        job.run()
        self.assertEqual(job.outcome, OUTCOME_PREVIEW)
        self.assertEqual(job.completed_count, 3)
        self.assertFalse(read_manifest(job.manifest_path)["tamamlandi_mi"])

    def test_preview_record_limit_configurable(self):
        src = _write(self.tmp.name, "j.json", {"kayitlar": [{"a": i} for i in range(100)]})
        job = ImportJob(src, os.path.join(self.tmp.name, "out"),
                        {"mode": "name", "value": "kayitlar"}, "preview",
                        preview_max_records=10)
        job.run()
        self.assertEqual(job.completed_count, 10)

    def test_preview_byte_limit_configurable(self):
        src = _write(self.tmp.name, "k.json", {"kayitlar": [{"a": "x" * 100} for _ in range(1000)]})
        job = ImportJob(src, os.path.join(self.tmp.name, "out"),
                        {"mode": "name", "value": "kayitlar"}, "preview",
                        preview_max_records=100000, preview_max_bytes=200)
        job.run()
        self.assertLess(job.completed_count, 1000)
        self.assertLessEqual(job.bytes_read, 300)  # kucuk bir bayt butcesi gercekten uygulandi


class TestImportJobLimitsAndCancel(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def test_max_depth_limit(self):
        nested = "1"
        for _ in range(50):
            nested = '{"a":' + nested + '}'
        src = _write(self.tmp.name, "derin.json", '[' + nested + ']')
        job = ImportJob(src, os.path.join(self.tmp.name, "out"), {"mode": "root_array"}, "full",
                        max_depth=10)
        job.run()
        self.assertEqual(job.outcome, OUTCOME_LIMIT_REACHED)
        self.assertFalse(read_manifest(job.manifest_path)["tamamlandi_mi"])

    def test_max_record_bytes_limit(self):
        src = _write(self.tmp.name, "gecici.json", [{"a": "x" * 1000}])
        job = ImportJob(src, os.path.join(self.tmp.name, "out"), {"mode": "root_array"}, "full",
                        max_record_bytes=100)
        job.run()
        self.assertEqual(job.outcome, OUTCOME_LIMIT_REACHED)

    def test_cancel_immediately(self):
        src = _write(self.tmp.name, "iptal.json", [{"a": i} for i in range(1000)])
        job = ImportJob(src, os.path.join(self.tmp.name, "out"), {"mode": "root_array"}, "full")
        job.request_cancel()
        job.run()
        self.assertEqual(job.outcome, OUTCOME_CANCELLED)
        self.assertEqual(job.completed_count, 0)
        self.assertFalse(read_manifest(job.manifest_path)["tamamlandi_mi"])

    def test_cancel_mid_transfer_keeps_partial_usable_store(self):
        src = _write(self.tmp.name, "iptal2.json", [{"a": i} for i in range(500)])
        job = ImportJob(src, os.path.join(self.tmp.name, "out"), {"mode": "root_array"}, "full")

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
        # 21. yazim TAMAMLANDIKTAN sonra iptal istendi (bayrak bir sonraki
        # dongu basinda kontrol edilir); bu yuzden 21 kayit tamamlanmis olur.
        self.assertEqual(job.completed_count, 21)
        reader = RecordReader(os.path.join(job.out_dir, "kayitlar.jsonl"), os.path.join(job.out_dir, "kayitlar.idx"))
        self.assertEqual(reader.record_count(), 21)  # yarim kayit/indeks YOK

    def test_write_error_keeps_store_consistent(self):
        src = _write(self.tmp.name, "hata.json", [{"a": i} for i in range(100)])
        job = ImportJob(src, os.path.join(self.tmp.name, "out"), {"mode": "root_array"}, "full")

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
        self.assertFalse(read_manifest(job.manifest_path)["tamamlandi_mi"])
        reader = RecordReader(os.path.join(job.out_dir, "kayitlar.jsonl"), os.path.join(job.out_dir, "kayitlar.idx"))
        self.assertEqual(reader.record_count(), 7)


class TestImportJobNewSubfolderEachTime(unittest.TestCase):
    def test_never_overwrites_creates_new_subfolder(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = _write(tmp, "m.json", [{"a": 1}])
            out_root = os.path.join(tmp, "cikti")
            job1 = ImportJob(src, out_root, {"mode": "root_array"}, "full")
            job1.run()
            job2 = ImportJob(src, out_root, {"mode": "root_array"}, "full")
            job2.run()
            self.assertNotEqual(job1.out_dir, job2.out_dir)
            self.assertTrue(os.path.isdir(job1.out_dir))
            self.assertTrue(os.path.isdir(job2.out_dir))


def _pump(mw, seconds=8.0):
    end = time.time() + seconds
    while time.time() < end:
        mw.root.update()
        time.sleep(0.02)
        if not mw._busy:
            break


class TestGuiImportWiring(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        from gui.main_window import MainWindow
        self.mw = MainWindow()
        self.addCleanup(self.mw.root.destroy)

    def test_import_then_open_and_page_search_sort_together(self):
        n = 1200
        src = _write(self.tmp.name, "buyukce.json",
                     {"kayitlar": [[i, f"deger-{i}"] for i in range(n)], "kuyruk": "x"})
        out_root = os.path.join(self.tmp.name, "cikti")

        from gui import dialogs
        original_ask = dialogs.ask_import_config

        def fake_ask(parent):
            return {
                "source": src, "out_dir": out_root, "mode": "full",
                "source_format": "json",
                "selector": {"mode": "name", "value": "kayitlar"},
                "preview_max_records": 1000, "preview_max_bytes": 32 * 1024 * 1024,
            }

        original_askyesno = dialogs.messagebox.askyesno
        dialogs.ask_import_config = fake_ask
        import gui.main_window as mw_mod
        original_mw_askyesno = mw_mod.messagebox.askyesno
        mw_mod.messagebox.askyesno = lambda *a, **k: True  # "depoyu simdi ac" -> evet
        try:
            self.mw._on_import_large_json()
            _pump(self.mw, seconds=15.0)
        finally:
            dialogs.ask_import_config = original_ask
            mw_mod.messagebox.askyesno = original_mw_askyesno

        # Depo otomatik acilmis olmali (disk modu).
        self.assertEqual(self.mw.table_view.mode, "disk")
        self.assertEqual(self.mw.table_view.disk_total_count, n)
        self.assertTrue(self.mw.table_view.disk_is_complete)

        # Sayfalama: sayfa 1 (>500 kayit oldugu icin 3 sayfa olmali)
        self.assertEqual(self.mw.table_view.page_count(), 3)

        # Satira git: 1200. konum -> son kayit (id=1199)
        self.mw.goto_var.set(str(n))
        self.mw._on_goto()
        _pump(self.mw)
        self.assertEqual(self.mw.table_view.selected_row_id(), n - 1)

        # Arama: pozisyonel kayittaki "deger-999" essiz bir metni arayalim.
        self.mw.search_var.set("deger-999")
        self.mw._on_search()
        _pump(self.mw, seconds=10.0)
        self.assertIsNotNone(self.mw.match_store)
        self.assertGreaterEqual(self.mw.match_store.count(), 1)

        # Siralama: Kolon 1'e gore azalan sirala, ilk satirin en buyuk id'ye sahip olmasi beklenir.
        self.mw._refresh_sort_columns()
        self.mw.sort_column_var.set("Kolon 1")
        self.mw.sort_dir_var.set("Azalan")
        self.mw._on_sort()
        _pump(self.mw, seconds=10.0)
        first_children = self.mw.table_view.tree.get_children()
        first_values = self.mw.table_view.tree.item(first_children[0], "values")
        self.assertEqual(first_values[1], str(n - 1))


if __name__ == "__main__":
    unittest.main()
