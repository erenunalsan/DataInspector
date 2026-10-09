"""JSON: satır başına bir kayıt (JSON Lines / satır satır basılmış dizi).

Desteklenen düzen — gerçekten büyük JSON veri dosyalarının neredeyse her
zaman üretildiği biçim:

    {"count":238758543,"cols":6,"rows":[      <- başlık satırı (atlanır)
    ["0_0_ab...","0_1_cd...", ...],           <- kayıt
    ["1_0_ef...","1_1_gh...", ...],           <- kayıt
    ...
    ["...","..."]                             <- son kayıt (virgülsüz)
    ]}                                        <- kuyruk (atlanır)

Kök doğrudan bir dizi (`[` ilk satırda, kayıtlar sonraki satırlarda) ya da
saf JSON Lines (her satır bağımsız bir nesne/dizi, hiç sarmalayıcı yok)
olabilir; üçü de aynı kuralla çözülür.

Kayıt satırının sonundaki virgül JSON'a göre satırın parçası değildir;
çözümlemeden önce atılır. Satır sonu JSON dizgilerinin İÇİNDE ham olarak
bulunamaz (JSON standardı yasaklar; `\\n` kaçışı kullanılır), bu yüzden
"bir satır = bir kayıt" varsayımı JSON'da yapısal olarak güvenlidir.
"""
import json
import re

from .base import (CozumlemeHatasi, KayitBicimi, kolon_adlari,
                   metin_deger)

# Başlık satırındaki `"count": 123` benzeri bildirimi yakalar (varsa).
_SAYAC = re.compile(rb'"(?:count|total|rows?_?count|n)"\s*:\s*(\d+)')


class JsonBicimi(KayitBicimi):
    tur = "json"

    def coz(self, ham_satir):
        metin = ham_satir.strip()
        if metin.endswith(b","):
            metin = metin[:-1]
        if not metin or metin[:1] not in (b"[", b"{"):
            # Kayıt her zaman bir dizi ya da nesnedir; '[', ']}', ',' gibi
            # yapısal satırlar kayıt DEĞİLDİR.
            raise CozumlemeHatasi("JSON kaydı '[' ya da '{' ile başlamalı.")
        try:
            deger = json.loads(metin.decode(self.kodlama, "replace"))
        except ValueError as e:
            raise CozumlemeHatasi(f"Geçersiz JSON: {e}") from e
        if isinstance(deger, list):
            return [metin_deger(h) for h in deger]
        if isinstance(deger, dict):
            return deger
        raise CozumlemeHatasi("JSON kaydı dizi ya da nesne olmalı.")

    def kolonlari_belirle(self):
        cozulmus = self.ornek_satirlar
        if cozulmus and all(isinstance(k, dict) for k in cozulmus):
            self.kolonlar = kolon_adlari(cozulmus)
            # Sözlük kayıtları, kolon sırasına göre listeye çevrilerek gösterilir.
            self.ornek_satirlar = [[metin_deger(k.get(a, "")) for a in self.kolonlar]
                                   for k in cozulmus]
        else:
            self.kolonlar = kolon_adlari(cozulmus)


def beyan_edilen_sayiyi_bul(bas_blok):
    """Başlık satırında bildirilen kayıt sayısını döner (yoksa None)."""
    ilk_satir_sonu = bas_blok.find(b"\n")
    if ilk_satir_sonu < 0:
        ilk_satir_sonu = min(len(bas_blok), 4096)
    m = _SAYAC.search(bas_blok, 0, ilk_satir_sonu)
    return int(m.group(1)) if m else None
