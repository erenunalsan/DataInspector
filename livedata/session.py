"""Bir kaynak dosya oturumu: biçim + indeks + tarayıcı + yükleyici + arama.

CSV, JSON, XML ve YAML için AYNI sınıftır; biçime özgü her şey
`formats` paketinde kalır (bkz. formats/base.py).

Arayüz (gui) bu sınıfla konuşur; alt katmanları doğrudan bilmez. Oturumun
üç sorumluluğu vardır:

  1. Alt bileşenlerin YAŞAM DÖNGÜSÜ (başlat/kapat, thread'lerin düzgün
     sonlanması).
  2. DİSK ÖNCELİĞİ: indeks taraması ile arama aynı fiziksel diski kullanır.
     İkisini yarıştırmak ikisini de yavaşlatır; bu yüzden arama başlarken
     tarayıcı DURAKLATILIR, arama bitince (yalnızca istenmişse) sürdürülür.

  2b. İNDEKS İSTEĞE BAĞLIDIR. Oturum açılışta HİÇBİR tarama yapmaz; tarayıcı
     duraklatılmış başlar. Çünkü indeks yalnızca iki şey için gerekir:
     uzak bir kayda atlamak ve KESİN toplam kayıt sayısı. Dosyayı açmak,
     baştan gezinmek ve ARAMA yapmak indekssiz çalışır (arama zaten baştan
     sona okuyup kayıtları kendi sayar). Kullanıcı uzak bir kayda gitmek
     isterse `indeksi_ilerlet()` YALNIZCA o kayda kadar tarar; `indeksi_tamamla()`
     dosyanın tamamını indeksler. Böylece 60-110 GB'lık bir dosyada sadece
     veriye bakmak ya da arama yapmak için dakikalarca disk okunmaz.
  3. GÖRÜNÜR SATIRLARIN TEMİNİ: `satirlar()` yalnızca ekranda görünen aralığı
     ister, eksik pencereleri arka plana kuyruklar ve henüz gelmemiş satırlar
     için None döner -- arayüz asla beklemez, asla donmaz.

Diske hiçbir şey yazılmaz; kaynak dosya salt okunur açılır.
"""
import os
import threading

from . import finder, formats, loader, rowindex, selection, sorting

# Kullanıcıya sunulan gezinme birimi. Kaydırma çubuğu bir sayfanın
# içinde ölçeklenir; sayfalar arası geçiş düğmelerle/satıra-git ile olur.
SAYFA_SATIR = 100_000


class VeriOturumu:
    """Tek bir CSV dosyası üzerinde açık oturum."""

    def __init__(self, yol, olay_kuyrugu, ayrac=None, kodlama=None,
                 baslik_var=None, tirnak_duyarli=None,
                 stride=rowindex.VARSAYILAN_STRIDE,
                 pencere=loader.VARSAYILAN_PENCERE,
                 onbellek=loader.VARSAYILAN_ONBELLEK,
                 sayfa_satir=SAYFA_SATIR,
                 tarama_blok=rowindex.VARSAYILAN_BLOK):
        self.yol = yol
        self.kuyruk = olay_kuyrugu
        self.sayfa_satir = sayfa_satir

        self.bicim = formats.bicim_tespit(
            yol, ayrac=ayrac, kodlama=kodlama, baslik_var=baslik_var,
            tirnak_duyarli=tirnak_duyarli)
        # Kaydırma çubuğu ölçeği için satır sayısı tahminini dosyanın
        # tamamına yayarak iyileştir (~3 MB okur). Dosya zaten bir kayıt
        # sayısı bildiriyorsa (JSON/XML/YAML başlıkları) buna gerek yoktur.
        if not self.bicim.beyan_edilen_kayit:
            formats.ortalama_satir_iyilestir(self.bicim)

        self.index = rowindex.RowIndex(self.bicim.veri_basi, stride=stride)
        # Duraklatılmış başlar: açılışta hiçbir bayt taranmaz.
        # Tarama bloğu, hedefli taramanın ne kadar "aşacağını" da belirler:
        # hedef her blok sonunda denetlenir, yani en fazla bir blok fazla
        # okunur (8 MiB -> 60 GB'lık dosyada ihmal edilebilir).
        self.tarayici = rowindex.IndexScanner(self.bicim, self.index, self.kuyruk,
                                              blok=tarama_blok,
                                              duraklatilmis_basla=True)
        self.yukleyici = loader.WindowLoader(self.bicim, self.index, self.kuyruk,
                                             pencere=pencere, onbellek=onbellek)
        self.arama = None
        self.siralama = None
        # Sıralı görünüm: kayıt numarası listesi. None -> kaynak sırası.
        self.gorunum = None
        # Kullanıcının işaretlediği kayıtlar (bkz. selection.py). Yalnızca
        # kayıt NUMARALARINI tutar; değerler gösterilirken dağınık erişimle
        # (bkz. kayitlar()) getirilir.
        self.secim = selection.SecimKumesi()
        # Tarayıcının çalışması İSTENİYOR mu? Arama bittiğinde tarayıcının
        # sürdürülüp sürdürülmeyeceğini bu belirler: istenmediyse duraklamış
        # kalır ve disk boşta kalır.
        self.indeks_isteniyor = False
        self._kilit = threading.Lock()
        self._kapandi = False

        # Dosyanın oturum sırasında değişmediğini doğrulamak için.
        st = os.stat(yol)
        self._imza = (st.st_size, st.st_mtime_ns)

    # -- yaşam döngüsü -------------------------------------------------
    def baslat(self):
        self.yukleyici.start()
        # Tarayıcı thread'i başlar ama İŞ YAPMAZ; ilk `indeksi_ilerlet()` ya da
        # `indeksi_tamamla()` çağrısına kadar duraklamış bekler.
        self.tarayici.start()

    # -- indeks talebi -------------------------------------------------
    def indeksi_ilerlet(self, hedef_satir):
        """İndeksi YALNIZCA `hedef_satir`'a kadar ilerletir.

        Zaten oraya kadar taranmışsa hiçbir şey yapmaz ve False döner.
        Arama sürüyorsa tarayıcı yine de duraklamış kalır (disk önceliği);
        arama bitince kaldığı yerden sürer.
        """
        if self.index.tamam or self.index.taranan_satir >= hedef_satir:
            return False
        self.indeks_isteniyor = True
        self.tarayici.hedef_satir = hedef_satir
        if not self.arama_calisiyor():
            self.tarayici.surdur()
        return True

    def indeksi_tamamla(self):
        """Dosyanın tamamını indeksler (her kayda anında erişim)."""
        if self.index.tamam:
            return False
        self.indeks_isteniyor = True
        self.tarayici.hedef_satir = None
        if not self.arama_calisiyor():
            self.tarayici.surdur()
        return True

    def indeks_calisiyor(self):
        return (self.tarayici.is_alive() and not self.tarayici.duraklatildi
                and not self.index.tamam)

    def indeks_hedefe_ulasti(self):
        """Tarayıcı hedefine vardı: yeni bir istek gelene dek duraklamış kalsın."""
        self.indeks_isteniyor = False

    def kapat(self):
        with self._kilit:
            if self._kapandi:
                return
            self._kapandi = True
        if self.arama is not None:
            self.arama.iptal()
        if self.siralama is not None:
            self.siralama.iptal()
        self.tarayici.iptal()
        self.yukleyici.dur()
        for t in (self.tarayici, self.yukleyici):
            if t.is_alive():
                t.join(timeout=3.0)

    def dosya_degisti_mi(self):
        """Kaynak dosya oturum başladığından beri değiştiyse True.

        Değişmişse indeks çıpaları artık yanlış konumları gösterir; arayüz
        kullanıcıyı uyarıp yeniden açmasını ister.
        """
        try:
            st = os.stat(self.yol)
        except OSError:
            return True
        return (st.st_size, st.st_mtime_ns) != self._imza

    # -- durum ---------------------------------------------------------
    @property
    def kolonlar(self):
        return self.bicim.kolonlar

    def bilinen_satir(self):
        """Kesin olarak konumlandırılabilen satır sayısı."""
        return self.index.bilinen_satir()

    def toplam_satir(self):
        """Kesin toplam (tarama bittiyse) ya da tahmin."""
        if self.index.tamam:
            return self.index.toplam_satir
        return max(self.index.taranan_satir, self.bicim.tahmini_satir_sayisi())

    def kesin_mi(self):
        return self.index.tamam

    def sayfa_sayisi(self):
        toplam = self.toplam_satir()
        if toplam <= 0:
            return 1
        return (toplam + self.sayfa_satir - 1) // self.sayfa_satir

    def sayfa_no(self, satir):
        return satir // self.sayfa_satir

    # -- görünür satırların temini -------------------------------------
    def satirlar(self, bas, adet, onyukle=2):
        """[bas, bas+adet) aralığı için (satir_no, degerler|None) listesi.

        `degerler` None ise satır henüz yüklenmemiştir: arayüz yer tutucu
        gösterir, pencere geldiğinde OLAY_PENCERE ile haber verilir ve
        arayüz yeniden çizer. Bu çağrı ASLA diske gitmez, ASLA beklemez --
        Tk ana thread'inden güvenle çağrılabilir.

        `onyukle` kadar komşu pencere düşük öncelikle kuyruklanır; kullanıcı
        kaydırdığında veri çoğu zaman hazır olur.
        """
        yk = self.yukleyici
        p = yk.pencere

        ilk_pid = bas // p
        son_pid = (bas + adet - 1) // p if adet > 0 else ilk_pid
        # Yükleyiciye "kullanıcı şu an burayı görüyor" de: bu aralığın
        # dışında kalan bekleyen görünür istekler okunmadan atılacak.
        yk.gorunur_ayarla(range(ilk_pid, son_pid + 1))

        # Kullanıcının BAKTIĞI aralık konumlandırılamıyorsa indeksi oraya
        # kadar ilerlet. Bu, indeks talebinin en doğal tetikleyicisidir:
        # sayfa içinde aşağı kaydırmak da (düğmeyle sayfa değiştirmek gibi)
        # yeni bir bölgeye bakmak demektir. Bu çağrı olmadan, açılıştan sonra
        # ilk çıpa aralığının ötesine kaydıran kullanıcı kalıcı olarak "…"
        # yer tutucuları görürdü.
        if adet > 0 and not self.index.erisilebilir(bas):
            self.indeksi_ilerlet(bas + adet + p)

        # Önce GÖRÜNÜR pencereler
        for pid in range(ilk_pid, son_pid + 1):
            if yk.onbellekten(pid) is None:
                yk.iste(pid, loader.ONCELIK_GORUNUR)

        # Sonra komşular (ön yükleme)
        for d in range(1, onyukle + 1):
            for pid in (ilk_pid - d, son_pid + d):
                if pid >= 0:
                    yk.iste(pid, loader.ONCELIK_ONYUKLEME)

        sonuc = []
        onbellek = {}
        for i in range(adet):
            satir = bas + i
            pid = satir // p
            if pid not in onbellek:
                onbellek[pid] = yk.onbellekten(pid)
            veri = onbellek[pid]
            if veri is None:
                sonuc.append((satir, None))
            else:
                k = satir - pid * p
                sonuc.append((satir, veri[k] if k < len(veri) else None))
        return sonuc

    def sayfa_onyukle(self, sayfa_no):
        """Bir sayfanın BAŞINI arka planda getirir ("sonraki sayfa hazır olsun").

        Sayfanın TAMAMI hiçbir zaman yüklenmez -- 100.000 satır RAM'e
        alınmaz; yalnızca kullanıcının o sayfaya geçince göreceği ilk
        pencereler hazırlanır.
        """
        bas = sayfa_no * self.sayfa_satir
        if bas < 0:
            return
        yk = self.yukleyici
        for k in range(3):
            yk.iste(bas // yk.pencere + k, loader.ONCELIK_ONYUKLEME)

    # -- arama ---------------------------------------------------------
    def arama_calisiyor(self):
        return self.arama is not None and self.arama.is_alive()

    def ara(self, metin, duyarli=False, bas_ofset=None, bas_satir=0,
            en_fazla=5000, regex=False):
        """Arka planda arama başlatır. Çalışan bir arama varsa hata verir."""
        if self.arama_calisiyor():
            raise RuntimeError("Zaten süren bir arama var.")
        desen = finder.Desen(metin, duyarli, self.bicim.kodlama, regex=regex)
        # Disk önceliği: arama sürerken indeks taraması beklesin.
        self.tarayici.duraklat()
        self.arama = finder.SearchJob(
            self.bicim, self.index, desen, self.kuyruk,
            bas_ofset=bas_ofset, bas_satir=bas_satir, en_fazla=en_fazla)
        self.arama.start()
        return desen

    def aramayi_durdur(self):
        if self.arama is not None:
            self.arama.iptal()

    def arama_bitti(self):
        """Arama bittiğinde çağrılır.

        Tarayıcı yalnızca BEKLEYEN bir indeks isteği varsa sürdürülür;
        yoksa duraklamış kalır ve disk boşta kalır.
        """
        if not self.tarayici.is_alive():
            return
        if self.indeks_isteniyor and not self.index.tamam:
            self.tarayici.surdur()

    # -- sıralama ve görünüm -------------------------------------------
    #
    # "Görünüm", sıralı bir KAYIT NUMARASI listesidir. Kaynak sırasında
    # görünüm yoktur (None) ve gösterim konumu = kayıt numarasıdır.
    # Sıralamadan sonra gösterim konumu görünümden okunur; satırlar yine
    # her zamanki yükleyiciyle, dağınık olarak getirilir (ölçülen: kayıt
    # başına 0,4 ms, ekran dolusu ~16 ms).
    def gorunum_var(self):
        return self.gorunum is not None

    def gorunum_ayarla(self, kayit_nolari):
        self.gorunum = list(kayit_nolari)

    def gorunum_temizle(self):
        self.gorunum = None

    def gorunum_uzunlugu(self):
        return len(self.gorunum) if self.gorunum is not None else 0

    def kayitlar(self, kayit_nolari):
        """Dağınık kayıtları getirir: [(kayit_no, degerler|None), ...].

        `satirlar()` gibi ASLA beklemez; gelmemiş olanlar için None döner.
        Ardışık olmadıkları için ön yükleme yapılmaz -- sıralı bir görünümde
        "komşu kayıt" diye bir şey yoktur.
        """
        yk = self.yukleyici
        p = yk.pencere
        nolar = list(kayit_nolari)
        pidler = {no // p for no in nolar}
        yk.gorunur_ayarla(pidler)

        sonuc = []
        onbellek = {}
        for no in nolar:
            pid = no // p
            if pid not in onbellek:
                veri = yk.onbellekten(pid)
                if veri is None:
                    yk.iste(pid, loader.ONCELIK_GORUNUR)
                onbellek[pid] = veri
            veri = onbellek[pid]
            if veri is None:
                sonuc.append((no, None))
            else:
                k = no - pid * p
                sonuc.append((no, veri[k] if k < len(veri) else None))
        return sonuc

    def siralama_calisiyor(self):
        return self.siralama is not None and self.siralama.is_alive()

    def _siralama_baslat(self, **kw):
        if self.siralama_calisiyor():
            raise RuntimeError("Zaten süren bir sıralama var.")
        # Disk önceliği: sıralama da tam bir geçiş yapar, indeks taramasıyla
        # yarıştırmak ikisini de yavaşlatır.
        self.tarayici.duraklat()
        self.siralama = sorting.SiralamaJob(self.bicim, self.index, self.kuyruk,
                                            **kw)
        self.siralama.start()
        return self.siralama

    def sirala_topk(self, kolon, yon, tur, k):
        """Tüm dosyada 'en büyük/en küçük K kayıt'. RAM K ile sabittir."""
        return self._siralama_baslat(kolon=kolon, yon=yon, tur=tur,
                                     kip=sorting.KIP_TUM_DOSYA, k=k)

    def sirala_sayfa(self, kolon, yon, tur, sayfa_bas, sayfa_adet):
        """Tek bir sayfayı kendi içinde sıralar.

        Tarama sayfanın başındaki ÇIPADAN başlar (çıpa sayfadan biraz önce
        olabilir); `kayit_bas`/`kayit_son` sınırları sayfa dışını eler.
        """
        cipa_satir, cipa_ofset = self.index.cipa_bul(sayfa_bas)
        return self._siralama_baslat(
            kolon=kolon, yon=yon, tur=tur, kip=sorting.KIP_ARALIK,
            bas_ofset=cipa_ofset, bas_satir=cipa_satir,
            kayit_bas=sayfa_bas, kayit_son=sayfa_bas + sayfa_adet)

    def sirala_liste(self, kolon, yon, tur, kayit_nolari):
        """Verilen kayıtları (ör. arama sonuçlarını) sıralar."""
        return self._siralama_baslat(kolon=kolon, yon=yon, tur=tur,
                                     kip=sorting.KIP_LISTE,
                                     satir_nolari=kayit_nolari)

    def siralamayi_durdur(self):
        if self.siralama is not None:
            self.siralama.iptal()

    def siralama_bitti(self):
        """Sıralama bitti: indeks taraması (isteniyorsa) diski geri alsın."""
        if not self.tarayici.is_alive():
            return
        if self.indeks_isteniyor and not self.index.tamam:
            self.tarayici.surdur()

    # -- bilgi ---------------------------------------------------------
    def bellek_ozeti(self):
        """Oturumun RAM kullanımının kaba dökümü (gösterim için)."""
        onbellek_satir = self.yukleyici.onbellek_satir_sayisi()
        return {
            "indeks_bayt": self.index.bellek_bayt(),
            "cipa": self.index.cipa_sayisi(),
            "onbellek_pencere": len(self.yukleyici._onbellek),
            "onbellek_satir": onbellek_satir,
            "onbellek_tavan_satir": (self.yukleyici.onbellek_tavani
                                     * self.yukleyici.pencere),
        }
