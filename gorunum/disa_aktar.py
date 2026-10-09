"""Seçili kayıtları Excel/Word/PDF olarak, arka planda parça parça toplayıp
üreten iş kuyruğu.

Masaüstü sürümünde (`SeciliVerilerPenceresi._kopyala_adim`) bu iş bir
Tkinter `after()` döngüsüydü: kayıtlar 2000'lik parçalar hâlinde arka
plandaki pencere yükleyiciden istenir, arayüz bu sırada kilitlenmezdi.

Web'de "arayüz kilitlenmesin" demek, bu toplama işini TEK BİR HTTP isteği
içinde yapmamak demektir -- yüz binlerce kayıtlık bir seçim, kayıt başına
~0,4ms'lik dağınık erişimle dakikalarca sürebilir ve bu süre boyunca bir
HTTP isteğini açık tutmak (zaman aşımı riski, ilerleme göstergesi yokluğu)
kötü bir tasarım olurdu. Bunun yerine: `baslat()` bir arka plan thread'i
başlatıp hemen bir TOKEN döner; istemci `ilerleme()`yi polling ile izler,
iş bitince `indir()` ile bir kerelik dosya baytlarını alır.
"""
import threading
import time
import uuid

from livedata import exporters

PARCA = 2000
ARALIK_SN = 0.05

_URETICILER = {
    "excel": exporters.xlsx_uret,
    "word": exporters.docx_uret,
    "pdf": exporters.pdf_uret,
}
_MIME = {
    "excel": ("application/vnd.openxmlformats-officedocument."
             "spreadsheetml.sheet", "secili_veriler.xlsx"),
    "word": ("application/vnd.openxmlformats-officedocument."
            "wordprocessingml.document", "secili_veriler.docx"),
    "pdf": ("application/pdf", "secili_veriler.pdf"),
}


class DisaAktarIsi:
    def __init__(self, oturum, nolar, kolon_adlari, baslik, bicim):
        if bicim not in _URETICILER:
            raise ValueError(f"Bilinmeyen dışa aktarım biçimi: {bicim!r}")
        self.oturum = oturum
        self.nolar = list(nolar)
        self.kolon_adlari = kolon_adlari
        self.baslik = baslik
        self.bicim = bicim
        self.toplanan = {}
        self.durum = "calisiyor"   # calisiyor | hazir | hata
        self.icerik = None
        self.mime, self.dosya_adi = _MIME[bicim]
        self.hata = None
        self._baslangic = time.perf_counter()
        self.sure = None
        self._iplik = threading.Thread(target=self._calis, daemon=True)

    def baslat(self):
        self._iplik.start()
        return self

    def _calis(self):
        try:
            while len(self.toplanan) < len(self.nolar):
                kalan = [no for no in self.nolar if no not in self.toplanan]
                parca = kalan[:PARCA]
                for no, degerler in self.oturum.kayitlar(parca):
                    if degerler is not None:
                        self.toplanan[no] = degerler
                if len(self.toplanan) < len(self.nolar):
                    time.sleep(ARALIK_SN)
            uretici = _URETICILER[self.bicim]
            self.icerik = uretici(self.baslik, self.kolon_adlari, self.nolar,
                                  self.toplanan)
            self.sure = time.perf_counter() - self._baslangic
            self.durum = "hazir"
        except Exception as e:  # pragma: no cover - beklenmedik hata yolu
            self.hata = str(e)
            self.durum = "hata"

    def ilerleme(self):
        return {
            "durum": self.durum, "toplanan": len(self.toplanan),
            "toplam": len(self.nolar), "hata": self.hata,
            "sure": self.sure,
        }


_kilit = threading.Lock()
_ISLER = {}


def baslat(oturum, nolar, kolon_adlari, baslik, bicim):
    is_ = DisaAktarIsi(oturum, nolar, kolon_adlari, baslik, bicim).baslat()
    token = uuid.uuid4().hex[:12]
    with _kilit:
        _ISLER[token] = is_
    return token


def al(token):
    with _kilit:
        return _ISLER.get(token)


def temizle(token):
    with _kilit:
        _ISLER.pop(token, None)
