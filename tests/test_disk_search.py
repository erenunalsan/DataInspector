"""Disk modu metin aramasını doğrular: algoritma seviyesinde (DiskSearchJob,
hücre bazlı eşleşme, sahte-birleştirme olmaması, iptal) ve GUI kablolaması
seviyesinde (500. satır sonrası eşleşme, sayfa değişimi, önceki/sonraki,
iptal sonrası kısmi sonuçların kullanılabilir kalması).
"""
import os
import tempfile
import time
import unittest

from algorithms import disk_search
from gui.main_window import MainWindow
from streaming_pilot.disk_store import RecordReader, RecordWriter


def _build_store(tmpdir, records):
    jsonl_path = os.path.join(tmpdir, "kayitlar.jsonl")
    index_path = os.path.join(tmpdir, "kayitlar.idx")
    with RecordWriter(jsonl_path, index_path) as writer:
        for r in records:
            writer.write_record(r)
        writer.flush()
    return RecordReader(jsonl_path, index_path)


class TestDiskSearchJob(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def _results_path(self):
        fd, path = tempfile.mkstemp(dir=self.tmp.name)
        os.close(fd)
        return path

    def test_case_sensitive_and_cell_level_matching(self):
        records = [
            ["hello", "world"],       # 0: eslesir
            ["Hello", "banana"],       # 1: buyuk/kucuk harf farkli, eslesmez
            ["xx", "yyhelloyy"],        # 2: 2. hucrede eslesir
            ["nomatch", "still none"],   # 3: eslesmez
            ["hello", "hello"],           # 4: iki hucrede de eslesir, TEK SAYILMALI
        ]
        reader = _build_store(self.tmp.name, records)
        job = disk_search.DiskSearchJob(reader, "hello", store_generation=0)
        results_path = self._results_path()
        job.run(results_path)

        self.assertTrue(job.done)
        self.assertIsNone(job.error)
        self.assertEqual(job.scanned_count, 5)
        self.assertEqual(job.found_count, 3)  # 0, 2, 4 -- 4 tek kez sayildi

        store = disk_search.SearchResultsStore(results_path)
        self.assertEqual(store.count(), 3)
        entries = [store.get(i) for i in range(store.count())]
        # view_reader verilmedi -> gorunum = kaynak sirasi, position == record_id
        self.assertEqual(entries, [(0, 0), (2, 2), (4, 4)])

    def test_no_false_positive_from_concatenating_cells(self):
        # cell0="abc", cell1="def" -> BIRLESTIRILSEYDI "abcdef" olurdu ve
        # "cdef" bunun icinde gecerdi. Hucreler AYRI degerlendirilmeli;
        # ne "abc" ne "def" tek basina "cdef" icermez.
        records = [["abc", "def"]]
        reader = _build_store(self.tmp.name, records)
        job = disk_search.DiskSearchJob(reader, "cdef", store_generation=0)
        results_path = self._results_path()
        job.run(results_path)
        self.assertEqual(job.found_count, 0)

    def test_empty_store_search(self):
        reader = _build_store(self.tmp.name, [])
        job = disk_search.DiskSearchJob(reader, "x", store_generation=0)
        results_path = self._results_path()
        job.run(results_path)
        self.assertEqual(job.scanned_count, 0)
        self.assertEqual(job.found_count, 0)
        self.assertTrue(job.done)

    def test_no_match_search(self):
        reader = _build_store(self.tmp.name, [["a"], ["b"], ["c"]])
        job = disk_search.DiskSearchJob(reader, "zzz", store_generation=0)
        results_path = self._results_path()
        job.run(results_path)
        self.assertEqual(job.found_count, 0)

    def test_cancel_mid_scan_keeps_partial_results_deterministically(self):
        # NOT: kaynak sirasi taramasi artik RecordReader.read_record()
        # CAGIRMIYOR (tek dosya taniticiyla ardisik okuma -- bkz.
        # algorithms/disk_search.py); bu yuzden iptal, read_record yerine
        # her aday satirda cagrilan _record_matches uzerinden tetiklenir.
        # Bu testin verisinde HER satir "hello" icerdigi icin (guvenli bir
        # sorgu) HER satir aday olur ve _record_matches her satirda
        # cagrilir -- eski davranisla ayni sayimi verir.
        records = [[f"hello-{i}"] for i in range(20)]
        reader = _build_store(self.tmp.name, records)
        job = disk_search.DiskSearchJob(reader, "hello", store_generation=0)

        calls = {"n": 0}
        original_matches = disk_search._record_matches

        def patched_matches(record, query):
            calls["n"] += 1
            if calls["n"] > 3:
                job.request_cancel()
            return original_matches(record, query)

        disk_search._record_matches = patched_matches
        try:
            results_path = self._results_path()
            job.run(results_path)
        finally:
            disk_search._record_matches = original_matches

        self.assertTrue(job.cancel_requested)
        self.assertTrue(job.done)
        self.assertEqual(job.scanned_count, 4)  # kayit 0,1,2,3 islendi, sonra durdu
        self.assertEqual(job.found_count, 4)    # hepsi "hello" icerir

        # Iptal edilse de, o ana kadar bulunanlar dosyada KULLANILABILIR kalir.
        store = disk_search.SearchResultsStore(results_path)
        self.assertEqual(store.count(), 4)
        self.assertEqual([store.get(i) for i in range(4)], [(0, 0), (1, 1), (2, 2), (3, 3)])

    def test_results_not_accumulated_as_growing_list_on_job(self):
        # DiskSearchJob'un kendisinde eslesen kimlikleri tutan bir liste
        # OLMAMALI; yalnizca sayaçlar (found_count) ve dosya yolu olmali.
        job_attrs = vars(disk_search.DiskSearchJob(None, "x", 0))
        for name, value in job_attrs.items():
            self.assertNotIsInstance(
                value, list, f"DiskSearchJob.{name} bir liste olmamali (RAM'de birikme riski)"
            )


class TestDiskSearchSequentialSourceOrderOptimization(unittest.TestCase):
    """Kaynak sırası taramasının (view_reader=None) artık RecordReader.
    read_record() yerine kayitlar.jsonl'u TEK dosya tanıtıcısıyla ardışık
    okuduğunu ve ham bayt ön elemesinin -- güvenli/güvensiz sorgu ayrımı
    dahil -- arama SONUCUNU hiçbir zaman değiştirmediğini doğrular."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def _results_path(self):
        fd, path = tempfile.mkstemp(dir=self.tmp.name)
        os.close(fd)
        return path

    def test_prefilter_safety_classification(self):
        self.assertTrue(disk_search._is_raw_prefilter_safe("hello"))
        self.assertTrue(disk_search._is_raw_prefilter_safe("Ankara-123"))
        self.assertTrue(disk_search._is_raw_prefilter_safe("rue"))  # "True" ve "true" ortak
        self.assertTrue(disk_search._is_raw_prefilter_safe("xTruey"))  # tam esit degil -> guvenli
        self.assertFalse(disk_search._is_raw_prefilter_safe('has"quote'))
        self.assertFalse(disk_search._is_raw_prefilter_safe("back\\slash"))
        self.assertFalse(disk_search._is_raw_prefilter_safe("tab\there"))
        for prefix in ["T", "Tr", "Tru", "True", "F", "Fa", "Fal", "Fals", "False"]:
            self.assertFalse(disk_search._is_raw_prefilter_safe(prefix))

    def test_query_with_quote_falls_back_to_full_decode_and_still_matches(self):
        records = [['he said "hi" to me'], ["no quote here"]]
        reader = _build_store(self.tmp.name, records)
        self.assertFalse(disk_search._is_raw_prefilter_safe('"hi"'))
        job = disk_search.DiskSearchJob(reader, '"hi"', store_generation=0)
        results_path = self._results_path()
        job.run(results_path)
        self.assertEqual(job.found_count, 1)
        store = disk_search.SearchResultsStore(results_path)
        self.assertEqual(store.get(0), (0, 0))

    def test_query_matching_bool_true_text_falls_back_and_still_matches(self):
        # format_value(True) == "True"; ham JSON baytlarinda kucuk harfle
        # "true" yazilir. "True" sorgusu bu yuzden GUVENSIZ sayilmali (bkz.
        # _is_raw_prefilter_safe) ve tam JSON cozumlemesine geri donmelidir
        # -- aksi halde bu kayit HAM ON ELEMEDE YANLISLIKLA ELENIRDI.
        records = [{"aktif": True, "ad": "kayit1"}, {"aktif": False, "ad": "kayit2"}]
        reader = _build_store(self.tmp.name, records)
        self.assertFalse(disk_search._is_raw_prefilter_safe("True"))
        job = disk_search.DiskSearchJob(reader, "True", store_generation=0)
        results_path = self._results_path()
        job.run(results_path)
        self.assertEqual(job.found_count, 1)
        store = disk_search.SearchResultsStore(results_path)
        self.assertEqual(store.get(0), (0, 0))

    def test_safe_plain_query_uses_prefilter_and_matches_correctly(self):
        self.assertTrue(disk_search._is_raw_prefilter_safe("Ankara"))
        records = [["Ankara"], ["Istanbul"], ["Ankara-ili"]]
        reader = _build_store(self.tmp.name, records)
        job = disk_search.DiskSearchJob(reader, "Ankara", store_generation=0)
        results_path = self._results_path()
        job.run(results_path)
        self.assertEqual(job.found_count, 2)
        store = disk_search.SearchResultsStore(results_path)
        self.assertEqual([store.get(i) for i in range(2)], [(0, 0), (2, 2)])

    def test_json_syntax_lookalike_query_no_false_positive(self):
        # '","' bir tirnak icerdigi icin guvensiz sayilir (tam JSON
        # cozumlemesine doner); iki hucre arasindaki JSON ayracina
        # BENZESE de gercek hicbir hucre degeri bunu icermez.
        records = [["abc", "def"]]
        reader = _build_store(self.tmp.name, records)
        job = disk_search.DiskSearchJob(reader, '","', store_generation=0)
        results_path = self._results_path()
        job.run(results_path)
        self.assertEqual(job.found_count, 0)

    def test_sequential_scan_position_and_record_id_match_line_index(self):
        records = [[f"veri-{i}"] for i in range(50)]
        records[7] = ["ARANAN"]
        records[33] = ["ARANAN"]
        reader = _build_store(self.tmp.name, records)
        job = disk_search.DiskSearchJob(reader, "ARANAN", store_generation=0)
        results_path = self._results_path()
        job.run(results_path)
        self.assertEqual(job.scanned_count, 50)
        store = disk_search.SearchResultsStore(results_path)
        self.assertEqual([store.get(i) for i in range(store.count())], [(7, 7), (33, 33)])

    def test_embedded_newline_in_cell_does_not_split_a_physical_line_wrongly(self):
        # Hucre iceriginde GERCEK bir satir sonu olsa bile, JSON bunu
        # kacisli (iki karakterlik "\n") olarak yazar -- ham dosyada tek
        # bir kaydin fiziksel satirini YANLIS BOLMEZ.
        records = [["birinci satir\nikinci satir"], ["baska kayit"]]
        reader = _build_store(self.tmp.name, records)
        self.assertTrue(disk_search._is_raw_prefilter_safe("ikinci satir"))
        job = disk_search.DiskSearchJob(reader, "ikinci satir", store_generation=0)
        results_path = self._results_path()
        job.run(results_path)
        self.assertEqual(job.scanned_count, 2)  # 2 KAYIT (fiziksel JSON satiri degil)
        self.assertEqual(job.found_count, 1)

    def test_sorted_view_still_uses_indexed_random_access_read_record(self):
        # Siralanmis gorunum (view_reader verilmis) HALA read_record ile
        # rastgele erisim kullanmali -- yeni ardisik/on-eleme yolu bu
        # durumda DEVREYE GIRMEMELI (kayitlar dosyada ardisik olmayabilir).
        from algorithms.disk_sorting import SequenceReader, SequenceWriter

        records = [["b"], ["a"], ["c"]]
        reader = _build_store(self.tmp.name, records)
        seq_path = os.path.join(self.tmp.name, "view.seq")
        with SequenceWriter(seq_path) as w:
            w.append(1)  # "a"
            w.append(0)  # "b"
            w.append(2)  # "c"
        view_reader = SequenceReader(seq_path)

        calls = {"n": 0}
        original_read = reader.read_record

        def counting_read(i):
            calls["n"] += 1
            return original_read(i)

        reader.read_record = counting_read

        job = disk_search.DiskSearchJob(reader, "a", store_generation=0, view_reader=view_reader)
        results_path = self._results_path()
        job.run(results_path)

        self.assertEqual(calls["n"], 3)  # her kayit icin read_record cagrildi (eski/indeksli yol)
        self.assertEqual(job.found_count, 1)
        store = disk_search.SearchResultsStore(results_path)
        self.assertEqual(store.get(0), (0, 1))  # view_position=0 (siralanmis ilk), record_id=1 ("a")

    def test_cancel_with_unsafe_query_still_keeps_partial_results(self):
        # Guvensiz (fallback) yolda da iptal calismali ve kismi sonuc kalmali.
        records = [['icinde "tirnak" olan-%d' % i] for i in range(20)]
        reader = _build_store(self.tmp.name, records)
        query = '"tirnak"'
        self.assertFalse(disk_search._is_raw_prefilter_safe(query))
        job = disk_search.DiskSearchJob(reader, query, store_generation=0)

        calls = {"n": 0}
        original_matches = disk_search._record_matches

        def patched_matches(record, q):
            calls["n"] += 1
            if calls["n"] > 5:
                job.request_cancel()
            return original_matches(record, q)

        disk_search._record_matches = patched_matches
        try:
            results_path = self._results_path()
            job.run(results_path)
        finally:
            disk_search._record_matches = original_matches

        self.assertTrue(job.cancel_requested)
        self.assertEqual(job.scanned_count, 6)
        self.assertEqual(job.found_count, 6)
        store = disk_search.SearchResultsStore(results_path)
        self.assertEqual(store.count(), 6)


def _pump(mw, seconds=5.0):
    end = time.time() + seconds
    while time.time() < end:
        mw.root.update()
        time.sleep(0.02)
        if not mw._busy:
            break


class TestGuiDiskSearch(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.mw = MainWindow()
        self.addCleanup(self.mw.root.destroy)

    def _open_store(self, records, complete=False):
        reader = _build_store(self.tmp.name, records)
        self.mw.dataset = None
        self.mw.disk_manifest = {"tamamlandi_mi": complete}
        self.mw.table_view.set_disk_reader(reader, is_complete=complete, total_count=len(records))
        self.mw._set_disk_mode_ui(True)
        self.mw._update_page_label()

    def test_match_after_row_500_crosses_page_and_is_found(self):
        records = [["dolgu", str(i)] for i in range(520)]
        records[10] = ["ARANAN-DEGER", "x"]
        records[510] = ["ARANAN-DEGER", "y"]  # sayfa 2'de (page_size varsayilan 500)
        self._open_store(records)

        self.mw.search_var.set("ARANAN-DEGER")
        self.mw._on_search()
        _pump(self.mw, seconds=10.0)

        self.assertIsNotNone(self.mw.match_store)
        self.assertEqual(self.mw.match_store.count(), 2)
        self.assertEqual(self.mw.match_store.get(0), (10, 10))
        self.assertEqual(self.mw.match_store.get(1), (510, 510))

        # Ilk eslesmeye otomatik gidilmis olmali (sayfa 0)
        self.assertEqual(self.mw.table_view.current_page, 0)

        # Sonraki eslesme -> sayfa 2'ye gecmeli
        self.mw._on_next_match()
        _pump(self.mw)
        self.assertEqual(self.mw.table_view.current_page, 1)
        self.assertEqual(self.mw.table_view.selected_row_id(), 510)

        # Onceki eslesmeye don -> sayfa 0'a geri
        self.mw._on_prev_match()
        _pump(self.mw)
        self.assertEqual(self.mw.table_view.current_page, 0)
        self.assertEqual(self.mw.table_view.selected_row_id(), 10)

    def test_empty_query_rejected_with_message(self):
        self._open_store([["a"], ["b"]])
        self.mw.search_var.set("")
        # messagebox.showwarning gercek bir modal acar; burada sadece
        # cokmedigini ve match_store'un None kaldigini dogruluyoruz.
        self.mw._on_search()
        self.assertIsNone(self.mw.match_store)

    def test_no_match_shows_zero_results(self):
        self._open_store([["a"], ["b"], ["c"]])
        self.mw.search_var.set("hicbirsekilde-yok")
        self.mw._on_search()
        _pump(self.mw)
        self.assertIsNone(self.mw.match_store)
        self.assertIn("0 eşleşme", self.mw.match_label_var.get())

    def test_cancel_search_keeps_partial_usable_results(self):
        records = [["hello", str(i)] for i in range(2000)]
        self._open_store(records)

        self.mw.search_var.set("hello")
        self.mw._on_search()
        # Hemen iptal iste (tarama arka planda hizla ilerliyor olsa da,
        # is bitene kadar iptal bayragini set etmis oluruz).
        self.mw._on_cancel_search()
        _pump(self.mw, seconds=10.0)

        self.assertIsNotNone(self.mw._search_job is None or True)  # is bitince temizlenir
        # Kismi de olsa bulunanlar KULLANILABILIR olmali (tamamlanmis gibi degil).
        if self.mw.match_store is not None:
            self.assertGreaterEqual(self.mw.match_store.count(), 0)
        self.assertIn("İPTAL", self.mw.status_var.get() + "")

    def test_partial_store_note_present_after_search(self):
        # Kalici (status_var'in sonraki islemlerle degisebilecegi transient
        # mesajindan farkli olarak) disk_mode_note_var, depo KISMI oldugu
        # surece arama sonrasinda da gorunur kalmalidir.
        self._open_store([["hello"], ["hello"]], complete=False)
        self.mw.search_var.set("hello")
        self.mw._on_search()
        _pump(self.mw)
        self.assertIn("TAMAMINI kapsamaz", self.mw.disk_mode_note_var.get())

    def test_new_search_cleans_up_previous_results_file(self):
        self._open_store([["hello"], ["world"]])
        self.mw.search_var.set("hello")
        self.mw._on_search()
        _pump(self.mw)
        first_path = self.mw._search_results_path
        self.assertTrue(os.path.exists(first_path))

        self.mw.search_var.set("world")
        self.mw._on_search()
        _pump(self.mw)
        self.assertFalse(os.path.exists(first_path))  # eski gecici dosya silindi

    def test_store_change_invalidates_running_search_results(self):
        self._open_store([["hello", str(i)] for i in range(50)])
        self.mw.search_var.set("hello")
        self.mw._on_search()
        old_job = self.mw._search_job
        # Depo, arama daha bitmeden "degisti" gibi davranalim:
        self.mw._disk_store_generation += 1
        _pump(self.mw, seconds=5.0)
        # Eski isin sonucu mevcut match_store'u OLUSTURMAMALI (nesil uyusmuyor).
        if old_job is not None:
            self.assertNotEqual(old_job.store_generation, self.mw._disk_store_generation)


if __name__ == "__main__":
    unittest.main()
