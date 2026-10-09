"""Disk modu harici sıralamasını doğrular: algoritma seviyesinde (çok parçalı
+ çok turlu birleştirme, artan/azalan, kararlılık, MISSING/None/NaN, Decimal/
büyük tamsayı, değişken kolon sayısı, boş depo, iptal, hata) ve GUI
kablolaması seviyesinde (sayfalama/satıra git/arama eşleşmesi/decoder
sıralama sonrası doğru kaydı kullanır, kaynak sırasına dönüş, iptal/hata
sonrası önceki görünümün korunması).
"""
import math
import os
import tempfile
import time
import unittest
from decimal import Decimal

from algorithms import disk_sorting
from gui.main_window import MainWindow
from streaming_pilot.disk_store import RecordReader, RecordWriter


def _build_store(tmpdir, records, name="a"):
    jsonl_path = os.path.join(tmpdir, f"kayitlar_{name}.jsonl")
    index_path = os.path.join(tmpdir, f"kayitlar_{name}.idx")
    with RecordWriter(jsonl_path, index_path) as writer:
        for r in records:
            writer.write_record(r)
        writer.flush()
    return RecordReader(jsonl_path, index_path)


class TestDiskSortJobBasics(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def _work_dir(self):
        d = tempfile.mkdtemp(dir=self.tmp.name)
        return d

    def _run_sort(self, records, column="Kolon 1", ascending=True,
                  chunk_max_records=5, max_open_runs=2, current_view_reader=None,
                  **kwargs):
        reader = _build_store(self.tmp.name, records, name=str(time.perf_counter()))
        job = disk_sorting.DiskSortJob(
            reader, current_view_reader, column, ascending, store_generation=0,
            chunk_max_records=chunk_max_records, max_open_runs=max_open_runs, **kwargs
        )
        job.run(self._work_dir())
        return job, reader

    def test_multi_chunk_multi_round_merge_ascending(self):
        # 50 kayit, grup basina 5 kayit (10 parca) ve birlestirmede en fazla
        # 2 dosya acik -> birden fazla parca VE birden fazla birlestirme
        # turu ZORUNLU olarak calisir.
        n = 50
        records = [[n - i] for i in range(n)]  # ["Kolon 1"] = 50,49,...,1
        job, reader = self._run_sort(records, chunk_max_records=5, max_open_runs=2)

        self.assertTrue(job.done)
        self.assertIsNone(job.error)
        self.assertFalse(job.cancel_requested)
        self.assertIsNotNone(job.result_path)
        self.assertGreater(job.merge_rounds_done, 1, "birden fazla birlestirme turu beklenirdi")

        view = disk_sorting.SequenceReader(job.result_path)
        self.assertEqual(view.count(), n)
        ordered_values = [reader.read_record(rid)[0] for rid in view.get_range(0, n)]
        self.assertEqual(ordered_values, list(range(1, n + 1)))

    def test_descending_order(self):
        records = [[i] for i in range(20)]
        job, reader = self._run_sort(records, ascending=False, chunk_max_records=4, max_open_runs=2)
        view = disk_sorting.SequenceReader(job.result_path)
        ordered_values = [reader.read_record(rid)[0] for rid in view.get_range(0, 20)]
        self.assertEqual(ordered_values, list(range(19, -1, -1)))

    def test_stability_across_chunks(self):
        # Ayni anahtara (5) sahip kayitlar, KUCUK grup boyutu nedeniyle
        # FARKLI parcalara dusecek; birlestirme sonrasi da orijinal (mevcut
        # gorunum) sirasini korumalilar.
        records = []
        for i in range(12):
            records.append([5, f"etiket-{i}"])  # hepsi ayni anahtar (Kolon 1=5)
        job, reader = self._run_sort(records, column="Kolon 1", chunk_max_records=3, max_open_runs=2)
        view = disk_sorting.SequenceReader(job.result_path)
        labels = [reader.read_record(rid)[1] for rid in view.get_range(0, 12)]
        self.assertEqual(labels, [f"etiket-{i}" for i in range(12)])

    def test_missing_none_nan_last_both_directions(self):
        records = [
            [2], [None], [1], ["eksik_alan_icin_bos"],  # bu satirin Kolon 2'si olacak, Kolon 1'i yok denemesi icin ayri ele alalim
        ]
        # Daha acik bir kurulum: bazi kayitlarda Kolon 1 hic yok (kisa kayit).
        records = [[2], [None], [1], []]  # 4. kayit: Kolon 1 tamamen eksik (MISSING)
        job_asc, reader_asc = self._run_sort(list(records), ascending=True, chunk_max_records=2, max_open_runs=2)
        view = disk_sorting.SequenceReader(job_asc.result_path)
        ordered = [reader_asc.read_record(rid) for rid in view.get_range(0, 4)]
        # Once gercek degerler (1, 2) sirali, sonra None/MISSING (bu ikisi de novalue) herhangi bir sirada.
        self.assertEqual([ordered[0][0], ordered[1][0]], [1, 2])
        tail_records = ordered[2:]
        self.assertEqual(len(tail_records), 2)

        job_desc, reader_desc = self._run_sort(list(records), ascending=False, chunk_max_records=2, max_open_runs=2)
        view2 = disk_sorting.SequenceReader(job_desc.result_path)
        ordered2 = [reader_desc.read_record(rid) for rid in view2.get_range(0, 4)]
        # Azalanda da gercek degerler basta (2, 1), novalue'lar yine sonda.
        self.assertEqual([ordered2[0][0], ordered2[1][0]], [2, 1])

    def test_nan_sorts_last_too(self):
        # Not: gerçek disk deposu (simplejson) NaN'ı JSON'a serileştiremez
        # (bu, streaming_pilot/disk_store.py'nin ayrı, önceden var olan bir
        # sınırlamasıdır -- zaten JSON kaynağında da NaN reddedilir, bkz.
        # parsers/json_parser.py). Bu nedenle NaN karşılaştırma kuralını,
        # tam disk deposu round-trip'i olmadan, doğrudan karşılaştırma
        # yardımcılarıyla test ediyoruz.
        nan_key = disk_sorting.make_sort_key(float("nan"), position=1, ascending=True)
        one_key = disk_sorting.make_sort_key(1.0, position=0, ascending=True)
        three_key = disk_sorting.make_sort_key(3.0, position=2, ascending=True)
        ordered = sorted([nan_key, one_key, three_key])
        self.assertEqual(ordered, [one_key, three_key, nan_key])
        self.assertTrue(disk_sorting._is_novalue(float("nan")))

    def test_decimal_and_big_int_preserved_and_ordered_numerically(self):
        big = 123456789012345678901234567890
        records = [
            [Decimal("2.50")], [big], [Decimal("2.5000")], [1],
        ]
        job, reader = self._run_sort(records, chunk_max_records=2, max_open_runs=2)
        view = disk_sorting.SequenceReader(job.result_path)
        ordered = [reader.read_record(rid)[0] for rid in view.get_range(0, 4)]
        # sayisal olarak siralanmis: 1 < 2.50 == 2.5000 < big
        self.assertEqual(ordered[0], 1)
        self.assertIn(ordered[1], (Decimal("2.50"), Decimal("2.5000")))
        self.assertIn(ordered[2], (Decimal("2.50"), Decimal("2.5000")))
        self.assertEqual(ordered[3], big)
        self.assertIsInstance(ordered[3], int)
        # Decimal degerler float'a degil, Decimal olarak korunmus olmali.
        self.assertIsInstance(ordered[1], Decimal)

    def test_variable_column_count_missing_via_kolon_name(self):
        records = [["a", 1], ["b"], ["c", 2, "fazla"]]
        job, reader = self._run_sort(records, column="Kolon 2", chunk_max_records=2, max_open_runs=2)
        view = disk_sorting.SequenceReader(job.result_path)
        ordered = [reader.read_record(rid) for rid in view.get_range(0, 3)]
        # Kolon 2'si olanlar (1, 2) once, olmayan ("b", Kolon 2 eksik) sonda.
        self.assertEqual([r[1] for r in ordered[:2]], [1, 2])
        self.assertEqual(ordered[2], ["b"])

    def test_empty_store_produces_empty_view(self):
        job, reader = self._run_sort([], chunk_max_records=5, max_open_runs=2)
        self.assertTrue(job.done)
        self.assertIsNone(job.error)
        self.assertIsNotNone(job.result_path)
        view = disk_sorting.SequenceReader(job.result_path)
        self.assertEqual(view.count(), 0)

    def test_cancel_during_run_creation_leaves_no_result(self):
        records = [[i] for i in range(30)]
        reader = _build_store(self.tmp.name, records, name="cancel1")
        job = disk_sorting.DiskSortJob(
            reader, None, "Kolon 1", True, store_generation=0,
            chunk_max_records=3, max_open_runs=2,
        )
        calls = {"n": 0}
        original_read = reader.read_record

        def patched_read(i):
            calls["n"] += 1
            if calls["n"] > 5:
                job.request_cancel()
            return original_read(i)

        reader.read_record = patched_read
        work_dir = self._work_dir()
        job.run(work_dir)

        self.assertTrue(job.cancel_requested)
        self.assertTrue(job.done)
        self.assertIsNone(job.result_path)
        self.assertIsNone(job.error)
        # Calisma klasorunde artik gecici parca dosyasi kalmamis olmali.
        remaining = os.listdir(work_dir)
        self.assertEqual(remaining, [])

    def test_oversized_single_key_raises_configurable_error(self):
        huge_text = "x" * 1000
        records = [[huge_text], [1]]
        reader = _build_store(self.tmp.name, records, name="oversize")
        job = disk_sorting.DiskSortJob(
            reader, None, "Kolon 1", True, store_generation=0,
            max_key_bytes=100,  # yapilandirilabilir, kucuk bir sinir
        )
        job.run(self._work_dir())
        self.assertTrue(job.done)
        self.assertIsNotNone(job.error)
        self.assertIsInstance(job.error, disk_sorting.SortConfigError)
        self.assertIsNone(job.result_path)

    def test_resort_uses_current_view_as_stability_base(self):
        # Once "b" harfine gore sirala (esit anahtarli iki kayit olacak
        # sekilde), sonra AYNI anahtara sahip ikinci bir alanda tekrar
        # sirala; esitlik durumunda ONCEKI GORUNUM sirasi korunmali.
        records = [
            ["z", 1], ["y", 1], ["x", 2], ["w", 1],
        ]
        reader = _build_store(self.tmp.name, records, name="resort")
        # 1. sirlama: Kolon 1'e gore (z,y,x,w) -> artan: w,x,y,z
        job1 = disk_sorting.DiskSortJob(reader, None, "Kolon 1", True, store_generation=0)
        job1.run(self._work_dir())
        view1 = disk_sorting.SequenceReader(job1.result_path)
        first_order = [reader.read_record(rid)[0] for rid in view1.get_range(0, 4)]
        self.assertEqual(first_order, ["w", "x", "y", "z"])

        # 2. sirlama: Kolon 2'ye gore (1,1,2,1) -- esit anahtarlar (deger=1)
        # onceki gorunumdeki (w,x,y,z sirasindaki) w,y,z sirasini korumali
        # (x, deger=2 oldugu icin sona gider).
        job2 = disk_sorting.DiskSortJob(reader, view1, "Kolon 2", True, store_generation=0)
        job2.run(self._work_dir())
        view2 = disk_sorting.SequenceReader(job2.result_path)
        second_order = [reader.read_record(rid)[0] for rid in view2.get_range(0, 4)]
        self.assertEqual(second_order, ["w", "y", "z", "x"])


def _pump(mw, seconds=8.0):
    end = time.time() + seconds
    while time.time() < end:
        mw.root.update()
        time.sleep(0.02)
        if not mw._busy:
            break


class TestGuiDiskSort(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.mw = MainWindow()
        self.addCleanup(self.mw.root.destroy)

    def _open_store(self, records, complete=False):
        reader = _build_store(self.tmp.name, records, name="gui")
        self.mw.disk_manifest = {"tamamlandi_mi": complete}
        self.mw.table_view.set_disk_reader(reader, is_complete=complete, total_count=len(records))
        self.mw._set_disk_mode_ui(True)
        self.mw._refresh_sort_columns()
        self.mw._update_page_label()

    def test_sort_then_paging_goto_search_decode_use_correct_records(self):
        # 20 kayit; Base64 icerigi ilk kayitta ("z" ile basliyor, en sona
        # gidecek sekilde artan sirada).
        import base64
        msg = b"siralama sonrasi decode testi"
        encoded = base64.b64encode(msg).decode("ascii")
        records = []
        for i in range(20):
            records.append([chr(ord('z') - i), i, encoded if i == 0 else ""])
        self._open_store(records)

        self.mw.sort_column_var.set("Kolon 1")
        self.mw.sort_dir_var.set("Artan")
        self.mw._on_sort()
        _pump(self.mw)

        self.assertIsNotNone(self.mw.table_view.disk_view_reader)
        # records[i] = [chr(ord('z')-i), ...]; i=0..19 -> karakterler 'z'..'g'.
        # Artan sirada en kucuk karakter 'g' (i=19) ilk satirda olmali.
        first_page = self.mw.table_view.tree.get_children()
        first_values = self.mw.table_view.tree.item(first_page[0], "values")
        self.assertEqual(first_values[1], "g")

        # Satira git: 20. (son) konum -> orijinal 0. kayit ("z", Base64 iceren) olmali.
        self.mw.goto_var.set("20")
        self.mw._on_goto()
        _pump(self.mw)
        selected_id = self.mw.table_view.selected_row_id()
        self.assertEqual(selected_id, 0)  # kaynak kayit kimligi degismedi

        # Decode: secili (sirali gorunumde SONUNCU, ama KAYNAKTA 0. olan)
        # satirin doğru ham kaydi kullanildigini dogrula.
        from gui import dialogs
        captured = {}
        original_ask = dialogs.ask_base64_config
        original_show = dialogs.show_decode_result

        def fake_ask(parent, columns):
            return {"columns": ["Kolon 3"], "prefix": "", "postfix": "", "apply_to": "joined"}

        def fake_show(parent, decoded_bytes, decoded_text, duration):
            captured["decoded_bytes"] = decoded_bytes

        dialogs.ask_base64_config = fake_ask
        dialogs.show_decode_result = fake_show
        try:
            self.mw._on_decode()
            _pump(self.mw)
        finally:
            dialogs.ask_base64_config = original_ask
            dialogs.show_decode_result = original_show

        self.assertEqual(captured.get("decoded_bytes"), msg)

        # Arama: siralanmis gorunumu izlemeli. "g" (artik ilk satirda) aransin.
        self.mw.search_var.set("g")
        self.mw._on_search()
        _pump(self.mw)
        self.assertIsNotNone(self.mw.match_store)
        first_match_view_position, first_match_record_id = self.mw.match_store.get(0)
        self.assertEqual(first_match_view_position, 0)  # sirali gorunumde ilk satir

    def test_return_to_source_order(self):
        records = [[chr(ord('z') - i)] for i in range(10)]
        self._open_store(records)
        self.mw.sort_column_var.set("Kolon 1")
        self.mw._on_sort()
        _pump(self.mw)
        self.assertIsNotNone(self.mw.table_view.disk_view_reader)

        self.mw._on_return_to_source_order()
        self.assertIsNone(self.mw.table_view.disk_view_reader)
        first_page = self.mw.table_view.tree.get_children()
        first_values = self.mw.table_view.tree.item(first_page[0], "values")
        self.assertEqual(first_values[1], "z")  # kaynak sirasina donuldu

    def test_cancel_sort_keeps_previous_view_usable(self):
        records = [[i] for i in range(200)]
        self._open_store(records)

        self.mw.sort_column_var.set("Kolon 1")
        self.mw._on_sort()
        self.mw._on_cancel_sort()
        _pump(self.mw, seconds=8.0)

        # Iptal sonrasi kaynak gorunum (disk_view_reader None) hala kullanilabilir.
        first_page = self.mw.table_view.tree.get_children()
        self.assertGreater(len(first_page), 0)
        self.assertIn("iptal", self.mw.status_var.get().lower())

    def test_successful_sort_invalidates_old_search_results(self):
        records = [[str(i)] for i in range(10)]
        self._open_store(records)

        self.mw.search_var.set("1")
        self.mw._on_search()
        _pump(self.mw)
        self.assertIsNotNone(self.mw.match_store)

        self.mw.sort_column_var.set("Kolon 1")
        self.mw._on_sort()
        _pump(self.mw)
        self.assertIsNone(self.mw.match_store)


if __name__ == "__main__":
    unittest.main()
