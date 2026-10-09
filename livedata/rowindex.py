"""Seyrek satır indeksi ve onu arka planda kuran tarayıcı thread'i.

Neden seyrek?
-------------
CSV'de satır uzunlukları değişkendir; N. satırın bayt konumu ancak baştan
sayarak bulunabilir. Her satırın konumunu tutmak 205 milyon satır x 8 bayt =
1,6 GB RAM demektir -- kabul edilemez. Bunun yerine her `stride` (varsayılan
1000) satırda BİR konum tutulur:

    205.060.846 / 1000 = 205.061 çıpa x 8 bayt = ~1,6 MB RAM

Bir satıra gitmek için en yakın önceki çıpaya `seek` edilir ve oradan en
fazla `stride - 1` kayıt ileri okunur (ölçülen: < 1 ms). Böylece rastgele
erişim, RAM'i doldurmadan pratikte anında olur.

Tarama maliyeti (dürüst tablo)
------------------------------
Kesin satır numarası ancak baytları okuyarak bulunabilir; bunun kestirme
yolu yoktur. 63,8 GB'lık kaynak, ölçülen ~0,37 GiB/sn disk hızıyla ~160
saniyede taranır. Bu yüzden tarama:

  - AÇILIŞI BEKLETMEZ: dosya anında açılır, kullanıcı baştan itibaren
    gezinebilir; tarama arka planda baştan sona ilerler.
  - DURDURULABİLİR/DURAKLATILABİLİR: arama başlayınca tarayıcı duraklatılır
    (ikisi de aynı diski kullanır; yarıştırmak ikisini de yavaşlatır).
  - İLERLEMESİNİ BİLDİRİR: okunan bayt, bulunan satır, hız ve kalan süre.

Thread güvenliği
----------------
Tek yazar (tarayıcı thread'i), çok okuyucu (arayüz + yükleyici) vardır.
Kilitsiz çalışır; yayımlama sırası buna dayanır:

    1. çıpa `_cipalar`'a eklenir
    2. SONRA `taranan_satir` güncellenir

Okuyucu önce `taranan_satir`'ı okur, ancak ona göre çıpa indeksler. GIL
altında `array.append` ve tamsayı ataması bölünmez olduğundan, okuyucu
`taranan_satir = N` gördüğünde N'e karşılık gelen çıpanın diziye çoktan
eklenmiş olduğu garantidir. `_ipuclari` (aramadan gelen ek çıpalar) tek
yazarlı değildir, bu yüzden orada kilit kullanılır.
"""
import threading
import time
from array import array
from bisect import bisect_right

from . import rowscan

VARSAYILAN_STRIDE = 1000          # kaç satırda bir çıpa
VARSAYILAN_BLOK = 8 << 20         # tarayıcının tek seferde okuduğu bayt
ILERLEME_ARALIGI = 0.20           # saniye: ilerleme olayı yayımlama sıklığı
# Aramadan ve SIRALAMADAN gelen ek çıpaların üst sınırı. Bir sayfa
# sıralaması 100.000 sonuç üretebildiği için bu tavan onu karşılamalıdır;
# ipucu başına ~48 bayt (iki liste ögesi + tamsayılar) ile 262.144 ipucu
# ~12 MB eder, yani RAM tavanı içinde kalır.
EN_FAZLA_IPUCU = 262_144

# Olay türleri (tarayıcı -> arayüz kuyruğu)
OLAY_ILERLEME = "ilerleme"
OLAY_BITTI = "bitti"
OLAY_HEDEF = "hedefe_ulasildi"   # istenen kayda kadar tarandı, tarayıcı durdu
OLAY_HATA = "hata"
OLAY_UYARI = "uyari"


class RowIndex:
    """Satır numarası -> bayt konumu seyrek eşlemesi."""

    def __init__(self, veri_basi, stride=VARSAYILAN_STRIDE):
        self.stride = stride
        self.veri_basi = veri_basi
        # _cipalar[k] = (k * stride) numaralı satırın mutlak bayt konumu.
        # 0. çıpa her zaman veri başıdır.
        self._cipalar = array("q", [veri_basi])
        self.taranan_satir = 0        # kesinleşmiş satır sayısı
        self.taranan_bayt = 0
        self.toplam_satir = None      # tarama bitince kesin değer
        self.tamam = False
        self.iptal_edildi = False

        self._ipucu_kilit = threading.Lock()
        self._ipucu_satirlar = []     # sıralı
        self._ipucu_ofsetler = []

    # -- yazar tarafı (yalnızca tarayıcı thread'i) ----------------------
    def _cipa_ekle(self, ofsetler):
        self._cipalar.extend(ofsetler)

    # -- okuyucu tarafı (herhangi bir thread) --------------------------
    def bilinen_satir(self):
        """Kesin olarak konumlandırılabilen satır sayısı."""
        return self.toplam_satir if self.tamam else self.taranan_satir

    def ipucu_ekle(self, satir, ofset):
        """Aramadan gelen bir (satır, bayt konumu) çiftini çıpa olarak ekler.

        Arama, indeks taramasının ULAŞMADIĞI bölgelerde de eşleşme bulur.
        Bu ipuçları sayesinde kullanıcı, indeks oraya varmamış olsa bile
        bulunan eşleşmenin çevresini anında görüntüleyebilir.
        """
        with self._ipucu_kilit:
            if len(self._ipucu_satirlar) >= EN_FAZLA_IPUCU:
                return
            k = bisect_right(self._ipucu_satirlar, satir)
            if k > 0 and self._ipucu_satirlar[k - 1] == satir:
                return
            self._ipucu_satirlar.insert(k, satir)
            self._ipucu_ofsetler.insert(k, ofset)

    def ipuclari_ekle(self, ciftler):
        """Çok sayıda (satır, bayt konumu) ipucunu TEK SEFERDE ekler.

        `ipucu_ekle`'yi döngüde çağırmak olmaz: her çağrı sıralı listeye
        `insert` yapar ve bu O(n) sürer; 100.000 ipucu için O(n²) = milyarlarca
        işlem eder. Burada hepsi eklenip liste bir kez sıralanır.

        Sıralama sonuçları için kullanılır: sonuç kayıtları dosyanın her
        yerine dağılmıştır ve bayt konumları bilinmeden gösterilemezler.
        """
        yeni = [(int(s), int(o)) for s, o in ciftler if o is not None]
        if not yeni:
            return 0
        with self._ipucu_kilit:
            mevcut = dict(zip(self._ipucu_satirlar, self._ipucu_ofsetler))
            mevcut.update(yeni)
            if len(mevcut) > EN_FAZLA_IPUCU:
                # En yeni ipuçları korunur: kullanıcının şu an baktığı
                # sonuç kümesi, çok önceki bir aramanınkinden önemlidir.
                korunacak = dict(yeni[-EN_FAZLA_IPUCU:])
                mevcut = korunacak
            sirali = sorted(mevcut.items())
            self._ipucu_satirlar = [s for s, _ in sirali]
            self._ipucu_ofsetler = [o for _, o in sirali]
            return len(sirali)

    def cipa_bul(self, satir):
        """`satir`'a en yakın ÖNCEKİ çıpayı (cipa_satir, bayt_ofset) döner.

        Hem düzenli çıpalar hem de aramadan gelen ipuçları değerlendirilir;
        hangisi hedefe daha yakınsa o kullanılır (daha az ileri okuma).
        """
        if satir < 0:
            satir = 0
        k = satir // self.stride
        # Yayımlama sırası gereği önce satır sayacını okuyoruz.
        en_fazla_k = min(k, len(self._cipalar) - 1)
        cipa_satir = en_fazla_k * self.stride
        cipa_ofset = self._cipalar[en_fazla_k]

        with self._ipucu_kilit:
            if self._ipucu_satirlar:
                i = bisect_right(self._ipucu_satirlar, satir) - 1
                if i >= 0 and self._ipucu_satirlar[i] > cipa_satir:
                    cipa_satir = self._ipucu_satirlar[i]
                    cipa_ofset = self._ipucu_ofsetler[i]
        return cipa_satir, cipa_ofset

    def erisilebilir(self, satir, tolerans=None):
        """`satir` şu anda KESİN ve UCUZ biçimde konumlandırılabilir mi?

        Ölçüt, taramanın nereye geldiği DEĞİLDİR: bir çıpanın bayt konumu
        bilindiği anda oradan ileri okumak, tarayıcı çok gerideyken bile
        doğru satırları verir (dosya değişmiyor). Gerçek kısıt maliyettir --
        çıpadan hedefe kadar kaç kayıt ileri okunacağı.

        Bu yüzden ölçüt: hedef, en yakın önceki çıpadan en fazla `tolerans`
        (varsayılan: bir çıpa aralığı = `stride`) kayıt ötede olmalı. Böylece:

          - Dosya açılır açılmaz ilk `stride` satır okunabilir (0. çıpa
            zaten veri başıdır) -- kullanıcı taramayı beklemez.
          - Taramanın çok ilerisindeki bir satır okunmaz; çünkü oraya
            ulaşmak milyonlarca kayıt ileri okumak demektir.
        """
        if satir < 0:
            return False
        if self.tamam and satir >= (self.toplam_satir or 0):
            return False
        cipa_satir, _ = self.cipa_bul(satir)
        sinir = self.stride if tolerans is None else tolerans
        return (satir - cipa_satir) <= sinir

    def ilk_erisilebilir(self, bas, son):
        """[bas, son) aralığındaki EN KÜÇÜK erişilebilir satırı döner; yoksa None.

        Arama, indeks taramasının çok ilerisinde eşleşme bulduğunda o satır
        için bir ipucu bırakır. O eşleşmenin çevresini gösterecek pencere ise
        ipucundan ÖNCE başlar ve tek başına konumlandırılamaz. Bu yöntem,
        pencerenin okunabilen kısmının nereden başladığını söyler; yükleyici
        öncesini "henüz bilinmiyor" olarak bırakır.
        """
        if bas < 0:
            bas = 0
        if self.erisilebilir(bas):
            return bas
        with self._ipucu_kilit:
            if not self._ipucu_satirlar:
                return None
            i = bisect_right(self._ipucu_satirlar, bas - 1)
            if i < len(self._ipucu_satirlar) and self._ipucu_satirlar[i] < son:
                return self._ipucu_satirlar[i]
        return None

    def bellek_bayt(self):
        """İndeksin yaklaşık RAM kullanımı."""
        return (len(self._cipalar) * self._cipalar.itemsize
                + len(self._ipucu_satirlar) * 16)

    def cipa_sayisi(self):
        return len(self._cipalar)


class IndexScanner(threading.Thread):
    """Kaynak dosyayı baştan sona okuyup RowIndex'i dolduran arka plan işi.

    Dosyayı yalnızca OKUR; hiçbir şey yazmaz. Aynı anda tek bir kopyası
    çalışır. `duraklat()` ile geçici olarak durdurulabilir (arama sırasında
    diski serbest bırakmak için), `iptal()` ile tamamen bitirilebilir.
    """

    def __init__(self, bicim, index, olay_kuyrugu, blok=VARSAYILAN_BLOK,
                 duraklatilmis_basla=False, hedef_satir=None):
        super().__init__(name="livedata-index", daemon=True)
        self.bicim = bicim
        self.index = index
        self.kuyruk = olay_kuyrugu
        self.blok = blok
        # Tarama HEDEFİ: bu kayda ulaşınca tarayıcı kendini duraklatır.
        # None -> sınırsız (dosyanın sonuna kadar). Böylece "kayıt N'e git"
        # isteği, dosyanın tamamını değil YALNIZCA N'e kadarki bölümü
        # okutur; kullanıcı uzak bir kayda hiç gitmezse hiç okunmaz.
        self.hedef_satir = hedef_satir

        self._iptal = threading.Event()
        self._devam = threading.Event()
        if not duraklatilmis_basla:
            self._devam.set()
        self.baslangic_zamani = None
        self.sure = None
        self._duraklama_suresi = 0.0

    # -- denetim -------------------------------------------------------
    def iptal(self):
        self._iptal.set()
        self._devam.set()          # duraklamışsa uyandır ki çıkabilsin

    def duraklat(self):
        self._devam.clear()

    def surdur(self):
        self._devam.set()

    def hedefe_tara(self, hedef):
        """Belirtilen kayda kadar taramayı sürdürür (oraya varınca durur)."""
        if self.index.tamam:
            return False
        if self.index.taranan_satir >= hedef:
            return False
        self.hedef_satir = hedef
        self._devam.set()
        return True

    def tamamla(self):
        """Hedefi kaldırır: dosyanın sonuna kadar tarar."""
        self.hedef_satir = None
        self._devam.set()

    @property
    def duraklatildi(self):
        return not self._devam.is_set()

    # -- çalışma -------------------------------------------------------
    def run(self):
        try:
            self._tara()
        except Exception as e:                      # noqa: BLE001
            self.kuyruk.put({"tur": OLAY_HATA, "hata": e})

    def _tara(self):
        bicim = self.bicim
        index = self.index
        stride = index.stride
        tirnak_duyarli = bicim.tirnak_duyarli
        quote = ord(bicim.tirnak) if bicim.tirnak else rowscan.QUOTE

        self.baslangic_zamani = time.perf_counter()
        son_bildirim = 0.0
        satir = 0
        parity = 0
        konum = bicim.veri_basi
        son_bayt_nl = True
        tirnak_uyarisi_verildi = tirnak_duyarli

        # Kayıtların bittiği sınır: JSON/XML'de dosyanın sonunda kayıt
        # OLMAYAN kuyruk satırları vardır (']}', '</rows>'); onları
        # saymamak için tarama burada durur.
        veri_sonu = getattr(bicim, "veri_sonu", bicim.boyut)

        with open(bicim.yol, "rb") as f:
            f.seek(konum)
            while not self._iptal.is_set():
                if not self._devam.is_set():
                    d0 = time.perf_counter()
                    self._devam.wait()
                    self._duraklama_suresi += time.perf_counter() - d0
                    if self._iptal.is_set():
                        break
                    # Duraklama sırasında dosya konumu korunur; seek gereksiz.

                kalan = veri_sonu - konum
                if kalan <= 0:
                    break
                blok = f.read(min(self.blok, kalan))
                if not blok:
                    break

                # Tırnak duyarlılığı kapalıyken tırnak görülürse bir kez uyar:
                # kullanıcı isterse yeniden tarayabilir.
                if not tirnak_uyarisi_verildi and b'"' in blok:
                    tirnak_uyarisi_verildi = True
                    self.kuyruk.put({
                        "tur": OLAY_UYARI,
                        "mesaj": (
                            "Dosyanın ilerleyen bölümünde çift tırnak (\") "
                            "görüldü; tarama 'tırnak duyarsız' modda başlamıştı. "
                            "Tırnak içinde satır sonu varsa satır numaraları "
                            "kayabilir. Kesinlik için dosyayı 'Tırnak duyarlı' "
                            "seçeneğiyle yeniden açın."),
                    })

                yeni_cipalar = []
                satir, parity = rowscan.scan_for_anchors(
                    blok, 0, len(blok), konum, parity, satir, stride,
                    yeni_cipalar, tirnak_duyarli, quote)

                if yeni_cipalar:
                    index._cipa_ekle(yeni_cipalar)
                son_bayt_nl = blok[-1] == rowscan.NL
                konum += len(blok)

                # Yayımlama sırası ÖNEMLİ: çıpalar önce, sayaç sonra.
                index.taranan_satir = satir
                index.taranan_bayt = konum - bicim.veri_basi

                simdi = time.perf_counter()
                if simdi - son_bildirim >= ILERLEME_ARALIGI:
                    son_bildirim = simdi
                    self._ilerleme_yayimla(simdi)

                # İstenen kayda ulaşıldıysa dur: gerisini okumaya gerek yok.
                hedef = self.hedef_satir
                if hedef is not None and satir >= hedef:
                    self._devam.clear()
                    self._ilerleme_yayimla(time.perf_counter())
                    self.kuyruk.put({"tur": OLAY_HEDEF, "satir": satir,
                                     "hedef": hedef,
                                     "bayt": index.taranan_bayt,
                                     "gecen": self._gecen()})

        if self._iptal.is_set():
            index.iptal_edildi = True
            self.sure = self._gecen()
            self.kuyruk.put({"tur": OLAY_BITTI, "iptal": True,
                             "satir": satir, "sure": self.sure})
            return

        # Dosya '\n' ile bitmiyorsa sondaki kısmi satır da bir kayıttır.
        if not son_bayt_nl and konum > bicim.veri_basi:
            satir += 1
        index.taranan_satir = satir
        index.toplam_satir = satir
        index.tamam = True
        self.sure = self._gecen()
        self._ilerleme_yayimla(time.perf_counter())
        self.kuyruk.put({"tur": OLAY_BITTI, "iptal": False,
                         "satir": satir, "sure": self.sure,
                         "bayt": index.taranan_bayt,
                         "cipa": index.cipa_sayisi(),
                         "bellek": index.bellek_bayt()})

    def _gecen(self):
        if self.baslangic_zamani is None:
            return 0.0
        return time.perf_counter() - self.baslangic_zamani - self._duraklama_suresi

    def _ilerleme_yayimla(self, simdi):
        gecen = max(1e-9, simdi - self.baslangic_zamani - self._duraklama_suresi)
        okunan = self.index.taranan_bayt
        toplam = self.bicim.veri_bayt
        hiz = okunan / gecen
        kalan = (toplam - okunan) / hiz if hiz > 0 else None
        self.kuyruk.put({
            "tur": OLAY_ILERLEME,
            "bayt": okunan,
            "toplam_bayt": toplam,
            "satir": self.index.taranan_satir,
            "gecen": gecen,
            "hiz": hiz,
            "kalan_sure": kalan,
        })
