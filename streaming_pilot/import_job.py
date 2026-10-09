"""GUI'den başlatılan büyük JSON aktarımı.

Kaynağı TEK SEFER, salt okunur açar; akışla okur (ijson tabanlı
StreamingArraySource); mevcut RecordWriter ile JSONL + ikili indeks
biçimine yazar; kendi manifest'ini üretir. MainWindow yalnızca bu modülü
(ImportJob) başlatır, ilerlemeyi izler ve sonucu açar — iş mantığının
tamamı burada yaşar.

İki mod:
  - "preview" (Önizleme): yapılandırılabilir kayıt/bayt sınırıyla KASITLI
    kısmi bir aktarımdır; sonucu HİÇBİR ZAMAN "tamamlandı" olarak
    raporlanmaz (sınır aşılmasa bile) -- bu, ayrı, bilinçli bir kategoridir.
  - "full" (Tam aktarım): pilotun 1000 kayıt / 32 MiB sınırları GİZLİCE
    uygulanmaz -- kayıt/bayt sınırı yoktur. Yalnızca AYRI, yapılandırılabilir
    tek-kayıt güvenlik sınırları (max_record_bytes, max_depth) geçerlidir.
    "Tamamlandı" (tamamlandi_mi=True) sayılması için ÜÇÜ BİRDEN gerekir:
    hedef dizi bulunmalı, TÜM elemanları yazılmalı, VE kaynağın geri kalanı
    da dosya sonuna kadar geçerli biçimde ayrıştırılmalıdır (yalnızca
    dizinin kapanması YETERLİ DEĞİLDİR -- bkz. StreamingArraySource'un
    drain_to_eof/STOP_FULLY_DRAINED mekanizması).

Her aktarım YENİ bir alt klasöre yazılır; mevcut depoların üzerine
YAZILMAZ. Bu sürümde yeniden başlatma her zaman kaynağın BAŞINDAN yeni bir
depoya aktarım yapar -- ijson'ın tamponlanmış konumundan güvenilir bir
devam noktası çıkarılabileceği VARSAYILMAZ (kaldığı yerden devam etme bu
sürümde YOKTUR).
"""
import datetime
import json
import os
import shutil
import time

from streaming_pilot.budgeted_reader import BudgetedBinaryReader
from streaming_pilot.csv_source import (
    CsvHeaderError,
    CsvStreamSource,
    DEFAULT_MAX_FIELD_BYTES,
    STOP_FIELD_TOO_LARGE as CSV_STOP_FIELD_TOO_LARGE,
    STOP_PARSE_ERROR as CSV_STOP_PARSE_ERROR,
    STOP_SOURCE_IO_ERROR as CSV_STOP_SOURCE_IO_ERROR,
    STOP_SOURCE_REAL_EOF as CSV_STOP_SOURCE_REAL_EOF,
)
from streaming_pilot.disk_store import RecordWriter
from streaming_pilot.streaming_source import (
    STOP_FULLY_DRAINED,
    SelectorError,
    StreamingArraySource,
)
from streaming_pilot.xml_source import (
    STOP_PARSE_ERROR as XML_STOP_PARSE_ERROR,
    STOP_RECORD_TOO_DEEP as XML_STOP_RECORD_TOO_DEEP,
    STOP_RECORD_TOO_LARGE as XML_STOP_RECORD_TOO_LARGE,
    STOP_SOURCE_IO_ERROR as XML_STOP_SOURCE_IO_ERROR,
    STOP_SOURCE_REAL_EOF as XML_STOP_SOURCE_REAL_EOF,
    XmlStreamSource,
)
from streaming_pilot.yaml_source import (
    STOP_FULLY_DRAINED as YAML_STOP_FULLY_DRAINED,
    STOP_PARSE_ERROR as YAML_STOP_PARSE_ERROR,
    STOP_RECORD_TOO_DEEP as YAML_STOP_RECORD_TOO_DEEP,
    STOP_RECORD_TOO_LARGE as YAML_STOP_RECORD_TOO_LARGE,
    STOP_SOURCE_IO_ERROR as YAML_STOP_SOURCE_IO_ERROR,
    STOP_SOURCE_REAL_EOF as YAML_STOP_SOURCE_REAL_EOF,
    STOP_UNSUPPORTED_STRUCTURE as YAML_STOP_UNSUPPORTED_STRUCTURE,
    YamlSelectorError,
    YamlStreamSource,
)

DEFAULT_PREVIEW_MAX_RECORDS = 1000
DEFAULT_PREVIEW_MAX_BYTES = 32 * 1024 * 1024

# Tek kayıt güvenlik sınırları -- kaynak/kayıt-adedi sınırlarından AYRI
# ayarlardır; hem önizleme hem tam aktarımda geçerlidir.
DEFAULT_MAX_RECORD_BYTES = 200 * 1024 * 1024  # ~200 MB (akış sırasında, yaklaşık ölçüm)
DEFAULT_MAX_DEPTH = 1000
DEFAULT_MAX_CSV_FIELD_BYTES = DEFAULT_MAX_FIELD_BYTES  # ~10 MB / CSV hucresi

DEFAULT_MIN_FREE_DISK_BYTES = 200 * 1024 * 1024  # bundan az bos alanla baslanmaz/devam edilmez
DISK_CHECK_INTERVAL_RECORDS = 500

MANIFEST_VERSION = 1

# -- Sonuç kategorileri (outcome): birbirinden AÇIKÇA ayrı tutulur --------
OUTCOME_PREVIEW = "onizleme"
OUTCOME_FULL_COMPLETE = "tam_aktarim_tamamlandi"
OUTCOME_CANCELLED = "kullanici_iptali"
OUTCOME_TARGET_NOT_FOUND = "hedef_dizi_bulunamadi"
OUTCOME_LIMIT_REACHED = "tek_kayit_sinirini_asti"
OUTCOME_PARSE_ERROR = "ayristirma_hatasi"
OUTCOME_SOURCE_IO_ERROR = "kaynak_okuma_hatasi"
OUTCOME_OUTPUT_IO_ERROR = "cikis_yazma_hatasi"
OUTCOME_OUTPUT_DISK_LOW = "cikis_diskinde_yetersiz_alan"
OUTCOME_SELECTOR_ERROR = "secici_hatasi"
OUTCOME_CSV_HEADER_ERROR = "baslik_hatasi"
OUTCOME_YAML_UNSUPPORTED_STRUCTURE = "yaml_desteklenmeyen_yapi"
OUTCOME_UNEXPECTED_ERROR = "beklenmeyen_hata"


class ImportJob:
    """Tek seferlik, iptal edilebilir bir aktarım işi. run() bir arka plan
    thread'inde çalıştırılmalıdır; hiçbir Tk widget'ına dokunmaz."""

    def __init__(self, source_path: str, out_root_dir: str, selector: dict, mode: str,
                 source_format: str = "json",
                 preview_max_records: int = DEFAULT_PREVIEW_MAX_RECORDS,
                 preview_max_bytes: int = DEFAULT_PREVIEW_MAX_BYTES,
                 max_record_bytes: int = DEFAULT_MAX_RECORD_BYTES,
                 max_depth: int = DEFAULT_MAX_DEPTH,
                 max_csv_field_bytes: int = DEFAULT_MAX_CSV_FIELD_BYTES,
                 min_free_disk_bytes: int = DEFAULT_MIN_FREE_DISK_BYTES):
        if mode not in ("preview", "full"):
            raise ValueError(f"Geçersiz mod: {mode!r} ('preview' ya da 'full' olmalı)")
        if source_format not in ("json", "csv", "xml", "yaml"):
            raise ValueError(
                f"Geçersiz kaynak biçimi: {source_format!r} "
                "('json', 'csv', 'xml' ya da 'yaml' olmalı)"
            )
        self.source_path = source_path
        self.out_root_dir = out_root_dir
        self.selector = selector
        self.mode = mode
        self.source_format = source_format
        self.preview_max_records = preview_max_records
        self.preview_max_bytes = preview_max_bytes
        self.max_record_bytes = max_record_bytes
        self.max_depth = max_depth
        self.max_csv_field_bytes = max_csv_field_bytes
        self.min_free_disk_bytes = min_free_disk_bytes

        self.cancel_requested = False
        self.done = False
        self.outcome = None
        self.stop_reason = None
        self.error_type_name = None
        self.selector_error_detail = None
        self.csv_headers = None
        self.csv_row_error_detail = None
        self.yaml_error_detail = None

        self.bytes_read = 0
        self.completed_count = 0
        self.written_bytes = 0
        self.element_kind_counts: dict = {}
        self.out_dir = None
        self.manifest_path = None
        self.start_time = time.perf_counter()
        self._end_time = None

    def request_cancel(self) -> None:
        self.cancel_requested = True

    def snapshot(self):
        return self.bytes_read, self.completed_count, self.written_bytes

    def elapsed(self) -> float:
        end = self._end_time if self._end_time is not None else time.perf_counter()
        return end - self.start_time

    def run(self) -> None:
        try:
            self._run()
        except Exception:
            # Beklenmeyen bir şey oldu; çıktı klasörü zaten oluşturulmuşsa
            # bile burada asla "tamamlandı" YAZILMAZ.
            self.outcome = OUTCOME_UNEXPECTED_ERROR
        finally:
            self._end_time = time.perf_counter()
            if self.out_dir is not None:
                try:
                    self._write_manifest()
                except OSError:
                    pass
            self.done = True

    def _run(self) -> None:
        os.makedirs(self.out_root_dir, exist_ok=True)
        stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        self.out_dir = os.path.join(self.out_root_dir, f"aktarim_{stamp}")
        os.makedirs(self.out_dir, exist_ok=False)
        self.manifest_path = os.path.join(self.out_dir, "manifest.json")
        jsonl_path = os.path.join(self.out_dir, "kayitlar.jsonl")
        index_path = os.path.join(self.out_dir, "kayitlar.idx")

        try:
            free = shutil.disk_usage(self.out_dir).free
        except OSError:
            free = None
        if free is not None and free < self.min_free_disk_bytes:
            self.outcome = OUTCOME_OUTPUT_DISK_LOW
            return

        if self.source_format == "csv":
            self._run_csv(jsonl_path, index_path)
        elif self.source_format == "xml":
            self._run_xml(jsonl_path, index_path)
        elif self.source_format == "yaml":
            self._run_yaml(jsonl_path, index_path)
        else:
            self._run_json(jsonl_path, index_path)

        if os.path.exists(jsonl_path):
            self.written_bytes = os.path.getsize(jsonl_path)

    def _run_json(self, jsonl_path: str, index_path: str) -> None:
        max_records = self.preview_max_records if self.mode == "preview" else (2 ** 62)
        # Tam aktarımda GERÇEK bir bayt sınırı yoktur (pilotun 32 MiB'ı
        # burada gizlice uygulanmaz); yine de StreamingArraySource,
        # budget_hit/real_eof alanlarını okuyabilmek için HER ZAMAN bir
        # BudgetedBinaryReader bekler -- bu yüzden pratikte hiçbir zaman
        # dolmayacak, anlamsız derecede büyük bir "bütçe" kullanılır.
        is_preview = (self.mode == "preview")
        max_bytes = self.preview_max_bytes if is_preview else (2 ** 62)
        drain = not is_preview

        with open(self.source_path, "rb") as raw_f:
            reader = BudgetedBinaryReader(raw_f, max_bytes)
            source = StreamingArraySource(
                reader, self.selector,
                max_record_bytes=self.max_record_bytes, max_depth=self.max_depth,
            )

            with RecordWriter(jsonl_path, index_path) as writer:
                try:
                    for i, element in enumerate(source.iter_records(max_records, drain_to_eof=drain)):
                        if self.cancel_requested:
                            self.outcome = OUTCOME_CANCELLED
                            break
                        try:
                            writer.write_record(element)
                        except OSError:
                            self.outcome = OUTCOME_OUTPUT_IO_ERROR
                            break
                        self.completed_count = writer.written_count
                        self.bytes_read = reader.bytes_read

                        if i % DISK_CHECK_INTERVAL_RECORDS == 0:
                            try:
                                free_now = shutil.disk_usage(self.out_dir).free
                            except OSError:
                                free_now = None
                            if free_now is not None and free_now < self.min_free_disk_bytes:
                                self.outcome = OUTCOME_OUTPUT_DISK_LOW
                                break
                    else:
                        # Döngü for-else: cancel/disk/yazma nedeniyle break
                        # OLMADAN doğal bitti -- source.stop_reason'a bak.
                        self.stop_reason = source.stop_reason
                        self.element_kind_counts = dict(source.element_kind_counts)
                        self._classify_natural_stop(source)
                except SelectorError as e:
                    self.outcome = OUTCOME_SELECTOR_ERROR
                    # Bu mesaj yalnızca yapısal bilgi içerir (ijson olay adı,
                    # kullanıcının kendi seçtiği sıra numarası); gerçek alan
                    # adı ya da hücre değeri asla içermez (bkz. streaming_source.py).
                    self.selector_error_detail = str(e)

                self.bytes_read = reader.bytes_read
                self.completed_count = writer.written_count
                writer.flush()

    def _run_csv(self, jsonl_path: str, index_path: str) -> None:
        # Selector kavramı YOKTUR (CSV'de her satır zaten bir kayıttır);
        # JSON'a özgü kök-dizi/alan-adı/alan-sırası seçimi burada geçerli
        # değildir. Kayıtlar SIRALI METİN LİSTELERİ (positional) olarak
        # yazılır -- başlıklar her satırda TEKRARLANMAZ (95M+ satırlık bir
        # depoda ciddi yer kazancı); gerçek başlıklar yalnızca manifest'te
        # BİR KEZ ("kolonlar") tutulur, bkz. _write_manifest.
        max_records = self.preview_max_records if self.mode == "preview" else (2 ** 62)
        # Tam aktarımda GERÇEK bir bayt sınırı yoktur -- JSON tarafındaki
        # aynı desen: pratikte hiçbir zaman dolmayacak, anlamsız derecede
        # büyük bir "bütçe" kullanılır.
        max_bytes = self.preview_max_bytes if self.mode == "preview" else (2 ** 62)

        try:
            # 'with' zinciri: dosya (text_f), CsvStreamSource (source -- global
            # csv.field_size_limit durumunun SAHİBİ, bkz. csv_source.py) ve
            # RecordWriter (writer), başarı/iptal/başlık hatası/csv.Error/
            # UnicodeDecodeError/yazma hatası/BEKLENMEYEN herhangi bir
            # exception dahil TÜM çıkış yollarında -- Python'ın 'with'
            # ifadesinin garantisiyle, generator'ın kendi kapanışına ya da
            # GC zamanlamasına bakılmaksızın -- deterministik olarak
            # kapanır/geri yüklenir.
            with open(self.source_path, "r", encoding="utf-8-sig", newline="") as text_f, \
                    CsvStreamSource(text_f, max_bytes, max_field_bytes=self.max_csv_field_bytes) as source, \
                    RecordWriter(jsonl_path, index_path) as writer:
                try:
                    for i, row in enumerate(source.iter_rows(max_records)):
                        if self.cancel_requested:
                            self.outcome = OUTCOME_CANCELLED
                            break
                        try:
                            writer.write_record(row)
                        except OSError:
                            self.outcome = OUTCOME_OUTPUT_IO_ERROR
                            break
                        self.completed_count = writer.written_count
                        self.bytes_read = source.bytes_read

                        if i % DISK_CHECK_INTERVAL_RECORDS == 0:
                            try:
                                free_now = shutil.disk_usage(self.out_dir).free
                            except OSError:
                                free_now = None
                            if free_now is not None and free_now < self.min_free_disk_bytes:
                                self.outcome = OUTCOME_OUTPUT_DISK_LOW
                                break
                    else:
                        # for-else: cancel/disk/yazma nedeniyle break OLMADAN
                        # doğal bitti -- source.stop_reason'a bak.
                        self.stop_reason = source.stop_reason
                        self._classify_csv_natural_stop(source)
                except CsvHeaderError as e:
                    self.outcome = OUTCOME_CSV_HEADER_ERROR
                    # Mevcut parsers/csv_parser.py (bellek modu) ile AYNI
                    # başlık hata mesajı biçimi; gerçek SATIR/HÜCRE verisi
                    # DEĞİL, yalnızca başlık yapısı hakkında bilgi içerir.
                    self.csv_row_error_detail = str(e)

                self.bytes_read = source.bytes_read
                self.completed_count = writer.written_count
                self.csv_headers = source.headers
                if source.error_type_name:
                    self.error_type_name = source.error_type_name
                if source.row_error_detail:
                    self.csv_row_error_detail = source.row_error_detail
                writer.flush()
        except OSError as e:
            self.error_type_name = type(e).__name__
            self.outcome = OUTCOME_SOURCE_IO_ERROR

    def _classify_csv_natural_stop(self, source: CsvStreamSource) -> None:
        if self.mode == "preview":
            # Önizleme; sınır aşılmış olsun olmasın, KASITLI kısmi bir
            # kategoridir -- asla "tamamlandı" olarak sunulmaz.
            self.outcome = OUTCOME_PREVIEW
            return

        reason = source.stop_reason
        if reason == CSV_STOP_SOURCE_REAL_EOF:
            self.outcome = OUTCOME_FULL_COMPLETE
            return
        if reason == CSV_STOP_PARSE_ERROR:
            self.outcome = OUTCOME_PARSE_ERROR
            return
        if reason == CSV_STOP_SOURCE_IO_ERROR:
            self.outcome = OUTCOME_SOURCE_IO_ERROR
            return
        if reason == CSV_STOP_FIELD_TOO_LARGE:
            self.outcome = OUTCOME_LIMIT_REACHED
            return
        # STOP_BYTE_BUDGET tam aktarımda pratikte hiç ulaşılmaz (bkz.
        # yukarıdaki anlamsız derecede büyük bütçe); yine de savunmacı
        # olarak "tamamlanmadı" say.
        self.outcome = OUTCOME_UNEXPECTED_ERROR

    def _run_xml(self, jsonl_path: str, index_path: str) -> None:
        # Secici: {"mode": "path", "value": ["item"]} ya da ["container",
        # "item"] -- kokun altinda (basit, wildcard'siz bir yolla) tekrar
        # eden kayit elementini belirtir (bkz. streaming_pilot/xml_source.py).
        # JSON'a ozgu kok-dizi/alan-adi/alan-sirasi kavramlari burada
        # GECERLI DEGILDIR.
        max_records = self.preview_max_records if self.mode == "preview" else (2 ** 62)
        # Tam aktarimda GERCEK bir bayt siniri yoktur -- JSON/CSV
        # tarafindaki AYNI desen: pratikte hicbir zaman dolmayacak,
        # anlamsiz derecede buyuk bir "butce" kullanilir.
        max_bytes = self.preview_max_bytes if self.mode == "preview" else (2 ** 62)

        with open(self.source_path, "rb") as raw_f:
            reader = BudgetedBinaryReader(raw_f, max_bytes)
            source = XmlStreamSource(
                reader, self.selector,
                max_record_bytes=self.max_record_bytes, max_depth=self.max_depth,
            )

            with RecordWriter(jsonl_path, index_path) as writer:
                for i, element in enumerate(source.iter_records(max_records)):
                    if self.cancel_requested:
                        self.outcome = OUTCOME_CANCELLED
                        break
                    try:
                        writer.write_record(element)
                    except OSError:
                        self.outcome = OUTCOME_OUTPUT_IO_ERROR
                        break
                    self.completed_count = writer.written_count
                    self.bytes_read = reader.bytes_read

                    if i % DISK_CHECK_INTERVAL_RECORDS == 0:
                        try:
                            free_now = shutil.disk_usage(self.out_dir).free
                        except OSError:
                            free_now = None
                        if free_now is not None and free_now < self.min_free_disk_bytes:
                            self.outcome = OUTCOME_OUTPUT_DISK_LOW
                            break
                else:
                    # for-else: cancel/disk/yazma nedeniyle break OLMADAN
                    # doğal bitti -- source.stop_reason'a bak.
                    self.stop_reason = source.stop_reason
                    self.element_kind_counts = dict(source.element_kind_counts)
                    self._classify_xml_natural_stop(source)

                self.bytes_read = reader.bytes_read
                self.completed_count = writer.written_count
                if source.error_type_name:
                    self.error_type_name = source.error_type_name
                writer.flush()

    def _classify_xml_natural_stop(self, source: XmlStreamSource) -> None:
        if self.mode == "preview":
            # Önizleme; sınır aşılmış olsun olmasın, KASITLI kısmi bir
            # kategoridir -- asla "tamamlandı" olarak sunulmaz.
            self.outcome = OUTCOME_PREVIEW
            return

        reason = source.stop_reason
        if reason == XML_STOP_SOURCE_REAL_EOF:
            if self.completed_count == 0 and not source.first_segment_matched:
                # Belge sonuna kadar okundu ama yolun İLK parçası bile hiç
                # eşleşmedi -- bu, "container gerçekten boş" değil, "seçici
                # muhtemelen yanlış" durumudur (JSON'daki
                # OUTCOME_TARGET_NOT_FOUND ile aynı rol).
                self.outcome = OUTCOME_TARGET_NOT_FOUND
                self.selector_error_detail = (
                    "Belirtilen kayıt elementi/path kaynak XML'de hiç bulunamadı "
                    "(yolun ilk parçası dahil hiçbir eşleşme yok)."
                )
            else:
                self.outcome = OUTCOME_FULL_COMPLETE
            return
        if reason == XML_STOP_PARSE_ERROR:
            self.outcome = OUTCOME_PARSE_ERROR
            return
        if reason == XML_STOP_SOURCE_IO_ERROR:
            self.outcome = OUTCOME_SOURCE_IO_ERROR
            return
        if reason in (XML_STOP_RECORD_TOO_LARGE, XML_STOP_RECORD_TOO_DEEP):
            self.outcome = OUTCOME_LIMIT_REACHED
            return
        # STOP_BYTE_BUDGET tam aktarımda pratikte hiç ulaşılmaz (bkz.
        # yukarıdaki anlamsız derecede büyük bütçe); yine de savunmacı
        # olarak "tamamlanmadı" say.
        self.outcome = OUTCOME_UNEXPECTED_ERROR

    def _run_yaml(self, jsonl_path: str, index_path: str) -> None:
        # Seçici JSON ile AYNI ŞEKİLDİR ({"mode": "root_array"/"name"/
        # "index"}) -- kök-dizi/alan-adı/alan-sırası seçici doğrulaması
        # dialogs.py'de JSON ile birebir aynı fonksiyon (_build_json_selector)
        # kullanılarak üretilir (bkz. gui/dialogs.py).
        max_records = self.preview_max_records if self.mode == "preview" else (2 ** 62)
        # Tam aktarımda GERÇEK bir bayt sınırı yoktur -- JSON/CSV/XML
        # tarafındaki AYNI desen: pratikte hiçbir zaman dolmayacak,
        # anlamsız derecede büyük bir "bütçe" kullanılır.
        is_preview = (self.mode == "preview")
        max_bytes = self.preview_max_bytes if is_preview else (2 ** 62)
        drain = not is_preview

        with open(self.source_path, "rb") as raw_f:
            reader = BudgetedBinaryReader(raw_f, max_bytes)
            source = YamlStreamSource(
                reader, self.selector,
                max_record_bytes=self.max_record_bytes, max_depth=self.max_depth,
            )

            with RecordWriter(jsonl_path, index_path) as writer:
                try:
                    for i, element in enumerate(source.iter_records(max_records, drain_to_eof=drain)):
                        if self.cancel_requested:
                            self.outcome = OUTCOME_CANCELLED
                            break
                        try:
                            writer.write_record(element)
                        except OSError:
                            self.outcome = OUTCOME_OUTPUT_IO_ERROR
                            break
                        self.completed_count = writer.written_count
                        self.bytes_read = reader.bytes_read

                        if i % DISK_CHECK_INTERVAL_RECORDS == 0:
                            try:
                                free_now = shutil.disk_usage(self.out_dir).free
                            except OSError:
                                free_now = None
                            if free_now is not None and free_now < self.min_free_disk_bytes:
                                self.outcome = OUTCOME_OUTPUT_DISK_LOW
                                break
                    else:
                        # for-else: cancel/disk/yazma nedeniyle break OLMADAN
                        # doğal bitti -- source.stop_reason'a bak.
                        self.stop_reason = source.stop_reason
                        self.element_kind_counts = dict(source.element_kind_counts)
                        self._classify_yaml_natural_stop(source)
                except YamlSelectorError as e:
                    self.outcome = OUTCOME_SELECTOR_ERROR
                    # Bu mesaj yalnızca yapısal bilgi içerir (olay türü,
                    # kullanıcının kendi seçtiği sıra numarası); gerçek alan
                    # adı ya da hücre değeri asla içermez (bkz. yaml_source.py).
                    self.selector_error_detail = str(e)

                self.bytes_read = reader.bytes_read
                self.completed_count = writer.written_count
                if source.error_type_name:
                    self.error_type_name = source.error_type_name
                writer.flush()

    def _classify_yaml_natural_stop(self, source: YamlStreamSource) -> None:
        if self.mode == "preview":
            # Önizleme; sınır aşılmış olsun olmasın, KASITLI kısmi bir
            # kategoridir -- asla "tamamlandı" olarak sunulmaz.
            self.outcome = OUTCOME_PREVIEW
            return

        reason = source.stop_reason
        if reason == YAML_STOP_FULLY_DRAINED:
            self.outcome = OUTCOME_FULL_COMPLETE
            return
        if reason == YAML_STOP_PARSE_ERROR:
            self.outcome = OUTCOME_PARSE_ERROR
            return
        if reason == YAML_STOP_SOURCE_IO_ERROR:
            self.outcome = OUTCOME_SOURCE_IO_ERROR
            return
        if reason in (YAML_STOP_RECORD_TOO_LARGE, YAML_STOP_RECORD_TOO_DEEP):
            self.outcome = OUTCOME_LIMIT_REACHED
            return
        if reason == YAML_STOP_UNSUPPORTED_STRUCTURE:
            self.outcome = OUTCOME_YAML_UNSUPPORTED_STRUCTURE
            self.yaml_error_detail = (
                "Kaynak YAML'de alias/anchor, çok belgeli yapı ya da desteklenmeyen "
                "bir tür/etiket kullanımı tespit edildi (bkz. hata sınıfı); büyük YAML "
                "aktarımı bu yapıları güvenle akışlaştıramaz."
            )
            return
        if reason == YAML_STOP_SOURCE_REAL_EOF and source.matched_key_ordinal is None \
                and self.selector.get("mode") != "root_array":
            # Belge sonuna kadar okundu ama secici hic eslesmedi (hedef
            # alan hic bulunamadi) -- JSON'daki AYNI kategori.
            self.outcome = OUTCOME_TARGET_NOT_FOUND
            self.selector_error_detail = (
                "Belirtilen alan adı/sırası kaynak YAML'de hiç bulunamadı."
            )
            return
        # Beklenmeyen bir kombinasyon; savunmacı olarak "tamamlanmadı" say.
        self.outcome = OUTCOME_UNEXPECTED_ERROR

    def _classify_natural_stop(self, source: StreamingArraySource) -> None:
        reason = source.stop_reason
        self.error_type_name = source.error_type_name

        if self.mode == "preview":
            # Önizleme; sınır aşılmış olsun olmasın, KASITLI kısmi bir
            # kategoridir -- asla "tamamlandı" olarak sunulmaz.
            self.outcome = OUTCOME_PREVIEW
            return

        if reason == STOP_FULLY_DRAINED:
            self.outcome = OUTCOME_FULL_COMPLETE
            return
        if reason in ("ayristirma_hatasi",):
            self.outcome = OUTCOME_PARSE_ERROR
            return
        if reason in ("kaynak_okuma_hatasi",):
            self.outcome = OUTCOME_SOURCE_IO_ERROR
            return
        if reason in ("kayit_cok_buyuk", "kayit_cok_derin"):
            self.outcome = OUTCOME_LIMIT_REACHED
            return
        if reason == "kaynak_dosyasi_tamamen_bitti" and source.matched_key_ordinal is None \
                and self.selector.get("mode") != "root_array":
            # Belge sonuna kadar okundu ama secici hic eslesmedi (hedef
            # dizi/alan hic bulunamadi).
            self.outcome = OUTCOME_TARGET_NOT_FOUND
            return
        # Beklenmeyen bir kombinasyon (ör. dizi kapandi ama drain
        # istenmedigi halde STOP_ARRAY_COMPLETE geldi -- tam modda
        # olmamali, ama savunmaci olarak "tamamlanmadi" say).
        self.outcome = OUTCOME_UNEXPECTED_ERROR

    def _write_manifest(self) -> None:
        complete = (self.mode == "full" and self.outcome == OUTCOME_FULL_COMPLETE)
        data = {
            "surum": MANIFEST_VERSION,
            "kaynak_dosya": self.source_path,
            "kaynak_format": self.source_format,
            "secici": self.selector,
            "mod": self.mode,
            "sonuc": self.outcome,
            "durma_nedeni": self.stop_reason,
            "hata_sinifi": self.error_type_name,
            "secici_hata_detayi": self.selector_error_detail,
            "csv_hata_detayi": self.csv_row_error_detail,
            "yaml_hata_detayi": self.yaml_error_detail,
            "eleman_turu_dagilimi": self.element_kind_counts,
            "tamamlanan_kayit_sayisi": self.completed_count,
            "kaynaktan_okunan_bayt": self.bytes_read,
            "yazilan_bayt": self.written_bytes,
            "gecen_sure_saniye": self.elapsed(),
            "tamamlandi_mi": complete,
        }
        if self.source_format == "csv":
            # Kayıtlar depoda SIRALI METİN LİSTESİ (positional) olarak
            # tutulur; gerçek kolon adları (CSV başlıkları) yalnızca burada,
            # manifest'te BİR KEZ saklanır -- GUI depo açıldığında kolon
            # adlarını buradan alır (bkz. gui/main_window.py, gui/table_view.py).
            data["kolonlar"] = self.csv_headers if self.csv_headers is not None else []
        with open(self.manifest_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
