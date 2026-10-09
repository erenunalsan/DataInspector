"""Ana pencere: Dosya Seç / Veriyi Getir ayrımı, İşlenmiş Veriyi Aç (disk
modu), worker+queue orkestrasyonu, arama, sıralama, Base64 çözümleme ve
süre ölçümü gösterimi.

Uzun işlemler (yükleme, disk sayfası okuma, arama, sıralama, Base64
çözümleme) arka plan thread'inde çalışır; sonuç bir queue üzerinden ana
thread'e (Tkinter'a) `after()` ile aktarılır. Tkinter bileşenleri yalnızca
ana thread'de güncellenir. Aynı anda yalnızca tek bir uzun işlem çalışır
(busy bayrağı). Thread kullanımı yalnızca arayüzün donmasını engeller;
Python'ın GIL'i nedeniyle CPU'ya bağlı işlemleri hızlandırmaz.
"""
import os
import queue
import tempfile
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import shutil

import parsers
from parsers import common as parsers_common
from parsers import csv_parser, json_parser, xml_parser, yaml_parser
from algorithms import disk_search
from algorithms import disk_sorting
from algorithms import search as search_algo
from algorithms import sorting as sorting_algo
from decoder import base64_decoder
from gui import dialogs
from gui.table_view import TableView, get_cell_value
from models import MISSING
from streaming_pilot.disk_store import RecordReader, read_manifest
from streaming_pilot.import_job import ImportJob, OUTCOME_FULL_COMPLETE

_SUPPORTED_EXTENSIONS = {".json", ".csv", ".yaml", ".yml", ".xml"}

# Normal (bellek-içi) yükleme yolu dosyayı tamamen belleğe okur; bu sınırın
# üzerindeki dosyalar için "İşlenmiş Veriyi Aç" (disk modu) kullanılmalıdır.
MAX_INMEMORY_BYTES = 300 * 1024 * 1024  # 300 MB

# "İşlenmiş Veriyi Aç" klasör seçme diyaloğu için makineye özgü hiçbir
# başlangıç konumu SABİTLENMEZ (taşınabilirlik); diyalog işletim sisteminin
# kendi varsayılan/son kullanılan konumundan açılır.


def _load_with_timings(path: str):
    """parsers.load()'un aynı adımlarını (okuma/ayrıştırma/normalizasyon)
    her birini ayrı time.perf_counter() ile ölçerek yürütür.

    Dosya boyutu MAX_INMEMORY_BYTES'ı aşıyorsa, sınırsız f.read() denemeden
    önce açıklayıcı bir hata verir. Yine de bir MemoryError oluşursa (ör.
    JSON'un bellekteki nesne grafiği ham metinden çok daha büyük olabildiği
    için), bunu da anlaşılır bir mesaja çevirir.
    """
    ext = os.path.splitext(path)[1].lower()
    if ext not in _SUPPORTED_EXTENSIONS:
        raise parsers_common.ParseError(
            f"Desteklenmeyen dosya uzantısı: '{ext}'. Desteklenenler: "
            ".json, .csv, .yaml/.yml, .xml"
        )

    try:
        size = os.path.getsize(path)
    except OSError as e:
        raise parsers_common.ParseError(f"Dosya boyutu okunamadı: {path} ({e})") from e

    if size > MAX_INMEMORY_BYTES:
        raise parsers_common.ParseError(
            f"Dosya çok büyük ({size / (1024 * 1024):.1f} MB). Bu ekran dosyayı "
            f"tamamen belleğe okur; {MAX_INMEMORY_BYTES // (1024 * 1024)} MB üzeri "
            "dosyalar için 'Büyük Veri Aktar (JSON/CSV/XML/YAML)' ile akışla işleyip "
            "'İşlenmiş Veriyi Aç' ile açmayı deneyin (JSON, CSV, XML ve YAML için)."
        )

    try:
        t0 = time.perf_counter()
        newline = "" if ext == ".csv" else None
        text = parsers_common.read_text_file(path, newline=newline)
        t1 = time.perf_counter()

        known_columns = None
        if ext == ".json":
            records = json_parser.parse(text)
        elif ext == ".csv":
            records, known_columns = csv_parser.parse(text)
        elif ext in (".yaml", ".yml"):
            records = yaml_parser.parse(text)
        else:
            records = xml_parser.parse(text)
        t2 = time.perf_counter()

        dataset = parsers_common.normalize(records, known_columns=known_columns)
        t3 = time.perf_counter()
    except MemoryError as e:
        raise parsers_common.ParseError(
            "Dosya belleğe sığmadı (MemoryError). Bu ekran dosyayı tamamen belleğe "
            "okur; çok büyük dosyalar için 'İşlenmiş Veriyi Aç' ile akışlı işlenmiş "
            "bir depoyu açmayı deneyin."
        ) from e

    timings = {
        "okuma": t1 - t0,
        "ayristirma": t2 - t1,
        "normalizasyon": t3 - t2,
        "toplam": t3 - t0,
    }
    return dataset, timings


class MainWindow:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("DataInspector")
        self.root.geometry("1000x650")

        self.dataset = None
        self.selected_path = None
        self.matches = []
        self.match_index = -1
        self.disk_manifest = None
        self._disk_mode_active = False
        self._has_data = False  # ilk basarili yukleme/aktarim sonrasi True olur

        # Disk modu arama durumu
        self._search_job = None
        self._search_results_path = None
        self.match_store = None
        self._disk_store_generation = 0

        # Disk modu sıralama durumu
        self._sort_job = None
        self._sort_work_dir = None          # AKTİF görünümü destekleyen klasör (varsa)
        self._pending_sort_work_dir = None    # sürmekte olan işin YENİ klasörü (henüz etkin değil)

        # Büyük JSON aktarım durumu
        self._import_job = None

        self._work_queue = queue.Queue()
        self._busy = False
        self._busy_widgets = []
        self._disk_only_widgets = []  # şu an boş; disk modunda ayrıca pasifleştirilecek widget yok

        self._build_widgets()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    # ------------------------------------------------------------------
    def _build_widgets(self):
        root = self.root

        # -- Dosya -----------------------------------------------------
        file_frame = ttk.LabelFrame(root, text="Dosya")
        file_frame.pack(fill="x", padx=8, pady=(6, 4))
        btn_select = ttk.Button(file_frame, text="Dosya Seç", command=self._on_select_file)
        btn_select.pack(side="left", padx=4, pady=4)
        self.path_var = tk.StringVar(value="(dosya seçilmedi)")
        ttk.Label(file_frame, textvariable=self.path_var, foreground="#444").pack(
            side="left", padx=8, fill="x", expand=True
        )
        btn_fetch = ttk.Button(file_frame, text="Veriyi Getir", command=self._on_fetch_data)
        btn_fetch.pack(side="left", padx=4, pady=4)

        # -- Büyük Veri --------------------------------------------------
        big_data_frame = ttk.LabelFrame(root, text="Büyük Veri")
        big_data_frame.pack(fill="x", padx=8, pady=4)
        btn_import_json = ttk.Button(
            big_data_frame, text="Büyük Veri Aktar (JSON/CSV/XML/YAML)", command=self._on_import_large_json
        )
        btn_import_json.pack(side="left", padx=4, pady=4)
        btn_cancel_import = ttk.Button(
            big_data_frame, text="Aktarımı İptal Et", command=self._on_cancel_import, state="disabled"
        )
        btn_cancel_import.pack(side="left", padx=4, pady=4)
        self._btn_cancel_import = btn_cancel_import
        btn_open_processed = ttk.Button(
            big_data_frame, text="İşlenmiş Veriyi Aç", command=self._on_open_processed_data
        )
        btn_open_processed.pack(side="left", padx=4, pady=4)

        # -- Arama ---------------------------------------------------------
        search_frame = ttk.LabelFrame(root, text="Arama")
        search_frame.pack(fill="x", padx=8, pady=4)
        ttk.Label(search_frame, text="Ara (Aa duyarlı):").pack(side="left", padx=(4, 0))
        self.search_var = tk.StringVar()
        search_entry = ttk.Entry(search_frame, textvariable=self.search_var, width=25)
        search_entry.pack(side="left", padx=4)
        btn_search = ttk.Button(search_frame, text="Ara", command=self._on_search)
        btn_search.pack(side="left")
        btn_prev_match = ttk.Button(search_frame, text="◀ Önceki", command=self._on_prev_match)
        btn_prev_match.pack(side="left", padx=(8, 0))
        btn_next_match = ttk.Button(search_frame, text="Sonraki ▶", command=self._on_next_match)
        btn_next_match.pack(side="left", padx=4)
        btn_cancel_search = ttk.Button(
            search_frame, text="Aramayı İptal Et", command=self._on_cancel_search, state="disabled"
        )
        btn_cancel_search.pack(side="left", padx=(8, 0))
        self._btn_cancel_search = btn_cancel_search
        self.match_label_var = tk.StringVar(value="")
        ttk.Label(search_frame, textvariable=self.match_label_var).pack(side="left", padx=8)

        # -- Sıralama --------------------------------------------------------
        sort_frame = ttk.LabelFrame(root, text="Sıralama")
        sort_frame.pack(fill="x", padx=8, pady=4)
        ttk.Label(sort_frame, text="Kolon:").pack(side="left", padx=(4, 0))
        self.sort_column_var = tk.StringVar()
        self.sort_column_combo = ttk.Combobox(
            sort_frame, textvariable=self.sort_column_var, state="readonly", width=20
        )
        self.sort_column_combo.pack(side="left", padx=4)
        self.sort_dir_var = tk.StringVar(value="Artan")
        sort_dir_combo = ttk.Combobox(
            sort_frame, textvariable=self.sort_dir_var, state="readonly",
            values=["Artan", "Azalan"], width=8,
        )
        sort_dir_combo.pack(side="left", padx=4)
        btn_sort = ttk.Button(sort_frame, text="Sırala", command=self._on_sort)
        btn_sort.pack(side="left", padx=4)
        btn_cancel_sort = ttk.Button(
            sort_frame, text="Sıralamayı İptal Et", command=self._on_cancel_sort, state="disabled"
        )
        btn_cancel_sort.pack(side="left", padx=(4, 0))
        self._btn_cancel_sort = btn_cancel_sort
        btn_return_source = ttk.Button(
            sort_frame, text="Kaynak Sırasına Dön", command=self._on_return_to_source_order,
            state="disabled",
        )
        btn_return_source.pack(side="left", padx=(8, 0))
        self._btn_return_source = btn_return_source

        # Genel, kalıcı bir durum notu (ör. disk modunda kısmi depo uyarısı
        # ya da veri henüz yüklenmediği için hangi işlemlerin kapalı olduğu).
        note_frame = ttk.Frame(root)
        note_frame.pack(fill="x", padx=8)
        self.disk_mode_note_var = tk.StringVar(value="")
        ttk.Label(note_frame, textvariable=self.disk_mode_note_var, foreground="#8a5a00").pack(side="left")
        self.data_required_note_var = tk.StringVar(
            value="Arama/sıralama/satıra git/Base64 için önce bir dosya yükleyin ya da işlenmiş veri açın."
        )
        ttk.Label(note_frame, textvariable=self.data_required_note_var, foreground="#8a5a00").pack(
            side="left", padx=(12, 0)
        )

        self.table_view = TableView(root)
        self.table_view.frame.pack(fill="both", expand=True, padx=8, pady=4)

        # -- Satıra Git (sayfalama dahil) -----------------------------------
        nav_frame = ttk.LabelFrame(root, text="Satıra Git")
        nav_frame.pack(fill="x", padx=8, pady=4)
        btn_prev_page = ttk.Button(nav_frame, text="◀ Önceki Sayfa", command=self._on_prev_page)
        btn_prev_page.pack(side="left", padx=(4, 0))
        self.page_label_var = tk.StringVar(value="Sayfa -/-")
        ttk.Label(nav_frame, textvariable=self.page_label_var).pack(side="left", padx=8)
        btn_next_page = ttk.Button(nav_frame, text="Sonraki Sayfa ▶", command=self._on_next_page)
        btn_next_page.pack(side="left")

        ttk.Label(nav_frame, text="Satıra git:").pack(side="left", padx=(16, 0))
        self.goto_var = tk.StringVar()
        goto_entry = ttk.Entry(nav_frame, textvariable=self.goto_var, width=10)
        goto_entry.pack(side="left", padx=4)
        btn_goto = ttk.Button(nav_frame, text="Git", command=self._on_goto)
        btn_goto.pack(side="left")

        # -- Base64 Çöz --------------------------------------------------------
        base64_frame = ttk.LabelFrame(root, text="Base64 Çöz")
        base64_frame.pack(fill="x", padx=8, pady=4)
        btn_decode = ttk.Button(
            base64_frame, text="Seçili Satırı Base64 Çöz (kolon/prefix/postfix sorulur)",
            command=self._on_decode,
        )
        btn_decode.pack(side="left", padx=4, pady=4)

        self.status_var = tk.StringVar(value="Hazır.")
        status_label = ttk.Label(root, textvariable=self.status_var, foreground="#006400")
        status_label.pack(fill="x", padx=8, pady=(0, 6))

        self._busy_widgets = [
            btn_select, btn_fetch, btn_open_processed, btn_import_json, btn_search,
            btn_prev_match, btn_next_match, btn_sort, btn_decode, btn_prev_page,
            btn_next_page, btn_return_source, btn_goto,
        ]
        # Arama ve sıralama artık disk modunda da aktiftir; bu liste şu an
        # boş bırakılmıştır. Aramayı İptal Et / Sıralamayı İptal Et
        # düğmeleri kasıtlı olarak _busy_widgets DIŞINDADIR, kendi
        # durumlarını ilgili _on_disk_*/_finish_disk_* metodları yönetir.
        self._disk_only_widgets = []

        # Veri yüklenmeden kullanılamayan kontroller: başlangıçta pasif,
        # yanlarındaki nota bakılarak neden pasif oldukları anlaşılır. İlk
        # veri (bellek ya da disk modu) yüklendiğinde _enable_data_controls
        # ile etkinleştirilir. "Kaynak Sırasına Dön" ayrıca yalnızca disk
        # modunda anlamlı olduğu için _set_disk_mode_ui tarafından ayrıca
        # yönetilir.
        self._data_dependent_widgets = [
            search_entry, btn_search, btn_prev_match, btn_next_match,
            btn_sort, btn_decode, btn_prev_page, btn_next_page, goto_entry, btn_goto,
        ]
        # Combobox'lar "normal" değil "readonly" durumunda etkin sayılır
        # (aksi halde serbest metin girişine izin verir); bu yüzden ayrı
        # bir listede tutulur.
        self._data_dependent_comboboxes = [self.sort_column_combo, sort_dir_combo]
        for widget in self._data_dependent_widgets:
            widget.configure(state="disabled")
        for widget in self._data_dependent_comboboxes:
            widget.configure(state="disabled")

    def _enable_data_controls(self) -> None:
        """İlk veri (bellek ya da disk modu) başarıyla yüklendiğinde,
        önceden veri gerektiği için pasif tutulan kontrolleri etkinleştirir
        ve genel açıklama notunu kaldırır."""
        self._has_data = True
        for widget in self._data_dependent_widgets:
            widget.configure(state="normal")
        for widget in self._data_dependent_comboboxes:
            widget.configure(state="readonly")
        self.data_required_note_var.set("")

    # ------------------------------------------------------------------
    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        for widget in self._busy_widgets:
            if busy:
                widget.configure(state="disabled")
            else:
                disabled_by_disk = self._disk_mode_active and widget in self._disk_only_widgets
                disabled_by_no_data = (not self._has_data) and widget in self._data_dependent_widgets
                disabled_by_not_disk = (widget is self._btn_return_source) and not self._disk_mode_active
                widget.configure(
                    state="disabled"
                    if (disabled_by_disk or disabled_by_no_data or disabled_by_not_disk)
                    else "normal"
                )

    def _set_disk_mode_ui(self, is_disk: bool) -> None:
        self._disk_mode_active = is_disk
        state = "disabled" if is_disk else "normal"
        for widget in self._disk_only_widgets:
            widget.configure(state=state)
        # "Kaynak Sırasına Dön" yalnızca disk modunda anlamlıdır.
        self._btn_return_source.configure(state="normal" if is_disk else "disabled")
        if is_disk:
            note = ""
            if not (self.disk_manifest and self.disk_manifest.get("tamamlandi_mi")):
                note = "Depo KISMİ bir yakalama; arama/sıralama kaynak dosyanın TAMAMINI kapsamaz."
            self.disk_mode_note_var.set(note)
        else:
            self.disk_mode_note_var.set("")

    def _run_in_background(self, fn, on_success, on_error):
        if self._busy:
            return
        self._set_busy(True)

        def worker():
            start = time.perf_counter()
            try:
                result = fn()
                duration = time.perf_counter() - start
                self._work_queue.put(("ok", result, duration))
            except Exception as e:
                self._work_queue.put(("error", e, None))

        threading.Thread(target=worker, daemon=True).start()
        self.root.after(30, self._poll_queue, on_success, on_error)

    def _poll_queue(self, on_success, on_error):
        try:
            status, payload, duration = self._work_queue.get_nowait()
        except queue.Empty:
            self.root.after(30, self._poll_queue, on_success, on_error)
            return
        self._set_busy(False)
        if status == "ok":
            on_success(payload, duration)
        else:
            on_error(payload)

    def _show_error(self, error: Exception) -> None:
        messagebox.showerror("Hata", str(error))

    # ------------------------------------------------------------------
    def _on_select_file(self):
        path = filedialog.askopenfilename(
            title="Veri dosyası seç",
            filetypes=[
                ("Desteklenen dosyalar", "*.json *.csv *.yaml *.yml *.xml"),
                ("Tüm dosyalar", "*.*"),
            ],
        )
        if path:
            self.selected_path = path
            self.path_var.set(path)
            self.status_var.set("Dosya seçildi. 'Veriyi Getir' ile yükleyin.")

    def _on_fetch_data(self):
        if not self.selected_path:
            messagebox.showwarning("Uyarı", "Önce bir dosya seçin.")
            return

        path = self.selected_path

        def do_load():
            return _load_with_timings(path)

        def on_success(payload, _duration):
            dataset, timings = payload
            self._cleanup_search_results()
            self._disk_store_generation += 1
            self._cleanup_sort_work_dir()
            self._cleanup_pending_sort_work_dir()
            self.dataset = dataset
            self.disk_manifest = None
            self._set_disk_mode_ui(False)
            self.table_view.set_dataset(dataset)
            self.sort_column_combo["values"] = list(dataset.columns)
            if dataset.columns:
                self.sort_column_var.set(dataset.columns[0])
            self.matches = []
            self.match_index = -1
            self.match_label_var.set("")
            self._enable_data_controls()
            self._update_page_label()
            self.status_var.set(
                "Yükleme -- okuma: {:.2f} ms, ayrıştırma: {:.2f} ms, normalizasyon: {:.2f} ms, "
                "toplam: {:.2f} ms, sayfa çizimi: {:.2f} ms ({} kayıt, {} satır)".format(
                    timings["okuma"] * 1000, timings["ayristirma"] * 1000,
                    timings["normalizasyon"] * 1000, timings["toplam"] * 1000,
                    (self.table_view.last_render_seconds or 0) * 1000,
                    len(dataset.rows), self.table_view.last_render_row_count,
                )
            )

        def on_error(error):
            self._show_error(error)
            self.status_var.set("Yükleme başarısız.")

        self._run_in_background(do_load, on_success, on_error)

    # ------------------------------------------------------------------
    def _on_open_processed_data(self):
        folder = filedialog.askdirectory(
            title="İşlenmiş veri klasörünü seç (streaming_pilot çıktısı)",
        )
        if not folder:
            return
        self._open_disk_store_folder(folder)

    def _open_disk_store_folder(self, folder: str) -> None:
        """folder içindeki kayitlar.jsonl/.idx/manifest.json'ı açar (klasör
        seçme diyaloğu olmadan, ör. bir aktarım işi bittikten hemen sonra
        doğrudan sonucu açmak için de kullanılır)."""
        jsonl_path = os.path.join(folder, "kayitlar.jsonl")
        index_path = os.path.join(folder, "kayitlar.idx")
        manifest_path = os.path.join(folder, "manifest.json")
        missing = [
            name for name, p in
            [("kayitlar.jsonl", jsonl_path), ("kayitlar.idx", index_path), ("manifest.json", manifest_path)]
            if not os.path.isfile(p)
        ]
        if missing:
            messagebox.showerror(
                "Hata",
                "Seçilen klasörde beklenen dosyalar eksik: " + ", ".join(missing),
            )
            return

        def do_open():
            manifest = read_manifest(manifest_path)
            reader = RecordReader(jsonl_path, index_path)
            count = reader.record_count()  # yalnızca indeks dosyasının BOYUTU okunur
            return reader, manifest, count

        def on_success(payload, _duration):
            reader, manifest, count = payload
            self._cleanup_search_results()
            self._disk_store_generation += 1
            self._cleanup_sort_work_dir()
            self._cleanup_pending_sort_work_dir()
            self.dataset = None
            self.disk_manifest = manifest
            self.matches = []
            self.match_index = -1
            self.match_label_var.set("")
            # CSV depolarinda kayitlar pozisyonel (liste) yazilir; gercek
            # basliklar yalnizca manifest'te bir kez tutulur -- kolon
            # adlarini sayfa icerigi yerine HER ZAMAN buradan alir (bkz.
            # gui/table_view.py). JSON depolarinda (kaynak_format yok ya
            # da "json") known_columns None kalir, mevcut davranis aynen surer.
            known_columns = (
                manifest.get("kolonlar") if manifest.get("kaynak_format") == "csv" else None
            )
            self.table_view.set_disk_reader(
                reader, is_complete=bool(manifest.get("tamamlandi_mi", False)), total_count=count,
                known_columns=known_columns,
            )
            self._set_disk_mode_ui(True)
            self._enable_data_controls()
            self._refresh_sort_columns()
            self._update_page_label()
            durum = "TAMAMLANDI" if manifest.get("tamamlandi_mi") else "KISMİ"
            self.status_var.set(
                f"İşlenmiş veri açıldı ({durum}): depoda {count} kayıt var. "
                "Kaynak dosyadaki TOPLAM kayıt sayısı bilinmiyor."
            )

        def on_error(error):
            self._show_error(error)

        self._run_in_background(do_open, on_success, on_error)

    # -- Büyük JSON aktarımı ----------------------------------------------
    def _on_import_large_json(self):
        if self._busy:
            return
        config = dialogs.ask_import_config(self.root)
        if not config:
            return

        job = ImportJob(
            config["source"], config["out_dir"], config["selector"], config["mode"],
            source_format=config["source_format"],
            preview_max_records=config["preview_max_records"],
            preview_max_bytes=config["preview_max_bytes"],
        )
        self._import_job = job

        self._set_busy(True)
        self._btn_cancel_import.configure(state="normal")

        def worker():
            job.run()

        threading.Thread(target=worker, daemon=True).start()
        self.root.after(150, self._poll_import_progress)

    def _on_cancel_import(self):
        if self._import_job is not None and not self._import_job.done:
            self._import_job.request_cancel()
            self._btn_cancel_import.configure(state="disabled")
            self.status_var.set("Aktarım iptal ediliyor...")

    def _poll_import_progress(self):
        job = self._import_job
        if job is None:
            return
        if not job.done:
            bytes_read, completed, written = job.snapshot()
            self.status_var.set(
                f"Aktarım sürüyor... okunan: {bytes_read} bayt, tamamlanan kayıt: {completed}, "
                f"yazılan: {written} bayt, geçen süre: {job.elapsed():.1f} sn"
            )
            self.root.after(150, self._poll_import_progress)
            return
        self._finish_import(job)

    def _finish_import(self, job: ImportJob) -> None:
        self._set_busy(False)
        self._btn_cancel_import.configure(state="disabled")
        if self._import_job is job:
            self._import_job = None

        bytes_read, completed, written = job.snapshot()
        complete = (job.mode == "full" and job.outcome == OUTCOME_FULL_COMPLETE)
        durum_metni = {
            "onizleme": "ÖNİZLEME (kısmi, kasıtlı)",
            "tam_aktarim_tamamlandi": "TAMAMLANDI",
            "kullanici_iptali": "İPTAL EDİLDİ",
            "hedef_dizi_bulunamadi": "HATA: hedef dizi/alan/element bulunamadı",
            "tek_kayit_sinirini_asti": "HATA: tek kayıt/hücre boyutu (ya da derinliği) sınırı aşıldı",
            "ayristirma_hatasi": "HATA: kaynağın devamı bozuk (JSON/XML/YAML sözdizimi hatası ya da CSV alan sayısı uyuşmazlığı)",
            "kaynak_okuma_hatasi": "HATA: kaynak dosya okunamadı (bağlantı kesildi olabilir)",
            "cikis_yazma_hatasi": "HATA: çıktı diskine yazılamadı",
            "cikis_diskinde_yetersiz_alan": "HATA: çıktı diskinde yeterli boş alan yok",
            "secici_hatasi": "HATA: seçici geçersiz (seçilen kayıt dizisi kaynakta bulunamadı)",
            "baslik_hatasi": "HATA: CSV başlığı geçersiz (boş/tekrarlanan başlık)",
            "yaml_desteklenmeyen_yapi": "HATA: desteklenmeyen YAML yapısı (alias/anchor/çok belgeli/özel tür)",
            "beklenmeyen_hata": "HATA: beklenmeyen bir sorun oluştu",
        }.get(job.outcome, str(job.outcome))
        if job.outcome in ("secici_hatasi", "hedef_dizi_bulunamadi") and job.selector_error_detail:
            durum_metni += f" — {job.selector_error_detail}"
        if job.outcome in ("baslik_hatasi", "ayristirma_hatasi") and job.csv_row_error_detail:
            durum_metni += f" — {job.csv_row_error_detail}"
        if job.outcome == "yaml_desteklenmeyen_yapi" and job.yaml_error_detail:
            durum_metni += f" — {job.yaml_error_detail}"

        self.status_var.set(
            f"Aktarım bitti ({durum_metni}): {completed} kayıt, {bytes_read} bayt okundu, "
            f"{written} bayt yazıldı, {job.elapsed():.2f} sn."
        )

        usable = job.out_dir is not None and completed > 0
        mesaj = (
            f"Durum: {durum_metni}\n"
            f"Tamamlanan kayıt sayısı: {completed}\n"
            f"Kaynaktan okunan bayt: {bytes_read}\n"
            f"Yazılan bayt: {written}\n"
            f"Geçen süre: {job.elapsed():.2f} sn\n"
            f"Çıktı klasörü: {job.out_dir}\n\n"
        )
        if complete:
            mesaj += "Aktarım TAM olarak tamamlandı (hedef dizi + kaynağın tamamı doğrulandı)."
        elif job.mode == "preview":
            mesaj += "Bu bir ÖNİZLEMEDİR; kaynağın tamamının aktarıldığı anlamına gelmez."
        else:
            mesaj += "Aktarım tamamlanmadı; depo KISMİDİR (varsa) ve öyle işaretlenmiştir."

        if usable:
            mesaj += "\n\nBu (kısmi de olsa) depoyu şimdi açmak ister misiniz?"
            if messagebox.askyesno("Aktarım Sonucu", mesaj):
                self._open_disk_store_folder(job.out_dir)
        else:
            messagebox.showinfo("Aktarım Sonucu", mesaj)

    # ------------------------------------------------------------------
    def _on_search(self):
        if self.table_view.mode == "disk":
            self._on_disk_search()
            return
        if not self.dataset:
            messagebox.showwarning("Uyarı", "Önce bir veri kümesi yükleyin.")
            return
        query = self.search_var.get()
        if not query:
            self.matches = []
            self.match_index = -1
            self.match_label_var.set("")
            self.status_var.set("Arama sorgusu boş; sonuçlar temizlendi.")
            return

        view_order = self.table_view.view_order
        dataset = self.dataset

        def do_search():
            return search_algo.find_matches(dataset, view_order, query)

        def on_success(matches, duration):
            self.matches = matches
            self.match_index = 0 if matches else -1
            if matches:
                self.match_label_var.set(f"{len(matches)} eşleşme (1/{len(matches)})")
                self.table_view.go_to_position(self.table_view.position_of(matches[0]))
            else:
                self.match_label_var.set("Eşleşme yok")
            self.status_var.set(
                f"Arama: {duration * 1000:.2f} ms ({len(dataset.rows)} kayıt, {len(matches)} eşleşme)"
            )

        def on_error(error):
            self._show_error(error)

        self._run_in_background(do_search, on_success, on_error)

    def _on_prev_match(self):
        if self.table_view.mode == "disk":
            self._disk_prev_next_match(-1)
            return
        if not self.matches:
            return
        self.match_index = (self.match_index - 1) % len(self.matches)
        self._go_to_current_match()

    def _on_next_match(self):
        if self.table_view.mode == "disk":
            self._disk_prev_next_match(1)
            return
        if not self.matches:
            return
        self.match_index = (self.match_index + 1) % len(self.matches)
        self._go_to_current_match()

    def _go_to_current_match(self):
        row_id = self.matches[self.match_index]
        self.table_view.go_to_position(self.table_view.position_of(row_id))
        self.match_label_var.set(f"{len(self.matches)} eşleşme ({self.match_index + 1}/{len(self.matches)})")

    # -- Disk modu arama --------------------------------------------------
    def _cleanup_search_results(self, path: str = None) -> None:
        """Artık gerekmeyen geçici arama sonucu dosyasını siler. path
        verilmezse mevcut arama durumunu da (match_store vb.) sıfırlar;
        verilirse yalnızca o dosyayı temizler (ör. geçersiz kılınmış eski
        bir işin sonucu)."""
        target = path if path is not None else self._search_results_path
        if target and os.path.exists(target):
            try:
                os.remove(target)
            except OSError:
                pass
        if path is None:
            self._search_results_path = None
            self.match_store = None
            self.match_index = -1
            self.match_label_var.set("")

    def _on_disk_search(self):
        if self.table_view.mode != "disk":
            messagebox.showwarning("Uyarı", "Önce işlenmiş veri açın.")
            return
        if self._busy:
            return
        query = self.search_var.get()
        if not query:
            messagebox.showwarning("Uyarı", "Arama metni boş olamaz.")
            return

        self._cleanup_search_results()

        reader = self.table_view.disk_reader
        fd, results_path = tempfile.mkstemp(prefix="datainspector_arama_", suffix=".idx")
        os.close(fd)

        job = disk_search.DiskSearchJob(
            reader, query, self._disk_store_generation,
            view_reader=self.table_view.disk_view_reader,
        )
        self._search_job = job

        self._set_busy(True)
        self._btn_cancel_search.configure(state="normal")

        def worker():
            job.run(results_path)

        threading.Thread(target=worker, daemon=True).start()
        self.root.after(150, self._poll_search_progress)

    def _on_cancel_search(self):
        if self._search_job is not None and not self._search_job.done:
            self._search_job.request_cancel()
            self._btn_cancel_search.configure(state="disabled")
            self.status_var.set("Arama iptal ediliyor...")

    def _poll_search_progress(self):
        job = self._search_job
        if job is None:
            return
        if not job.done:
            scanned, found = job.snapshot()
            self.status_var.set(
                f"Arama sürüyor... taranan: {scanned}, bulunan: {found}, "
                f"geçen süre: {job.elapsed():.1f} sn"
            )
            self.root.after(150, self._poll_search_progress)
            return
        self._finish_disk_search(job)

    def _finish_disk_search(self, job) -> None:
        self._set_busy(False)
        self._btn_cancel_search.configure(state="disabled")

        if job.store_generation != self._disk_store_generation:
            # Arama sürerken depo değişti; bu işin sonucu artık geçersiz,
            # yeni tabloyu/durumu ETKİLEMEZ.
            self._cleanup_search_results(path=job.results_path)
            if self._search_job is job:
                self._search_job = None
            return

        if self._search_job is job:
            self._search_job = None

        if job.error is not None:
            self._show_error(job.error)
            self.status_var.set("Arama başarısız.")
            self._cleanup_search_results(path=job.results_path)
            return

        scanned, found = job.snapshot()
        self._search_results_path = job.results_path
        self.match_store = disk_search.SearchResultsStore(job.results_path) if found else None
        self.match_index = 0 if found else -1

        depo_notu = ""
        if not (self.disk_manifest and self.disk_manifest.get("tamamlandi_mi")):
            depo_notu = " Kısmi depoda arama tamamlanması, kaynak dosyanın TAMAMININ arandığı anlamına gelmez."
        iptal_notu = " [İPTAL EDİLDİ, o ana kadarki kısmi sonuçlar]" if job.cancel_requested else ""

        self.match_label_var.set(f"{found} eşleşme" + (f" (1/{found})" if found else " yok"))
        self.status_var.set(
            f"Arama tamamlandı{iptal_notu}: {scanned} kayıt tarandı, {found} eşleşme, "
            f"{job.elapsed():.2f} sn.{depo_notu}"
        )

        if found:
            self._go_to_disk_match(0)

    def _disk_prev_next_match(self, delta: int) -> None:
        if not self.match_store or self._busy:
            return
        total = self.match_store.count()
        if total == 0:
            return
        self.match_index = (self.match_index + delta) % total
        self._go_to_disk_match(self.match_index)

    def _go_to_disk_match(self, index: int) -> None:
        # (görünüm konumu, kaynak kayıt kimliği) doğrudan sonuç dosyasından
        # okunur; deponun tamamını kapsayan bir RAM ters-eşlemesi kurulmaz.
        view_position, record_id = self.match_store.get(index)
        position = view_position + 1

        def do_fetch():
            return self.table_view.fetch_disk_page((position - 1) // self.table_view.page_size)

        def on_success(fetched, duration):
            self.table_view.apply_disk_page(fetched)
            iid = str(record_id)
            self.table_view.tree.selection_set(iid)
            self.table_view.tree.focus(iid)
            self.table_view.tree.see(iid)
            self._update_page_label()
            total = self.match_store.count()
            self.match_label_var.set(f"{total} eşleşme ({index + 1}/{total})")
            self.status_var.set(f"Eşleşmeye git: {duration * 1000:.2f} ms")

        def on_error(error):
            self._show_error(error)

        self._run_in_background(do_fetch, on_success, on_error)

    # ------------------------------------------------------------------
    def _on_sort(self):
        if self.table_view.mode == "disk":
            self._on_disk_sort()
            return
        if not self.dataset:
            messagebox.showwarning("Uyarı", "Önce bir veri kümesi yükleyin.")
            return
        column = self.sort_column_var.get()
        if not column:
            messagebox.showwarning("Uyarı", "Sıralanacak kolonu seçin.")
            return
        ascending = self.sort_dir_var.get() == "Artan"

        dataset = self.dataset
        view_order = self.table_view.view_order

        def do_sort():
            return sorting_algo.merge_sort_view(dataset, view_order, column, ascending)

        def on_success(new_order, duration):
            self.table_view.set_view_order(new_order)
            self._update_page_label()
            self.status_var.set(
                f"Sıralama ({column}, {self.sort_dir_var.get()}): {duration * 1000:.2f} ms "
                f"({len(dataset.rows)} kayıt)"
            )

        def on_error(error):
            self._show_error(error)

        self._run_in_background(do_sort, on_success, on_error)

    def _refresh_sort_columns(self) -> None:
        """Disk modunda sıralama kolon seçenekleri, o an görüntülenen
        sayfanın kolonlarına (current_page_columns) dayanır -- değişken
        kolon sayısı nedeniyle sabit/global bir kolon listesi yoktur."""
        if self.table_view.mode != "disk":
            return
        cols = list(self.table_view.current_page_columns)
        self.sort_column_combo["values"] = cols
        if cols and self.sort_column_var.get() not in cols:
            self.sort_column_var.set(cols[0])

    # -- Disk modu sıralama ------------------------------------------------
    def _cleanup_sort_work_dir(self) -> None:
        """AKTİF görünümü destekleyen klasörü siler (görünüm artık ona
        ihtiyaç duymuyorsa: depo değişti, kaynak sırasına dönüldü ya da
        uygulama kapanıyor). Sürmekte olan bir işin KENDİ (henüz etkin
        olmayan) klasörünü etkilemez."""
        if self._sort_work_dir and os.path.isdir(self._sort_work_dir):
            shutil.rmtree(self._sort_work_dir, ignore_errors=True)
        self._sort_work_dir = None

    def _cleanup_pending_sort_work_dir(self) -> None:
        if self._pending_sort_work_dir and os.path.isdir(self._pending_sort_work_dir):
            shutil.rmtree(self._pending_sort_work_dir, ignore_errors=True)
        self._pending_sort_work_dir = None

    def _on_disk_sort(self):
        if self.table_view.mode != "disk":
            messagebox.showwarning("Uyarı", "Önce işlenmiş veri açın.")
            return
        if self._busy:
            return
        column = self.sort_column_var.get()
        if not column:
            messagebox.showwarning("Uyarı", "Sıralanacak kolonu seçin.")
            return
        ascending = self.sort_dir_var.get() == "Artan"

        # Yeni işin klasörü AYRI tutulur; mevcut aktif görünümün dayandığı
        # eski klasör, yeni sıralama BAŞARIYLA bitene kadar SİLİNMEZ (iptal/
        # hata durumunda önceki görünüm kullanılabilir kalsın diye).
        self._cleanup_pending_sort_work_dir()
        self._pending_sort_work_dir = tempfile.mkdtemp(prefix="datainspector_siralama_")

        job = disk_sorting.DiskSortJob(
            self.table_view.disk_reader,
            self.table_view.disk_view_reader,  # mevcut görünüm -> kararlılık tabanı
            column, ascending,
            self._disk_store_generation,
            known_columns=self.table_view.disk_known_columns,
        )
        self._sort_job = job

        self._set_busy(True)
        self._btn_cancel_sort.configure(state="normal")

        work_dir = self._pending_sort_work_dir

        def worker():
            job.run(work_dir)

        threading.Thread(target=worker, daemon=True).start()
        self.root.after(150, self._poll_sort_progress)

    def _on_cancel_sort(self):
        if self._sort_job is not None and not self._sort_job.done:
            self._sort_job.request_cancel()
            self._btn_cancel_sort.configure(state="disabled")
            self.status_var.set("Sıralama iptal ediliyor...")

    def _poll_sort_progress(self):
        job = self._sort_job
        if job is None:
            return
        if not job.done:
            scanned, total, rounds = job.snapshot()
            self.status_var.set(
                f"Sıralama sürüyor... taranan: {scanned}/{total}, birleştirme turu: {rounds}, "
                f"geçen süre: {job.elapsed():.1f} sn"
            )
            self.root.after(150, self._poll_sort_progress)
            return
        self._finish_disk_sort(job)

    def _finish_disk_sort(self, job) -> None:
        self._set_busy(False)
        self._btn_cancel_sort.configure(state="disabled")
        if self._sort_job is job:
            self._sort_job = None

        if job.store_generation != self._disk_store_generation:
            # Sıralama sürerken depo değişti; bu işin sonucu artık geçersiz,
            # yeni tabloyu ETKİLEMEZ. Önceki görünüm kullanılabilir kalır.
            self._cleanup_pending_sort_work_dir()
            return

        if job.cancel_requested:
            self._cleanup_pending_sort_work_dir()
            self.status_var.set("Sıralama iptal edildi; önceki görünüm korunuyor.")
            return

        if job.error is not None:
            self._cleanup_pending_sort_work_dir()
            self._show_error(job.error)
            self.status_var.set("Sıralama başarısız; önceki görünüm korunuyor.")
            return

        # Yalnızca TAMAMEN başarılı üretildikten sonra yeni görünüm etkinleşir.
        # Eski aktif klasör (varsa) ancak ŞİMDİ, yenisi devreye girdikten
        # sonra silinir.
        old_work_dir = self._sort_work_dir
        self._sort_work_dir = self._pending_sort_work_dir
        self._pending_sort_work_dir = None
        view_reader = disk_sorting.SequenceReader(job.result_path)
        self.table_view.set_disk_view_reader(view_reader)
        if old_work_dir and os.path.isdir(old_work_dir):
            shutil.rmtree(old_work_dir, ignore_errors=True)
        self._refresh_sort_columns()
        self._update_page_label()

        # Sıralama değişti -> eski arama sonuçları (görünüm konumlarına göre
        # kayıtlıydı) artık geçersizdir.
        self._cleanup_search_results()

        scanned, total, rounds = job.snapshot()
        self.status_var.set(
            f"Sıralama tamamlandı ({job.column}, {self.sort_dir_var.get()}): "
            f"{total} kayıt, {rounds} birleştirme turu, {job.elapsed():.2f} sn."
        )

    def _on_return_to_source_order(self):
        if self.table_view.mode != "disk":
            return
        self.table_view.set_disk_view_reader(None)
        self._refresh_sort_columns()
        self._update_page_label()
        self._cleanup_search_results()
        self.status_var.set("Kaynak sırasına dönüldü.")

    # ------------------------------------------------------------------
    def _on_decode(self):
        if self.table_view.mode == "empty":
            messagebox.showwarning("Uyarı", "Önce bir veri kümesi veya işlenmiş veri açın.")
            return
        row_index = self.table_view.selected_row_id()
        if row_index is None:
            messagebox.showwarning("Uyarı", "Base64 çözümlemek için önce bir satır seçin.")
            return

        if self.table_view.mode == "disk":
            columns = list(self.table_view.current_page_columns)
            config = dialogs.ask_base64_config(self.root, columns)
            if not config or not config["columns"]:
                return
            disk_reader = self.table_view.disk_reader
            selected_columns = config["columns"]

            def do_decode():
                record = disk_reader.read_record(row_index)
                parts = [get_cell_value(record, col, columns) for col in selected_columns]
                text = base64_decoder.extract_base64_text(
                    parts, prefix=config["prefix"], postfix=config["postfix"],
                    apply_to=config["apply_to"],
                    prefix_mode=config.get("prefix_mode", "starts_with"),
                )
                data = base64_decoder.decode_base64(text)
                decoded_text = base64_decoder.try_decode_text(data)
                return data, decoded_text
        else:
            config = dialogs.ask_base64_config(self.root, list(self.dataset.columns))
            if not config or not config["columns"]:
                return
            rows_by_id = {row.row_id: row for row in self.dataset.rows}
            row = rows_by_id[row_index]
            try:
                parts = [row.raw.get(col, MISSING) for col in config["columns"]]
            except Exception as e:
                self._show_error(e)
                return

            def do_decode():
                text = base64_decoder.extract_base64_text(
                    parts, prefix=config["prefix"], postfix=config["postfix"],
                    apply_to=config["apply_to"],
                    prefix_mode=config.get("prefix_mode", "starts_with"),
                )
                data = base64_decoder.decode_base64(text)
                decoded_text = base64_decoder.try_decode_text(data)
                return data, decoded_text

        def on_success(payload, duration):
            data, decoded_text = payload
            dialogs.show_decode_result(self.root, data, decoded_text, duration)
            self.status_var.set(f"Base64 çözümleme: {duration * 1000:.2f} ms ({len(data)} bayt)")

        def on_error(error):
            self._show_error(error)

        self._run_in_background(do_decode, on_success, on_error)

    # ------------------------------------------------------------------
    def _on_prev_page(self):
        self._change_page(-1)

    def _on_next_page(self):
        self._change_page(1)

    def _change_page(self, delta: int) -> None:
        if self.table_view.mode == "empty":
            return
        if self.table_view.mode == "disk":
            target = self.table_view.current_page + delta

            def do_fetch():
                return self.table_view.fetch_disk_page(target)

            def on_success(fetched, duration):
                self.table_view.apply_disk_page(fetched)
                self._refresh_sort_columns()
                self._update_page_label()
                self.status_var.set(
                    f"Sayfa okuma: {duration * 1000:.2f} ms "
                    f"({self.table_view.last_render_row_count} kayıt)"
                )

            def on_error(error):
                self._show_error(error)

            self._run_in_background(do_fetch, on_success, on_error)
        else:
            if delta < 0:
                self.table_view.previous_page()
            else:
                self.table_view.next_page()
            self._update_page_label()

    def _on_goto(self):
        if self.table_view.mode == "empty":
            messagebox.showwarning("Uyarı", "Önce bir veri kümesi veya işlenmiş veri açın.")
            return
        raw = self.goto_var.get().strip()
        try:
            position = int(raw)
        except ValueError:
            messagebox.showerror("Hata", "Geçerli bir satır numarası girin.")
            return

        total = self.table_view.total_length()
        if position < 1 or position > total:
            messagebox.showerror(
                "Hata", f"Geçersiz satır konumu: {position} (1-{total} arasında olmalı)"
            )
            return

        if self.table_view.mode == "disk":
            target_page = (position - 1) // self.table_view.page_size

            def do_fetch():
                return self.table_view.fetch_disk_page(target_page)

            def on_success(fetched, duration):
                self.table_view.apply_disk_page(fetched)
                # iid HER ZAMAN kaynak kayıt kimliğidir; görünüm sıralanmışsa
                # bu, (position - 1)'den farklı olabilir -- doğru kimlik
                # fetch_disk_page'in döndürdüğü record_ids listesinden alınır.
                offset = position - 1 - fetched["start"]
                iid = str(fetched["record_ids"][offset])
                self.table_view.tree.selection_set(iid)
                self.table_view.tree.focus(iid)
                self.table_view.tree.see(iid)
                self._update_page_label()
                self.status_var.set(f"Satıra git: {duration * 1000:.2f} ms")

            def on_error(error):
                self._show_error(error)

            self._run_in_background(do_fetch, on_success, on_error)
        else:
            try:
                self.table_view.go_to_position(position)
            except Exception as e:
                messagebox.showerror("Hata", str(e))
            self._update_page_label()

    def _update_page_label(self):
        tv = self.table_view
        self.page_label_var.set(f"Sayfa {tv.current_page + 1}/{tv.page_count()}")

    # ------------------------------------------------------------------
    def _on_close(self) -> None:
        if self._search_job is not None:
            self._search_job.request_cancel()
        if self._sort_job is not None:
            self._sort_job.request_cancel()
        if self._import_job is not None:
            self._import_job.request_cancel()
        self._cleanup_search_results()
        self._cleanup_sort_work_dir()
        self._cleanup_pending_sort_work_dir()
        self.root.destroy()

    def run(self):
        self.root.mainloop()
