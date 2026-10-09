"""XML: satır başına bir kayıt elementi.

Desteklenen düzen:

    <?xml version="1.0" encoding="UTF-8"?>        <- atlanır
    <rows count="293180461" cols="8">             <- atlanır (sarmalayıcı)
    <r><c>0_0_ab...</c><c>0_1_cd...</c>...</r>    <- kayıt
    <r><c>1_0_ef...</c>...</r>                    <- kayıt
    ...
    </rows>                                       <- atlanır

Her kayıt satırı kendi başına geçerli bir XML parçasıdır; bu yüzden
`ET.fromstring` ile tek tek çözülebilir ve dosyanın tamamını ayrıştıran bir
akış çözümleyicisine gerek kalmaz. Bu, rastgele erişimi mümkün kılan temel
özelliktir: 200 milyonuncu kaydı okumak için ondan öncekileri okumak
gerekmez.

Kolon adları: kayıt elementinin çocukları farklı etiketlere sahipse bu
etiketler kolon adı olur (ör. `<ad>`, `<yas>`); hepsi aynı etiketse (ör.
`<c>`) konumsal 'Kolon N' adları kullanılır.
"""
import re
import xml.etree.ElementTree as ET

from .base import CozumlemeHatasi, KayitBicimi

_SAYAC = re.compile(rb'\b(?:count|total|rows)\s*=\s*"(\d+)"')
# Ad alanı öneki: {http://...}etiket -> etiket
_AD_ALANI = re.compile(r"^\{[^}]*\}")


class XmlBicimi(KayitBicimi):
    tur = "xml"

    def __init__(self, yol, boyut, kodlama):
        super().__init__(yol, boyut, kodlama)
        self.kayit_etiketi = None      # ör. 'r'

    def coz(self, ham_satir):
        metin = ham_satir.strip()
        if not metin.startswith(b"<") or metin.startswith(b"<?") or metin.startswith(b"<!"):
            raise CozumlemeHatasi("XML kaydı bir element ile başlamalı.")
        try:
            element = ET.fromstring(metin.decode(self.kodlama, "replace"))
        except ET.ParseError as e:
            raise CozumlemeHatasi(f"Geçersiz XML: {e}") from e
        etiket = _yalin(element.tag)
        if self.kayit_etiketi is not None and etiket != self.kayit_etiketi:
            raise CozumlemeHatasi(
                f"Beklenen kayıt elementi <{self.kayit_etiketi}>, bulunan <{etiket}>.")
        cocuklar = list(element)
        if not cocuklar:
            # Çocuğu olmayan bir element sarmalayıcı olabilir (<rows ...>);
            # yalnızca metni varsa tek hücrelik bir kayıt sayılır.
            if element.text and element.text.strip():
                return [element.text]
            raise CozumlemeHatasi("Kayıt elementinin alanı yok.")
        return [c.text if c.text is not None else "" for c in cocuklar]

    def kolonlari_belirle(self, ilk_ham=None):
        """Kolon adlarını ilk kaydın çocuk etiketlerinden türetir."""
        etiketler = []
        if ilk_ham is not None:
            try:
                element = ET.fromstring(ilk_ham.decode(self.kodlama, "replace"))
                etiketler = [_yalin(c.tag) for c in element]
            except ET.ParseError:
                etiketler = []
        if etiketler and len(set(etiketler)) > 1:
            self.kolonlar = etiketler
        else:
            en_uzun = max((len(k) for k in self.ornek_satirlar), default=len(etiketler))
            self.kolonlar = [f"Kolon {i + 1}" for i in range(en_uzun)]


def _yalin(etiket):
    """'{ad-alani}etiket' -> 'etiket'."""
    return _AD_ALANI.sub("", etiket)


def kayit_etiketi_bul(bas_blok, kodlama):
    """Sarmalayıcıları atlayıp tekrar eden KAYIT elementinin adını bulur.

    Ölçüt: satır başında açılan ve AYNI satırda kapanan, ardışık satırlarda
    tekrar eden ilk element. `<?xml ...?>`, yorumlar ve kendisi kapanmayan
    sarmalayıcılar (ör. `<rows count="...">`) böylece elenir.
    """
    sayac = {}
    pos = 0
    incelenen = 0
    while incelenen < 200:
        nl = bas_blok.find(b"\n", pos)
        if nl < 0:
            break
        satir = bas_blok[pos:nl].strip()
        pos = nl + 1
        incelenen += 1
        if not satir.startswith(b"<") or satir.startswith(b"<?") or satir.startswith(b"<!"):
            continue
        m = re.match(rb"<\s*([^\s/>]+)", satir)
        if not m:
            continue
        ad = m.group(1).decode(kodlama, "replace")
        # Aynı satırda kapanıyor mu? (sarmalayıcılar kapanmaz)
        if satir.endswith(b"/>") or satir.endswith(f"</{ad}>".encode(kodlama, "replace")):
            sayac[ad] = sayac.get(ad, 0) + 1
    if not sayac:
        return None
    return max(sayac.items(), key=lambda x: x[1])[0]


def beyan_edilen_sayiyi_bul(bas_blok):
    """Sarmalayıcı elementteki count/total/rows niteliğini döner (yoksa None)."""
    sinir = bas_blok.find(b"\n", bas_blok.find(b"\n") + 1)
    if sinir < 0:
        sinir = min(len(bas_blok), 4096)
    m = _SAYAC.search(bas_blok, 0, sinir)
    return int(m.group(1)) if m else None
