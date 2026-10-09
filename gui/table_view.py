"""ttk.Treeview sarmalayıcısı: sayfalama, view_order yönetimi, satıra gitme,
seçim koruma.

İki mod destekler:
  - "memory": mevcut küçük-dosya akışı (Dataset.rows tamamen bellekte).
  - "disk"  : streaming_pilot.disk_store.RecordReader üzerinden, YALNIZCA
    istenen sayfa (<=500 kayıt) okunur; tüm kayıtlar/indeks/kimlikler asla
    liste/sözlük halinde belleğe toplanmaz.

Dataset.rows (bellek modu) her zaman orijinal yükleme sırasında kalır ve
buradan hiç değiştirilmez; görünüm sırası (view_order) ayrı bir row_id
listesi olarak tutulur. "Satıra git", her iki modda da 1 tabanlı konumu
ifade eder.
"""
import time
import tkinter as tk
from tkinter import ttk

from models import MISSING, format_value

PAGE_SIZE = 500


def columns_for_records(records: list) -> list:
    """Sayfadaki kayıtlardan kolon adlarını türetir.

    Nesne kayıtları için: anahtarların ilk-görülme birleşimi.
    Pozisyonel (liste) kayıtlar için: bu SAYFADAKİ en uzun kaydın uzunluğu
    kadar "Kolon 1".."Kolon N" (sabit bir kolon sayısı varsayılmaz; uzun
    kayıtlar kırpılmaz, kısa kayıtlardaki eksik hücreler çağıran tarafta
    MISSING ile doldurulur).
    """
    if not records:
        return []
    if all(isinstance(r, dict) for r in records):
        cols = []
        seen = set()
        for r in records:
            for k in r.keys():
                if k not in seen:
                    seen.add(k)
                    cols.append(k)
        return cols
    max_len = 0
    for r in records:
        length = len(r) if isinstance(r, (list, dict)) else 1
        max_len = max(max_len, length)
    return [f"Kolon {i + 1}" for i in range(max_len)]


def get_cell_value(record, column_name: str, columns: list):
    """record (dict ya da list) içinden column_name'e karşılık gelen ham
    değeri okur; yoksa MISSING döner."""
    if isinstance(record, dict):
        return record.get(column_name, MISSING)
    if isinstance(record, list):
        try:
            idx = columns.index(column_name)
        except ValueError:
            return MISSING
        if 0 <= idx < len(record):
            return record[idx]
        return MISSING
    return MISSING


def _positional_row_values(record, columns: list) -> list:
    if isinstance(record, dict):
        return [format_value(record.get(c, MISSING)) for c in columns]
    if isinstance(record, list):
        return [
            format_value(record[i]) if i < len(record) else format_value(MISSING)
            for i in range(len(columns))
        ]
    if columns:
        return [format_value(record)] + [format_value(MISSING)] * (len(columns) - 1)
    return [format_value(record)]


class TableView:
    def __init__(self, parent):
        self.mode = "empty"  # "empty" | "memory" | "disk"

        self.dataset = None
        self.view_order = []

        self.disk_reader = None
        self.disk_total_count = 0
        self.disk_is_complete = False
        self.disk_view_reader = None  # None -> görünüm = kaynak sırası; degilse sıralanmış görünüm
        self.disk_known_columns = None  # CSV depoları icin manifest'ten gelen sabit baslik listesi
        self.current_page_columns = []

        self.page_size = PAGE_SIZE
        self.current_page = 0
        self.last_render_seconds = None
        self.last_render_row_count = 0

        self.frame = ttk.Frame(parent)
        self.tree = ttk.Treeview(self.frame, show="headings")
        vsb = ttk.Scrollbar(self.frame, orient="vertical", command=self.tree.yview)
        hsb = ttk.Scrollbar(self.frame, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)

        self.tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")
        self.frame.rowconfigure(0, weight=1)
        self.frame.columnconfigure(0, weight=1)

    # ------------------------------------------------------------------
    def set_dataset(self, dataset) -> None:
        self.mode = "memory"
        self.dataset = dataset
        self.disk_reader = None
        self.view_order = [row.row_id for row in dataset.rows]
        self.current_page = 0
        self._apply_tree_columns(["#"] + list(dataset.columns))
        self.render_page(0)

    def set_disk_reader(self, reader, is_complete: bool, total_count: int,
                        known_columns: list = None) -> None:
        """known_columns verilirse (CSV depoları -- manifest'teki sabit
        başlık listesi), kolon adları sayfa içeriğinden türetilmez, HER
        ZAMAN bu liste kullanılır -- başlık-only (sıfır kayıtlı) bir depoda
        bile kolonlar kaybolmaz. JSON depoları için None kalır (mevcut
        davranış: kolonlar sayfadaki kayıtlardan türetilir)."""
        self.mode = "disk"
        self.dataset = None
        self.view_order = []
        self.disk_reader = reader
        self.disk_is_complete = is_complete
        self.disk_total_count = total_count
        self.disk_view_reader = None  # yeni depo -> kaynak sırasıyla başla
        self.disk_known_columns = known_columns
        self.current_page = 0
        self.render_page(0)  # kolonlar bu ilk sayfadan (ya da known_columns'tan) türetilir

    def set_disk_view_reader(self, view_reader) -> None:
        """Sıralama sonrası (ya da "Kaynak Sırasına Dön" için None ile)
        görünüm sırasını değiştirir. Sayfa 0'a döner ve yeniden çizer."""
        self.disk_view_reader = view_reader
        self.current_page = 0
        self.render_page(0)

    def set_view_order(self, new_order: list) -> None:
        self.view_order = new_order
        self.current_page = 0
        self.render_page(0)

    def _apply_tree_columns(self, columns: list) -> None:
        # Yeni kolon listesi ÖNCEKİNDEN kısaysa, Tk'nin "displaycolumns"u
        # eski (artık var olmayan) kolon kimliklerine referans tutmaya
        # devam eder ve "columns"u değiştirirken "Invalid column index"
        # hatası fırlatır. Önce boşaltıp öyle değiştirmek bunu önler.
        self.tree["displaycolumns"] = ()
        self.tree["columns"] = columns
        self.tree["displaycolumns"] = columns
        for col in columns:
            self.tree.heading(col, text=col)
            width = 60 if col == "#" else 140
            self.tree.column(col, width=width, anchor="w", stretch=True)

    # ------------------------------------------------------------------
    def total_length(self) -> int:
        if self.mode == "disk":
            return self.disk_total_count
        return len(self.view_order)

    def page_count(self) -> int:
        total = self.total_length()
        if not total:
            return 1
        return (total + self.page_size - 1) // self.page_size

    def render_page(self, page_index: int) -> None:
        """Ana thread'de çağrılmalıdır (Tk widget günceller). Disk modunda
        arka planda çalıştırmak için bunun yerine fetch_disk_page (arka
        plan thread'inde) + apply_disk_page (ana thread'de) çiftini
        kullanın."""
        if self.mode == "disk":
            self.apply_disk_page(self.fetch_disk_page(page_index))
            return

        page_index = max(0, min(page_index, self.page_count() - 1))
        self.current_page = page_index
        start = page_index * self.page_size
        end = start + self.page_size
        page_row_ids = self.view_order[start:end]

        rows_by_id = {row.row_id: row for row in self.dataset.rows} if self.dataset else {}

        start_time = time.perf_counter()
        self.tree.delete(*self.tree.get_children())
        for offset, row_id in enumerate(page_row_ids):
            row = rows_by_id[row_id]
            position = start + offset + 1
            values = [position] + [
                format_value(row.raw.get(col, MISSING)) for col in self.dataset.columns
            ]
            self.tree.insert("", "end", iid=str(row_id), values=values)
        self.last_render_seconds = time.perf_counter() - start_time
        self.last_render_row_count = len(page_row_ids)

    # -- disk modu: iki aşamalı (thread-güvenli) sayfa okuma ------------
    def fetch_disk_page(self, page_index: int) -> dict:
        """Yalnızca disk okuması yapar; hiçbir Tk widget'ına dokunmaz —
        arka plan thread'inde çağrılabilir. Sonucu ana thread'de
        apply_disk_page ile uygulayın.

        Görünüm kaynak sırasındaysa (disk_view_reader None), sayfa
        RecordReader.read_page ile TEK bir bitişik blok olarak okunur
        (verimli). Görünüm sıralanmışsa, bu sayfadaki kayıt kimlikleri
        depoda ardışık OLMAYABİLİR; bu durumda her kayıt kendi konumundan
        (read_record) tek tek okunur."""
        page_index = max(0, min(page_index, self.page_count() - 1))
        start = page_index * self.page_size

        if self.disk_view_reader is None:
            records = self.disk_reader.read_page(start, self.page_size)
            record_ids = list(range(start, start + len(records)))
        else:
            record_ids = self.disk_view_reader.get_range(start, self.page_size)
            records = [self.disk_reader.read_record(rid) for rid in record_ids]

        columns = (
            self.disk_known_columns if self.disk_known_columns is not None
            else columns_for_records(records)
        )
        return {
            "page_index": page_index, "start": start, "records": records,
            "record_ids": record_ids, "columns": columns,
        }

    def apply_disk_page(self, fetched: dict) -> None:
        """fetch_disk_page sonucunu Treeview'e uygular. YALNIZCA ana
        thread'de çağrılmalıdır. Treeview iid'si HER ZAMAN kaynak kayıt
        kimliğidir (görünüm konumu değil) — bu sayede seçili satırın
        Base64 işlemi, sıralamadan etkilenmeden doğru ham kaydı kullanır."""
        self.current_page = fetched["page_index"]
        columns = fetched["columns"]
        self.current_page_columns = columns
        start = fetched["start"]
        records = fetched["records"]
        record_ids = fetched["record_ids"]

        start_time = time.perf_counter()
        self.tree.delete(*self.tree.get_children())
        self._apply_tree_columns(["#"] + columns)
        for offset, (record, record_id) in enumerate(zip(records, record_ids)):
            position = start + offset + 1
            row_values = _positional_row_values(record, columns)
            self.tree.insert("", "end", iid=str(record_id), values=[position] + row_values)
        self.last_render_seconds = time.perf_counter() - start_time
        self.last_render_row_count = len(records)

    # ------------------------------------------------------------------
    def next_page(self) -> None:
        self.render_page(self.current_page + 1)

    def previous_page(self) -> None:
        self.render_page(self.current_page - 1)

    def go_to_position(self, position_1_based: int) -> None:
        """view_order (bellek modu) ya da toplam kayıt sayısı (disk modu)
        içindeki 1 tabanlı konuma gider; gerekirse sayfa değiştirir. Disk
        modunda arka planda çalıştırmak isteyen çağıran taraf, bunun yerine
        fetch_disk_page + apply_disk_page çiftini + seçim kodunu kendisi
        uygulamalıdır (bkz. gui/main_window.py._on_goto)."""
        total = self.total_length()
        if position_1_based < 1 or position_1_based > total:
            raise ValueError(
                f"Geçersiz satır konumu: {position_1_based} (1-{total} arasında olmalı)"
            )
        target_page = (position_1_based - 1) // self.page_size
        if target_page != self.current_page:
            self.render_page(target_page)

        if self.mode == "disk":
            record_id = (
                (position_1_based - 1) if self.disk_view_reader is None
                else self.disk_view_reader.get(position_1_based - 1)
            )
            iid = str(record_id)
        else:
            row_id = self.view_order[position_1_based - 1]
            iid = str(row_id)
        self.tree.selection_set(iid)
        self.tree.focus(iid)
        self.tree.see(iid)

    def selected_row_id(self):
        """Bellek modunda Dataset.Row.row_id; disk modunda depodaki 0
        tabanlı kayıt indeksini döner."""
        selection = self.tree.selection()
        if not selection:
            return None
        return int(selection[0])

    def position_of(self, row_id: int) -> int:
        """row_id'nin view_order içindeki 1 tabanlı konumunu döner (yalnızca
        bellek modu; disk modunda konum zaten row_id + 1'dir)."""
        return self.view_order.index(row_id) + 1
