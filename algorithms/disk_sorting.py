"""Disk modunda (açık kayıt deposunun TAMAMINDA) harici (external) sıralama.

Python'ın hazır sıralaması (list.sort()/sorted(), parça-içi) ve heapq.merge
(parçalar arası k-yönlü birleştirme) kullanılır — bunlar stdlib standart
araçlarıdır; projenin kendi algoritmasını yazma zorunluluğu bu yol için
kaldırılmıştır.

Kayıtlar küçük gruplar (chunk) halinde işlenir. Geçici parça (run)
dosyalarında yalnızca (sıralama anahtarı, kaynak kayıt kimliği) çiftleri
bulunur; ham kayıtlar hiçbir zaman kopyalanmaz. Anahtarların tip ve
hassasiyeti (Decimal dahil) pickle ile korunur.

Bellek bütçesi yalnızca kayıt adediyle SINIRLANMAZ: bir grubun bellekte
tutulan anahtarlarının toplam (pickle ile ölçülen) bayt boyutu da izlenir;
iki sınırdan hangisine önce ulaşılırsa grup diske yazılır. Bu, kullanılan
sürecin TAMAMININ bu bütçeyle sınırlı kalacağının garantisi DEĞİLDİR —
Python nesne ek yükü, geçici dosya arabellekleri ve GC davranışı gerçek
süreç belleğini bu nominal bütçenin üzerine çıkarabilir.

Sonuçta üretilen "görünüm sırası" (view_order.seq), sabit boyutlu (8
bayt/uint64) bir dosyadır: dosyadaki i'inci kayıt, yeni görünümün i'inci
(0 tabanlı) konumundaki KAYNAK KAYIT KİMLİĞİDİR. Bu dosya asla RAM
listesine çevrilmez; yalnızca istenen aralık okunur (bkz. SequenceReader).
"""
import heapq
import math
import os
import pickle
import struct
import time
from decimal import Decimal

from models import MISSING

SEQ_ENTRY_STRUCT = struct.Struct("<Q")

DEFAULT_CHUNK_MAX_RECORDS = 20_000
DEFAULT_CHUNK_MAX_KEY_BYTES = 8 * 1024 * 1024   # 8 MB / grup
DEFAULT_MAX_KEY_BYTES = 1 * 1024 * 1024           # tek bir anahtar için sınır
DEFAULT_MAX_OPEN_RUNS = 8                           # birleştirmede aynı anda açık dosya sayısı


class SortConfigError(Exception):
    """Yapılandırma/kaynak sınırı ihlali (ör. aşırı büyük tek bir anahtar)."""


# ---------------------------------------------------------------------
# Karşılaştırma kuralları: mevcut bellek-modu kuralları (bkz.
# algorithms/sorting.py) korunur, Decimal desteği eklenir.
# ---------------------------------------------------------------------

def _is_novalue(value) -> bool:
    if value is MISSING or value is None:
        return True
    if isinstance(value, float) and math.isnan(value):
        return True
    return False


def _type_rank(value) -> int:
    if isinstance(value, bool):
        return 0
    if isinstance(value, (int, float, Decimal)):
        return 1
    if isinstance(value, str):
        return 2
    return 3  # liste vb. karmaşık türler


def _rank_and_value(value):
    rank = _type_rank(value)
    if rank == 3:
        return rank, str(value)
    return rank, value


class _Desc:
    """Azalan sıralama için: aynı rank içindeki karşılaştırmayı ters çevirir.
    Gruplar arası öncelik (rank) bundan ETKİLENMEZ; yalnızca aynı rank
    içindeki değer karşılaştırması ters döner. Böylece MISSING/None/NaN'ın
    her zaman sonda kalması ve tip-grubu önceliği yönden bağımsız kalır."""
    __slots__ = ("value",)

    def __init__(self, value):
        self.value = value

    def __lt__(self, other):
        return other.value < self.value

    def __eq__(self, other):
        return self.value == other.value


def make_sort_key(raw_value, position: int, ascending: bool):
    """(is_novalue, rank, deger, position) — position, aynı-anahtarlı
    kayıtların ÖNCEKİ görünüm sırasını (kararlılık) hem tek bir parça
    içinde hem de FARKLI parçalar/birleştirme turları arasında (heapq.merge
    ile) korumak için son eleman olarak eklenir."""
    if _is_novalue(raw_value):
        return (True, 0, None, position)
    rank, val = _rank_and_value(raw_value)
    value_component = val if ascending else _Desc(val)
    return (False, rank, value_component, position)


def get_cell_value_by_name(record, column_name: str, known_columns: list = None):
    """record (dict ya da list) içinden column_name'e karşılık gelen ham
    değeri okur.

    Nesne kayıtlarında doğrudan anahtar kullanılır. Pozisyonel (liste)
    kayıtlarda iki yol vardır:
      - known_columns verilmişse (CSV depoları -- manifest'teki SABİT
        başlık listesi): column_name bu listede aranır, bulunan indekse
        çözülür. Bu, sayfaya özgü bir kolon listesine ihtiyaç duymadan
        (tüm depo taranırken) gerçek başlık adıyla sıralama yapılmasını
        sağlar.
      - known_columns YOKSA (JSON pozisyonel kayıtlar -- mevcut/değişmemiş
        davranış): yalnızca "Kolon N" adı, N-1 pozisyonuna çözülür.
    Yoksa MISSING döner."""
    if isinstance(record, dict):
        return record.get(column_name, MISSING)
    if isinstance(record, list):
        if known_columns is not None:
            try:
                idx = known_columns.index(column_name)
            except ValueError:
                return MISSING
            if 0 <= idx < len(record):
                return record[idx]
            return MISSING
        if column_name.startswith("Kolon "):
            try:
                idx = int(column_name[len("Kolon "):]) - 1
            except ValueError:
                return MISSING
            if 0 <= idx < len(record):
                return record[idx]
        return MISSING
    return MISSING


def key_size_bytes(raw_value) -> int:
    try:
        return len(pickle.dumps(raw_value, protocol=pickle.HIGHEST_PROTOCOL))
    except Exception:
        return 0


# ---------------------------------------------------------------------
# view_order.seq okuma/yazma: sabit boyutlu (8 bayt) uint64 dizisi.
# ---------------------------------------------------------------------

class SequenceWriter:
    def __init__(self, path: str):
        self._f = open(path, "wb")

    def append(self, record_id: int) -> None:
        self._f.write(SEQ_ENTRY_STRUCT.pack(record_id))

    def close(self) -> None:
        self._f.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
        return False


class SequenceReader:
    """view konumu -> kaynak kayıt kimliği. Kapatılıp yeniden açılabilir;
    her çağrı yalnızca istenen aralığı okur, tüm dosya RAM'e yüklenmez."""

    def __init__(self, path: str):
        self.path = path

    def count(self) -> int:
        return os.path.getsize(self.path) // SEQ_ENTRY_STRUCT.size

    def get_range(self, start: int, count: int) -> list:
        with open(self.path, "rb") as f:
            f.seek(start * SEQ_ENTRY_STRUCT.size)
            raw = f.read(count * SEQ_ENTRY_STRUCT.size)
        n = len(raw) // SEQ_ENTRY_STRUCT.size
        return [SEQ_ENTRY_STRUCT.unpack_from(raw, i * SEQ_ENTRY_STRUCT.size)[0] for i in range(n)]

    def get(self, position: int) -> int:
        values = self.get_range(position, 1)
        if not values:
            raise IndexError(f"Görünüm konumu aralık dışı: {position}")
        return values[0]


def _iter_run_entries(path: str):
    """Bir parça (run) dosyasındaki (anahtar, kayıt_kimliği) çiftlerini
    TEK TEK üretir; dosyanın tamamını belleğe yüklemez."""
    with open(path, "rb") as f:
        while True:
            try:
                yield pickle.load(f)
            except EOFError:
                return


def _remove_quietly(paths) -> None:
    for p in paths:
        try:
            os.remove(p)
        except OSError:
            pass


# ---------------------------------------------------------------------
# DiskSortJob
# ---------------------------------------------------------------------

class DiskSortJob:
    """Tek seferlik, iptal edilebilir bir disk sıralama işi.

    run() bir arka plan thread'inde çalıştırılmalıdır; hiçbir Tk widget'ına
    dokunmaz.
    """

    def __init__(self, disk_reader, current_view_reader, column: str, ascending: bool,
                 store_generation: int,
                 chunk_max_records: int = DEFAULT_CHUNK_MAX_RECORDS,
                 chunk_max_key_bytes: int = DEFAULT_CHUNK_MAX_KEY_BYTES,
                 max_key_bytes: int = DEFAULT_MAX_KEY_BYTES,
                 max_open_runs: int = DEFAULT_MAX_OPEN_RUNS,
                 known_columns: list = None):
        self.disk_reader = disk_reader
        self.current_view_reader = current_view_reader  # None -> kaynak sırası (0..N-1)
        self.column = column
        self.ascending = ascending
        self.store_generation = store_generation
        # CSV depoları icin manifest'teki sabit baslik listesi (bkz.
        # get_cell_value_by_name); JSON depolarinda None kalir (mevcut
        # "Kolon N" davranisi degismez).
        self.known_columns = known_columns

        self.chunk_max_records = chunk_max_records
        self.chunk_max_key_bytes = chunk_max_key_bytes
        self.max_key_bytes = max_key_bytes
        self.max_open_runs = max_open_runs

        self.scanned_count = 0
        self.total_count = 0
        self.merge_rounds_done = 0
        self.cancel_requested = False
        self.done = False
        self.error = None
        self.result_path = None
        self.start_time = time.perf_counter()
        self._end_time = None
        self._pending_paths = []  # temizlik için; iptal/hata anında da silinir

    def request_cancel(self) -> None:
        self.cancel_requested = True

    def snapshot(self):
        return self.scanned_count, self.total_count, self.merge_rounds_done

    def elapsed(self) -> float:
        end = self._end_time if self._end_time is not None else time.perf_counter()
        return end - self.start_time

    # -- kaynak: mevcut görünüm sırasını (konum, kayıt_kimliği) olarak üretir --
    def _iter_current_view(self):
        if self.current_view_reader is None:
            n = self.disk_reader.record_count()
            for p in range(n):
                yield p, p
            return
        total = self.current_view_reader.count()
        batch = 4096
        p = 0
        while p < total:
            ids = self.current_view_reader.get_range(p, min(batch, total - p))
            for rid in ids:
                yield p, rid
                p += 1

    def run(self, work_dir: str) -> None:
        try:
            self._run(work_dir)
        except Exception as e:
            self.error = e
            _remove_quietly(self._pending_paths)
            self._pending_paths = []
        finally:
            self._end_time = time.perf_counter()
            self.done = True

    def _run(self, work_dir: str) -> None:
        os.makedirs(work_dir, exist_ok=True)
        self.total_count = (
            self.disk_reader.record_count() if self.current_view_reader is None
            else self.current_view_reader.count()
        )

        run_paths = []
        chunk = []
        chunk_key_bytes = 0

        def flush_chunk():
            nonlocal chunk, chunk_key_bytes
            if not chunk:
                return
            chunk.sort(key=lambda item: item[0])
            path = os.path.join(work_dir, f"run_{len(run_paths)}.pkl")
            with open(path, "wb") as f:
                for entry in chunk:
                    pickle.dump(entry, f, protocol=pickle.HIGHEST_PROTOCOL)
            run_paths.append(path)
            self._pending_paths = list(run_paths)
            chunk = []
            chunk_key_bytes = 0

        for position, record_id in self._iter_current_view():
            if self.cancel_requested:
                _remove_quietly(run_paths)
                return
            record = self.disk_reader.read_record(record_id)
            raw_value = get_cell_value_by_name(record, self.column, self.known_columns)

            size = key_size_bytes(raw_value)
            if size > self.max_key_bytes:
                raise SortConfigError(
                    f"Tek bir sıralama anahtarı çok büyük ({size} bayt, sınır "
                    f"{self.max_key_bytes} bayt); görünüm konumu {position}."
                )

            key = make_sort_key(raw_value, position, self.ascending)
            chunk.append((key, record_id))
            chunk_key_bytes += size
            self.scanned_count = position + 1

            if len(chunk) >= self.chunk_max_records or chunk_key_bytes >= self.chunk_max_key_bytes:
                flush_chunk()

        flush_chunk()

        if self.cancel_requested:
            _remove_quietly(run_paths)
            return

        if not run_paths:
            # Boş depo: bos bir view_order.seq üret.
            output_path = os.path.join(work_dir, "view_order.seq")
            with SequenceWriter(output_path):
                pass
            self.result_path = output_path
            return

        result = self._merge_runs(run_paths, work_dir)
        if result is None:
            return  # iptal edildi, _merge_runs kendi temizligini yapti
        self.result_path = result

    def _merge_runs(self, run_paths: list, work_dir: str):
        current = list(run_paths)
        round_num = 0
        while len(current) > self.max_open_runs:
            if self.cancel_requested:
                _remove_quietly(current)
                return None
            round_num += 1
            new_paths = []
            for i in range(0, len(current), self.max_open_runs):
                if self.cancel_requested:
                    _remove_quietly(new_paths)
                    _remove_quietly(current)
                    return None
                group = current[i:i + self.max_open_runs]
                merged_path = os.path.join(work_dir, f"merged_r{round_num}_{i}.pkl")
                self._merge_group_to_run_file(group, merged_path)
                new_paths.append(merged_path)
            _remove_quietly(current)
            current = new_paths
            self._pending_paths = list(current)
            self.merge_rounds_done += 1

        if self.cancel_requested:
            _remove_quietly(current)
            return None

        output_path = os.path.join(work_dir, "view_order.seq")
        self._merge_group_to_sequence(current, output_path)
        _remove_quietly(current)
        self._pending_paths = []
        self.merge_rounds_done += 1

        if self.cancel_requested:
            _remove_quietly([output_path])
            return None
        return output_path

    def _merge_group_to_run_file(self, paths: list, out_path: str) -> None:
        iterators = [_iter_run_entries(p) for p in paths]
        with open(out_path, "wb") as out:
            for entry in heapq.merge(*iterators, key=lambda e: e[0]):
                pickle.dump(entry, out, protocol=pickle.HIGHEST_PROTOCOL)

    def _merge_group_to_sequence(self, paths: list, out_path: str) -> None:
        iterators = [_iter_run_entries(p) for p in paths]
        with SequenceWriter(out_path) as seq:
            for _key, record_id in heapq.merge(*iterators, key=lambda e: e[0]):
                seq.append(record_id)
