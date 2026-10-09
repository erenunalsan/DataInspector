"""Arka plan olay kuyruğunu (queue.Queue) tüketip JSON'a uygun, anlık bir
durum sözlüğüne dönüştüren adaptör.

Tkinter sürümünde (`livedata/ui/app.py`) bu iş `_kuyrugu_isle`/`_olay`
metotlarının işiydi: kuyruğu düzenli aralıklarla (30ms) boşaltıp widget'ları
günceller, ayrıca `oturum.siralama_bitti()`, `oturum.arama_bitti()`,
`oturum.indeks_hedefe_ulasti()`, `oturum.gorunum_ayarla()` gibi durum
mutasyonlarını doğrudan tetiklerdi.

Web sürümünde HTTP istek/yanıt döngüsü durumsuzdur; bu yüzden kuyruğu
TEK bir arka plan thread'i sürekli tüketir ve sonucu bir STANDART DURUM
SÖZLÜĞÜNE yazar. Tarayıcı bu sözlüğü periyodik olarak
(`GET /api/oturum/<id>/durum`) okur. `oturum.*_bitti()` gibi durum
mutasyonları da AYNI şekilde bu thread içinden, Tkinter sürümüyle birebir
aynı noktalarda çağrılır -- böylece iki arayüz aynı çekirdeği aynı
kurallarla kullanır.

Kuyruğu yalnızca bu thread tüketir; HTTP istek thread'leri asla
`queue.get()` çağırmaz -- yalnızca son anlık görüntüyü okurlar. Bu, birden
çok tarayıcı sekmesi/isteği aynı oturumu izlerken birbirinin olayını
"çalmasını" önler (Tkinter'da tek bir tüketici olduğu için bu sorun hiç
yoktu; web'de birden çok istemci olabileceğinden bilinçli bir tasarım
kararıdır).
"""
import queue
import threading

from livedata import finder, loader, rowindex, sorting

# Kuyruk boşken en fazla bu kadar bekleyip tekrar dene (stop() çağrısının
# makul bir gecikmeyle etkili olması için kısa tutulur).
BEKLEME_SN = 0.05
EN_FAZLA_KONSOL = 500
EN_FAZLA_ESLESME = 20_000


def _bos_indeks():
    return {"oran": 0.0, "tamam": False, "calisiyor": False,
            "metin": "— (istek üzerine)"}


def _bos_arama():
    return {"calisiyor": False, "oran": 0.0, "eslesme": 0, "metin": "—"}


def _bos_siralama():
    return {"calisiyor": False, "oran": 0.0, "metin": "—"}


class DurumTakipcisi:
    """Bir `VeriOturumu`nun olay kuyruğunu tüketen arka plan işçisi."""

    def __init__(self, oturum, kuyruk):
        self._oturum = oturum
        self._kuyruk = kuyruk
        self._kilit = threading.Lock()
        self._durdu = threading.Event()
        self._iplik = None

        self._indeks = _bos_indeks()
        self._arama = _bos_arama()
        self._siralama = _bos_siralama()
        self._konsol = []      # [{id, seviye, metin}], id artan ve kalıcı
        self._konsol_sayac = 0
        self._eslesmeler = []  # [{id, satir, onizleme, kirpik}]

    # -- yaşam döngüsü ---------------------------------------------------
    def baslat(self):
        self._iplik = threading.Thread(target=self._dongu, daemon=True)
        self._iplik.start()

    def dur(self):
        self._durdu.set()

    # -- yazma (yalnızca kendi thread'i içinden) --------------------------
    def _konsola_yaz(self, metin, seviye="bilgi"):
        self._konsol_sayac += 1
        self._konsol.append({"id": self._konsol_sayac, "seviye": seviye,
                             "metin": metin})
        if len(self._konsol) > EN_FAZLA_KONSOL:
            self._konsol = self._konsol[-EN_FAZLA_KONSOL:]

    def _dongu(self):
        while not self._durdu.is_set():
            try:
                olay = self._kuyruk.get(timeout=BEKLEME_SN)
            except queue.Empty:
                continue
            with self._kilit:
                self._isle(olay)

    def _isle(self, olay):
        tur = olay.get("tur")

        if tur == rowindex.OLAY_ILERLEME:
            toplam = olay["toplam_bayt"] or 1
            oran = 100.0 * olay["bayt"] / toplam
            self._indeks = {
                "oran": oran, "tamam": False, "calisiyor": True,
                "satir": olay["satir"], "bayt": olay["bayt"],
                "toplam_bayt": toplam, "gecen": olay["gecen"],
                "kalan_sure": olay.get("kalan_sure"),
                "metin": f"%{oran:.1f} · {olay['satir']} kayıt",
            }

        elif tur == rowindex.OLAY_HEDEF:
            self._oturum.indeks_hedefe_ulasti()
            self._indeks["calisiyor"] = False
            self._indeks["metin"] = "durduruldu (istenen kayda ulaşıldı)"

        elif tur == rowindex.OLAY_BITTI:
            iptal = olay.get("iptal", False)
            self._indeks = {
                "oran": 0.0 if iptal else 100.0, "tamam": not iptal,
                "calisiyor": False, "satir": olay["satir"],
                "bayt": olay.get("bayt", 0), "sure": olay.get("sure"),
                "iptal": iptal,
                "metin": "durduruldu" if iptal else "TAMAM",
            }

        elif tur == rowindex.OLAY_UYARI:
            self._konsola_yaz(olay["mesaj"], "uyari")

        elif tur == rowindex.OLAY_HATA:
            self._konsola_yaz(f"İndeks taraması hata verdi: {olay['hata']}", "hata")

        elif tur == loader.OLAY_HATA:
            self._konsola_yaz(f"Satır yükleyici hata verdi: {olay['hata']}", "hata")

        elif tur == loader.OLAY_PENCERE:
            pass  # bir sonraki /satirlar isteği zaten güncel veriyi getirir

        elif tur == finder.OLAY_ESLESME:
            for e in olay["eslesmeler"]:
                self._eslesmeler.append({
                    "id": len(self._eslesmeler), "satir": e.satir,
                    "onizleme": e.onizleme, "kirpik": e.kirpik,
                })
            if len(self._eslesmeler) > EN_FAZLA_ESLESME:
                self._eslesmeler = self._eslesmeler[-EN_FAZLA_ESLESME:]
            self._arama["eslesme"] = len(self._eslesmeler)

        elif tur == finder.OLAY_ILERLEME:
            if olay.get("doldu"):
                return
            toplam = olay["toplam"] or 1
            oran = 100.0 * olay["bayt"] / toplam
            self._arama.update({
                "calisiyor": True, "oran": oran,
                "eslesme": olay["eslesme"],
                "kalan_sure": olay.get("kalan_sure"),
                "metin": f"%{oran:.1f} · {olay['eslesme']} eşleşme",
            })

        elif tur == finder.OLAY_BITTI:
            self._oturum.arama_bitti()
            self._arama.update({
                "calisiyor": False, "bitti": True,
                "iptal": olay["iptal"], "sure": olay["sure"],
                "eslesme": olay["eslesme"],
                "oran": 0.0 if olay["iptal"] else 100.0,
                "metin": ("durduruldu" if olay["iptal"] else "tamamlandı")
                         + f" · {olay['eslesme']} eşleşme",
            })

        elif tur == finder.OLAY_HATA:
            self._oturum.arama_bitti()
            self._arama["calisiyor"] = False
            self._konsola_yaz(f"Arama hata verdi: {olay['hata']}", "hata")

        elif tur == sorting.OLAY_ILERLEME:
            toplam = olay["toplam"] or 1
            oran = 100.0 * olay["ilerleme"] / toplam
            self._siralama.update({
                "calisiyor": True, "oran": oran,
                "metin": f"%{oran:.1f} · {olay['incelenen']} kayıt incelendi",
            })

        elif tur == sorting.OLAY_BITTI:
            self._oturum.siralama_bitti()
            kayitlar = olay["kayitlar"]
            if kayitlar:
                # Tkinter sürümüyle birebir aynı nokta: sıralama sonucu
                # geldiğinde oturum "sıralı görünüme" geçer.
                self._oturum.gorunum_ayarla(kayitlar)
            self._siralama.update({
                "calisiyor": False, "bitti": True,
                "iptal": olay["iptal"], "sure": olay["sure"],
                "bos_anahtar": olay["bos_anahtar"],
                "kayit_sayisi": len(kayitlar),
                "tavan_asildi": olay.get("tavan_asildi", False),
                "metin": ("durduruldu" if olay["iptal"] else "tamamlandı")
                         + f" · {len(kayitlar)} kayıt",
            })

        elif tur == sorting.OLAY_HATA:
            self._siralama["calisiyor"] = False
            self._konsola_yaz(f"Sıralama hata verdi: {olay['hata']}", "hata")

    # -- okuma (herhangi bir HTTP istek thread'inden) ---------------------
    def anlik_goruntu(self, konsol_sonrasi=0, eslesme_sonrasi=0):
        """Son durumun bir kopyasını döner; kuyruğu TÜKETMEZ."""
        with self._kilit:
            yeni_konsol = [k for k in self._konsol if k["id"] > konsol_sonrasi]
            yeni_eslesme = self._eslesmeler[eslesme_sonrasi:]
            return {
                "indeks": dict(self._indeks),
                "arama": dict(self._arama),
                "siralama": dict(self._siralama),
                "konsol": yeni_konsol,
                "konsol_son_id": self._konsol_sayac,
                "eslesmeler": yeni_eslesme,
                "eslesme_toplam": len(self._eslesmeler),
            }

    def eslesme_satirlari(self):
        """O anki arama sonuçlarının kayıt numaraları (sıralama 'Arama
        sonuçları' kapsamı için)."""
        with self._kilit:
            return [e["satir"] for e in self._eslesmeler]

    def dis_mesaj(self, metin, seviye="bilgi"):
        """Görünüm katmanının (ör. dosya açılışında) konsola tek seferlik
        bir mesaj eklemesi için -- kuyruktan gelmeyen olaylar içindir."""
        with self._kilit:
            self._konsola_yaz(metin, seviye)
