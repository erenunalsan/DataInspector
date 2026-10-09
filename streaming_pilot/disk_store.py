"""Diskte JSONL + sabit boyutlu ikili indeks + küçük manifest ile kayıt
saklama. Hiçbir aşamada tüm veri kümesi ya da tüm indeks belleğe
yüklenmez; her çağrı yalnızca istenen aralığı okur.

İndeks kaydı: struct "<QQ" (offset uint64, length uint64) = 16 bayt.
Ofset/uzunluk, KENDİ çıktı JSONL dosyamız üzerinden hesaplanır — kaynağın
(ijson'ın okuduğu gerçek dosyanın) tell() değeriyle hiçbir ilgisi yoktur.
"""
import json as _stdlib_json
import os
import struct

import simplejson as sj

from streaming_pilot.streaming_source import COMPLETE_STOP_REASONS

INDEX_ENTRY_STRUCT = struct.Struct("<QQ")
INDEX_ENTRY_SIZE = INDEX_ENTRY_STRUCT.size

MANIFEST_VERSION = 1


class RecordWriter:
    """Kayıtları JSONL dosyasına yazar; her kayıt için kendi çıktı
    dosyamızdaki bayt ofset/uzunluğunu ayrı bir indeks dosyasına ekler.
    Decimal/büyük tamsayı/metin değerleri simplejson (use_decimal=True)
    ile kayıpsız serileştirilir; default=str veya zorunlu float
    dönüşümü YOKTUR.
    """

    def __init__(self, jsonl_path: str, index_path: str):
        self.jsonl_path = jsonl_path
        self.index_path = index_path
        self._jsonl_f = open(jsonl_path, "wb")
        self._index_f = open(index_path, "wb")
        self._offset = 0
        self.written_count = 0

    def write_record(self, value) -> None:
        encoded = sj.dumps(value, use_decimal=True, ensure_ascii=False).encode("utf-8")
        self._jsonl_f.write(encoded)
        self._jsonl_f.write(b"\n")
        self._index_f.write(INDEX_ENTRY_STRUCT.pack(self._offset, len(encoded)))
        self._offset += len(encoded) + 1
        self.written_count += 1

    def flush(self) -> None:
        self._jsonl_f.flush()
        self._index_f.flush()

    def close(self) -> None:
        self._jsonl_f.close()
        self._index_f.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
        return False


class RecordReader:
    """Kapatılıp yeniden açılabilir; her çağrı yalnızca istenen aralığı
    okur (indeksin tamamı asla belleğe yüklenmez)."""

    MAX_PAGE_SIZE = 500

    def __init__(self, jsonl_path: str, index_path: str):
        self.jsonl_path = jsonl_path
        self.index_path = index_path

    def record_count(self) -> int:
        size = os.path.getsize(self.index_path)
        return size // INDEX_ENTRY_SIZE

    def _read_index_entries(self, start: int, count: int):
        with open(self.index_path, "rb") as f:
            f.seek(start * INDEX_ENTRY_SIZE)
            raw = f.read(count * INDEX_ENTRY_SIZE)
        n = len(raw) // INDEX_ENTRY_SIZE
        return [INDEX_ENTRY_STRUCT.unpack_from(raw, i * INDEX_ENTRY_SIZE) for i in range(n)]

    def read_record(self, i: int):
        entries = self._read_index_entries(i, 1)
        if not entries:
            raise IndexError(f"Kayıt indeksi aralık dışı: {i}")
        offset, length = entries[0]
        with open(self.jsonl_path, "rb") as f:
            f.seek(offset)
            raw = f.read(length)
        return sj.loads(raw.decode("utf-8"), use_decimal=True)

    def read_page(self, start: int, count: int = 500):
        """[start, start+count) aralığındaki kayıtları döner (en fazla 500)."""
        if count > self.MAX_PAGE_SIZE:
            raise ValueError(f"Bir sayfada en fazla {self.MAX_PAGE_SIZE} kayıt okunabilir")
        entries = self._read_index_entries(start, count)
        if not entries:
            return []
        first_offset = entries[0][0]
        last_offset, last_len = entries[-1]
        span = (last_offset + last_len) - first_offset
        with open(self.jsonl_path, "rb") as f:
            f.seek(first_offset)
            blob = f.read(span)
        records = []
        for offset, length in entries:
            rel = offset - first_offset
            raw = blob[rel: rel + length]
            records.append(sj.loads(raw.decode("utf-8"), use_decimal=True))
        return records


def write_manifest(path: str, *, source_path: str, selector: dict,
                    element_kind_counts: dict, completed_count: int,
                    bytes_read: int, stop_reason: str,
                    error_type_name) -> None:
    """Küçük, yalnızca sayı/durum/yol içeren bir manifest yazar (veri
    içeriği yoktur). tamamlandi_mi yalnızca gerçekten hiçbir budama/hata
    olmadan durulduysa True olur; aktarım yarımsa asla True olmaz."""
    complete = stop_reason in COMPLETE_STOP_REASONS
    data = {
        "surum": MANIFEST_VERSION,
        "kaynak_dosya": source_path,
        "secici": selector,
        "eleman_turu_dagilimi": element_kind_counts,
        "tamamlanan_kayit_sayisi": completed_count,
        "kaynaktan_okunan_bayt": bytes_read,
        "durma_nedeni": stop_reason,
        "hata_sinifi": error_type_name,
        "tamamlandi_mi": complete,
    }
    with open(path, "w", encoding="utf-8") as f:
        _stdlib_json.dump(data, f, ensure_ascii=False, indent=2)


def read_manifest(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return _stdlib_json.load(f)


def is_dataset_complete(manifest_path: str) -> bool:
    """Bir aktarımın TAMAMLANMIŞ veri kümesi olarak gösterilip
    gösterilemeyeceğinin tek yetkili kaynağı budur."""
    return bool(read_manifest(manifest_path).get("tamamlandi_mi", False))
