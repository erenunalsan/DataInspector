"""Açık `VeriOturumu`larını process-içi bir sözlükte tutan kayıt defteri.

HTTP istekleri arasında DURUMSUZDUR; ama `VeriOturumu` (açık dosya, arka
plan thread'leri, indeks/yükleyici durumu) istekler arası YAŞAMALIDIR --
her istekte dosyayı yeniden açmak hem "diske hiçbir şey yazılmaz/gereksiz
okuma yapılmaz" ilkesini bozar hem de arka plan taramasını sıfırlardı. Bu
modül tam olarak bunu çözer: tek bir process-içi sözlük, oturum kimliğine
(oid) göre anahtarlı.

ÖNEMLİ KISIT: bu sözlük yalnızca TEK bir process içinde anlamlıdır. Bu
yüzden uygulama TEK worker/process ile çalıştırılmalıdır -- ör.
`python manage.py runserver --noreload` ya da
`waitress-serve --threads=8 --processes=1 webproj.wsgi:application`.
Çoklu THREAD serbesttir (zaten her oturumun kendi arka plan thread'leri
var), çoklu PROCESS değildir. Bkz. LIVEDATA_WEB.md.
"""
import queue
import threading
import time
import uuid

from livedata.session import VeriOturumu

from .olaylar import DurumTakipcisi

# Bu süre boyunca hiç istek almayan bir oturum otomatik kapatılır (tarayıcı
# sekmesi unutulup kapatıldığında arka plan thread'lerinin sonsuza dek açık
# kalmaması için).
BOSTA_ESIK_SN = 60 * 60  # 1 saat


class _Girdi:
    __slots__ = ("oturum", "takipci", "son_erisim", "yol")

    def __init__(self, oturum, takipci, yol):
        self.oturum = oturum
        self.takipci = takipci
        self.yol = yol
        self.son_erisim = time.time()


class OturumKaydi:
    def __init__(self):
        self._kilit = threading.Lock()
        self._girdiler = {}

    def olustur(self, yol, **secenekler):
        """Yeni bir oturum açar, arka plan iş parçacıklarını başlatır ve
        (oid, oturum) döner. `secenekler` doğrudan `VeriOturumu`ya geçer."""
        kuyruk = queue.Queue()
        oturum = VeriOturumu(yol, kuyruk, **secenekler)
        oturum.baslat()
        takipci = DurumTakipcisi(oturum, kuyruk)
        takipci.baslat()

        oid = uuid.uuid4().hex[:12]
        with self._kilit:
            self._girdiler[oid] = _Girdi(oturum, takipci, yol)
        return oid, oturum

    def al(self, oid):
        """(oturum, takipci) döner; yoksa (None, None)."""
        with self._kilit:
            girdi = self._girdiler.get(oid)
            if girdi is None:
                return None, None
            girdi.son_erisim = time.time()
            return girdi.oturum, girdi.takipci

    def kapat(self, oid):
        with self._kilit:
            girdi = self._girdiler.pop(oid, None)
        if girdi is not None:
            girdi.takipci.dur()
            girdi.oturum.kapat()

    def bosta_kalanlari_kapat(self, esik_sn=BOSTA_ESIK_SN):
        simdi = time.time()
        with self._kilit:
            eskiler = [oid for oid, g in self._girdiler.items()
                      if simdi - g.son_erisim > esik_sn]
        for oid in eskiler:
            self.kapat(oid)
        return eskiler

    def hepsini_kapat(self):
        """Süreç kapanırken (ör. sunucu durdurulurken) tüm oturumları temizler."""
        with self._kilit:
            oidler = list(self._girdiler)
        for oid in oidler:
            self.kapat(oid)


# Process genelinde TEK örnek -- bkz. modül docstring'indeki kısıt.
KAYIT = OturumKaydi()
