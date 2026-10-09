"""Biçim tespiti: dosya uzantısına göre doğru `KayitBicimi`'ni üretir.

Dört biçim de aynı sözleşmeyi karşılar (bkz. base.py), bu yüzden indeks,
rastgele erişim, arama ve arayüz katmanları biçimden HABERSİZDİR: hepsi
yalnızca `veri_basi`, `veri_sonu` ve `coz()` ile konuşur.
"""
import os

from .base import (BAS_ORNEK, BicimHatasi, CozumlemeHatasi, KayitBicimi,
                   sinirlari_bul)
from .csv_bicim import CsvBicim
from .csv_bicim import bicim_tespit as _csv_tespit
from .csv_bicim import ortalama_satir_iyilestir
from .json_bicim import JsonBicimi
from .json_bicim import beyan_edilen_sayiyi_bul as _json_sayac
from .xml_bicim import XmlBicimi
from .xml_bicim import beyan_edilen_sayiyi_bul as _xml_sayac
from .xml_bicim import kayit_etiketi_bul
from .yaml_bicim import YamlBicimi
from .yaml_bicim import beyan_edilen_sayiyi_bul as _yaml_sayac

__all__ = ["BicimHatasi", "CozumlemeHatasi", "KayitBicimi", "CsvBicim",
           "JsonBicimi", "XmlBicimi", "YamlBicimi", "bicim_tespit",
           "ortalama_satir_iyilestir", "UZANTILAR", "tur_bul"]

UZANTILAR = {
    ".csv": "csv", ".txt": "csv", ".tsv": "csv",
    ".json": "json", ".jsonl": "json", ".ndjson": "json",
    ".xml": "xml",
    ".yaml": "yaml", ".yml": "yaml",
}

_UTF16_BOMS = (b"\xff\xfe", b"\xfe\xff")
_UTF32_BOMS = (b"\xff\xfe\x00\x00", b"\x00\x00\xfe\xff")
_UTF8_BOM = b"\xef\xbb\xbf"


def tur_bul(yol):
    """Dosya uzantısından biçim türünü döner; tanınmazsa BicimHatasi."""
    uzanti = os.path.splitext(yol)[1].lower()
    tur = UZANTILAR.get(uzanti)
    if tur is None:
        raise BicimHatasi(
            f"Desteklenmeyen dosya uzantısı: '{uzanti}'. Desteklenenler: "
            + ", ".join(sorted(UZANTILAR)))
    return tur


def _kodlama_sec(ornek, kodlama):
    if kodlama is not None:
        if kodlama.lower().replace("_", "-") in ("utf-16", "utf-32",
                                                 "utf-16-le", "utf-16-be"):
            raise BicimHatasi(
                f"'{kodlama}' desteklenmiyor: satır sınırları ham bayt düzeyinde "
                "bulunuyor. UTF-8 ya da tek baytlı bir kodlama kullanın.")
        return kodlama
    if ornek.startswith(_UTF32_BOMS[0]) or ornek.startswith(_UTF32_BOMS[1]):
        raise BicimHatasi(
            "Dosya UTF-32 BOM ile başlıyor. Bu görüntüleyici satır sınırlarını "
            "ham bayt düzeyinde bulduğu için UTF-16/UTF-32 desteklemez.")
    if ornek.startswith(_UTF16_BOMS[0]) or ornek.startswith(_UTF16_BOMS[1]):
        raise BicimHatasi(
            "Dosya UTF-16 BOM ile başlıyor. Bu görüntüleyici satır sınırlarını "
            "ham bayt düzeyinde bulduğu için UTF-16/UTF-32 desteklemez.")
    if ornek.startswith(_UTF8_BOM):
        return "utf-8-sig"
    return "utf-8"


def bicim_tespit(yol, tur=None, ayrac=None, kodlama=None, baslik_var=None,
                 tirnak_duyarli=None):
    """Kaynak dosyanın biçimini tespit eder ve bir `KayitBicimi` döner.

    `tur` verilmezse uzantıdan belirlenir. CSV'ye özgü parametreler
    (ayrac/baslik_var/tirnak_duyarli) yalnızca CSV'de anlamlıdır; diğer
    biçimlerde yok sayılır çünkü orada kayıt sınırı ve alan ayrımı biçimin
    kendi dilbilgisinden gelir.
    """
    if tur is None:
        tur = tur_bul(yol)
    if tur == "csv":
        return _csv_tespit(yol, ayrac=ayrac, kodlama=kodlama,
                           baslik_var=baslik_var, tirnak_duyarli=tirnak_duyarli)

    boyut = os.path.getsize(yol)
    if boyut == 0:
        raise BicimHatasi("Dosya boş (0 bayt).")
    with open(yol, "rb") as f:
        bas_blok = f.read(min(BAS_ORNEK, boyut))
    kodlama = _kodlama_sec(bas_blok, kodlama)

    if tur == "json":
        bicim = JsonBicimi(yol, boyut, kodlama)
        bicim.beyan_edilen_kayit = _json_sayac(bas_blok)
        sinirlari_bul(bicim)
        bicim.kolonlari_belirle()
    elif tur == "xml":
        bicim = XmlBicimi(yol, boyut, kodlama)
        bicim.kayit_etiketi = kayit_etiketi_bul(bas_blok, kodlama)
        if bicim.kayit_etiketi is None:
            raise BicimHatasi(
                "Tekrar eden bir kayıt elementi bulunamadı. Bu ekran, her "
                "kaydın kendi satırında tam bir element olarak yazıldığı XML "
                "dosyaları içindir (ör. <r>...</r>).")
        bicim.beyan_edilen_kayit = _xml_sayac(bas_blok)
        sinirlari_bul(bicim)
        ilk_ham = _ilk_kayit_ham(bicim)
        bicim.kolonlari_belirle(ilk_ham)
    elif tur == "yaml":
        bicim = YamlBicimi(yol, boyut, kodlama)
        bicim.beyan_edilen_kayit = _yaml_sayac(bas_blok)
        sinirlari_bul(bicim)
        bicim.kolonlari_belirle()
    else:                                             # pragma: no cover
        raise BicimHatasi(f"Bilinmeyen biçim türü: {tur}")
    return bicim


def _ilk_kayit_ham(bicim):
    """İlk kayıt satırının ham baytlarını döner (kolon adlarını türetmek için)."""
    with open(bicim.yol, "rb") as f:
        f.seek(bicim.veri_basi)
        blok = f.read(1 << 16)
    nl = blok.find(b"\n")
    return blok[:nl].rstrip(b"\r") if nl >= 0 else blok
