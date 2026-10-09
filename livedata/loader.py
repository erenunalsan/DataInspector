"""Arka planda satır penceresi yükleyen thread + sınırlı (LRU) önbellek.

Tembel yükleme (lazy load) burada gerçekleşir. Arayüz hiçbir zaman "şu
100.000 satırlık sayfayı yükle" demez; yalnızca "şu anda EKRANDA GÖRÜNEN
satırlar hangi pencerelerdeyse onları getir" der. Pencere boyu küçüktür
(varsayılan 250 satır), böylece:

  - Ekranda 40 satır görünüyorsa en fazla 2 pencere (500 satır) gerekir.
  - Önbellek üst sınırı sabittir (varsayılan 96 pencere = 24.000 satır);
    kullanıcı ne kadar gezinirse gezinsin RAM kullanımı bu tavanı aşmaz.
    En eski kullanılan pencere düşürülür (LRU).

Öncelik
-------
İstekler öncelikli bir kuyrukta bekler:

  ONCELIK_GORUNUR    -- kullanıcının ŞU AN baktığı satırlar; her şeyin önüne
                        geçer.
  ONCELIK_ONYUKLEME  -- görünen alanın hemen öncesi/sonrası ve komşu sayfa;
                        kullanıcı oraya kaydırdığında veri hazır olsun diye
                        boşta getirilir.

Bayat isteklerin atılması: kullanıcı hızlıca kaydırdığında geride onlarca
artık geçersiz görünür-istek birikir. Arayüz her görünüm değişiminde
`gorunur_ayarla()` ile o an EKRANDA OLAN pencere aralığını bildirir;
yükleyici, bu aralığın dışında kalan GÖRÜNÜR istekleri okumadan atar.
Böylece kaydırma sırasında disk, kullanıcının artık bakmadığı satırlarla
meşgul edilmez.

(Bunun yerine artan bir "nesil" sayacı kullanmak canlı kilide yol açıyordu:
`satirlar()` yükleyicinin kuyruğu boşaltmasından hızlı çağrılırsa, sıradaki
istek her seferinde "eski nesil" sayılıp atılır, yerine konan istek de bir
sonraki turda eskir ve pencere HİÇ yüklenmezdi. Görünür aralık ölçütünde
böyle bir yarış yoktur: aralık değişmediği sürece istek geçerli kalır.)
"""
import queue
import threading
import time
from collections import OrderedDict

from .blockreader import BlockReader

ONCELIK_GORUNUR = 0
ONCELIK_ONYUKLEME = 1

VARSAYILAN_PENCERE = 250          # satır / pencere
VARSAYILAN_ONBELLEK = 96          # pencere (96 x 250 = 24.000 satır tavan)
# Kuyruk bu kadar dolduğunda yeni ÖN YÜKLEME istekleri kabul edilmez;
# görünür istekler her zaman kabul edilir.
KUYRUK_TAVANI = 256

OLAY_PENCERE = "pencere"          # bir pencere hazır
OLAY_HATA = "yukleyici_hata"


class WindowLoader(threading.Thread):
    """Pencere isteklerini sırayla işleyen tek arka plan thread'i.

    Neden TEK thread? Okumalar aynı fiziksel diski kullanır; ölçümde 8
    paralel okuyucu toplam hızı yalnızca ~1,4 kat artırdı, buna karşılık
    kafa/kuyruk atlamaları rastgele erişim gecikmesini bozuyor. Tek
    thread + öncelikli kuyruk, "önce kullanıcının gördüğü" garantisini
    çok daha net veriyor.
    """

    def __init__(self, bicim, index, olay_kuyrugu,
                 pencere=VARSAYILAN_PENCERE, onbellek=VARSAYILAN_ONBELLEK):
        super().__init__(name="livedata-loader", daemon=True)
        self.bicim = bicim
        self.index = index
        self.kuyruk_disari = olay_kuyrugu
        self.pencere = pencere
        self.onbellek_tavani = onbellek

        self._istekler = queue.PriorityQueue()
        self._sira = 0
        self._sira_kilit = threading.Lock()
        self._bekleyen = set()
        self._onbellek = OrderedDict()          # pencere_id -> list[list[str]]
        self._kilit = threading.Lock()
        self._dur = threading.Event()
        # O an ekranda olan pencerelerin kümesi. None -> "henüz bilinmiyor",
        # hiçbir istek bayat sayılmaz.
        self._gorunur = None

        # İstatistik (yalnızca gösterim)
        self.yuklenen_pencere = 0
        self.toplam_sure = 0.0
        self.isabet = 0
        self.iska = 0

    # -- arayüz tarafı -------------------------------------------------
    def pencere_id(self, satir):
        return satir // self.pencere

    def pencere_bas(self, pencere_id):
        return pencere_id * self.pencere

    def gorunur_ayarla(self, pidler):
        """Ekranda olan pencerelerin KÜMESİNİ bildirir.

        Bu kümenin dışında kalan GÖRÜNÜR öncelikli istekler, sıraları
        geldiğinde okunmadan atılır. Küme (aralık değil) olması gerekir:
        sıralı bir görünümde ekrandaki satırlar dosyanın her yerine
        dağılmıştır, ardışık bir pencere aralığı oluşturmazlar.
        """
        self._gorunur = frozenset(pidler)

    def onbellekten(self, pencere_id):
        """Pencere önbellekteyse döner, değilse None. Tk thread'inden güvenli."""
        with self._kilit:
            v = self._onbellek.get(pencere_id)
            if v is not None:
                self._onbellek.move_to_end(pencere_id)
                self.isabet += 1
            else:
                self.iska += 1
            return v

    def iste(self, pencere_id, oncelik=ONCELIK_GORUNUR):
        """Bir pencereyi kuyruğa alır (önbellekteyse ya da beklemedeyse atlar)."""
        with self._kilit:
            if pencere_id in self._onbellek:
                return False
            if pencere_id in self._bekleyen:
                return False
            if (oncelik != ONCELIK_GORUNUR
                    and self._istekler.qsize() >= KUYRUK_TAVANI):
                return False
            self._bekleyen.add(pencere_id)
        with self._sira_kilit:
            self._sira += 1
            sira = self._sira
        self._istekler.put((oncelik, sira, pencere_id))
        return True

    def bekleyen_sayisi(self):
        return self._istekler.qsize()

    def onbellek_satir_sayisi(self):
        with self._kilit:
            return sum(len(v) for v in self._onbellek.values())

    def dur(self):
        self._dur.set()
        self._istekler.put((-1, -1, None))         # uyandırma işareti

    def onbellek_temizle(self):
        with self._kilit:
            self._onbellek.clear()

    # -- thread tarafı -------------------------------------------------
    def run(self):
        okuyucu = None
        try:
            okuyucu = BlockReader(self.bicim, self.index)
            while not self._dur.is_set():
                oncelik, _sira, pid = self._istekler.get()
                if pid is None:
                    break
                try:
                    self._isle(okuyucu, oncelik, pid)
                finally:
                    with self._kilit:
                        self._bekleyen.discard(pid)
        except Exception as e:                          # noqa: BLE001
            self.kuyruk_disari.put({"tur": OLAY_HATA, "hata": e})
        finally:
            if okuyucu is not None:
                okuyucu.kapat()

    def _isle(self, okuyucu, oncelik, pid):
        # Kullanıcı çoktan başka yere baktıysa bu okumayı hiç yapma.
        if oncelik == ONCELIK_GORUNUR:
            gorunur = self._gorunur
            if gorunur is not None and pid not in gorunur:
                return
        with self._kilit:
            if pid in self._onbellek:
                return

        bas = self.pencere_bas(pid)
        t0 = time.perf_counter()
        if self.index.erisilebilir(bas):
            satirlar = okuyucu.satir_oku(bas, self.pencere)
        else:
            # Henüz indekslenmemiş bölge: baştan okursak satır numaraları
            # yanlış olur. Yine de pencerenin İÇİNDE (aramanın bıraktığı bir
            # ipucu sayesinde) konumlandırılabilen bir satır olabilir; o
            # satırdan itibarını okur, öncesini "bilinmiyor" bırakırız.
            alt = self.index.ilk_erisilebilir(bas, bas + self.pencere)
            if alt is None:
                return
            okunan = okuyucu.satir_oku(alt, self.pencere - (alt - bas))
            satirlar = [None] * (alt - bas) + okunan
        sure = time.perf_counter() - t0

        with self._kilit:
            self._onbellek[pid] = satirlar
            self._onbellek.move_to_end(pid)
            while len(self._onbellek) > self.onbellek_tavani:
                self._onbellek.popitem(last=False)
            self.yuklenen_pencere += 1
            self.toplam_sure += sure

        self.kuyruk_disari.put({
            "tur": OLAY_PENCERE,
            "id": pid,
            "bas": bas,
            "adet": len(satirlar),
            "sure": sure,
            "oncelik": oncelik,
        })
