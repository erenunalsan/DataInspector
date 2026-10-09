"""time.perf_counter() tabanlı basit süre ölçüm yardımcısı."""
import time


class Timer:
    """`with Timer() as t: ...` bloğunun süresini saniye cinsinden `t.elapsed`'e yazar."""

    def __enter__(self):
        self._start = time.perf_counter()
        self.elapsed = None
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.elapsed = time.perf_counter() - self._start
        return False
