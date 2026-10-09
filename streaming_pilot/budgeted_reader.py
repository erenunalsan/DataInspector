"""Toplam okuma baytını sabit bir bütçeyle sınırlayan, ikili (binary) dosya
sarmalayıcısı.

Bütçe, alttaki gerçek dosya okuyucusunun kendisinde uygulanır; ijson'ın
kendi iç tamponlama okumaları da (hangi boyutta .read() çağırırsa çağırsın)
bu sayaca dahildir, çünkü hepsi bu sarmalayıcının read()'inden geçer.

İki durum kesin olarak ayrı tutulur:
  - budget_hit:  bütçe dolduğu için OKUMA KENDİMİZ kestik (gerçek dosyanın
                 sonuna henüz gelinmemiş olabilir).
  - real_eof:    alttaki gerçek dosya, bütçe dolmadan kendiliğinden bitti
                 (gerçek EOF).
Bu ikisi asla "bozuk JSON" ile karıştırılmaz; ayrım tamamen bu sınıfta,
ijson'a hiç danışılmadan yapılır.
"""


class BudgetedBinaryReader:
    def __init__(self, fileobj, budget_bytes: int):
        if budget_bytes <= 0:
            raise ValueError("budget_bytes pozitif olmalı")
        self._f = fileobj
        self.budget_bytes = budget_bytes
        self.bytes_read = 0
        self.budget_hit = False
        self.real_eof = False

    def read(self, size=-1):
        if self.budget_hit or self.real_eof:
            return b""

        remaining = self.budget_bytes - self.bytes_read
        if remaining <= 0:
            self.budget_hit = True
            return b""

        to_read = remaining if (size is None or size < 0) else min(size, remaining)
        if to_read == 0:
            # 0 bayt istenip 0 bayt donmesi EOF degildir (ör. ijson'un
            # baslangicta yaptigi read(0) "yoklama" cagrisi gibi).
            return b""

        chunk = self._f.read(to_read)

        if chunk == b"":
            self.real_eof = True
            return b""

        self.bytes_read += len(chunk)
        if self.bytes_read >= self.budget_bytes:
            self.budget_hit = True
        return chunk

    def readable(self) -> bool:
        return True
