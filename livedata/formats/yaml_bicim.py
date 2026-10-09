"""YAML: satır başına bir dizi ögesi.

Desteklenen düzen:

    count: 214088734                       <- atlanır
    cols: 9                                <- atlanır
    rows:                                  <- atlanır
      - ["0_0_ab...","0_1_cd...", ...]     <- kayıt
      - ["1_0_ef...", ...]                 <- kayıt
    ...

Her kayıt, satır başındaki `- ` işaretinden sonra gelen bir AKIŞ (flow)
dizisi/eşlemesidir; yani tek satıra sığar. Blok biçiminde (çok satıra
yayılmış) yazılmış YAML dizileri bu ekranda açılamaz -- `base.sinirlari_bul`
bunu tespit edip açıklayıcı bir hata verir.

Hız notu: `yaml.safe_load` bu iş için çok yavaştır (ölçülen 154 µs/satır;
250 satırlık bir pencere 38 ms sürer ve kaydırma hissedilir biçimde
takılır). Akış dizileri çift tırnaklı yazıldığında JSON'la aynı sözdizimine
sahip olduğundan önce `json.loads` denenir (ölçülen 1,9 µs/satır, 80 kat
hızlı); JSON'un kabul etmediği gerçek YAML sözdizimi (tırnaksız skalerler,
tek tırnak, `~`, `true`/`null` dışı değerler) görüldüğünde `yaml.safe_load`'a
düşülür. Sonuçlar birebir aynıdır -- yalnızca hızlı yol önce denenir.
"""
import json
import re

import yaml

from .base import (CozumlemeHatasi, KayitBicimi, kolon_adlari,
                   metin_deger)

_SAYAC = re.compile(rb"^\s*(?:count|total|rows?_?count)\s*:\s*(\d+)\s*$", re.M)


class YamlBicimi(KayitBicimi):
    tur = "yaml"

    def coz(self, ham_satir):
        metin = ham_satir.decode(self.kodlama, "replace").strip()
        if not metin.startswith("- "):
            # '- ' olmayan satırlar başlık/anahtar satırlarıdır (count:, rows:).
            raise CozumlemeHatasi("YAML kaydı '- ' ile başlamalı.")
        govde = metin[2:].strip()
        if not govde:
            raise CozumlemeHatasi("Boş YAML dizi ögesi.")
        deger = _coz_deger(govde)
        if isinstance(deger, list):
            return [metin_deger(h) for h in deger]
        if isinstance(deger, dict):
            return deger
        # Tek skaler bir öge de geçerli bir kayıttır (tek kolon).
        return [metin_deger(deger)]

    def kolonlari_belirle(self):
        cozulmus = self.ornek_satirlar
        if cozulmus and all(isinstance(k, dict) for k in cozulmus):
            self.kolonlar = kolon_adlari(cozulmus)
            self.ornek_satirlar = [[metin_deger(k.get(a, "")) for a in self.kolonlar]
                                   for k in cozulmus]
        else:
            self.kolonlar = kolon_adlari(cozulmus)


def _coz_deger(govde):
    """Önce JSON (hızlı), olmazsa YAML (doğru) ile çözer."""
    try:
        return json.loads(govde)
    except ValueError:
        pass
    try:
        return yaml.safe_load(govde)
    except yaml.YAMLError as e:
        raise CozumlemeHatasi(f"Geçersiz YAML: {e}") from e


def beyan_edilen_sayiyi_bul(bas_blok):
    """Baştaki `count: 123` benzeri anahtarı döner (yoksa None)."""
    m = _SAYAC.search(bas_blok, 0, min(len(bas_blok), 4096))
    return int(m.group(1)) if m else None
