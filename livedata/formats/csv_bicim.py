"""CSV: ayraç, kodlama ve başlık satırı tespiti.

Tespit YALNIZCA dosyanın başındaki küçük bir örnek (varsayılan 1 MiB)
üzerinden yapılır; dosyanın tamamı hiçbir zaman okunmaz. Tespit edilen her
alan kullanıcı tarafından arayüzden ELLE geçersiz kılınabilir -- sezgisel
tespit bir kolaylıktır, doğruluğun tek dayanağı değildir.

Kodlama kısıtı (bilinçli): Bu görüntüleyici satır sınırlarını HAM BAYT
düzeyinde ('\\n' = 0x0A) bulur. Bu yaklaşım UTF-8 ve tüm tek baytlı
kodlamalarda (latin-1, cp1254, ...) doğrudur; UTF-16/UTF-32'de değildir
(orada 0x0A baytı bir metin karakterinin parçası olabilir). Bu yüzden
UTF-16/32 BOM'u görülürse açıkça hata verilir -- sessizce yanlış satır
bölmek yerine.
"""
import csv
import os
from collections import Counter

from .. import rowscan
from .base import BicimHatasi, KayitBicimi

# Biçim tespiti için dosyanın başından okunacak örnek boyu.
ORNEK_BAYT = 1 << 20            # 1 MiB
# Başlık/ayraç sezgisinde incelenecek en fazla satır.
ORNEK_SATIR = 200

ADAY_AYRACLAR = (";", ",", "\t", "|")

_UTF16_BOMS = (b"\xff\xfe", b"\xfe\xff")
_UTF32_BOMS = (b"\xff\xfe\x00\x00", b"\x00\x00\xfe\xff")
_UTF8_BOM = b"\xef\xbb\xbf"


class CsvBicim(KayitBicimi):
    """Bir kaynak CSV dosyasının çözümlenmiş biçimi.

    Dört biçim içinde satır sınırının koşulsuz '
' OLMADIĞI tek biçim
    budur: tırnak içine alınmış bir hücre satır sonu içerebilir. Bu yüzden
    `tirnak_duyarli` yalnızca burada anlamlıdır (bkz. rowscan'deki parite).

    Alanlar:
      yol           -- dosya yolu
      boyut         -- dosya boyutu (bayt)
      kodlama       -- 'utf-8', 'utf-8-sig', 'cp1254', ... (bayt-güvenli olmalı)
      ayrac         -- tek karakterlik ayraç
      tirnak        -- tırnak karakteri ('"')
      baslik_var    -- ilk satır başlık mı
      kolonlar      -- kolon adları (başlık yoksa 'Kolon 1'..'Kolon N')
      veri_basi     -- ilk VERİ satırının mutlak bayt konumu
      tirnak_duyarli-- satır sınırı bulunurken tırnak paritesi izlensin mi
      ort_satir_bayt-- örnekten ölçülen ortalama satır uzunluğu (tahmin için)
      ornek_satirlar-- örnekten çözümlenmiş ilk birkaç satır (önizleme)
    """

    tur = "csv"

    def __init__(self, yol, boyut, kodlama, ayrac, tirnak, baslik_var,
                 kolonlar, veri_basi, tirnak_duyarli, ort_satir_bayt,
                 ornek_satirlar):
        super().__init__(yol, boyut, kodlama)
        self.ayrac = ayrac
        self.tirnak = tirnak
        self.baslik_var = baslik_var
        self.kolonlar = kolonlar
        self.veri_basi = veri_basi
        self.veri_sonu = boyut          # CSV'de kuyruk satırı yoktur
        self.tirnak_duyarli = tirnak_duyarli
        self.ort_satir_bayt = ort_satir_bayt
        self.ornek_satirlar = ornek_satirlar

    def coz(self, ham_satir):
        """Tek bir fiziksel satırı hücrelere böler.

        Tırnaksız dosyalarda doğrudan ayraçla bölünür (csv modülünden
        belirgin biçimde hızlı, sonucu birebir aynı); tırnaklı dosyalarda
        csv modülü kullanılır.
        """
        if ham_satir.endswith(b"\r"):
            ham_satir = ham_satir[:-1]
        metin = ham_satir.decode(self.kodlama, "replace")
        if not self.tirnak_duyarli:
            return metin.split(self.ayrac)
        return next(csv.reader([metin], delimiter=self.ayrac,
                               quotechar=self.tirnak), [])

    def kayit_mi(self, ham_satir):
        """CSV'de başlık dışındaki her satır bir kayıttır."""
        return bool(ham_satir.strip())

    def ozet(self):
        return (f"CSV · {self.ayrac!r} ayraç · {len(self.kolonlar)} kolon · "
                f"{self.kodlama} · başlık: {'var' if self.baslik_var else 'yok'} · "
                f"tırnak duyarlı: {'evet' if self.tirnak_duyarli else 'hayır'}")


def _kodlama_tespit(ornek):
    """BOM'a bakarak kodlama seçer. UTF-16/32 için BicimHatasi fırlatır."""
    if ornek.startswith(_UTF32_BOMS[0]) or ornek.startswith(_UTF32_BOMS[1]):
        raise BicimHatasi(
            "Dosya UTF-32 BOM ile başlıyor. Bu görüntüleyici satır sınırlarını "
            "ham bayt düzeyinde bulduğu için UTF-16/UTF-32 desteklemez; dosyayı "
            "UTF-8'e dönüştürüp yeniden deneyin.")
    if ornek.startswith(_UTF16_BOMS[0]) or ornek.startswith(_UTF16_BOMS[1]):
        raise BicimHatasi(
            "Dosya UTF-16 BOM ile başlıyor. Bu görüntüleyici satır sınırlarını "
            "ham bayt düzeyinde bulduğu için UTF-16/UTF-32 desteklemez; dosyayı "
            "UTF-8'e dönüştürüp yeniden deneyin.")
    if ornek.startswith(_UTF8_BOM):
        return "utf-8-sig"
    return "utf-8"


def _fiziksel_satirlar(ornek, en_fazla, tam_dosya=False):
    """Örnekten en fazla `en_fazla` TAM fiziksel satırı (bayt) döner.

    `tam_dosya` True ise (örnek dosyanın tamamını kapsıyorsa) sondaki
    '\\n' ile bitmeyen satır da eklenir -- küçük dosyalarda son satırı
    düşürmemek için gereklidir.
    """
    satirlar = []
    pos = 0
    n = len(ornek)
    while pos < n and len(satirlar) < en_fazla:
        nl = ornek.find(rowscan.NL, pos)
        if nl < 0:
            if tam_dosya and pos < n:
                satirlar.append(ornek[pos:].rstrip(b"\r"))
            break
        satirlar.append(ornek[pos:nl].rstrip(b"\r"))
        pos = nl + 1
    return satirlar


def _ayrac_tespit(satirlar):
    """Aday ayraçlar içinden, satırlar arasında EN TUTARLI olanı seçer.

    Ölçüt, "her satırda en az bir kez geçmesi" DEĞİLDİR: tırnak içinde satır
    sonu barındıran bir kayıt birden fazla FİZİKSEL satıra yayılır ve devam
    satırlarında hiç ayraç bulunmayabilir. Böyle bir satır, doğru ayracı
    eleyecek kadar ağır basmamalıdır.

    Bunun yerine her aday için sıfır olmayan adetlerin EN YAYGIN değeri (mod)
    bulunur ve satırların ne kadarının bu adetle uyuştuğuna bakılır. Eşitlik
    durumunda satır başına daha çok geçen aday kazanır.
    """
    if not satirlar:
        return ","
    en_iyi = None
    for ay in ADAY_AYRACLAR:
        b = ay.encode()
        adetler = [s.count(b) for s in satirlar]
        sifirsiz = [a for a in adetler if a > 0]
        if not sifirsiz:
            continue
        mod = Counter(sifirsiz).most_common(1)[0][0]
        uyum = sum(1 for a in adetler if a == mod) / len(adetler)
        puan = (uyum, mod)
        if en_iyi is None or puan > en_iyi[0]:
            en_iyi = (puan, ay)
    return en_iyi[1] if en_iyi else ","


def _hucre_profili(hucre):
    """Bir hücrenin karakter sınıfı profili: (rakam_oranı, harf_oranı, sayısal_mı)."""
    if not hucre:
        return (0.0, 0.0, False)
    rakam = sum(1 for c in hucre if c.isdigit())
    harf = sum(1 for c in hucre if c.isalpha())
    n = len(hucre)
    sayisal = False
    try:
        float(hucre.replace(",", ".").strip())
        sayisal = True
    except ValueError:
        pass
    return (rakam / n, harf / n, sayisal)


def _baslik_tespit(satirlar):
    """İlk satırın başlık olup olmadığını sezer.

    İki ölçüt sırayla denenir:

      1. SAYISALLIK: veri satırlarında bir kolon tutarlı biçimde sayısalsa
         ve ilk satırın o kolonu sayısal DEĞİLSE -> başlık. (En güvenilir ve
         en yaygın işaret.)
      2. KARAKTER PROFİLİ: ilk satırın kolon profilleri, veri satırlarının
         ortalama profilinden belirgin biçimde uzaksa -> başlık.

    Hiçbiri kesin değilse False (başlık yok) döner -- yanlışlıkla bir VERİ
    satırını başlık sayıp gizlemek, tersinden daha zararlıdır. Kullanıcı
    arayüzden her zaman elle değiştirebilir.
    """
    if len(satirlar) < 3:
        return False
    ilk, veri = satirlar[0], satirlar[1:]
    kolon_sayisi = len(ilk)
    if kolon_sayisi == 0:
        return False

    # Boş ya da tekrarlı hücre içeren bir satır geçerli bir başlık olamaz.
    if any(not h.strip() for h in ilk):
        return False
    if len(set(ilk)) != len(ilk):
        return False

    ilk_prof = [_hucre_profili(h) for h in ilk]
    veri_prof = []
    for s in veri:
        if len(s) != kolon_sayisi:
            continue
        veri_prof.append([_hucre_profili(h) for h in s])
    if len(veri_prof) < 2:
        return False

    # 1) Sayısallık ölçütü
    for k in range(kolon_sayisi):
        veri_sayisal = sum(1 for p in veri_prof if p[k][2])
        if veri_sayisal >= max(2, int(0.9 * len(veri_prof))) and not ilk_prof[k][2]:
            return True

    # 2) Uzunluk ölçütü: başlıklar tipik olarak kısa etiketlerdir, veri
    # satırları ise (kimlik/hash/açıklama içerdiği için) belirgin biçimde
    # daha uzundur. İlk satır veri satırlarının yarısından kısaysa başlıktır.
    ilk_uzunluk = sum(len(h) for h in ilk)
    veri_uzunluklar = sorted(sum(len(h) for h in s) for s in veri
                             if len(s) == kolon_sayisi)
    if veri_uzunluklar:
        medyan = veri_uzunluklar[len(veri_uzunluklar) // 2]
        if medyan > 0 and ilk_uzunluk < 0.5 * medyan:
            return True

    # 3) Karakter profili uzaklığı
    toplam_uzaklik = 0.0
    for k in range(kolon_sayisi):
        ort_rakam = sum(p[k][0] for p in veri_prof) / len(veri_prof)
        ort_harf = sum(p[k][1] for p in veri_prof) / len(veri_prof)
        toplam_uzaklik += abs(ilk_prof[k][0] - ort_rakam) + abs(ilk_prof[k][1] - ort_harf)
    return (toplam_uzaklik / kolon_sayisi) > 0.55


def _cozumle(satirlar_bayt, kodlama, ayrac, tirnak):
    """Fiziksel bayt satırlarını csv modülüyle kayıtlara çevirir."""
    metin = [s.decode(kodlama, errors="replace") for s in satirlar_bayt]
    okuyucu = csv.reader(metin, delimiter=ayrac, quotechar=tirnak)
    return [r for r in okuyucu]


def bicim_tespit(yol, ayrac=None, kodlama=None, baslik_var=None,
                 tirnak_duyarli=None, ornek_bayt=ORNEK_BAYT):
    """Kaynak CSV'nin biçimini döner (CsvBicim).

    None verilen her parametre otomatik tespit edilir; verilenler AYNEN
    kullanılır (kullanıcının elle seçimi sezgiyi her zaman ezer).
    """
    boyut = os.path.getsize(yol)
    if boyut == 0:
        raise BicimHatasi("Dosya boş (0 bayt).")

    with open(yol, "rb") as f:
        ornek = f.read(min(ornek_bayt, boyut))

    if kodlama is None:
        kodlama = _kodlama_tespit(ornek)
    elif kodlama.lower().replace("_", "-") in ("utf-16", "utf-32",
                                               "utf-16-le", "utf-16-be"):
        raise BicimHatasi(
            f"'{kodlama}' desteklenmiyor: satır sınırları ham bayt düzeyinde "
            "bulunuyor. UTF-8 ya da tek baytlı bir kodlama kullanın.")

    bom_uzunluk = len(_UTF8_BOM) if kodlama == "utf-8-sig" else 0
    govde = ornek[bom_uzunluk:]

    satirlar_bayt = _fiziksel_satirlar(govde, ORNEK_SATIR,
                                       tam_dosya=len(ornek) >= boyut)
    if not satirlar_bayt:
        raise BicimHatasi(
            f"Dosyanın ilk {len(ornek)} baytında hiç satır sonu ('\\n') yok. "
            "Bu bir CSV dosyası olmayabilir (ya da tek satırlık devasa bir "
            "kayıt içeriyor).")

    if ayrac is None:
        ayrac = _ayrac_tespit(satirlar_bayt)
    if tirnak_duyarli is None:
        # Örnekte hiç tırnak yoksa tırnak paritesi izlemeye gerek yoktur;
        # tarama böylece tamamen memchr hızında kalır. Tarayıcı, ilerleyen
        # bölgelerde tırnak görürse kullanıcıyı ayrıca uyarır.
        tirnak_duyarli = b'"' in govde

    kayitlar = _cozumle(satirlar_bayt, kodlama, ayrac, '"')
    if baslik_var is None:
        baslik_var = _baslik_tespit(kayitlar)

    if baslik_var:
        nl = rowscan.first_row_end(govde, 0, quote_aware=tirnak_duyarli)
        if nl < 0:
            raise BicimHatasi("Başlık satırının sonu bulunamadı.")
        veri_basi = bom_uzunluk + nl + 1
        kolonlar = [h.strip() for h in kayitlar[0]] if kayitlar else []
        ornek_satirlar = kayitlar[1:11]
    else:
        veri_basi = bom_uzunluk
        kolon_sayisi = max((len(k) for k in kayitlar[:50]), default=1)
        kolonlar = [f"Kolon {i + 1}" for i in range(kolon_sayisi)]
        ornek_satirlar = kayitlar[:10]

    # Ortalama satır uzunluğu: örnekteki TAM satırların bayt ortalaması.
    veri_satirlari = satirlar_bayt[1:] if baslik_var else satirlar_bayt
    if veri_satirlari:
        ort = sum(len(s) + 1 for s in veri_satirlari) / len(veri_satirlari)
    else:
        ort = 0.0

    return CsvBicim(yol=yol, boyut=boyut, kodlama=kodlama, ayrac=ayrac,
                    tirnak='"', baslik_var=baslik_var, kolonlar=kolonlar,
                    veri_basi=veri_basi, tirnak_duyarli=tirnak_duyarli,
                    ort_satir_bayt=ort, ornek_satirlar=ornek_satirlar)


def ortalama_satir_iyilestir(bicim, nokta=12, pencere=256 * 1024):
    """Ortalama satır uzunluğu tahminini dosyanın TAMAMINA yayarak iyileştirir.

    `bicim_tespit` yalnızca dosyanın BAŞINI örnekler; satır uzunluğu dosya
    boyunca değişiyorsa (ör. artan kayıt numaraları satırları uzatıyorsa) bu
    tahmin sapar. Bu fonksiyon dosyanın çeşitli yerlerinden `nokta` adet
    küçük pencere okuyup (toplam ~3 MB) ortalamayı düzeltir ve `bicim`
    üzerinde günceller.

    Yalnızca TAHMİN içindir (ilerleme çubuğu / kaydırma çubuğu ölçeği);
    hiçbir konumlandırma kararı buna dayanmaz -- kesin konum her zaman
    indeks çıpalarından gelir.
    """
    if bicim.veri_bayt <= pencere:
        return bicim.ort_satir_bayt

    toplam_bayt = 0
    toplam_satir = 0
    with open(bicim.yol, "rb") as f:
        for i in range(nokta):
            konum = bicim.veri_basi + int(bicim.veri_bayt * (i + 0.5) / nokta)
            f.seek(konum)
            blok = f.read(pencere)
            if len(blok) < 1024:
                continue
            # Kısmi satırlarla ölçüm yapmamak için ilk ve son '\n' arasını al.
            bas = blok.find(rowscan.NL)
            son = blok.rfind(rowscan.NL)
            if bas < 0 or son <= bas:
                continue
            satir, _ = rowscan.count_rows(blok, bas + 1, son + 1, 0,
                                          bicim.tirnak_duyarli)
            if satir:
                toplam_satir += satir
                toplam_bayt += (son + 1) - (bas + 1)

    if toplam_satir:
        bicim.ort_satir_bayt = toplam_bayt / toplam_satir
    return bicim.ort_satir_bayt
