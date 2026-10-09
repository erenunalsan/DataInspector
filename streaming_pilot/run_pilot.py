"""Pilot çalıştırma orkestrasyonu: kaynağı TEK SEFER, salt okunur açar;
akışla okur; kayıtları diske (JSONL + indeks) yazar; bir manifest üretir.

Mevcut GUI/parsers entegrasyonu YOKTUR; parsers.load() burada hiç
çağrılmaz. Otomatik yeniden tarama yapılmaz (bir kere denenir, biter).
"""
import argparse
import ctypes
import os
import time

from streaming_pilot.budgeted_reader import BudgetedBinaryReader
from streaming_pilot.disk_store import RecordWriter, write_manifest
from streaming_pilot.streaming_source import StreamingArraySource

DEFAULT_MAX_BYTES = 32 * 1024 * 1024
DEFAULT_MAX_RECORDS = 1000


def peak_working_set_bytes():
    """Bu Python sürecinin şu ana kadarki en yüksek çalışma kümesi (working
    set) boyutu, Windows'un GetProcessMemoryInfo API'siyle (ctypes, ek
    bağımlılık yok) ölçülür. Bu, TÜM sürecin belleğidir; yalnızca bu
    pilotun kullandığı miktarla sınırlı değildir ve kesin bir üst sınır
    değil, ölçüm anına kadarki gözlemdir (örneklenmiş tepe değeri)."""
    from ctypes import wintypes

    class PROCESS_MEMORY_COUNTERS(ctypes.Structure):
        _fields_ = [
            ("cb", wintypes.DWORD),
            ("PageFaultCount", wintypes.DWORD),
            ("PeakWorkingSetSize", ctypes.c_size_t),
            ("WorkingSetSize", ctypes.c_size_t),
            ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
            ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
            ("PagefileUsage", ctypes.c_size_t),
            ("PeakPagefileUsage", ctypes.c_size_t),
        ]

    try:
        psapi = ctypes.WinDLL("psapi.dll")
        kernel32 = ctypes.WinDLL("kernel32.dll")
        kernel32.GetCurrentProcess.restype = wintypes.HANDLE
        psapi.GetProcessMemoryInfo.argtypes = [
            wintypes.HANDLE, ctypes.POINTER(PROCESS_MEMORY_COUNTERS), wintypes.DWORD,
        ]
        psapi.GetProcessMemoryInfo.restype = wintypes.BOOL

        counters = PROCESS_MEMORY_COUNTERS()
        counters.cb = ctypes.sizeof(PROCESS_MEMORY_COUNTERS)
        handle = kernel32.GetCurrentProcess()
        ok = psapi.GetProcessMemoryInfo(handle, ctypes.byref(counters), counters.cb)
        if not ok:
            return None
        return counters.PeakWorkingSetSize
    except Exception:
        return None


def parse_selector(spec: str) -> dict:
    """'index:3' | 'name:GERCEK_AD' | 'first_array' biçimini çözer.
    Hiçbir gerçek anahtar adı burada sabit kodlanmaz; çağıran taraf verir."""
    if spec == "first_array":
        return {"mode": "first_array"}
    mode, sep, value = spec.partition(":")
    if not sep:
        raise ValueError(f"Geçersiz seçici: {spec!r}")
    if mode == "index":
        return {"mode": "index", "value": int(value)}
    if mode == "name":
        return {"mode": "name", "value": value}
    raise ValueError(f"Geçersiz seçici modu: {mode!r}")


def run_pilot(source_path: str, out_dir: str, selector: dict,
              max_bytes: int = DEFAULT_MAX_BYTES,
              max_records: int = DEFAULT_MAX_RECORDS) -> dict:
    os.makedirs(out_dir, exist_ok=True)
    jsonl_path = os.path.join(out_dir, "kayitlar.jsonl")
    index_path = os.path.join(out_dir, "kayitlar.idx")
    manifest_path = os.path.join(out_dir, "manifest.json")

    start = time.perf_counter()
    with open(source_path, "rb") as raw_f:
        reader = BudgetedBinaryReader(raw_f, max_bytes)
        source = StreamingArraySource(reader, selector)
        with RecordWriter(jsonl_path, index_path) as writer:
            for element in source.iter_records(max_records):
                writer.write_record(element)
            writer.flush()
    elapsed = time.perf_counter() - start

    write_manifest(
        manifest_path,
        source_path=source_path,
        selector=selector,
        element_kind_counts=source.element_kind_counts,
        completed_count=source.completed_count,
        bytes_read=reader.bytes_read,
        stop_reason=source.stop_reason,
        error_type_name=source.error_type_name,
    )

    return {
        "jsonl_path": jsonl_path,
        "index_path": index_path,
        "manifest_path": manifest_path,
        "elapsed_seconds": elapsed,
        "bytes_read": reader.bytes_read,
        "completed_count": source.completed_count,
        "stop_reason": source.stop_reason,
        "element_kind_counts": dict(source.element_kind_counts),
        "error_type_name": source.error_type_name,
        "peak_working_set_bytes": peak_working_set_bytes(),
    }


def main():
    ap = argparse.ArgumentParser(
        description="Akışlı JSON -> diskte JSONL+indeks pilotu (DuckDB kullanılmaz)"
    )
    ap.add_argument("--source", required=True)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--selector", required=True, help="index:N | name:AD | first_array")
    ap.add_argument("--max-bytes", type=int, default=DEFAULT_MAX_BYTES)
    ap.add_argument("--max-records", type=int, default=DEFAULT_MAX_RECORDS)
    args = ap.parse_args()

    result = run_pilot(
        args.source, args.out_dir, parse_selector(args.selector),
        max_bytes=args.max_bytes, max_records=args.max_records,
    )
    for k, v in result.items():
        print(f"{k}: {v}")


if __name__ == "__main__":
    main()
