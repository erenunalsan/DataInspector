"""Sıralama: Top-K, sayfa içi sıralama ve seçili kayıt listesini sıralama.

Neden "tam sıralama" yok?
-------------------------
205 milyon kaydı sıralı gezmek, "sıralı konum P'de hangi kayıt var?"
sorusunun cevabını -- yani bir PERMÜTASYONU -- saklamayı gerektirir. Bu,
kayıt başına 8 bayt, toplam ~1,53 GiB'dır. Rastgele bir permütasyon tanım
gereği sıkıştırılamaz (bilgi-kuramsal alt sınır ~672 MB). Bu büyüklük ne
RAM tavanına sığar ne de diske yazılabilir; ikisi de bu ekranın temel
kurallarını çiğner. Bu yüzden burada permütasyon GEREKTİRMEYEN üç sıralama
biçimi uygulanmıştır:

  1. SAYFA (`KIP_ARALIK`)  -- ekrandaki 100.000'lik sayfayı kendi içinde
     sıralar. Sonuç, sayfa boyu kadar (≤100.000) kayıt numarasıdır: ~800 KB.
  2. TOP-K (`KIP_TUM_DOSYA`) -- "X kolonuna göre en büyük/en küçük N kayıt".
     Tek geçiş, sınırlı bir heap; sonuç K kayıt numarasıdır. Dosya ne kadar
     büyük olursa olsun RAM sabittir.
  3. LİSTE (`KIP_LISTE`)   -- verilen kayıt numaralarını (ör. arama
     sonuçlarını) sıralar. Kayıtlar tek tek okunur.

Üçünün de sonucu aynı şeydir: **sıralı bir kayıt numarası listesi**. Arayüz
bunu bir "görünüm" olarak kullanır ve satırları her zamanki yükleyiciyle
getirir.

Sonuçların GÖSTERİLEBİLİR olması
--------------------------------
Top-K sonuçları dosyanın her yerine dağılmıştır. İndeks oraya ulaşmamışsa o
kayıtlar okunamaz -- ve tüm dosyayı indekslemek, sıralamanın kendisi kadar
daha sürerdi. Gerek yok: tarama sırasında her kaydın BAYT KONUMU zaten
biliniyor. Kazanan kayıtların konumları toplanıp bitişte indekse ipucu
olarak verilir; böylece sonuçlar indeksten bağımsız olarak anında
görüntülenebilir.

Anahtar çıkarma maliyeti (ölçülmüş, 3. kolon)
---------------------------------------------
Sıralamanın gerçek darboğazı taramak değil, HER kayıttan anahtarı
çıkarmaktır:

    CSV   0,35 µs/kayıt -> disk sınırlı  (genel yol yeter)
    JSON  1,44 µs/kayıt -> CPU sınırlı, ~5,7 dk
    YAML  1,74 µs/kayıt -> CPU sınırlı, ~6,2 dk
    XML   8,46 µs/kayıt -> 41 dk  (KABUL EDİLEMEZ)
    XML   0,50 µs/kayıt -> disk sınırlı, ~2,4 dk  (bayt düzeyinde hızlı yol)

Bu yüzden XML için, kaydı hiç çözümlemeden k. çocuk elementin metnini bulan
bayt düzeyinde bir çıkarıcı vardır (17 kat hızlı). Diğer üç biçimde genel
yol (biçimin kendi `coz_liste`'si) zaten yeterlidir.

Sıralama düzeni
---------------
Metin sıralaması KOD NOKTASI sırasındadır (Python'ın varsayılan `str`
karşılaştırması), Türkçe alfabe sırası DEĞİLDİR: "z" < "ç" olur. Yerel-
duyarlı harmanlama (`locale.strxfrm`) kayıt başına ek maliyet getirir ve
işletim sistemi ayarına göre makineden makineye değişen sonuç üretir;
burada öngörülebilirlik yeğlenmiştir.

Değeri okunamayan ya da olmayan alanlar (sayısal sıralamada sayıya
çevrilemeyen değerler dâhil) sonuca HİÇ alınmaz ve sayıları kullanıcıya
bildirilir -- "boş" kayıtları sıranın sonuna doldurmak, sıralamanın ne
anlama geldiğini bulanıklaştırır.
"""
import heapq
import re
import threading
import time
import xml.etree.ElementTree as ET

from .blockreader import BlockReader
from .rowscan import NL

# `NL` bir tamsayıdır (0x0A); find/rfind onu kabul eder ama split etmez.
NL_B = bytes([NL])

TUR_METIN = "metin"
TUR_SAYI = "sayi"

ARTAN = "artan"
AZALAN = "azalan"

KIP_TUM_DOSYA = "tum_dosya"     # Top-K: tüm dosyayı tara, en iyi K'yı tut
KIP_ARALIK = "aralik"           # Bir kayıt aralığını (sayfayı) tamamen sırala
KIP_LISTE = "liste"             # Verilen kayıt numaralarını sırala

OLAY_ILERLEME = "siralama_ilerleme"
OLAY_BITTI = "siralama_bitti"
OLAY_HATA = "siralama_hata"

VARSAYILAN_BLOK = 8 << 20
ILERLEME_ARALIGI = 0.30
ONIZLEME_ADET = 200             # ilerleme olayında gönderilen örnek sayısı
# KIP_ARALIK'ta toplanacak kayıt üst sınırı. Bir sayfa 100.000 kayıttır;
# bu tavan, bozuk bir sayfa sınırında RAM'in öngörülemez büyümesini önler.
ARALIK_TAVANI = 250_000

_AD_ALANI = re.compile(r"^\{[^}]*\}")


class SiralamaHatasi(Exception):
    """Kullanıcıya gösterilebilir sıralama hatası."""


# ======================================================================
# Anahtar çıkarma
# ======================================================================
class AnahtarCikarici:
    """Bir kayıttan sıralama anahtarını çıkarır.

    `ham(satir_baytlari)` ham bir fiziksel satırdan, `cozulmus(kayit)` ise
    zaten çözümlenmiş bir kayıt listesinden anahtarı alır. İkisi de metin
    (str) ya da None döner; None "bu kayıtta bu alan yok/okunamadı" demektir.
    """

    def __init__(self, bicim, kolon):
        self.bicim = bicim
        self.kolon = kolon

    def cozulmus(self, kayit):
        if self.kolon < len(kayit):
            return kayit[self.kolon]
        return None

    def ham(self, satir):
        try:
            return self.cozulmus(self.bicim.coz_liste(satir))
        except Exception:                        # noqa: BLE001
            return None


class XmlAnahtarCikarici(AnahtarCikarici):
    """XML için bayt düzeyinde k. çocuk elementi bulur (17 kat hızlı).

    `<r><c>a</c><c>b</c>...</r>` düzeninde k. `<c>`'yi bulmak, kaydı
    `ET.fromstring` ile çözümlemekten 8,46 µs yerine 0,50 µs sürer; bu fark
    293 milyon kayıtta 41 dakika ile 2,4 dakika arasındaki farktır.

    Doğruluk: XML'de element metni ham `<` içeremez (`&lt;` olarak kaçırılır),
    bu yüzden `find` ile sınır bulmak güvenlidir. Beklenen etiket bulunamazsa
    (farklı yapıda bir kayıt) sessizce genel yola düşülür.
    """

    def __init__(self, bicim, kolon, cocuk_etiketi):
        super().__init__(bicim, kolon)
        kodlama = bicim.kodlama
        self._ac = ("<" + cocuk_etiketi + ">").encode(kodlama, "replace")
        self._kapa = ("</" + cocuk_etiketi + ">").encode(kodlama, "replace")
        self._kodlama = kodlama

    def ham(self, satir):
        pos = 0
        for _ in range(self.kolon + 1):
            pos = satir.find(self._ac, pos)
            if pos < 0:
                return super().ham(satir)        # beklenmedik yapı -> genel yol
            pos += len(self._ac)
        son = satir.find(self._kapa, pos)
        if son < 0:
            return super().ham(satir)
        return satir[pos:son].decode(self._kodlama, "replace")


def cikarici_olustur(bicim, kolon):
    """Biçime en uygun anahtar çıkarıcıyı üretir."""
    if bicim.tur == "xml":
        etiket = _xml_cocuk_etiketi(bicim)
        if etiket:
            return XmlAnahtarCikarici(bicim, kolon, etiket)
    return AnahtarCikarici(bicim, kolon)


def _xml_cocuk_etiketi(bicim):
    """İlk kaydın çocuk elementlerinin ORTAK etiketini döner (yoksa None).

    Çocuklar farklı etiketlere sahipse (kolon adları etiketlerden türetilmişse)
    konumsal bayt araması yapılamaz; o durumda None döner ve genel yol
    kullanılır.
    """
    try:
        with open(bicim.yol, "rb") as f:
            f.seek(bicim.veri_basi)
            blok = f.read(1 << 16)
        nl = blok.find(NL)
        ham = blok[:nl] if nl >= 0 else blok
        element = ET.fromstring(ham.decode(bicim.kodlama, "replace"))
        etiketler = [_AD_ALANI.sub("", c.tag) for c in element]
    except Exception:                            # noqa: BLE001
        return None
    if etiketler and len(set(etiketler)) == 1:
        return etiketler[0]
    return None


# ======================================================================
# Karşılaştırma
# ======================================================================
class _Ters:
    """Karşılaştırması ters çevrilmiş sarmalayıcı (min-heap'i max-heap yapar)."""

    __slots__ = ("deger",)

    def __init__(self, deger):
        self.deger = deger

    def __lt__(self, other):
        return other.deger < self.deger

    def __eq__(self, other):
        return isinstance(other, _Ters) and self.deger == other.deger


def anahtar_degeri(metin, tur):
    """Ham metni karşılaştırılabilir değere çevirir; olmazsa None.

    Sayısal türde hem '1234.56' hem '1.234,56' (Türkçe) yazımı kabul edilir.
    """
    if metin is None:
        return None
    if tur == TUR_METIN:
        return metin
    s = metin.strip()
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        pass
    try:
        return float(s.replace(".", "").replace(",", "."))
    except ValueError:
        return None


# ======================================================================
# Sıralama işi
# ======================================================================
class SiralamaJob(threading.Thread):
    """Üç kipte de çalışan sıralama işi. Sonucu sıralı kayıt numaralarıdır."""

    def __init__(self, bicim, index, kuyruk, kolon, yon=AZALAN, tur=TUR_METIN,
                 kip=KIP_TUM_DOSYA, k=10_000, bas_ofset=None, son_ofset=None,
                 bas_satir=0, satir_nolari=None, blok=VARSAYILAN_BLOK,
                 aralik_tavani=ARALIK_TAVANI, kayit_bas=None, kayit_son=None):
        super().__init__(name="livedata-sort", daemon=True)
        self.bicim = bicim
        self.index = index
        self.kuyruk = kuyruk
        self.kolon = kolon
        self.yon = yon
        self.tur = tur
        self.kip = kip
        self.k = max(1, int(k)) if k else 1
        self.bas_ofset = bicim.veri_basi if bas_ofset is None else bas_ofset
        self.son_ofset = bicim.veri_sonu if son_ofset is None else son_ofset
        self.bas_satir = bas_satir
        self.satir_nolari = list(satir_nolari or ())
        self.blok = blok
        self.aralik_tavani = aralik_tavani
        # Yalnızca bu kayıt aralığındakiler toplanır. Sayfa sıralamasında
        # tarama, sayfanın başındaki ÇIPADAN başlamak zorundadır (çıpa
        # sayfadan biraz önce olabilir); bu sınırlar sayfa dışına taşan
        # kayıtları eler ve sayfa bitince taramayı durdurur.
        self.kayit_bas = kayit_bas
        self.kayit_son = kayit_son

        self.cikarici = cikarici_olustur(bicim, kolon)
        self._iptal = threading.Event()

        # Sonuç ve istatistik
        self.sonuc = []           # sıralı kayıt numaraları
        self.ofsetler = []        # aynı sırada bayt konumları (indekse ipucu)
        self.incelenen = 0
        self.bos_anahtar = 0      # değeri okunamayan kayıt sayısı
        self.okunan_bayt = 0
        self.sure = None
        self.tavan_asildi = False

    def iptal(self):
        self._iptal.set()

    # ------------------------------------------------------------------
    def run(self):
        t0 = time.perf_counter()
        try:
            if self.kip == KIP_LISTE:
                toplananlar = self._liste_tara()
            else:
                toplananlar = self._aralik_tara()
        except Exception as e:                   # noqa: BLE001
            self.kuyruk.put({"tur": OLAY_HATA, "hata": e})
            return

        self.sonuc, self.ofsetler = self._sirala(toplananlar)
        # Sonuç kayıtları dosyanın her yerine dağılmıştır; bayt konumlarını
        # indekse ipucu olarak vermezsek, indeks oraya ulaşmadığı sürece
        # gösterilemezler. Konumları tarama sırasında zaten öğrendik.
        if self.ofsetler:
            self.index.ipuclari_ekle(zip(self.sonuc, self.ofsetler))
        self.sure = time.perf_counter() - t0
        self.kuyruk.put({
            "tur": OLAY_BITTI,
            "iptal": self._iptal.is_set(),
            "kayitlar": self.sonuc,
            "incelenen": self.incelenen,
            "bos_anahtar": self.bos_anahtar,
            "bayt": self.okunan_bayt,
            "sure": self.sure,
            "tavan_asildi": self.tavan_asildi,
            "kip": self.kip,
        })

    # -- toplama -------------------------------------------------------
    def _aralik_tara(self):
        """Kayıtları tarayıp (anahtar, kayıt_no, bayt_konumu) üçlüleri toplar.

        KIP_TUM_DOSYA'da sınırlı bir heap tutulur (RAM K ile sabit);
        KIP_ARALIK'ta aralıktaki tüm kayıtlar toplanır (sayfa boyuyla sınırlı).
        """
        heap = []
        hepsi = []
        topk = self.kip == KIP_TUM_DOSYA
        enbuyuk = self.yon == AZALAN   # azalan -> en büyük K
        satir_no = self.bas_satir
        kalinti = b""
        konum = self.bas_ofset
        t0 = time.perf_counter()
        son_bildirim = 0.0
        cikar = self.cikarici.ham
        deger = anahtar_degeri
        anahtar_turu = self.tur

        with open(self.bicim.yol, "rb") as f:
            f.seek(konum)
            dur = False
            while not dur and not self._iptal.is_set():
                kalan = self.son_ofset - konum
                if kalan <= 0:
                    break
                blok = f.read(min(self.blok, kalan))
                if not blok:
                    break
                konum += len(blok)
                self.okunan_bayt = konum - self.bas_ofset

                veri = kalinti + blok
                taban = konum - len(veri)      # veri[0]'ın mutlak bayt konumu
                son_nl = veri.rfind(NL)
                if son_nl < 0:
                    kalinti = veri
                    continue

                # `split` yerine `find` döngüsü: her kaydın BAYT KONUMUNU da
                # bilmemiz gerekiyor (sonuçları indekse ipucu vermek için).
                # Ek maliyet kayıt başına ~0,1 µs; tarama zaten diske ya da
                # anahtar çözümlemesine bağlı olduğu için ihmal edilebilir.
                pos = 0
                while pos <= son_nl:
                    nl = veri.find(NL, pos)
                    if nl < 0 or nl > son_nl:
                        break
                    satir = veri[pos:nl]
                    ofset = taban + pos
                    pos = nl + 1
                    if self.kayit_son is not None and satir_no >= self.kayit_son:
                        dur = True
                        break
                    if satir and (self.kayit_bas is None
                                  or satir_no >= self.kayit_bas):
                        a = deger(cikar(satir), anahtar_turu)
                        if a is None:
                            self.bos_anahtar += 1
                        elif topk:
                            self._heap_ekle(heap, a, satir_no, ofset, enbuyuk)
                        else:
                            hepsi.append((a, satir_no, ofset))
                        self.incelenen += 1
                    satir_no += 1
                kalinti = veri[pos:]

                if not topk and len(hepsi) >= self.aralik_tavani:
                    self.tavan_asildi = True
                    break

                simdi = time.perf_counter()
                if simdi - son_bildirim >= ILERLEME_ARALIGI:
                    son_bildirim = simdi
                    self._ilerleme(t0, heap if topk else hepsi, topk, enbuyuk)

            # Veri bölümü '\n' ile bitmiyorsa sondaki kısmi kayıt.
            uygun = ((self.kayit_bas is None or satir_no >= self.kayit_bas)
                     and (self.kayit_son is None or satir_no < self.kayit_son))
            if kalinti.strip() and uygun and not dur and not self._iptal.is_set():
                a = deger(cikar(kalinti), anahtar_turu)
                if a is None:
                    self.bos_anahtar += 1
                elif topk:
                    self._heap_ekle(heap, a, satir_no, konum - len(kalinti),
                                    enbuyuk)
                else:
                    hepsi.append((a, satir_no, konum - len(kalinti)))
                self.incelenen += 1

        return heap if topk else hepsi

    def _heap_ekle(self, heap, a, satir_no, ofset, enbuyuk):
        """Sınırlı heap'e ekler: RAM K ile sabittir, dosya boyutundan bağımsız."""
        oge = (a, satir_no, ofset) if enbuyuk else (_Ters(a), satir_no, ofset)
        if len(heap) < self.k:
            heapq.heappush(heap, oge)
        elif heap[0] < oge:
            heapq.heapreplace(heap, oge)

    def _liste_tara(self):
        """Verilen kayıt numaralarını okuyup anahtarlarını toplar.

        Bu kayıtlar zaten erişilebilir (indeksten ya da aramanın bıraktığı
        ipuçlarından geliyorlar), bu yüzden bayt konumu toplamaya gerek yok.
        """
        toplanan = []
        okuyucu = BlockReader(self.bicim, self.index)
        t0 = time.perf_counter()
        son_bildirim = 0.0
        try:
            for no in self.satir_nolari:
                if self._iptal.is_set():
                    break
                try:
                    kayitlar = okuyucu.satir_oku(no, 1)
                except Exception:                # noqa: BLE001
                    kayitlar = []
                a = None
                if kayitlar:
                    a = anahtar_degeri(self.cikarici.cozulmus(kayitlar[0]),
                                       self.tur)
                if a is None:
                    self.bos_anahtar += 1
                else:
                    toplanan.append((a, no, None))
                self.incelenen += 1
                simdi = time.perf_counter()
                if simdi - son_bildirim >= ILERLEME_ARALIGI:
                    son_bildirim = simdi
                    self._ilerleme(t0, toplanan, False, self.yon == AZALAN,
                                   toplam=len(self.satir_nolari))
        finally:
            okuyucu.kapat()
        return toplanan

    # -- sıralama ve bildirim ------------------------------------------
    def _sirala(self, toplananlar):
        """(anahtar, kayıt_no, ofset) üçlülerini sıralı iki listeye çevirir.

        Döner: (kayit_nolari, bayt_ofsetleri) -- aynı sırada. Konumlar
        bilinmiyorsa (KIP_LISTE) ikinci liste boştur.
        """
        if self.kip == KIP_TUM_DOSYA and self.yon == ARTAN:
            # Artan yönde heap `_Ters` sarmalı tutar; önce sarmalı çöz.
            toplananlar = [(o[0].deger, o[1], o[2]) for o in toplananlar]
        duz = sorted(toplananlar, key=lambda o: o[0], reverse=self.yon == AZALAN)
        kayitlar = [o[1] for o in duz]
        ofsetler = [o[2] for o in duz]
        if any(x is None for x in ofsetler):
            ofsetler = []
        return kayitlar, ofsetler

    def _ornek(self, toplananlar, topk, enbuyuk):
        """İlerleme olayı için o ana kadarki EN İYİ birkaç kaydın önizlemesi.

        Top-K kipinde heap'in kendi sıralaması zaten yönü kodlar (azalanda
        düz anahtar, artanda `_Ters` sarmalı), bu yüzden her iki yönde de
        `nlargest` doğru uçtan alır. Aralık/liste kipinde anahtarlar ham
        tutulduğu için yöne göre uç seçilir.
        """
        if topk:
            return [o[1] for o in heapq.nlargest(ONIZLEME_ADET, toplananlar)]
        uc = heapq.nlargest if enbuyuk else heapq.nsmallest
        return [o[1] for o in uc(ONIZLEME_ADET, toplananlar,
                                 key=lambda o: o[0])]

    def _ilerleme(self, t0, toplananlar, topk, enbuyuk, toplam=None):
        gecen = max(1e-9, time.perf_counter() - t0)
        if toplam is None:
            toplam = self.son_ofset - self.bas_ofset
            ilerleme = self.okunan_bayt
        else:
            ilerleme = self.incelenen
        hiz = self.okunan_bayt / gecen if self.okunan_bayt else 0
        kalan = ((toplam - ilerleme) / (ilerleme / gecen)) if ilerleme else None
        self.kuyruk.put({
            "tur": OLAY_ILERLEME,
            "ilerleme": ilerleme,
            "toplam": toplam,
            "incelenen": self.incelenen,
            "bayt": self.okunan_bayt,
            "gecen": gecen,
            "hiz": hiz,
            "kalan_sure": kalan,
            "ornek": self._ornek(toplananlar, topk, enbuyuk),
        })
