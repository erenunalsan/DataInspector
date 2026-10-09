"""GUI'nin disk modunu (streaming_pilot RecordReader entegrasyonu) sentetik
bir depoyla doğrular: sayfa geçişleri, satıra gitme ve Base64 decoder
bağlantısı. Gerçek dosya taranmaz; gerçek klasör seçme diyaloğu (modal)
tetiklenmez -- yalnızca bir diyalog açıp kapatan gui.dialogs.ask_base64_config
test süresince sabit bir yapılandırma döndürecek şekilde değiştirilir
(monkeypatch); bu, tek gerçekten etkileşimli/bloke edici parçadır.
"""
import base64
import os
import tempfile
import time
import unittest

from gui import dialogs
from gui.main_window import MainWindow
from streaming_pilot.disk_store import RecordReader, RecordWriter, write_manifest

MSG = "GUI disk modu testi"
ENCODED = base64.b64encode(MSG.encode("utf-8")).decode("ascii")
WRAPPED = f"B64:{ENCODED}:END"


def _write_synthetic_store(out_dir: str, complete: bool):
    jsonl_path = os.path.join(out_dir, "kayitlar.jsonl")
    index_path = os.path.join(out_dir, "kayitlar.idx")
    manifest_path = os.path.join(out_dir, "manifest.json")

    records = [
        ["a", 1, True],                                   # 3 eleman (kisa)
        ["b", 2, False, "extra1", "extra2"],                # 5 eleman
        ["c", 3, True, "x", "y", WRAPPED, "z", "son"],       # 8 eleman (bu sayfanin en uzunu)
        ["d", 4],                                            # sonraki sayfa: 2 eleman
        ["e", 5, "orta"],                                     # sonraki sayfa: 3 eleman
        ["f", 6],                                             # sonraki sayfa: 2 eleman
    ]
    with RecordWriter(jsonl_path, index_path) as writer:
        for r in records:
            writer.write_record(r)
        writer.flush()

    write_manifest(
        manifest_path, source_path="sentetik-kaynak.json",
        selector={"mode": "index", "value": 1},
        element_kind_counts={"dizi_pozisyonel": len(records)},
        completed_count=len(records), bytes_read=12345,
        stop_reason="kayit_siniri" if not complete else "dizi_tamamlandi",
        error_type_name=None,
    )
    return jsonl_path, index_path, manifest_path, len(records)


def _pump(mw, seconds=2.0):
    end = time.time() + seconds
    while time.time() < end:
        mw.root.update()
        time.sleep(0.02)
        if not mw._busy:
            break


class TestGuiDiskMode(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.mw = MainWindow()
        self.addCleanup(self.mw.root.destroy)
        # Sayfa gecisini az sayida sentetik kayitla da gercekten test
        # edebilmek icin sayfa boyutunu kucultuyoruz (yalnizca bu test icin).
        self.mw.table_view.page_size = 3

    def _open_store(self, complete: bool):
        jsonl_path, index_path, manifest_path, count = _write_synthetic_store(
            self.tmp.name, complete
        )
        reader = RecordReader(jsonl_path, index_path)
        manifest = {"tamamlandi_mi": complete}
        self.mw.dataset = None
        self.mw.disk_manifest = manifest
        self.mw.table_view.set_disk_reader(reader, is_complete=complete, total_count=count)
        self.mw._set_disk_mode_ui(True)
        self.mw._enable_data_controls()  # gercek "depo acildi" akisinin de yaptigi gibi
        self.mw._update_page_label()
        return count

    def test_first_page_dynamic_columns_no_truncation_missing_padding(self):
        self._open_store(complete=False)
        self.mw.root.update()

        # Sayfa 0 (page_size=3): kayitlar 0,1,2 -> uzunluklar 3,5,8 -> 8 kolon
        self.assertEqual(len(self.mw.table_view.current_page_columns), 8)
        self.assertEqual(
            self.mw.table_view.current_page_columns,
            [f"Kolon {i + 1}" for i in range(8)],
        )

        children = self.mw.table_view.tree.get_children()
        self.assertEqual(len(children), 3)

        # Kayit 0 (["a",1,True], 3 eleman): Kolon 4..8 MISSING (bos metin) olmali,
        # kirpilma/hata YOK.
        vals0 = self.mw.table_view.tree.item(children[0], "values")
        # vals0[0] = "#" pozisyon sutunu, sonra 8 veri kolonu
        self.assertEqual(len(vals0), 1 + 8)
        self.assertEqual(vals0[1], "a")
        self.assertEqual(vals0[2], "1")
        self.assertEqual(vals0[3], "True")
        for i in range(4, 9):
            self.assertEqual(vals0[i], "")  # MISSING -> format_value ile bos metin

        # Kayit 2 (8 eleman, en uzunu): hicbir hucre kirpilmadan gorunur.
        vals2 = self.mw.table_view.tree.item(children[2], "values")
        self.assertEqual(vals2[1], "c")
        self.assertEqual(vals2[8], "son")  # son (8.) kolon kirpilmadan geldi

    def test_page_navigation_changes_columns_for_shorter_records(self):
        self._open_store(complete=False)
        self.mw.root.update()
        self.assertEqual(self.mw.table_view.page_count(), 2)  # 6 kayit / page_size 3

        self.mw._on_next_page()
        _pump(self.mw)

        self.assertEqual(self.mw.table_view.current_page, 1)
        # Sayfa 1: kayitlar 3,4,5 -> uzunluklar 2,3,2 -> 3 kolon
        self.assertEqual(len(self.mw.table_view.current_page_columns), 3)
        children = self.mw.table_view.tree.get_children()
        self.assertEqual(len(children), 3)
        vals = self.mw.table_view.tree.item(children[0], "values")
        self.assertEqual(vals[1], "d")
        self.assertEqual(vals[3], "")  # kayit 3 ["d",4] -> Kolon 3 MISSING

        self.mw._on_prev_page()
        _pump(self.mw)
        self.assertEqual(self.mw.table_view.current_page, 0)

    def test_goto_switches_page_and_selects_row(self):
        self._open_store(complete=False)
        self.mw.root.update()

        self.mw.goto_var.set("5")  # 1-tabanli: kayit index 4 ("e"), sayfa 1'de
        self.mw._on_goto()
        _pump(self.mw)

        self.assertEqual(self.mw.table_view.current_page, 1)
        selected = self.mw.table_view.selected_row_id()
        self.assertEqual(selected, 4)  # 0-tabanli depo indeksi

        # Gecersiz konum acik ve anlasilir sekilde reddedilmeli (cokme yok)
        self.mw.goto_var.set("999")
        self.mw._on_goto()  # messagebox.showerror cagirir; testte pencere kapali kalir, sorun degil
        self.mw.root.update()

    def test_decode_wiring_extracts_correct_cell_and_decodes(self):
        self._open_store(complete=False)
        self.mw.root.update()

        # Kayit 2 (["c",3,True,"x","y",WRAPPED,"z","son"]) sayfa 0'da, WRAPPED "Kolon 6"da.
        self.mw.table_view.tree.selection_set("2")
        self.mw.table_view.tree.focus("2")

        captured = {}
        original_ask = dialogs.ask_base64_config
        original_show = dialogs.show_decode_result

        def fake_ask(parent, columns):
            captured["columns_seen"] = list(columns)
            return {"columns": ["Kolon 6"], "prefix": "B64:", "postfix": ":END", "apply_to": "joined"}

        def fake_show(parent, decoded_bytes, decoded_text, duration):
            captured["decoded_bytes"] = decoded_bytes
            captured["decoded_text"] = decoded_text

        dialogs.ask_base64_config = fake_ask
        dialogs.show_decode_result = fake_show
        try:
            self.mw._on_decode()
            _pump(self.mw)
        finally:
            dialogs.ask_base64_config = original_ask
            dialogs.show_decode_result = original_show

        self.assertEqual(captured["columns_seen"], [f"Kolon {i + 1}" for i in range(8)])
        self.assertEqual(captured["decoded_bytes"], MSG.encode("utf-8"))
        self.assertEqual(captured["decoded_text"], MSG)

    def test_decode_wiring_marker_mode_passes_prefix_mode_to_decoder(self):
        # Regresyon 8: GUI yapilandirmasindaki YENI "prefix_mode" secimi
        # (dialogs.ask_base64_config -> _on_decode -> extract_base64_text)
        # dogru iletiliyor mu? Hucre, kolon numarasina gore DEGISEN dinamik
        # bir onekle sarilmis -- yalnizca "metin ici isaretci" modu bunu
        # dogru cozebilir (starts_with modu farkli oneklerle calismaz).
        marker_msg = "GUI marker modu testi"
        marker_encoded = base64.b64encode(marker_msg.encode("utf-8")).decode("ascii")
        marker_wrapped = f"118380417_0_½_{marker_encoded}"

        jsonl_path = os.path.join(self.tmp.name, "marker_kayitlar.jsonl")
        index_path = os.path.join(self.tmp.name, "marker_kayitlar.idx")
        with RecordWriter(jsonl_path, index_path) as writer:
            writer.write_record([marker_wrapped, "diger-hucre"])
            writer.flush()
        reader = RecordReader(jsonl_path, index_path)
        self.mw.dataset = None
        self.mw.disk_manifest = {"tamamlandi_mi": True}
        self.mw.table_view.set_disk_reader(reader, is_complete=True, total_count=1)
        self.mw._set_disk_mode_ui(True)
        self.mw._enable_data_controls()
        self.mw._update_page_label()
        self.mw.root.update()

        self.mw.table_view.tree.selection_set("0")
        self.mw.table_view.tree.focus("0")

        captured = {}
        original_ask = dialogs.ask_base64_config
        original_show = dialogs.show_decode_result

        def fake_ask(parent, columns):
            return {
                "columns": ["Kolon 1"], "prefix": "½_", "postfix": "",
                "apply_to": "joined", "prefix_mode": "marker",
            }

        def fake_show(parent, decoded_bytes, decoded_text, duration):
            captured["decoded_text"] = decoded_text

        dialogs.ask_base64_config = fake_ask
        dialogs.show_decode_result = fake_show
        try:
            self.mw._on_decode()
            _pump(self.mw)
        finally:
            dialogs.ask_base64_config = original_ask
            dialogs.show_decode_result = original_show

        self.assertEqual(captured["decoded_text"], marker_msg)

    def test_decode_without_selection_warns_not_crashes(self):
        self._open_store(complete=False)
        self.mw.root.update()
        self.mw.table_view.tree.selection_remove(self.mw.table_view.tree.selection())
        # messagebox.showwarning gercek bir modal acar; burada yalnizca
        # cokmedigini/hata firlatmadigini dogruluyoruz.
        try:
            self.mw._on_decode()
        except Exception as e:
            self.fail(f"Secim yokken _on_decode cokmemeli, ama: {e}")

    def test_partial_vs_complete_status_reflected(self):
        count = self._open_store(complete=False)
        self.assertFalse(self.mw.table_view.disk_is_complete)
        self.assertEqual(self.mw.table_view.disk_total_count, count)

        # Ayni depoyu "tamamlandi" olarak da acabilmeliyiz (manifest farkli olsaydi).
        self.mw.table_view.set_disk_reader(
            self.mw.table_view.disk_reader, is_complete=True, total_count=count
        )
        self.assertTrue(self.mw.table_view.disk_is_complete)

    def test_search_and_sort_both_enabled_in_disk_mode(self):
        # Arama VE sıralama artık disk modunda aktiftir; yalnızca kalıcı
        # not (depo kısmi olduğunda) görünür kalır.
        self._open_store(complete=False)
        self.assertEqual(str(self.mw.sort_column_combo["state"]), "readonly")
        self.assertNotEqual(self.mw.disk_mode_note_var.get(), "")
        self.assertIn("TAMAMINI kapsamaz", self.mw.disk_mode_note_var.get())

    def test_normal_mode_reenables_after_disk_mode(self):
        self._open_store(complete=False)
        for widget in self.mw._disk_only_widgets:
            self.assertEqual(str(widget["state"]), "disabled")
        # Kucuk-dosya moduna donusu simule et (gercek _on_fetch_data on_success mantigi)
        self.mw._set_disk_mode_ui(False)
        for widget in self.mw._disk_only_widgets:
            self.assertEqual(str(widget["state"]), "normal")


if __name__ == "__main__":
    unittest.main()
