"""Büyük YAML desteğini doğrular:
  - streaming_pilot/yaml_source.py (düşük seviye, dosya açmadan YamlStreamSource)
  - streaming_pilot/import_job.py'nin YAML dalı (ImportJob(source_format="yaml"))
  - GUI'nin (table_view/main_window) sentetik bir YAML deposuyla sayfalama,
    satıra gitme, arama, sıralama ve Base64 akışı

Gerçek D: diski / harici veri KULLANILMAZ; tamamı sentetik, yerel geçici
dosyalardır.
"""
import base64
import io
import os
import tempfile
import time
import unittest

from streaming_pilot.budgeted_reader import BudgetedBinaryReader
from streaming_pilot.disk_store import RecordReader, read_manifest
import streaming_pilot.disk_store as disk_store_mod
from streaming_pilot.import_job import (
    ImportJob,
    OUTCOME_CANCELLED,
    OUTCOME_FULL_COMPLETE,
    OUTCOME_LIMIT_REACHED,
    OUTCOME_OUTPUT_IO_ERROR,
    OUTCOME_PARSE_ERROR,
    OUTCOME_PREVIEW,
    OUTCOME_TARGET_NOT_FOUND,
    OUTCOME_YAML_UNSUPPORTED_STRUCTURE,
)
from streaming_pilot.yaml_source import (
    STOP_ARRAY_COMPLETE,
    STOP_BYTE_BUDGET,
    STOP_FULLY_DRAINED,
    STOP_PARSE_ERROR,
    STOP_RECORD_TOO_DEEP,
    STOP_RECORD_TOO_LARGE,
    STOP_SOURCE_REAL_EOF,
    STOP_UNSUPPORTED_STRUCTURE,
    YamlSelectorError,
    YamlStreamSource,
)
from parsers.yaml_parser import parse as small_yaml_parse


def _reader_for_text(text: str, budget: int = 2 ** 62) -> BudgetedBinaryReader:
    return BudgetedBinaryReader(io.BytesIO(text.encode("utf-8")), budget)


def _write_yaml(tmp, name, text: str) -> str:
    path = os.path.join(tmp, name)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    return path


class TestYamlStreamSourceBasics(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def test_root_sequence(self):
        reader = _reader_for_text("- a: 1\n- a: 2\n")
        source = YamlStreamSource(reader, {"mode": "root_array"})
        records = list(source.iter_records(1000, drain_to_eof=True))
        self.assertEqual(records, [{"a": 1}, {"a": 2}])
        self.assertEqual(source.stop_reason, STOP_FULLY_DRAINED)

    def test_mapping_field_by_name(self):
        reader = _reader_for_text("meta: 1\nkayitlar:\n  - a: 1\n  - a: 2\n")
        source = YamlStreamSource(reader, {"mode": "name", "value": "kayitlar"})
        records = list(source.iter_records(1000, drain_to_eof=True))
        self.assertEqual(records, [{"a": 1}, {"a": 2}])
        self.assertEqual(source.matched_key_ordinal, 2)

    def test_mapping_field_by_1based_index(self):
        reader = _reader_for_text("meta: 1\nkayitlar:\n  - a: 1\n")
        source = YamlStreamSource(reader, {"mode": "index", "value": 2})
        records = list(source.iter_records(1000, drain_to_eof=True))
        self.assertEqual(records, [{"a": 1}])

    def test_mapping_and_positional_sequence_records(self):
        # Kayitlar hem mapping (dict) hem pozisyonel sequence (list) olabilir.
        reader = _reader_for_text("- a: 1\n- [1, 2, 3]\n")
        source = YamlStreamSource(reader, {"mode": "root_array"})
        records = list(source.iter_records(1000, drain_to_eof=True))
        self.assertEqual(records, [{"a": 1}, [1, 2, 3]])
        self.assertEqual(source.element_kind_counts.get("nesne"), 1)
        self.assertEqual(source.element_kind_counts.get("dizi_pozisyonel"), 1)

    def test_turkish_unicode_preserved(self):
        # Deger tirnaklanir: duz (unquoted) bir skalerde ": " gecmesi
        # zaten YAML'da (gercek safe_load'da da) gecersizdir -- bu test
        # dogrudan veri icerigiyle ilgilidir, bu sozdizimsel kisitla degil.
        original = "Türkçe test: şğüçöı ĞÜŞİÖÇ"
        reader = _reader_for_text(f'- ad: "{original}"\n')
        source = YamlStreamSource(reader, {"mode": "root_array"})
        records = list(source.iter_records(1000, drain_to_eof=True))
        self.assertEqual(records, [{"ad": original}])

    def test_scalar_types_match_safe_load_behavior(self):
        text = (
            "- a: true\n"
            "  b: null\n"
            "  c: 12345678901234567890\n"
            "  d: 3.5\n"
            '  e: "00123"\n'
            "  f: 00123\n"
            "  g: yes\n"
            "  h: no\n"
        )
        reader = _reader_for_text(text)
        source = YamlStreamSource(reader, {"mode": "root_array"})
        records = list(source.iter_records(1000, drain_to_eof=True))
        expected = {
            "a": True, "b": None, "c": 12345678901234567890, "d": 3.5,
            "e": "00123", "f": 83, "g": True, "h": False,
        }
        self.assertEqual(records, [expected])
        # dogrudan safe_load ile de KARSILASTIR (ayni davranis).
        import yaml
        self.assertEqual(yaml.safe_load(text)[0], expected)

    def test_empty_sequence(self):
        reader = _reader_for_text("[]\n")
        source = YamlStreamSource(reader, {"mode": "root_array"})
        records = list(source.iter_records(1000, drain_to_eof=True))
        self.assertEqual(records, [])
        self.assertEqual(source.stop_reason, STOP_FULLY_DRAINED)

    def test_wrong_selector_never_matches(self):
        reader = _reader_for_text("meta: 1\n")
        source = YamlStreamSource(reader, {"mode": "name", "value": "yok"})
        records = list(source.iter_records(1000, drain_to_eof=True))
        self.assertEqual(records, [])
        self.assertIsNone(source.matched_key_ordinal)
        self.assertEqual(source.stop_reason, STOP_SOURCE_REAL_EOF)

    def test_root_not_sequence_or_mapping_raises_selector_error(self):
        reader = _reader_for_text("sadece bir metin\n")
        source = YamlStreamSource(reader, {"mode": "root_array"})
        with self.assertRaises(YamlSelectorError):
            list(source.iter_records(1000, drain_to_eof=True))

    def test_malformed_yaml_reported_as_parse_error(self):
        reader = _reader_for_text("a: [1, 2\n")
        source = YamlStreamSource(reader, {"mode": "name", "value": "a"})
        list(source.iter_records(1000, drain_to_eof=True))
        self.assertEqual(source.stop_reason, STOP_PARSE_ERROR)
        self.assertEqual(source.error_type_name, "ParserError")

    def test_alias_rejected(self):
        reader = _reader_for_text("- a: &x 1\n  b: *x\n")
        source = YamlStreamSource(reader, {"mode": "root_array"})
        records = list(source.iter_records(1000, drain_to_eof=True))
        self.assertEqual(records, [])
        self.assertEqual(source.stop_reason, STOP_UNSUPPORTED_STRUCTURE)
        self.assertEqual(source.error_type_name, "YamlUnsupportedStructureError")

    def test_anchor_without_alias_also_rejected(self):
        reader = _reader_for_text("- a: &x 1\n")
        source = YamlStreamSource(reader, {"mode": "root_array"})
        records = list(source.iter_records(1000, drain_to_eof=True))
        self.assertEqual(records, [])
        self.assertEqual(source.stop_reason, STOP_UNSUPPORTED_STRUCTURE)

    def test_special_tag_timestamp_rejected(self):
        reader = _reader_for_text("- tarih: 2024-01-01\n")
        source = YamlStreamSource(reader, {"mode": "root_array"})
        records = list(source.iter_records(1000, drain_to_eof=True))
        self.assertEqual(records, [])
        self.assertEqual(source.stop_reason, STOP_UNSUPPORTED_STRUCTURE)

    def test_special_tag_binary_rejected(self):
        reader = _reader_for_text("- veri: !!binary |\n    aGVsbG8=\n")
        source = YamlStreamSource(reader, {"mode": "root_array"})
        records = list(source.iter_records(1000, drain_to_eof=True))
        self.assertEqual(records, [])
        self.assertEqual(source.stop_reason, STOP_UNSUPPORTED_STRUCTURE)

    def test_non_string_key_rejected(self):
        reader = _reader_for_text("- 1: bir\n")
        source = YamlStreamSource(reader, {"mode": "root_array"})
        records = list(source.iter_records(1000, drain_to_eof=True))
        self.assertEqual(records, [])
        self.assertEqual(source.stop_reason, STOP_UNSUPPORTED_STRUCTURE)

    def test_multi_document_rejected(self):
        reader = _reader_for_text("---\na:\n  - x: 1\n---\nb: 2\n")
        source = YamlStreamSource(reader, {"mode": "name", "value": "a"})
        records = list(source.iter_records(1000, drain_to_eof=True))
        # Ilk belgedeki kayit(lar) zaten uretilmis olabilir; asil kontrol
        # ikinci belgenin reddedildigidir.
        self.assertEqual(records, [{"x": 1}])
        self.assertEqual(source.stop_reason, STOP_UNSUPPORTED_STRUCTURE)

    def test_no_data_leak_in_unsupported_structure_error_detail(self):
        reader = _reader_for_text("- gizli: &x GIZLI_DEGER_XYZ\n  b: *x\n")
        source = YamlStreamSource(reader, {"mode": "root_array"})
        list(source.iter_records(1000, drain_to_eof=True))
        # error_type_name yalnizca SINIF adidir; gercek deger asla icermez.
        self.assertEqual(source.error_type_name, "YamlUnsupportedStructureError")

    def test_max_depth_limit(self):
        reader = _reader_for_text("- a:\n    b:\n      c:\n        d: deep\n")
        source = YamlStreamSource(reader, {"mode": "root_array"}, max_depth=1)
        records = list(source.iter_records(1000, drain_to_eof=True))
        self.assertEqual(records, [])
        self.assertEqual(source.stop_reason, STOP_RECORD_TOO_DEEP)

    def test_max_record_bytes_limit(self):
        reader = _reader_for_text("- a: " + ("x" * 5000) + "\n")
        source = YamlStreamSource(reader, {"mode": "root_array"}, max_record_bytes=100)
        records = list(source.iter_records(1000, drain_to_eof=True))
        self.assertEqual(records, [])
        self.assertEqual(source.stop_reason, STOP_RECORD_TOO_LARGE)

    def test_preview_record_limit(self):
        text = "".join(f"- a: {i}\n" for i in range(100))
        reader = _reader_for_text(text)
        source = YamlStreamSource(reader, {"mode": "root_array"})
        records = list(source.iter_records(10))
        self.assertEqual(len(records), 10)
        self.assertEqual(source.stop_reason, "kayit_siniri")

    def test_preview_byte_budget_realistic_scale_discards_only_suspect_tail(self):
        # Gercekci olcek: libyaml'in tipik ~16KB dahili tampon boyutunun
        # COK ustunde bir butce/veri kullanilir; boylece "gecis" ile
        # gercek kirpilma NOKTASI ayni civarda kalir (bkz. yaml_source.py
        # modul docstring'indeki "KRITIK butce guvenligi").
        padding = "".join(f"- a: dolgu-{i}\n" for i in range(1500))
        text = padding + "- a: metin-" + ("x" * 2000) + "\n" + "- a: kisa-son\n"
        reader = _reader_for_text(text, budget=16500)
        source = YamlStreamSource(reader, {"mode": "root_array"})
        records = list(source.iter_records(10 ** 9, drain_to_eof=True))

        self.assertGreater(len(records), 1000)  # cok sayida saglam kayit korunmus
        self.assertEqual(source.stop_reason, STOP_BYTE_BUDGET)
        # "kisa-son" (butceden SONRA gelen) kesinlikle YOK.
        self.assertNotIn({"a": "kisa-son"}, records)
        # Kirpilmis/supheli bir "metin-..." kaydi da YOK (ya tamamen
        # okundu ya da hic yazilmadi -- eksik kayit YOK).
        for rec in records:
            val = rec["a"]
            if isinstance(val, str) and val.startswith("metin-"):
                self.fail(f"Kirpilmis olabilecek supheli bir kayit bulundu: {val!r}")
        # Onceki (butceden cok once tamamlanmis) kayitlarin BOZULMADAN
        # korundugunu dogrula.
        self.assertIn({"a": "dolgu-0"}, records)
        self.assertIn({"a": "dolgu-500"}, records)

    def test_no_growing_ram_list_on_source_object(self):
        text = "".join(f"- a: {i}\n" for i in range(2000))
        reader = _reader_for_text(text)
        source = YamlStreamSource(reader, {"mode": "root_array"})
        count = sum(1 for _ in source.iter_records(10 ** 9, drain_to_eof=True))
        self.assertEqual(count, 2000)
        for name, value in vars(source).items():
            if isinstance(value, list):
                self.fail(f"YamlStreamSource.{name} bir liste olmamalı (RAM'de birikme riski)")

    def test_matches_small_parser_representative_output(self):
        text = (
            "- ad: Ali\n"
            "  adres:\n"
            "    il: Ankara\n"
            "  etiketler:\n"
            "    - x\n"
            "    - y\n"
            "  puan: 5\n"
            "- ad: Ayse\n"
            "  puan: null\n"
        )
        small_result = small_yaml_parse(text)
        reader = _reader_for_text(text)
        source = YamlStreamSource(reader, {"mode": "root_array"})
        stream_result = list(source.iter_records(1000, drain_to_eof=True))
        self.assertEqual(stream_result, small_result)


class TestImportJobYaml(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def test_full_transfer_not_capped_at_1000_records(self):
        n = 5000
        text = "kayitlar:\n" + "".join(f"  - ad: kayit-{i}\n" for i in range(n))
        src = _write_yaml(self.tmp.name, "buyuk.yaml", text)
        job = ImportJob(
            src, os.path.join(self.tmp.name, "out"),
            {"mode": "name", "value": "kayitlar"}, "full", source_format="yaml",
        )
        job.run()
        self.assertEqual(job.outcome, OUTCOME_FULL_COMPLETE)
        self.assertEqual(job.completed_count, n)
        self.assertGreater(job.completed_count, 1000)
        manifest = read_manifest(job.manifest_path)
        self.assertTrue(manifest["tamamlandi_mi"])
        self.assertEqual(manifest["kaynak_format"], "yaml")
        reader = RecordReader(os.path.join(job.out_dir, "kayitlar.jsonl"), os.path.join(job.out_dir, "kayitlar.idx"))
        self.assertEqual(reader.record_count(), n)
        self.assertEqual(reader.read_record(0), {"ad": "kayit-0"})
        self.assertEqual(reader.read_record(n - 1), {"ad": f"kayit-{n - 1}"})

    def test_preview_never_marked_complete(self):
        text = "".join(f"- a: {i}\n" for i in range(100))
        src = _write_yaml(self.tmp.name, "onizleme.yaml", text)
        job = ImportJob(
            src, os.path.join(self.tmp.name, "out"),
            {"mode": "root_array"}, "preview", source_format="yaml",
            preview_max_records=10,
        )
        job.run()
        self.assertEqual(job.outcome, OUTCOME_PREVIEW)
        self.assertEqual(job.completed_count, 10)
        self.assertFalse(read_manifest(job.manifest_path)["tamamlandi_mi"])

    def test_wrong_selector_outcome_and_no_data_leak(self):
        src = _write_yaml(self.tmp.name, "yanlis.yaml", "foo: gizli-deger\n")
        job = ImportJob(
            src, os.path.join(self.tmp.name, "out"),
            {"mode": "name", "value": "yok"}, "full", source_format="yaml",
        )
        job.run()
        self.assertEqual(job.outcome, OUTCOME_TARGET_NOT_FOUND)
        self.assertEqual(job.completed_count, 0)
        self.assertNotIn("gizli-deger", job.selector_error_detail)

    def test_malformed_yaml_outcome(self):
        src = _write_yaml(self.tmp.name, "bozuk.yaml", "a: [1, 2\n")
        job = ImportJob(
            src, os.path.join(self.tmp.name, "out"),
            {"mode": "name", "value": "a"}, "full", source_format="yaml",
        )
        job.run()
        self.assertEqual(job.outcome, OUTCOME_PARSE_ERROR)
        self.assertFalse(read_manifest(job.manifest_path)["tamamlandi_mi"])

    def test_unsupported_structure_outcome_alias(self):
        src = _write_yaml(self.tmp.name, "alias.yaml", "- a: &x 1\n  b: *x\n")
        job = ImportJob(
            src, os.path.join(self.tmp.name, "out"),
            {"mode": "root_array"}, "full", source_format="yaml",
        )
        job.run()
        self.assertEqual(job.outcome, OUTCOME_YAML_UNSUPPORTED_STRUCTURE)
        self.assertIsNotNone(job.yaml_error_detail)
        self.assertFalse(read_manifest(job.manifest_path)["tamamlandi_mi"])

    def test_depth_limit_outcome(self):
        src = _write_yaml(self.tmp.name, "derin.yaml", "- a:\n    b:\n      c:\n        d: deep\n")
        job = ImportJob(
            src, os.path.join(self.tmp.name, "out"),
            {"mode": "root_array"}, "full", source_format="yaml",
            max_depth=1,
        )
        job.run()
        self.assertEqual(job.outcome, OUTCOME_LIMIT_REACHED)

    def test_cancel_mid_transfer_keeps_partial_usable_store(self):
        n = 500
        text = "".join(f"- a: {i}\n" for i in range(n))
        src = _write_yaml(self.tmp.name, "iptal.yaml", text)
        job = ImportJob(
            src, os.path.join(self.tmp.name, "out"),
            {"mode": "root_array"}, "full", source_format="yaml",
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
        text = "".join(f"- a: {i}\n" for i in range(n))
        src = _write_yaml(self.tmp.name, "hata.yaml", text)
        job = ImportJob(
            src, os.path.join(self.tmp.name, "out"),
            {"mode": "root_array"}, "full", source_format="yaml",
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
        src = _write_yaml(self.tmp.name, "eski.json", "")
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


MSG = "YAML disk modu Base64 testi"
ENCODED = base64.b64encode(MSG.encode("utf-8")).decode("ascii")
WRAPPED = f"B64:{ENCODED}:END"


class TestGuiYamlDiskMode(unittest.TestCase):
    """Sentetik (gerçek D: diski KULLANILMAYAN) bir YAML deposuyla GUI'nin
    sayfalama, satıra gitme, arama, sıralama ve seçili satır Base64 akışını
    doğrular. YAML kayıtları (JSON'daki 'nesne' kaydı gibi) dict biçiminde
    depolandığı için table_view/disk_search/disk_sorting zaten var olan
    genel (dict-kaydı) yolu kullanır."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        from gui.main_window import MainWindow
        self.mw = MainWindow()
        self.addCleanup(self.mw.root.destroy)

    def _build_yaml_store(self, n=1200):
        lines = ["kayitlar:"]
        for i in range(n):
            not_val = WRAPPED if i == 999 else "x"
            lines.append(f"  - id: {i}")
            lines.append(f"    isim: kisi-{i}")
            lines.append(f'    not: "{not_val}"')
        text = "\n".join(lines) + "\n"
        src = _write_yaml(self.tmp.name, "buyukce.yaml", text)
        out_root = os.path.join(self.tmp.name, "cikti")
        job = ImportJob(
            src, out_root, {"mode": "name", "value": "kayitlar"}, "full",
            source_format="yaml",
        )
        job.run()
        self.assertEqual(job.outcome, OUTCOME_FULL_COMPLETE)
        return job, n

    def test_paging_goto_search_sort_and_decode(self):
        job, n = self._build_yaml_store()

        from gui import dialogs
        original_ask = dialogs.ask_import_config

        def fake_ask(parent):
            return {
                "source": job.source_path, "out_dir": job.out_root_dir, "mode": "full",
                "source_format": "yaml", "selector": {"mode": "name", "value": "kayitlar"},
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

        self.assertEqual(self.mw.table_view.page_count(), 3)

        self.mw.goto_var.set(str(n))
        self.mw._on_goto()
        _pump(self.mw)
        self.assertEqual(self.mw.table_view.selected_row_id(), n - 1)

        self.mw.search_var.set("kisi-999")
        self.mw._on_search()
        _pump(self.mw, seconds=10.0)
        self.assertIsNotNone(self.mw.match_store)
        self.assertGreaterEqual(self.mw.match_store.count(), 1)

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
