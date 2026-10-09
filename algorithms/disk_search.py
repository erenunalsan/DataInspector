"""Disk modunda (açık kayıt deposunun TAMAMINDA) düz metin içerme araması.

Büyük/küçük harfe duyarlı, Python'ın `in` operatörüyle yapılır. Projenin
kendi arama algoritması (KMP, algorithms/search.py) yalnızca bellek-içi
küçük dosya modu için geçerlidir; disk modunda bu zorunluluk kaldırılmıştır.

Kayıtlar depodan, MEVCUT GÖRÜNÜM SIRASINI izleyerek (view_reader verilmişse
onun ürettiği sırayla, yoksa kaynak sırasıyla) tek tek okunur; tüm kayıtlar
ya da metinleri belleğe toplanmaz. Eşleşen (görünüm konumu, kaynak kayıt
kimliği) çiftleri RAM'de büyüyen bir listede TUTULMAZ; sırayla, ayrı bir
geçici ikili dosyaya 2x64 bit (uint64, little-endian) olarak yazılır —
böylece bir eşleşmeye gitmek için gereken görünüm konumu, deponun tamamını
kapsayan bir RAM ters-eşlemesi kurmadan doğrudan sonuç dosyasından okunur.

**Kaynak sırası taraması (view_reader None) için performans notu:** Bu
yol artık `RecordReader.read_record()` ile kayıt başına ayrı dosya
açma/`seek()` YAPMAZ; bunun yerine `kayitlar.jsonl` TEK bir dosya
tanıtıcısıyla baştan sona ardışık okunur (bkz. `_iter_jsonl_lines_sequential`).
Güvenli sorgularda (bkz. `_is_raw_prefilter_safe`) önce HAM (JSON'a
çözümlenmemiş) bayt/metin üzerinde ucuz bir ön eleme yapılır; yalnızca aday
satırlar JSON'a çözümlenip mevcut `format_value`/hücre-bazlı `_record_matches`
ile DOĞRULANIR. Bu iki adımlı yaklaşım, arama SONUCUNU asla değiştirmez --
yalnızca hangi satırların pahalı JSON çözümlemesinden GEÇTİĞİNİ azaltır.
Güvensiz sorgularda ön eleme atlanır (her satır doğrudan çözümlenir); tek
dosya tanıtıcısı avantajı yine de korunur. **Sıralanmış görünüm** (view_reader
verilmiş) bu optimizasyonu KULLANMAZ -- kayıtlar dosyada ardışık
olmayabileceğinden mevcut indeksli `read_record()` yolunda kalır.
"""
import os
import struct
import time

import simplejson as sj

from models import format_value

_ENTRY_STRUCT = struct.Struct("<QQ")  # (view_position, record_id)

# format_value(cell), bir kaydın HAM (simplejson ile kodlanmış) JSON
# baytlarından yalnızca TEK bir bilinen durumda farklı metin üretir: bool
# True/False -> Python str() ile "True"/"False" (büyük harfli) yazılırken,
# JSON bunu küçük harfle ("true"/"false", tırnaksız) kodlar. format_value
# başka HİÇBİR büyük/küçük harf ya da biçim farkı üretmez (MISSING/None
# HER ZAMAN "" olur; sayı/Decimal iki temsilde de aynı basamaklarla
# yazılır -- bkz. RecordWriter'ın simplejson(use_decimal=True) kullanımı).
# Bu yüzden sorgu TAM OLARAK bu 9 ön-ekten biriyse (ör. "T", "Tru", "False")
# ham bayt ön elemesi GÜVENSİZDİR (yanlış negatif riski taşır) -- bkz.
# _is_raw_prefilter_safe.
_BOOL_TEXT_PREFIXES = frozenset("True"[:k] for k in range(1, 5)) | frozenset(
    "False"[:k] for k in range(1, 6)
)


def _is_raw_prefilter_safe(query: str) -> bool:
    """`query`, bir kaydın HAM (JSON'a çözümlenmemiş) bayt gösterimi
    üzerinde doğrudan bir bayt/metin ön elemesi için GÜVENLİ mi -- yani:
    query herhangi bir hücrenin format_value(cell) metninde bir alt dize
    olarak geçiyorsa, AYNI query'nin kaydın ham JSON baytlarında da
    MUTLAKA bir alt dize olarak geçeceği garanti mi (yanlış negatif YOK)?

    İki güvensiz durum vardır:
      1. `query`, `"`, `\\` ya da bir ASCII kontrol karakteri (0x00-0x1F)
         içeriyorsa: JSON, bir metin hücresinin İÇİNDEKİ bu karakterleri
         escape eder (ör. gerçek `"` -> ham baytlarda `\\"`); query'nin
         kendisi böyle bir karakter içeriyorsa düz metindeki bir eşleşme
         ham baytlarda AYNI ŞEKİLDE görünmeyebilir.
      2. `query`, TAM OLARAK "True"/"False" metninin bir ön-ekiyse (bkz.
         `_BOOL_TEXT_PREFIXES`) -- bkz. yukarıdaki modül-seviyesi not.

    Her iki durumda da False döner; çağıran taraf ham ön elemeyi ATLAYIP
    HER satırı doğrudan JSON'a çözümler (tek dosya tanıtıcısı avantajı
    yine de korunur) -- mevcut arama anlamı hiçbir zaman değişmez."""
    if query in _BOOL_TEXT_PREFIXES:
        return False
    for ch in query:
        if ch == '"' or ch == "\\" or ord(ch) < 0x20:
            return False
    return True


def _iter_jsonl_lines_sequential(jsonl_path: str):
    """`kayitlar.jsonl`'u TEK bir dosya tanıtıcısıyla, baştan sona fiziksel
    satır satır okur. `RecordWriter` her kaydı `<json>\\n` olarak yazdığından
    (bkz. disk_store.py) ve JSON kodlayıcıları bir metin hücresinin
    İÇİNDEKİ gerçek satır sonu karakterlerini HER ZAMAN `\\n` (iki karakterlik
    escape) olarak yazdığından, dosyadaki HAM 0x0A baytları YALNIZCA kayıt
    sınırlarında bulunur -- bu yüzden basit satır-satır okuma, kayıt
    sınırlarını asla yanlış bölmez.

    (record_id, ham_bayt) çiftleri üretir; record_id, dosyaya yazılma
    sırasına göre 0 tabanlı ve ARDIŞIKTIR -- bu yalnızca KAYNAK sırası
    (view_reader is None) taramasında geçerlidir; sıralanmış bir görünümde
    kayıtlar dosyada ardışık olmayabileceği için bu yol kullanılmaz."""
    with open(jsonl_path, "rb") as f:
        record_id = 0
        for raw_line in f:
            yield record_id, raw_line.rstrip(b"\n")
            record_id += 1


def _record_cells(record):
    """Bir kaydın TÜM hücrelerini verir (ekranda o an bilinen kolon
    sayısından bağımsız). Hücreler asla birleştirilmez; her biri ayrı
    değerlendirilir (farklı hücreleri birleştirip sahte eşleşme üretmemek
    için)."""
    if isinstance(record, dict):
        return record.values()
    if isinstance(record, list):
        return record
    return [record]


def _record_matches(record, query: str) -> bool:
    for cell in _record_cells(record):
        if query in format_value(cell):
            return True
    return False


class DiskSearchJob:
    """Tek seferlik, iptal edilebilir bir disk arama işi.

    run() bir arka plan thread'inde çalıştırılmalıdır; hiçbir Tk
    widget'ına dokunmaz. İlerleme (scanned_count/found_count) basit int
    alanlarla tutulur; ana thread bunları yalnızca YAKLAŞIK bir gösterge
    olarak periyodik okur (kilit gerektirmez, CPython'da atomik atama).
    """

    def __init__(self, disk_reader, query: str, store_generation: int, view_reader=None):
        self.disk_reader = disk_reader
        self.query = query
        self.store_generation = store_generation
        self.view_reader = view_reader  # None -> kaynak sırası; degilse mevcut sıralı görünüm

        self.scanned_count = 0
        self.found_count = 0
        self.cancel_requested = False
        self.done = False
        self.error = None
        self.results_path = None
        self.start_time = time.perf_counter()
        self._end_time = None

    def request_cancel(self) -> None:
        self.cancel_requested = True

    def snapshot(self):
        return self.scanned_count, self.found_count

    def elapsed(self) -> float:
        end = self._end_time if self._end_time is not None else time.perf_counter()
        return end - self.start_time

    def _iter_current_view(self):
        """YALNIZCA sıralanmış görünüm (view_reader verilmiş) için kullanılır.
        Kaynak sırası artık burada DEĞİL, tek dosya tanıtıcılı
        `_run_source_order_sequential`'da işlenir (bkz. aşağı)."""
        total = self.view_reader.count()
        batch = 4096
        p = 0
        while p < total:
            ids = self.view_reader.get_range(p, min(batch, total - p))
            for rid in ids:
                yield p, rid
                p += 1

    def run(self, results_path: str) -> None:
        """Mevcut görünüm sırasını izleyerek okur. İptal edilirse ya da bir
        hata oluşursa, o ana kadar bulunan eşleşmeler dosyada kalır (yarım
        bırakılan bir SONRAKİ kaydın kısmi verisi asla yazılmaz)."""
        self.results_path = results_path
        try:
            with open(results_path, "wb") as out:
                if self.view_reader is None:
                    self._run_source_order_sequential(out)
                else:
                    self._run_via_view_reader(out)
        except Exception as e:
            self.error = e
        finally:
            self._end_time = time.perf_counter()
            self.done = True

    def _run_via_view_reader(self, out) -> None:
        """Sıralanmış görünüm: MEVCUT indeksli yol (RecordReader.read_record
        ile rastgele erişim) DEĞİŞMEDEN kullanılır -- sıralanmış bir
        görünümde kayıtlar dosyada ardışık OLMAYABİLİR, bu yüzden ardışık
        dosya okuması burada uygulanamaz."""
        for position, record_id in self._iter_current_view():
            if self.cancel_requested:
                break
            record = self.disk_reader.read_record(record_id)
            if _record_matches(record, self.query):
                out.write(_ENTRY_STRUCT.pack(position, record_id))
                self.found_count += 1
            self.scanned_count = position + 1

    def _run_source_order_sequential(self, out) -> None:
        """Kaynak sırası (view_reader is None): `kayitlar.jsonl` TEK bir
        dosya tanıtıcısıyla baştan sona ardışık okunur -- kayıt başına ayrı
        dosya açma/`seek()` YAPILMAZ. Güvenli sorgularda önce ham bayt/metin
        ön elemesi yapılır; yalnızca aday satırlar JSON'a çözümlenip mevcut
        `format_value`/hücre-bazlı `_record_matches` ile DOĞRULANIR --
        böylece hücreler arası birleşmeden sahte eşleşme oluşmaz ve mevcut
        arama anlamı hiç değişmez. Güvensiz sorgularda (bkz.
        `_is_raw_prefilter_safe`) ön eleme atlanır, HER satır doğrudan
        JSON'a çözümlenir (tek dosya tanıtıcısı avantajı yine de korunur)."""
        query_bytes = self.query.encode("utf-8") if _is_raw_prefilter_safe(self.query) else None
        jsonl_path = self.disk_reader.jsonl_path
        for record_id, raw_line in _iter_jsonl_lines_sequential(jsonl_path):
            if self.cancel_requested:
                break
            if query_bytes is not None and query_bytes not in raw_line:
                self.scanned_count = record_id + 1
                continue
            record = sj.loads(raw_line.decode("utf-8"), use_decimal=True)
            if _record_matches(record, self.query):
                out.write(_ENTRY_STRUCT.pack(record_id, record_id))
                self.found_count += 1
            self.scanned_count = record_id + 1


class SearchResultsStore:
    """Arama sonuçlarını (görünüm konumu, kaynak kayıt kimliği) çiftleri
    olarak tutan, sabit boyutlu (16 bayt) ikili dosya üzerinden bir görünüm.
    Sonuçların tamamı asla belleğe yüklenmez; istenen konum doğrudan
    dosyadan okunur."""

    def __init__(self, path: str):
        self.path = path

    def count(self) -> int:
        return os.path.getsize(self.path) // _ENTRY_STRUCT.size

    def get(self, index: int):
        """(view_position, record_id) çiftini döner."""
        with open(self.path, "rb") as f:
            f.seek(index * _ENTRY_STRUCT.size)
            raw = f.read(_ENTRY_STRUCT.size)
        if len(raw) < _ENTRY_STRUCT.size:
            raise IndexError(f"Arama sonucu konumu aralık dışı: {index}")
        return _ENTRY_STRUCT.unpack(raw)
