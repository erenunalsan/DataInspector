"""Büyük XML desteğini doğrular:
  - streaming_pilot/xml_source.py (düşük seviye, dosya açmadan XmlStreamSource)
  - streaming_pilot/import_job.py'nin XML dalı (ImportJob(source_format="xml"))
  - GUI'nin (table_view/main_window) sentetik bir XML deposuyla sayfalama,
    satıra gitme, arama, sıralama ve Base64 akışı

Gerçek D: diski / harici veri KULLANILMAZ; tamamı sentetik, yerel geçici
dosyalardır.
"""
import base64
import gc
import io
import os
import tempfile
import time
import unittest
import xml.etree.ElementTree as ET

from streaming_pilot.budgeted_reader import BudgetedBinaryReader
from streaming_pilot.disk_store import RecordReader
from streaming_pilot.import_job import (
    ImportJob,
    OUTCOME_CANCELLED,
    OUTCOME_FULL_COMPLETE,
    OUTCOME_LIMIT_REACHED,
    OUTCOME_OUTPUT_IO_ERROR,
    OUTCOME_PARSE_ERROR,
    OUTCOME_PREVIEW,
    OUTCOME_TARGET_NOT_FOUND,
)
from streaming_pilot.disk_store import read_manifest
import streaming_pilot.disk_store as disk_store_mod
from streaming_pilot.xml_source import (
    STOP_BYTE_BUDGET,
    STOP_PARSE_ERROR,
    STOP_RECORD_TOO_DEEP,
    STOP_RECORD_TOO_LARGE,
    STOP_SOURCE_REAL_EOF,
    XmlStreamSource,
)


def _reader_for_bytes(data: bytes, budget: int = 2 ** 62) -> BudgetedBinaryReader:
    return BudgetedBinaryReader(io.BytesIO(data), budget)


def _write_xml(tmp, name, text: str) -> str:
    path = os.path.join(tmp, name)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    return path


class TestXmlStreamSourceBasics(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def test_repeating_record_under_root(self):
        reader = _reader_for_bytes(
            b"<root><item><ad>Ali</ad></item><item><ad>Ayse</ad></item></root>"
        )
        source = XmlStreamSource(reader, {"mode": "path", "value": ["item"]})
        records = list(source.iter_records(1000))
        self.assertEqual(records, [{"ad": "Ali"}, {"ad": "Ayse"}])
        self.assertEqual(source.stop_reason, STOP_SOURCE_REAL_EOF)
        self.assertTrue(source.first_segment_matched)

    def test_nested_path_selection(self):
        reader = _reader_for_bytes(
            b"<root><kayitlar><item><ad>Ali</ad></item><item><ad>Ayse</ad></item>"
            b"</kayitlar></root>"
        )
        source = XmlStreamSource(reader, {"mode": "path", "value": ["kayitlar", "item"]})
        records = list(source.iter_records(1000))
        self.assertEqual(records, [{"ad": "Ali"}, {"ad": "Ayse"}])

    def test_multiple_containers_all_contribute_records(self):
        # "TEK bir container'i bul" varsayimi YOK -- birden fazla container
        # varsa HEPSININ altindaki eslesen kayitlar toplanmali.
        reader = _reader_for_bytes(
            b"<root>"
            b"<grup><item><ad>A</ad></item></grup>"
            b"<grup><item><ad>B</ad></item></grup>"
            b"</root>"
        )
        source = XmlStreamSource(reader, {"mode": "path", "value": ["grup", "item"]})
        records = list(source.iter_records(1000))
        self.assertEqual(records, [{"ad": "A"}, {"ad": "B"}])

    def test_namespace_local_name_matching(self):
        xml = (
            '<root xmlns:ns="http://ornek.com/ns">'
            '<ns:item id="1"><ad>Ali</ad></ns:item>'
            "</root>"
        ).encode("utf-8")
        reader = _reader_for_bytes(xml)
        source = XmlStreamSource(reader, {"mode": "path", "value": ["item"]})
        records = list(source.iter_records(1000))
        self.assertEqual(records, [{"@id": "1", "ad": "Ali"}])

    def test_namespace_exact_clark_notation_matching(self):
        xml = (
            '<root xmlns:ns="http://ornek.com/ns">'
            "<ns:item><ad>Ali</ad></ns:item>"
            "<item><ad>DigerNamespace</ad></item>"
            "</root>"
        ).encode("utf-8")
        reader = _reader_for_bytes(xml)
        source = XmlStreamSource(
            reader, {"mode": "path", "value": ["{http://ornek.com/ns}item"]}
        )
        records = list(source.iter_records(1000))
        # Yalnizca TAM Clark notation eslesmesi -- namespace'siz "item" HARIC.
        self.assertEqual(records, [{"ad": "Ali"}])

    def test_attribute_text_child_and_repeated_child_conversion(self):
        reader = _reader_for_bytes(
            b'<root><item id="7"><ad>Ali</ad><etiket>a</etiket><etiket>b</etiket>'
            b"</item></root>"
        )
        source = XmlStreamSource(reader, {"mode": "path", "value": ["item"]})
        records = list(source.iter_records(1000))
        self.assertEqual(records, [{"@id": "7", "ad": "Ali", "etiket": ["a", "b"]}])

    def test_turkish_unicode_preserved(self):
        original = "Türkçe test: şğüçöı ĞÜŞİÖÇ"
        xml = f"<root><item><ad>{original}</ad></item></root>".encode("utf-8")
        reader = _reader_for_bytes(xml)
        source = XmlStreamSource(reader, {"mode": "path", "value": ["item"]})
        records = list(source.iter_records(1000))
        self.assertEqual(records, [{"ad": original}])

    def test_empty_root_zero_records(self):
        reader = _reader_for_bytes(b"<root></root>")
        source = XmlStreamSource(reader, {"mode": "path", "value": ["item"]})
        records = list(source.iter_records(1000))
        self.assertEqual(records, [])
        self.assertEqual(source.stop_reason, STOP_SOURCE_REAL_EOF)
        self.assertFalse(source.first_segment_matched)

    def test_container_present_but_no_matching_children(self):
        reader = _reader_for_bytes(b"<root><kayitlar></kayitlar></root>")
        source = XmlStreamSource(reader, {"mode": "path", "value": ["kayitlar", "item"]})
        records = list(source.iter_records(1000))
        self.assertEqual(records, [])
        self.assertEqual(source.stop_reason, STOP_SOURCE_REAL_EOF)
        # kayitlar (yolun ilk parcasi) en az bir kez goruldu -- bu "yanlis
        # secici" degil, "gercekten bos container" durumudur.
        self.assertTrue(source.first_segment_matched)

    def test_wrong_selector_never_matches(self):
        reader = _reader_for_bytes(b"<root><foo><ad>Ali</ad></foo></root>")
        source = XmlStreamSource(reader, {"mode": "path", "value": ["item"]})
        records = list(source.iter_records(1000))
        self.assertEqual(records, [])
        self.assertFalse(source.first_segment_matched)

    def test_malformed_unclosed_xml_rejected(self):
        reader = _reader_for_bytes(b"<root><item><ad>Ali</ad></root>")
        source = XmlStreamSource(reader, {"mode": "path", "value": ["item"]})
        records = list(source.iter_records(1000))
        self.assertEqual(records, [])
        self.assertEqual(source.stop_reason, STOP_PARSE_ERROR)
        self.assertEqual(source.error_type_name, "ParseError")

    def test_record_without_any_field_rejected_same_as_small_parser(self):
        reader = _reader_for_bytes(b"<root><item/></root>")
        source = XmlStreamSource(reader, {"mode": "path", "value": ["item"]})
        records = list(source.iter_records(1000))
        self.assertEqual(records, [])
        self.assertEqual(source.stop_reason, STOP_PARSE_ERROR)

    def test_mixed_content_rejected_same_as_small_parser(self):
        reader = _reader_for_bytes(b"<root><item>metin<alt>1</alt></item></root>")
        source = XmlStreamSource(reader, {"mode": "path", "value": ["item"]})
        records = list(source.iter_records(1000))
        self.assertEqual(records, [])
        self.assertEqual(source.stop_reason, STOP_PARSE_ERROR)

    def test_preview_record_limit(self):
        xml = b"<root>" + b"".join(
            f"<item><ad>k{i}</ad></item>".encode() for i in range(100)
        ) + b"</root>"
        reader = _reader_for_bytes(xml)
        source = XmlStreamSource(reader, {"mode": "path", "value": ["item"]})
        records = list(source.iter_records(10))
        self.assertEqual(len(records), 10)
        self.assertEqual(source.stop_reason, "kayit_siniri")

    def test_preview_byte_budget_cuts_mid_record_no_partial_record_written(self):
        xml = b"<root>" + b"".join(
            f"<item><ad>kayit-{i}-biraz-uzunca-metin-doldurma</ad></item>".encode()
            for i in range(300)
        ) + b"</root>"
        reader = _reader_for_bytes(xml, budget=150)  # kucuk butce, ortada kesecek
        source = XmlStreamSource(reader, {"mode": "path", "value": ["item"]})
        records = list(source.iter_records(10 ** 9))
        self.assertGreater(len(records), 0)
        self.assertLess(len(records), 300)
        # Butce, "ayristirma hatasi" degil, bir bütçe/onizleme siniri
        # olarak siniflandirilmali (bkz. modul docstring'i).
        self.assertEqual(source.stop_reason, STOP_BYTE_BUDGET)
        self.assertTrue(reader.budget_hit)
        # Her kayit tam olmali (yarim kalan bir "ad" metni asla gorunmemeli).
        for rec in records:
            self.assertTrue(rec["ad"].startswith("kayit-"))
            self.assertIn("biraz-uzunca-metin-doldurma", rec["ad"])

    def test_max_depth_limit(self):
        reader = _reader_for_bytes(
            b"<root><item><a><b><c>deep</c></b></a></item></root>"
        )
        source = XmlStreamSource(reader, {"mode": "path", "value": ["item"]}, max_depth=1)
        records = list(source.iter_records(1000))
        self.assertEqual(records, [])
        self.assertEqual(source.stop_reason, STOP_RECORD_TOO_DEEP)

    def test_max_record_bytes_limit(self):
        reader = _reader_for_bytes(
            ("<root><item><ad>" + ("x" * 5000) + "</ad></item></root>").encode("utf-8")
        )
        source = XmlStreamSource(
            reader, {"mode": "path", "value": ["item"]}, max_record_bytes=100,
        )
        records = list(source.iter_records(1000))
        self.assertEqual(records, [])
        self.assertEqual(source.stop_reason, STOP_RECORD_TOO_LARGE)

    def test_elements_cleared_and_removed_no_growing_element_count(self):
        # "Milyonlarca bos element referansi birikmemeli" iddiasini
        # dogrudan Element nesnelerinin GERCEKTEN serbest birakildigini
        # olcerek kanitlar (yalnizca liste-yok kontrolu degil).
        n = 5000
        xml = b"<root><kayitlar>" + b"".join(
            f"<item><ad>kayit-{i}</ad></item>".encode() for i in range(n)
        ) + b"</kayitlar></root>"
        reader = _reader_for_bytes(xml)
        source = XmlStreamSource(reader, {"mode": "path", "value": ["kayitlar", "item"]})

        gc.collect()
        before = sum(1 for o in gc.get_objects() if isinstance(o, ET.Element))

        count = 0
        for _ in source.iter_records(10 ** 9):
            count += 1
        self.assertEqual(count, n)

        gc.collect()
        after = sum(1 for o in gc.get_objects() if isinstance(o, ET.Element))
        # n=5000 kayit islendi ama bellekte kalan Element sayisi bunun
        # CO<K> ALTINDA olmali (buyumeyen, sabit kucuklukte bir kalinti).
        self.assertLess(after - before, 200)

        # XmlStreamSource'un KENDISINDE kayit sayisiyla buyuyen bir liste
        # OLMAMALI (element_kind_counts sabit anahtarli kucuk bir sozluktur).
        for name, value in vars(source).items():
            if isinstance(value, list):
                self.fail(f"XmlStreamSource.{name} bir liste olmamali (RAM'de birikme riski)")


class TestImportJobXml(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def test_full_transfer_not_capped_at_1000_records(self):
        n = 5000
        text = "<root><kayitlar>" + "".join(
            f"<item><ad>kayit-{i}</ad></item>" for i in range(n)
        ) + "</kayitlar></root>"
        src = _write_xml(self.tmp.name, "buyuk.xml", text)
        job = ImportJob(
            src, os.path.join(self.tmp.name, "out"),
            {"mode": "path", "value": ["kayitlar", "item"]}, "full", source_format="xml",
        )
        job.run()
        self.assertEqual(job.outcome, OUTCOME_FULL_COMPLETE)
        self.assertEqual(job.completed_count, n)
        self.assertGreater(job.completed_count, 1000)
        manifest = read_manifest(job.manifest_path)
        self.assertTrue(manifest["tamamlandi_mi"])
        self.assertEqual(manifest["kaynak_format"], "xml")
        reader = RecordReader(os.path.join(job.out_dir, "kayitlar.jsonl"), os.path.join(job.out_dir, "kayitlar.idx"))
        self.assertEqual(reader.record_count(), n)
        self.assertEqual(reader.read_record(0), {"ad": "kayit-0"})
        self.assertEqual(reader.read_record(n - 1), {"ad": f"kayit-{n - 1}"})

    def test_preview_never_marked_complete(self):
        text = "<root>" + "".join(f"<item><ad>{i}</ad></item>" for i in range(100)) + "</root>"
        src = _write_xml(self.tmp.name, "onizleme.xml", text)
        job = ImportJob(
            src, os.path.join(self.tmp.name, "out"),
            {"mode": "path", "value": ["item"]}, "preview", source_format="xml",
            preview_max_records=10,
        )
        job.run()
        self.assertEqual(job.outcome, OUTCOME_PREVIEW)
        self.assertEqual(job.completed_count, 10)
        self.assertFalse(read_manifest(job.manifest_path)["tamamlandi_mi"])

    def test_wrong_selector_outcome_and_no_data_leak(self):
        src = _write_xml(self.tmp.name, "yanlis.xml", "<root><foo><ad>gizli-deger</ad></foo></root>")
        job = ImportJob(
            src, os.path.join(self.tmp.name, "out"),
            {"mode": "path", "value": ["item"]}, "full", source_format="xml",
        )
        job.run()
        self.assertEqual(job.outcome, OUTCOME_TARGET_NOT_FOUND)
        self.assertEqual(job.completed_count, 0)
        self.assertNotIn("gizli-deger", job.selector_error_detail)

    def test_malformed_xml_outcome(self):
        src = _write_xml(self.tmp.name, "bozuk.xml", "<root><item><ad>Ali</ad></root>")
        job = ImportJob(
            src, os.path.join(self.tmp.name, "out"),
            {"mode": "path", "value": ["item"]}, "full", source_format="xml",
        )
        job.run()
        self.assertEqual(job.outcome, OUTCOME_PARSE_ERROR)
        self.assertFalse(read_manifest(job.manifest_path)["tamamlandi_mi"])

    def test_depth_limit_outcome(self):
        src = _write_xml(self.tmp.name, "derin.xml", "<root><item><a><b><c>deep</c></b></a></item></root>")
        job = ImportJob(
            src, os.path.join(self.tmp.name, "out"),
            {"mode": "path", "value": ["item"]}, "full", source_format="xml",
            max_depth=1,
        )
        job.run()
        self.assertEqual(job.outcome, OUTCOME_LIMIT_REACHED)

    def test_cancel_mid_transfer_keeps_partial_usable_store(self):
        n = 500
        text = "<root>" + "".join(f"<item><ad>{i}</ad></item>" for i in range(n)) + "</root>"
        src = _write_xml(self.tmp.name, "iptal.xml", text)
        job = ImportJob(
            src, os.path.join(self.tmp.name, "out"),
            {"mode": "path", "value": ["item"]}, "full", source_format="xml",
        )

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
        self.assertEqual(reader.record_count(), 21)
        self.assertFalse(read_manifest(job.manifest_path)["tamamlandi_mi"])

    def test_write_error_keeps_store_consistent(self):
        n = 100
        text = "<root>" + "".join(f"<item><ad>{i}</ad></item>" for i in range(n)) + "</root>"
        src = _write_xml(self.tmp.name, "hata.xml", text)
        job = ImportJob(
            src, os.path.join(self.tmp.name, "out"),
            {"mode": "path", "value": ["item"]}, "full", source_format="xml",
        )

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

    def test_old_json_store_manifest_still_opens(self):
        # Bu XML ozelligi eklenmeden ONCEKI bir JSON deposunun manifest'i
        # (kaynak_format zaten "json" olarak yaziliyordu) hala sorunsuz
        # okunabilmeli -- XML destegi JSON/CSV manifest semasini bozmadi.
        src = _write_xml(self.tmp.name, "eski.json", "")  # icerik onemsiz, sadece format kontrolu
        job = ImportJob(
            os.path.join(self.tmp.name, "j.json"),
            os.path.join(self.tmp.name, "out"),
            {"mode": "root_array"}, "full", source_format="json",
        )
        with open(job.source_path, "w", encoding="utf-8") as f:
            f.write('[{"a": 1}, {"a": 2}]')
        job.run()
        manifest = read_manifest(job.manifest_path)
        self.assertEqual(manifest["kaynak_format"], "json")
        self.assertTrue(manifest["tamamlandi_mi"])


def _pump(mw, seconds=8.0):
    end = time.time() + seconds
    while time.time() < end:
        mw.root.update()
        time.sleep(0.02)
        if not mw._busy:
            break


MSG = "XML disk modu Base64 testi"
ENCODED = base64.b64encode(MSG.encode("utf-8")).decode("ascii")
WRAPPED = f"B64:{ENCODED}:END"


class TestGuiXmlDiskMode(unittest.TestCase):
    """Sentetik (gerçek D: diski KULLANILMAYAN) bir XML deposuyla GUI'nin
    sayfalama, satıra gitme, arama, sıralama ve seçili satır Base64 akışını
    doğrular. XML kayıtları (JSON'daki 'nesne' kaydı gibi) dict biçiminde
    depolandığı için table_view/disk_search/disk_sorting zaten var olan
    genel (dict-kaydı) yolu kullanır -- CSV'nin aksine hiçbir yeni
    known_columns mekanizmasına ihtiyaç YOKTUR."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        from gui.main_window import MainWindow
        self.mw = MainWindow()
        self.addCleanup(self.mw.root.destroy)

    def _build_xml_store(self, n=1200):
        parts = []
        for i in range(n):
            not_val = WRAPPED if i == 999 else "x"
            parts.append(f"<item><id>{i}</id><isim>kisi-{i}</isim><not>{not_val}</not></item>")
        text = "<root><kayitlar>" + "".join(parts) + "</kayitlar></root>"
        src = _write_xml(self.tmp.name, "buyukce.xml", text)
        out_root = os.path.join(self.tmp.name, "cikti")
        job = ImportJob(
            src, out_root, {"mode": "path", "value": ["kayitlar", "item"]}, "full",
            source_format="xml",
        )
        job.run()
        self.assertEqual(job.outcome, OUTCOME_FULL_COMPLETE)
        return job, n

    def test_paging_goto_search_sort_and_decode(self):
        job, n = self._build_xml_store()

        from gui import dialogs
        original_ask = dialogs.ask_import_config

        def fake_ask(parent):
            return {
                "source": job.source_path, "out_dir": job.out_root_dir, "mode": "full",
                "source_format": "xml", "selector": {"mode": "path", "value": ["kayitlar", "item"]},
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

        # Sayfalama: 1200 kayit / 500 sayfa boyutu -> 3 sayfa
        self.assertEqual(self.mw.table_view.page_count(), 3)

        # Satira git: son kayit
        self.mw.goto_var.set(str(n))
        self.mw._on_goto()
        _pump(self.mw)
        self.assertEqual(self.mw.table_view.selected_row_id(), n - 1)

        # Arama
        self.mw.search_var.set("kisi-999")
        self.mw._on_search()
        _pump(self.mw, seconds=10.0)
        self.assertIsNotNone(self.mw.match_store)
        self.assertGreaterEqual(self.mw.match_store.count(), 1)

        # Siralama: gercek alan adiyla ("isim") azalan sirala.
        self.mw._refresh_sort_columns()
        self.assertIn("isim", list(self.mw.sort_column_combo["values"]))
        self.mw.sort_column_var.set("isim")
        self.mw.sort_dir_var.set("Azalan")
        self.mw._on_sort()
        _pump(self.mw, seconds=10.0)
        first_children = self.mw.table_view.tree.get_children()
        first_values = self.mw.table_view.tree.item(first_children[0], "values")
        columns = self.mw.table_view.current_page_columns
        isim_col_index = 1 + columns.index("isim")
        self.assertEqual(first_values[isim_col_index], "kisi-999")

        # Kaynak sirasina don, sonra WRAPPED Base64 hucresini (id=999) coz.
        self.mw._on_return_to_source_order()
        _pump(self.mw)
        self.mw.goto_var.set("1000")
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

        self.assertIn("isim", captured["columns_seen"])
        self.assertEqual(captured["decoded_text"], MSG)


if __name__ == "__main__":
    unittest.main()
