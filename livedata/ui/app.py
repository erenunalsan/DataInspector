"""livedata ana penceresi.

Ekran, Office uygulamalarındaki "şerit" (ribbon) düzenini izler:

  1. Hızlı erişim  -- dosya yolu + Dosya Seç / Aç / Kapat / 🌐 Web Arayüzü
                      (her zaman görünür; "Web Arayüzü" aynı dosyayı tarayıcıda
                      açar -- bkz. LIVEDATA_WEB.md, gerekirse sunucuyu kendisi
                      arka planda başlatır)
  2. Şerit         -- sekmeli araç çubuğu; yalnızca SEÇİLİ sekmenin düğmeleri
                      görünür: Dosya (biçim seçenekleri) · Ana Sayfa (gezinme,
                      satıra git, Base64, indeks) · Arama · Sıralama · Seçim.
                      Ctrl+1..5 sekmeleri doğrudan açar.
  3. Tablo         -- sanal tablo (yalnızca görünen satırlar gerçeklenir)
  4. Konsol / Arama sonuçları -- sekmeli alt panel
  5. Durum çubuğu  -- indeks taraması, arama ilerlemesi ve RAM/disk özeti

Şerit düzeninden önce beş bölüm (Dosya/Gezinme/Arama/Sıralama/Seçim) alt alta
dizili ve hepsi aynı anda görünürdü; bu, tabloya kalan yeri daraltıyor ve
kullanıcıya o an ihtiyaç duymadığı onlarca kontrolü birden gösteriyordu.

Tkinter kuralı: TÜM widget güncellemeleri ana thread'dedir. Arka plan
thread'leri (indeks tarayıcı, pencere yükleyici, arama) sonuçlarını bir
`queue.Queue`'ya yazar; ana thread bunu `after()` ile düzenli aralıklarla
boşaltır. Bu yüzden uzun işlemler ekranı hiçbir zaman kilitlemez.
"""
import os
import queue
import subprocess
import sys
import threading
import time
import tkinter as tk
import urllib.parse
import urllib.request
import webbrowser
from tkinter import filedialog, messagebox, ttk

import sv_ttk

from .. import finder, loader, rowindex, selection, son_dosyalar, sorting, units
from ..formats import BicimHatasi
from ..session import VeriOturumu
from . import renkler
from .b64dialog import Base64Penceresi
from .console import KonsolAlani
from .selectionwindow import SeciliVerilerPenceresi
from .virtualtable import SanalTablo

KUYRUK_ARALIGI = 30        # ms: olay kuyruğu boşaltma sıklığı
DURUM_ARALIGI = 700        # ms: durum satırı yenileme sıklığı
KONSOL_ILERLEME_ARALIGI = 3.0   # sn: indeks ilerlemesini konsola yazma sıklığı
EN_FAZLA_SONUC = 5000
KONSOL_YUKSEKLIGI = 165   # px: alt panelin (konsol/sonuçlar) varsayılan payı

# Web arayüzü (Django, bkz. LIVEDATA_WEB.md) -- "Web Arayüzü" düğmesi bu
# adreste bir sunucu bulur ya da başlatır.
WEB_PORT = 8000
WEB_URL = f"http://127.0.0.1:{WEB_PORT}/"
WEB_BASLAMA_ZAMAN_ASIMI = 8.0  # sn -- sunucunun ayağa kalkmasını bekleme üst sınırı

# Sıralama kapsamları. Üçü de bir PERMÜTASYON gerektirmez; bu yüzden
# "diske hiçbir şey yazma" kuralı bozulmadan uygulanabilirler (bkz. sorting).
KAPSAM_SAYFA = "Bu sayfa (tam sıralama)"
KAPSAM_TUM = "Tüm dosya (en iyi N)"
KAPSAM_ARAMA = "Arama sonuçları"

AYRAC_SECENEK = [("Otomatik", None), ("; (noktalı virgül)", ";"),
                 (", (virgül)", ","), ("\\t (sekme)", "\t"), ("| (dik çizgi)", "|")]
KODLAMA_SECENEK = ["Otomatik", "utf-8", "utf-8-sig", "cp1254", "latin-1"]
BASLIK_SECENEK = [("Otomatik", None), ("Var", True), ("Yok", False)]


class LiveDataPenceresi:
    def __init__(self, baslangic_yolu=None, otomatik_ac=False):
        self.root = tk.Tk()
        self.root.title("livedata — büyük veri görüntüleyici (CSV · JSON · XML · YAML)")
        self.root.minsize(1000, 600)
        self._simgeyi_uygula()
        self._temayi_uygula()
        self._pencereyi_ekrana_sigdir()

        self.kuyruk = queue.Queue()
        self.oturum = None
        self.sayfa = 0
        self.eslesmeler = []
        self.eslesme_idx = -1
        self.bekleyen_git = None
        self.arama_deseni = None

        self._son_konsol_ilerleme = 0.0
        self._pencere_sayaci = 0
        self._pencere_sure = 0.0
        self._son_pencere_ozeti = 0.0
        self._acilis_zamani = None
        self._web_surec = None    # Django sunucusu için subprocess.Popen (bkz. _web_arayuzunu_ac)
        self._dosya_degisti_uyarildi = False
        self.gorunur_kolonlar = None   # None = tüm kolonlar görünür; aksi hâlde indeks listesi

        self._arayuz_kur()
        self.root.protocol("WM_DELETE_WINDOW", self._cikis)
        self.root.after(KUYRUK_ARALIGI, self._kuyrugu_isle)
        self.root.after(DURUM_ARALIGI, self._durum_dongusu)

        self._acilis_mesaji()
        if baslangic_yolu and os.path.exists(baslangic_yolu):
            self.yol_degisken.set(baslangic_yolu)
            if otomatik_ac:
                # Pencere çizildikten sonra aç ki ilk kare hemen görünsün.
                self.root.after(60, self._ac)
            else:
                self.konsol.yaz(
                    f"Hazır dosya yolu dolduruldu: {baslangic_yolu} "
                    "— açmak için 'Aç' düğmesine basın.", "bilgi")

    # ==================================================================
    # Görünüm: pencere ikonu + açık/koyu tema (sv-ttk)
    #
    # Varsayılan ttk teması (Windows'ta genelde 'vista'/'winnative') düz,
    # gri kutucuklardan oluşur. sv-ttk tek satırlık bir çağrıyla tüm
    # widget'ları Windows 11 Fluent görünümüne (yuvarlatılmış köşeler,
    # gerçek koyu tema) kavuşturur. Standart ttk widget'ları dışında bu
    # projenin KENDİ sabit renkleri de vardı (tablo satır vurguları, konsol
    # seviye renkleri, birkaç durum etiketi) -- bunlar `renkler.py`
    # üzerinden tema-duyarlı hâle getirildi; aksi hâlde koyu temada ör.
    # lacivert bir etiket görünmez, açık sarı bir tablo satırı göz yakardı.
    # ==================================================================
    def _simgeyi_uygula(self):
        # PyInstaller ile TEK DOSYA (--onefile) paketlendiğinde, bu modülün
        # KENDİ __file__'ı değil `sys._MEIPASS` (çalışma anında açılan geçici
        # dizin) kullanılmalıdır -- aksi hâlde paketlenmiş .exe'de ikon hiç
        # bulunamaz (bkz. tools/exe_paketle.py / PyInstaller belgeleri).
        taban = getattr(sys, "_MEIPASS", os.path.dirname(os.path.dirname(
            os.path.dirname(os.path.abspath(__file__)))))
        ikon = os.path.join(taban, "livedata", "ui", "assets", "icon.ico")
        if not os.path.isfile(ikon):
            # Paketlenmemiş (kaynak) çalıştırmada MEIPASS yok; bu dosyanın
            # kendi yanındaki assets/ dizinine düş.
            ikon = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "assets", "icon.ico")
        try:
            self.root.iconbitmap(ikon)
        except tk.TclError:
            pass  # ikon dosyası yoksa (ör. taşınmış kurulum) sessizce geç

    def _tema_tercihi(self):
        """Windows sistem koyu modunu algılamaya çalışır; olmazsa açık tema."""
        try:
            import winreg
            anahtar = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize")
            deger, _ = winreg.QueryValueEx(anahtar, "AppsUseLightTheme")
            return "light" if deger else "dark"
        except Exception:
            return "light"

    def _temayi_uygula(self):
        try:
            sv_ttk.set_theme(self._tema_tercihi())
        except Exception:
            pass

    def _temayi_degistir(self):
        """🌗 düğmesi: açık/koyu temayı değiştirir ve BU projenin kendi
        (sv-ttk'nin bilmediği) renklerini -- konsol, tablo satırları, birkaç
        durum etiketi -- tazeler."""
        sv_ttk.toggle_theme()
        self.tema_dugme.configure(
            text="☀ Açık Tema" if renkler.koyu_mu() else "🌙 Koyu Tema")
        self.konsol.tema_yenile()
        self.tablo.tema_yenile()
        self.tablo.yenile()
        self.bicim_etiket.configure(foreground=renkler.vurgu())
        self.git_notu.configure(foreground=renkler.uyari())
        self.durum_etiket.configure(foreground=renkler.islem_rengi())
        self._kapsam_degisti()

    def _pencereyi_ekrana_sigdir(self):
        """Pencereyi çalışma alanına oturtur ve büyütülmüş (zoomed) açar.

        `winfo_screenheight()` GÖREV ÇUBUĞUNU da içeren tam ekran yüksekliğini
        verir; ondan türetilen bir boyut, pencerenin altını (ilerleme
        çubukları ve durum satırını) görev çubuğunun arkasında bırakıyordu.
        Büyütülmüş açmak bu hesabı işletim sistemine bırakır: pencere her
        zaman gerçek çalışma alanına tam oturur. Kullanıcı normal boyuta
        döndürürse aşağıdaki geometri kullanılır.
        """
        ekran_g = self.root.winfo_screenwidth()
        ekran_y = self.root.winfo_screenheight()
        g = min(1500, max(1000, ekran_g - 120))
        # Görev çubuğu + pencere çerçevesi payı: normal boyutta da sığsın.
        y = min(950, max(600, ekran_y - 170))
        x = max(0, (ekran_g - g) // 2)
        self.root.geometry(f"{g}x{y}+{x}+20")
        try:
            self.root.state("zoomed")
        except tk.TclError:
            # Windows dışı: 'zoomed' desteklenmeyebilir, normal boyut kalır.
            pass

    # ==================================================================
    # Arayüz kurulumu — Office tarzı "şerit" (ribbon): üstte her zaman
    # görünen ince bir hızlı erişim çubuğu (dosya aç/kapat), altında
    # sekmeli bir şerit (Dosya / Ana Sayfa / Arama / Sıralama / Seçim) --
    # o an seçili sekmenin düğmeleri görünür, diğerleri gizlenir.
    #
    # Önceki sürümde beş ayrı LabelFrame art arda dizilip HEPSİ her an
    # ekranda duruyordu; bu, tabloyu görmeden önce ~200px dikey alan
    # tüketiyor ve kullanıcıya aynı anda ihtiyacı olmayan onlarca kontrolü
    # birden gösteriyordu. Şerit, aynı düğmeleri gruplar hâlinde ama
    # yalnızca ilgili sekme açıkken gösterir.
    # ==================================================================
    def _arayuz_kur(self):
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(2, weight=1)

        self._hizli_erisim_bolgesi()
        self._serit_kur()
        self._govde_bolgesi()
        self._ilerleme_bolgesi()
        self._kontrolleri_ayarla(acik=False)

    # -- şerit yardımcıları -----------------------------------------------
    def _grup(self, parent, baslik):
        """Bir şerit grubu oluşturur: üstte kontroller için bir çerçeve,
        altta küçük gri bir başlık (Office'teki grup adları gibi) ve
        sağında ince bir ayraç. Düğmeler dönen çerçeveye paketlenmelidir.
        """
        dis = ttk.Frame(parent)
        dis.pack(side="left", fill="y")
        ust = ttk.Frame(dis)
        ust.pack(side="top", fill="both", expand=True, pady=(1, 0))
        ttk.Label(dis, text=baslik, foreground="#9a9a9a",
                  font=("Segoe UI", 8)).pack(side="bottom", pady=(3, 1))
        ttk.Separator(parent, orient="vertical").pack(side="left", fill="y",
                                                       padx=8, pady=3)
        return ust

    def _hizli_erisim_bolgesi(self):
        """Sekmeden bağımsız, her zaman görünen ince şerit: dosya aç/kapat.

        Office'teki "Hızlı Erişim Araç Çubuğu" karşılığı -- en sık kullanılan
        eylem (dosya açma) hangi sekmede olunursa olunsun elin altındadır.
        """
        cerceve = ttk.Frame(self.root, padding=(8, 6, 8, 4))
        cerceve.grid(row=0, column=0, sticky="ew")
        cerceve.columnconfigure(2, weight=1)

        ttk.Button(cerceve, text="📁 Dosya Seç…", width=14,
                   command=self._dosya_sec).grid(row=0, column=0, padx=(0, 2))
        self.son_dosyalar_dugme = ttk.Button(cerceve, text="🕘", width=3,
                                             command=self._son_dosyalari_goster)
        self.son_dosyalar_dugme.grid(row=0, column=1, padx=(0, 6))
        self.yol_degisken = tk.StringVar()
        giris = ttk.Entry(cerceve, textvariable=self.yol_degisken)
        giris.grid(row=0, column=2, sticky="ew")
        giris.bind("<Return>", lambda e: self._ac())

        self.ac_dugme = ttk.Button(cerceve, text="▶  Aç", width=8, command=self._ac)
        self.ac_dugme.grid(row=0, column=3, padx=(6, 2))
        self.kapat_dugme = ttk.Button(cerceve, text="✕  Kapat", width=8,
                                      command=self._kapat)
        self.kapat_dugme.grid(row=0, column=4, padx=2)

        self.bicim_etiket = ttk.Label(cerceve, text="", foreground=renkler.vurgu())
        self.bicim_etiket.grid(row=0, column=5, padx=(12, 0))

        self.web_ac_dugme = ttk.Button(cerceve, text="🌐 Web Arayüzü", width=15,
                                       command=self._web_arayuzunu_ac)
        self.web_ac_dugme.grid(row=0, column=6, padx=(12, 0))

        self.tema_dugme = ttk.Button(
            cerceve, width=13,
            text="☀ Açık Tema" if renkler.koyu_mu() else "🌙 Koyu Tema",
            command=self._temayi_degistir)
        self.tema_dugme.grid(row=0, column=7, padx=(6, 0))

    def _serit_kur(self):
        self.serit = ttk.Notebook(self.root)
        self.serit.grid(row=1, column=0, sticky="ew", padx=8, pady=(0, 3))

        self._sekme_dosya = ttk.Frame(self.serit, padding=(8, 4))
        self._sekme_ana = ttk.Frame(self.serit, padding=(8, 4))
        self._sekme_arama = ttk.Frame(self.serit, padding=(8, 4))
        self._sekme_siralama = ttk.Frame(self.serit, padding=(8, 4))
        self._sekme_secim = ttk.Frame(self.serit, padding=(8, 4))

        self.serit.add(self._sekme_dosya, text="  Dosya  ")
        self.serit.add(self._sekme_ana, text="  Ana Sayfa  ")
        self.serit.add(self._sekme_arama, text="  Arama  ")
        self.serit.add(self._sekme_siralama, text="  Sıralama  ")
        self.serit.add(self._sekme_secim, text="  Seçim  ")

        # Klavye kısayolları: Ctrl+1..5 doğrudan ilgili sekmeyi açar.
        # (ttk'nin enable_traversal'ı Ctrl+Tab'ı PENCEREYE bağlar; bu
        # pencerede alttaki Konsol/Arama sonuçları için ikinci bir Notebook
        # daha olduğundan hangisinin döneceği odağa göre değişiyordu --
        # doğrudan atama belirsizlik bırakmaz.)
        for i, sekme in enumerate(
                (self._sekme_dosya, self._sekme_ana, self._sekme_arama,
                 self._sekme_siralama, self._sekme_secim), start=1):
            self.root.bind(f"<Control-Key-{i}>",
                          lambda e, s=sekme: self.serit.select(s))

        self._dosya_bolgesi()
        self._gezinme_bolgesi()
        self._arama_bolgesi()
        self._siralama_bolgesi()
        self._secim_bolgesi()
        self.serit.select(self._sekme_dosya)

    def _dosya_bolgesi(self):
        cerceve = self._sekme_dosya

        grup = self._grup(cerceve, "Ayırıcı / Kodlama")
        ttk.Label(grup, text="Ayraç:").pack(side="left")
        self.ayrac_degisken = tk.StringVar(value=AYRAC_SECENEK[0][0])
        ttk.Combobox(grup, textvariable=self.ayrac_degisken, width=17,
                     state="readonly",
                     values=[a[0] for a in AYRAC_SECENEK]).pack(side="left", padx=(3, 10))
        ttk.Label(grup, text="Kodlama:").pack(side="left")
        self.kodlama_degisken = tk.StringVar(value=KODLAMA_SECENEK[0])
        ttk.Combobox(grup, textvariable=self.kodlama_degisken, width=11,
                     state="readonly",
                     values=KODLAMA_SECENEK).pack(side="left", padx=(3, 0))

        grup2 = self._grup(cerceve, "Başlık / Tırnak")
        ttk.Label(grup2, text="İlk satır başlık:").pack(side="left")
        self.baslik_degisken = tk.StringVar(value=BASLIK_SECENEK[0][0])
        ttk.Combobox(grup2, textvariable=self.baslik_degisken, width=9,
                     state="readonly",
                     values=[b[0] for b in BASLIK_SECENEK]).pack(side="left", padx=(3, 10))
        self.tirnak_degisken = tk.StringVar(value="Otomatik")
        ttk.Label(grup2, text="Tırnak:").pack(side="left")
        ttk.Combobox(grup2, textvariable=self.tirnak_degisken, width=11,
                     state="readonly",
                     values=["Otomatik", "Duyarlı", "Duyarsız (hızlı)"]
                     ).pack(side="left", padx=(3, 0))

        ttk.Label(cerceve, foreground="#8a8a8a",
                 text="Bu seçenekler yalnızca CSV içindir ve dosyayı yukarıdaki "
                      "'Aç' ile açmadan ÖNCE ayarlanmalıdır."
                 ).pack(side="left", padx=(6, 0))

    def _gezinme_bolgesi(self):
        cerceve = self._sekme_ana

        grup = self._grup(cerceve, "Sayfa")
        self.onceki_dugme = ttk.Button(grup, text="◀", width=3,
                                       command=self._onceki_sayfa)
        self.onceki_dugme.pack(side="left")
        self.sonraki_dugme = ttk.Button(grup, text="▶", width=3,
                                        command=self._sonraki_sayfa)
        self.sonraki_dugme.pack(side="left", padx=(2, 10))
        self.sayfa_etiket = ttk.Label(grup, text="Sayfa —", width=42)
        self.sayfa_etiket.pack(side="left")

        grup2 = self._grup(cerceve, "Satıra git")
        self.git_degisken = tk.StringVar()
        git_giris = ttk.Entry(grup2, textvariable=self.git_degisken, width=14)
        git_giris.pack(side="left", padx=(0, 4))
        git_giris.bind("<Return>", lambda e: self._git())
        self.git_dugme = ttk.Button(grup2, text="Git", width=6, command=self._git)
        self.git_dugme.pack(side="left")
        self.taban_degisken = tk.BooleanVar(value=False)
        ttk.Checkbutton(grup2, text="1'den başlat", variable=self.taban_degisken,
                        command=self._taban_degisti).pack(side="left", padx=(10, 0))

        grup3 = self._grup(cerceve, "Araçlar")
        self.b64_dugme = ttk.Button(grup3, text="Base64 Çöz", width=13,
                                    command=self._base64_coz)
        self.b64_dugme.pack(side="left")
        self.indeks_dugme = ttk.Button(grup3, text="Tam indeksle", width=14,
                                       command=self._indeksi_tamamla)
        self.indeks_dugme.pack(side="left", padx=(4, 0))
        self.kolonlar_dugme = ttk.Button(grup3, text="Kolonlar…", width=11,
                                         command=self._kolon_secici_ac)
        self.kolonlar_dugme.pack(side="left", padx=(4, 0))

        self.git_notu = ttk.Label(cerceve, text="", foreground=renkler.uyari())
        self.git_notu.pack(side="left", padx=(6, 0))

    def _arama_bolgesi(self):
        cerceve = self._sekme_arama

        grup = self._grup(cerceve, "Ara")
        ttk.Label(grup, text="Aranan metin:").pack(side="left")
        self.arama_degisken = tk.StringVar()
        arama_giris = ttk.Entry(grup, textvariable=self.arama_degisken, width=38)
        arama_giris.pack(side="left", padx=4)
        arama_giris.bind("<Return>", lambda e: self._ara())
        self.duyarli_degisken = tk.BooleanVar(value=False)
        ttk.Checkbutton(grup, text="Büyük/küçük harfe duyarlı",
                        variable=self.duyarli_degisken).pack(side="left", padx=(4, 8))
        self.regex_degisken = tk.BooleanVar(value=False)
        ttk.Checkbutton(grup, text="Regex (düzenli ifade)",
                        variable=self.regex_degisken).pack(side="left", padx=(0, 8))
        self.ara_dugme = ttk.Button(grup, text="Ara", width=8, command=self._ara)
        self.ara_dugme.pack(side="left", padx=2)
        self.arama_dur_dugme = ttk.Button(grup, text="Durdur", width=8,
                                          command=self._arama_durdur)
        self.arama_dur_dugme.pack(side="left", padx=2)

        grup2 = self._grup(cerceve, "Eşleşmeler")
        self.eslesme_onceki = ttk.Button(grup2, text="◀", width=3,
                                         command=lambda: self._eslesme_gez(-1))
        self.eslesme_onceki.pack(side="left")
        self.eslesme_sonraki = ttk.Button(grup2, text="▶", width=3,
                                          command=lambda: self._eslesme_gez(1))
        self.eslesme_sonraki.pack(side="left", padx=(2, 6))
        self.eslesme_etiket = ttk.Label(grup2, text="eşleşme yok", width=38)
        self.eslesme_etiket.pack(side="left")

    def _siralama_bolgesi(self):
        cerceve = self._sekme_siralama

        grup = self._grup(cerceve, "Kolon / Yön / Tür")
        ttk.Label(grup, text="Kolon:").pack(side="left")
        self.sirala_kolon = tk.StringVar()
        self.sirala_kolon_kutu = ttk.Combobox(grup, textvariable=self.sirala_kolon,
                                              width=16, state="readonly", values=[])
        self.sirala_kolon_kutu.pack(side="left", padx=(3, 8))
        self.sirala_yon = tk.StringVar(value="Azalan (Z→A, 9→0)")
        ttk.Combobox(grup, textvariable=self.sirala_yon, width=17,
                     state="readonly",
                     values=["Azalan (Z→A, 9→0)", "Artan (A→Z, 0→9)"]
                     ).pack(side="left", padx=(3, 8))
        self.sirala_tur = tk.StringVar(value="Metin")
        ttk.Combobox(grup, textvariable=self.sirala_tur, width=7,
                     state="readonly", values=["Metin", "Sayı"]
                     ).pack(side="left", padx=(3, 0))

        grup2 = self._grup(cerceve, "Kapsam")
        self.sirala_kapsam = tk.StringVar(value=KAPSAM_SAYFA)
        kapsam_kutu = ttk.Combobox(grup2, textvariable=self.sirala_kapsam,
                                   width=24, state="readonly",
                                   values=[KAPSAM_SAYFA, KAPSAM_TUM, KAPSAM_ARAMA])
        kapsam_kutu.pack(side="left", padx=(0, 8))
        kapsam_kutu.bind("<<ComboboxSelected>>", lambda e: self._kapsam_degisti())
        self.sirala_k_etiket = ttk.Label(grup2, text="En iyi:")
        self.sirala_k_etiket.pack(side="left")
        self.sirala_k = tk.StringVar(value="10000")
        self.sirala_k_giris = ttk.Entry(grup2, textvariable=self.sirala_k, width=8)
        self.sirala_k_giris.pack(side="left", padx=(3, 0))

        grup3 = self._grup(cerceve, "Eylemler")
        self.sirala_dugme = ttk.Button(grup3, text="Sırala", width=9,
                                       command=self._sirala)
        self.sirala_dugme.pack(side="left", padx=2)
        self.sirala_dur_dugme = ttk.Button(grup3, text="Durdur", width=8,
                                           command=self._siralamayi_durdur)
        self.sirala_dur_dugme.pack(side="left", padx=2)
        self.sirala_sifirla_dugme = ttk.Button(grup3, text="Kaynak sırasına dön",
                                               width=20,
                                               command=self._siralamayi_sifirla)
        self.sirala_sifirla_dugme.pack(side="left", padx=(6, 0))
        self._kapsam_degisti()

    def _secim_bolgesi(self):
        cerceve = self._sekme_secim

        grup = self._grup(cerceve, "Seçim")
        self.secim_sayfa_dugme = ttk.Button(grup, text="Sayfayı Seç",
                                            width=12, command=self._sayfayi_sec)
        self.secim_sayfa_dugme.pack(side="left")
        self.secim_temizle_dugme = ttk.Button(grup, text="Seçimi Temizle",
                                              width=15,
                                              command=self._secimi_temizle)
        self.secim_temizle_dugme.pack(side="left", padx=(4, 0))

        grup2 = self._grup(cerceve, "Durum")
        self.secim_etiket = ttk.Label(grup2, text="Seçili: 0 kayıt", width=20)
        self.secim_etiket.pack(side="left")
        self.secim_goster_dugme = ttk.Button(
            grup2, text="Seçilenleri Göster…", width=20,
            command=self._secilenleri_goster)
        self.secim_goster_dugme.pack(side="left", padx=(8, 0))

        ttk.Label(cerceve, foreground="#8a8a8a",
                 text="İpucu: satırın solundaki kutucuğu (ya da Boşluk "
                      "tuşunu) kullanarak kayıtları işaretleyin. İşaretlenen "
                      "kayıtlar sayfa/sıralama değişse de kalıcıdır."
                 ).pack(side="left", padx=(6, 0))

    def _govde_bolgesi(self):
        bolme = ttk.PanedWindow(self.root, orient="vertical")
        bolme.grid(row=2, column=0, sticky="nsew", padx=8, pady=3)

        self.tablo = SanalTablo(bolme, saglayici=self._satir_saglayici,
                                sinir_asildi=self._sinir_asildi,
                                secim_degisti=self._secim_degisti,
                                secili_mi=self._secili_mi,
                                secim_degistir=self._secim_degistir)
        self.tablo.tree.bind("<Double-1>", lambda e: self._detay_goster())
        bolme.add(self.tablo, weight=4)

        alt = ttk.Notebook(bolme)
        self.konsol = KonsolAlani(alt, padding=(6, 4))
        alt.add(self.konsol, text="Konsol")

        sonuc_cerceve = ttk.Frame(alt, padding=(6, 4))
        self.sonuc_tablo = ttk.Treeview(
            sonuc_cerceve, show="headings", selectmode="browse",
            columns=("satir", "onizleme"), height=4)
        self.sonuc_tablo.heading("satir", text="Satır #")
        self.sonuc_tablo.column("satir", width=120, anchor="e", stretch=False)
        self.sonuc_tablo.heading("onizleme", text="Satır önizlemesi")
        self.sonuc_tablo.column("onizleme", width=1100, anchor="w")
        sk = ttk.Scrollbar(sonuc_cerceve, orient="vertical",
                           command=self.sonuc_tablo.yview)
        self.sonuc_tablo.configure(yscrollcommand=sk.set)
        self.sonuc_tablo.grid(row=0, column=0, sticky="nsew")
        sk.grid(row=0, column=1, sticky="ns")
        sonuc_cerceve.rowconfigure(0, weight=1)
        sonuc_cerceve.columnconfigure(0, weight=1)
        self.sonuc_tablo.bind("<<TreeviewSelect>>", self._sonuc_secildi)
        alt.add(sonuc_cerceve, text="Arama sonuçları")
        self.alt_defter = alt
        bolme.add(alt, weight=1)
        self.bolme = bolme
        # Bölme çizgisi, panolar boyutlandıktan SONRA konumlandırılmalı;
        # ttk ilk yerleşimde panolara istedikleri boyutu verir ve konsol
        # tabloya göre gereğinden fazla yer kaplar.
        self.root.after(250, self._bolme_dengele)

    def _bolme_dengele(self):
        """Tablo/konsol bölme çizgisini konsola sabit bir pay bırakacak
        şekilde ayarlar; kalan tüm yükseklik tabloya gider (daha çok satır)."""
        try:
            yukseklik = self.bolme.winfo_height()
            if yukseklik > 320:
                self.bolme.sashpos(0, max(180, yukseklik - KONSOL_YUKSEKLIGI))
        except tk.TclError:
            pass

    def _ilerleme_bolgesi(self):
        cerceve = ttk.Frame(self.root, padding=(10, 4))
        cerceve.grid(row=3, column=0, sticky="ew", padx=8, pady=(0, 6))
        cerceve.columnconfigure(2, weight=1)

        ttk.Label(cerceve, text="İndeks taraması:", width=16).grid(row=0, column=0,
                                                                   sticky="w")
        self.indeks_cubuk = ttk.Progressbar(cerceve, length=260, maximum=1000)
        self.indeks_cubuk.grid(row=0, column=1, padx=6)
        self.indeks_etiket = ttk.Label(cerceve, text="— (istek üzerine)",
                                       anchor="w")
        self.indeks_etiket.grid(row=0, column=2, sticky="ew")

        self.islem_etiket = ttk.Label(cerceve, text="Arama:", width=16)
        self.islem_etiket.grid(row=1, column=0, sticky="w")
        self.arama_cubuk = ttk.Progressbar(cerceve, length=260, maximum=1000)
        self.arama_cubuk.grid(row=1, column=1, padx=6, pady=2)
        self.arama_ilerleme_etiket = ttk.Label(cerceve, text="—", anchor="w")
        self.arama_ilerleme_etiket.grid(row=1, column=2, sticky="ew")

        self.durum_etiket = ttk.Label(cerceve, text="Dosya açılmadı.",
                                      anchor="w", foreground=renkler.islem_rengi())
        self.durum_etiket.grid(row=2, column=0, columnspan=3, sticky="ew",
                               pady=(4, 0))

    def _acilis_mesaji(self):
        self.konsol.bolum("livedata")
        self.konsol.yaz("Büyük CSV / JSON / XML / YAML dosyalarını KAYNAĞINDAN, "
                        "yerinde inceleyen görüntüleyici.", "bilgi")
        self.konsol.yaz("Çalışma ilkeleri: (1) diske hiçbir şey yazılmaz — ara "
                        "dosya/önbellek oluşturulmaz; (2) dosya belleğe "
                        "alınmaz — yalnızca ekranda görünen satırlar okunur; "
                        "(3) tüm uzun işlemler arka planda çalışır, arayüz "
                        "kilitlenmez.", "bilgi")
        self.konsol.yaz(
            "Dört biçim de aynı motorla açılır: kayıtlar satır satır okunur, "
            "her satır kendi biçiminin kurallarıyla (CSV ayraç, JSON/YAML "
            "çözümleme, XML element) hücrelere çevrilir. Gezinme, satıra "
            "gitme ve arama biçimden bağımsızdır.", "bilgi")
        self.konsol.yaz("Başlamak için 'Dosya Seç…' ile bir dosya seçip 'Aç' "
                        "düğmesine basın.", "bilgi")
        self.konsol.yaz(
            "Araçlar üstteki şerit sekmelerindedir: Dosya · Ana Sayfa · Arama "
            "· Sıralama · Seçim. Sekmeler arasında Ctrl+1 … Ctrl+5 ile de "
            "geçebilirsiniz.", "bilgi")

    # ==================================================================
    # Dosya açma / kapama
    # ==================================================================
    def _dosya_sec(self):
        yol = filedialog.askopenfilename(
            title="Veri dosyası seçin (CSV / JSON / XML / YAML)",
            filetypes=[
                ("Desteklenen veri dosyaları",
                 "*.csv *.tsv *.txt *.json *.jsonl *.ndjson *.xml *.yaml *.yml"),
                ("CSV", "*.csv *.tsv *.txt"),
                ("JSON / JSON Lines", "*.json *.jsonl *.ndjson"),
                ("XML", "*.xml"),
                ("YAML", "*.yaml *.yml"),
                ("Tüm dosyalar", "*.*")])
        if yol:
            self.yol_degisken.set(yol)
            try:
                boyut = os.path.getsize(yol)
                self.konsol.yaz(f"Dosya seçildi: {yol}  ({units.bayt(boyut)})",
                                "bilgi")
            except OSError as e:
                self.konsol.yaz(f"Dosya bilgisi okunamadı: {e}", "hata")

    def _son_dosyalari_goster(self):
        """🕘 düğmesi: son açılan dosyaların bir açılır menüsünü gösterir."""
        liste = son_dosyalar.oku()
        menu = tk.Menu(self.root, tearoff=0)
        if not liste:
            menu.add_command(label="(henüz dosya açılmadı)", state="disabled")
        else:
            for yol in liste:
                gosterim = yol if len(yol) <= 70 else "…" + yol[-67:]
                menu.add_command(
                    label=gosterim,
                    command=lambda y=yol: self._son_dosyadan_ac(y))
            menu.add_separator()
            menu.add_command(label="Listeyi temizle",
                             command=self._son_dosyalari_temizle)
        x = self.son_dosyalar_dugme.winfo_rootx()
        y = self.son_dosyalar_dugme.winfo_rooty() + self.son_dosyalar_dugme.winfo_height()
        try:
            menu.tk_popup(x, y)
        finally:
            menu.grab_release()

    def _son_dosyadan_ac(self, yol):
        self.yol_degisken.set(yol)
        self._ac()

    def _son_dosyalari_temizle(self):
        son_dosyalar.temizle()
        self.konsol.yaz("Son dosyalar listesi temizlendi.", "islem")

    def _secenekleri_oku(self):
        ayrac = dict(AYRAC_SECENEK)[self.ayrac_degisken.get()]
        kodlama = self.kodlama_degisken.get()
        kodlama = None if kodlama == "Otomatik" else kodlama
        baslik = dict(BASLIK_SECENEK)[self.baslik_degisken.get()]
        t = self.tirnak_degisken.get()
        tirnak = None if t == "Otomatik" else (t == "Duyarlı")
        return ayrac, kodlama, baslik, tirnak

    def _ac(self):
        yol = self.yol_degisken.get().strip().strip('"')
        if not yol:
            messagebox.showwarning("Dosya yok", "Önce bir veri dosyası seçin.")
            return
        if not os.path.isfile(yol):
            messagebox.showerror("Bulunamadı", f"Dosya bulunamadı:\n{yol}")
            return
        if self.oturum is not None:
            self._kapat()
        self._dosya_degisti_uyarildi = False
        self.gorunur_kolonlar = None

        ayrac, kodlama, baslik, tirnak = self._secenekleri_oku()
        self.konsol.bolum("Dosya açılıyor")
        t0 = time.perf_counter()
        try:
            oturum = VeriOturumu(yol, self.kuyruk, ayrac=ayrac, kodlama=kodlama,
                               baslik_var=baslik, tirnak_duyarli=tirnak)
        except (BicimHatasi, OSError, ValueError) as e:
            self.konsol.yaz(f"Açılamadı: {e}", "hata")
            messagebox.showerror("Açılamadı", str(e))
            return
        tespit_sure = time.perf_counter() - t0

        self.oturum = oturum
        self.sayfa = 0
        self.eslesmeler = []
        self.eslesme_idx = -1
        self._acilis_zamani = time.perf_counter()
        self._sonuclari_temizle()
        self._secim_etiketini_guncelle()

        b = oturum.bicim
        self.konsol.yaz(f"Dosya: {yol}", "tamam", kalin=True)
        self.konsol.yaz(f"Boyut: {units.bayt(b.boyut)} "
                        f"({units.sayi(b.boyut)} bayt)", "bilgi")
        self.konsol.yaz(f"Biçim tespiti {units.sure(tespit_sure)} sürdü → {b.ozet()}",
                        "sure")
        self.konsol.yaz(f"Kolonlar ({len(b.kolonlar)}): "
                        + ", ".join(b.kolonlar[:12])
                        + (" …" if len(b.kolonlar) > 12 else ""), "bilgi")
        if b.tur == "csv" and not getattr(b, "baslik_var", True):
            self.konsol.yaz("Başlık satırı bulunmadı; kolon adları 'Kolon N' "
                            "olarak üretildi. Yanlışsa 'İlk satır başlık: Var' "
                            "seçip yeniden açın.", "uyari")
        if b.veri_basi or b.veri_sonu != b.boyut:
            self.konsol.yaz(
                f"Kayıt bölgesi: bayt {units.sayi(b.veri_basi)} – "
                f"{units.sayi(b.veri_sonu)} ({units.bayt(b.veri_bayt)}). "
                "Baştaki başlık ve sondaki kapanış satırları kayıt sayılmaz.",
                "bilgi")
        if b.beyan_edilen_kayit:
            self.konsol.yaz(
                f"Dosya başlığı {units.sayi(b.beyan_edilen_kayit)} kayıt "
                "bildiriyor. Bu değer ölçü olarak kullanılmaz; tarama bitince "
                "gerçekten sayılan kayıtla karşılaştırılacak.", "bilgi")
        else:
            self.konsol.yaz(
                f"Tahmini kayıt sayısı: ≈{units.sayi(b.tahmini_satir_sayisi())} "
                f"(ortalama {b.ort_satir_bayt:.0f} bayt/satır üzerinden). Kesin "
                "sayı indeks taraması bitince belirlenecek.", "bilgi")
        self.bicim_etiket.configure(text=b.ozet())

        # Tablo kolonları: örnek satırlardan kaba genişlik tahmini
        genislikler = self._kolon_genislikleri(b)
        self.tablo.taban = 1 if self.taban_degisken.get() else 0
        self.tablo.kolonlari_ayarla(b.kolonlar, genislikler)
        self.sirala_kolon_kutu.configure(values=list(b.kolonlar))
        if b.kolonlar:
            self.sirala_kolon.set(b.kolonlar[0])

        oturum.baslat()
        son_dosyalar.ekle(yol)
        self.konsol.yaz(
            "İndeks taraması BAŞLATILMADI — bu ekran dosyayı açmak için tarama "
            "gerektirmez. Gezinme, sayfa geçişi ve ARAMA indekssiz çalışır; "
            "indeks yalnızca uzak bir kayda atlamak ve KESİN toplam sayı için "
            "gerekir. Uzak bir kayda gitmek istediğinizde yalnızca O KAYDA "
            "KADAR taranır; dosyanın tamamını indekslemek için 'Tam indeksle'.",
            "bilgi")
        self.konsol.yaz(
            f"Pencere boyu {oturum.yukleyici.pencere} satır, önbellek tavanı "
            f"{oturum.yukleyici.onbellek_tavani} pencere "
            f"(= en fazla {units.sayi(oturum.yukleyici.onbellek_tavani * oturum.yukleyici.pencere)} "
            "satır RAM'de tutulur).", "bilgi")

        self._kontrolleri_ayarla(acik=True)
        # Dosya açıldı: kullanıcının bundan sonra ihtiyaç duyacağı sekme
        # "Dosya seçenekleri" değil, gezinmedir (Office'te bir belge
        # açılınca "Giriş" sekmesinde olunması gibi).
        self.serit.select(self._sekme_ana)
        self._sayfaya_git(0, gunlukle=False)
        self.konsol.yaz("İlk sayfa hazır — tarama sürerken gezinebilirsiniz.",
                        "tamam")

    def _kolon_genislikleri(self, bicim):
        genislikler = []
        for i in range(len(bicim.kolonlar)):
            en = len(bicim.kolonlar[i])
            for satir in bicim.ornek_satirlar[:10]:
                if i < len(satir):
                    en = max(en, len(satir[i]))
            genislikler.append(min(460, 12 + en * 7))
        return genislikler

    # ==================================================================
    # Ana tabloda kolon gizleme/gösterme
    # ==================================================================
    def _kolon_secici_ac(self):
        if self.oturum is None:
            return
        tum_kolonlar = list(self.oturum.kolonlar)
        aktif = (set(self.gorunur_kolonlar) if self.gorunur_kolonlar is not None
                else set(range(len(tum_kolonlar))))

        pencere = tk.Toplevel(self.root)
        pencere.title("Kolonlar")
        pencere.transient(self.root)
        pencere.geometry("560x320")

        cerceve = ttk.Frame(pencere, padding=10)
        cerceve.pack(fill="both", expand=True)
        ttk.Label(cerceve, text="Ana tabloda gösterilecek kolonlar:").pack(
            anchor="w", pady=(0, 6))

        liste_kapsayici = ttk.Frame(cerceve)
        liste_kapsayici.pack(fill="both", expand=True)
        kaydir = ttk.Scrollbar(liste_kapsayici, orient="vertical")
        canvas = tk.Canvas(liste_kapsayici, highlightthickness=0,
                           yscrollcommand=kaydir.set)
        kaydir.configure(command=canvas.yview)
        canvas.pack(side="left", fill="both", expand=True)
        kaydir.pack(side="right", fill="y")
        ic_cerceve = ttk.Frame(canvas)
        canvas.create_window((0, 0), window=ic_cerceve, anchor="nw")
        ic_cerceve.bind("<Configure>",
                        lambda e: canvas.configure(scrollregion=canvas.bbox("all")))

        degiskenler = []
        for i, ad in enumerate(tum_kolonlar):
            v = tk.BooleanVar(value=i in aktif)
            degiskenler.append(v)
            ttk.Checkbutton(ic_cerceve, text=ad, variable=v).grid(
                row=i // 3, column=i % 3, sticky="w", padx=6, pady=2)

        def uygula():
            secili = [i for i, v in enumerate(degiskenler) if v.get()]
            if not secili:
                messagebox.showwarning(
                    "Kolonlar", "En az bir kolon seçili kalmalı.", parent=pencere)
                return
            self.gorunur_kolonlar = (None if len(secili) == len(tum_kolonlar)
                                     else secili)
            self._kolon_gorunurlugunu_uygula()
            pencere.destroy()

        alt = ttk.Frame(cerceve)
        alt.pack(fill="x", pady=(10, 0))
        ttk.Button(alt, text="Tümü", width=8,
                  command=lambda: [v.set(True) for v in degiskenler]
                  ).pack(side="left")
        ttk.Button(alt, text="Hiçbiri", width=8,
                  command=lambda: [v.set(False) for v in degiskenler]
                  ).pack(side="left", padx=(4, 0))
        ttk.Button(alt, text="Uygula", width=10, command=uygula).pack(side="right")
        ttk.Button(alt, text="İptal", width=10,
                  command=pencere.destroy).pack(side="right", padx=(0, 6))
        pencere.bind("<Escape>", lambda e: pencere.destroy())

    def _kolon_gorunurlugunu_uygula(self):
        """`self.gorunur_kolonlar`ı tabloya uygular (başlıklar + genişlikler)
        ve yeniden çizer. `oturum.kolonlar` (sıralama/arama'nın kullandığı)
        HİÇ değişmez -- yalnızca GÖSTERİM filtrelenir."""
        if self.oturum is None:
            return
        tum_adlar = list(self.oturum.kolonlar)
        tum_genislikler = self._kolon_genislikleri(self.oturum.bicim)
        if self.gorunur_kolonlar is None:
            adlar, genislikler = tum_adlar, tum_genislikler
        else:
            adlar = [tum_adlar[i] for i in self.gorunur_kolonlar]
            genislikler = [tum_genislikler[i] for i in self.gorunur_kolonlar]
        self.tablo.kolonlari_ayarla(adlar, genislikler)
        self.tablo.yenile()
        n = len(adlar)
        toplam = len(tum_adlar)
        self.konsol.yaz(
            f"Kolon görünümü güncellendi: {n}/{toplam} kolon gösteriliyor."
            if n != toplam else "Tüm kolonlar gösteriliyor.", "islem")

    def _kapat(self):
        if self.oturum is None:
            return
        self.konsol.yaz("Oturum kapatılıyor…", "islem")
        self.oturum.kapat()
        self.oturum = None
        self.eslesmeler = []
        self.eslesme_idx = -1
        self.bekleyen_git = None
        self.gorunur_kolonlar = None
        self._sonuclari_temizle()
        self.tablo.aralik_ayarla(0, 0)
        self.tablo.kolonlari_ayarla([])
        self.sirala_kolon_kutu.configure(values=[])
        self.sirala_kolon.set("")
        self.islem_etiket.configure(text="Arama:")
        self.secim_etiket.configure(text="Seçili: 0 kayıt")
        self.indeks_cubuk["value"] = 0
        self.arama_cubuk["value"] = 0
        self.indeks_etiket.configure(text="— (istek üzerine)")
        self.arama_ilerleme_etiket.configure(text="—")
        self.sayfa_etiket.configure(text="Sayfa —")
        self.bicim_etiket.configure(text="")
        self.durum_etiket.configure(text="Dosya açılmadı.")
        self.serit.select(self._sekme_dosya)
        self._kontrolleri_ayarla(acik=False)
        self.konsol.yaz("Oturum kapatıldı; tüm arka plan işleri durduruldu.",
                        "tamam")

    def _kontrolleri_ayarla(self, acik):
        durum = "normal" if acik else "disabled"
        for w in (self.onceki_dugme, self.sonraki_dugme, self.git_dugme,
                  self.ara_dugme, self.eslesme_onceki, self.eslesme_sonraki,
                  self.kapat_dugme, self.b64_dugme, self.indeks_dugme,
                  self.kolonlar_dugme,
                  self.sirala_dugme, self.sirala_sifirla_dugme,
                  self.secim_sayfa_dugme, self.secim_temizle_dugme,
                  self.secim_goster_dugme):
            w.configure(state=durum)
        self.arama_dur_dugme.configure(state="disabled")
        self.sirala_dur_dugme.configure(state="disabled")

    # ==================================================================
    # Sayfalama ve satıra gitme
    # ==================================================================
    def _sayfa_araligi(self, sayfa):
        """Sayfanın (bas, adet) mutlak satır aralığı."""
        o = self.oturum
        bas = sayfa * o.sayfa_satir
        toplam = o.toplam_satir()
        adet = o.sayfa_satir
        if o.kesin_mi():
            adet = max(0, min(o.sayfa_satir, toplam - bas))
        return bas, adet

    def _sayfaya_git(self, sayfa, ust=0, gunlukle=True):
        o = self.oturum
        if o is None:
            return
        sayfa = max(0, min(sayfa, o.sayfa_sayisi() - 1))
        self.sayfa = sayfa
        bas, adet = self._sayfa_araligi(sayfa)
        # Sayfanın başı henüz konumlandırılamıyorsa indeksi oraya kadar ilerlet.
        if not o.index.erisilebilir(bas):
            o.indeksi_ilerlet(bas + o.yukleyici.pencere)
        t0 = time.perf_counter()
        self.tablo.aralik_ayarla(bas, adet, ust=ust)
        sure = time.perf_counter() - t0
        self._sayfa_etiketi_guncelle()
        o.sayfa_onyukle(sayfa + 1)
        if sayfa > 0:
            o.sayfa_onyukle(sayfa - 1)
        if gunlukle:
            self.konsol.yaz(
                f"Sayfa {units.sayi(sayfa + 1)} açıldı — satır "
                f"{units.sayi(bas + self.tablo.taban)}…"
                f"{units.sayi(bas + adet - 1 + self.tablo.taban)}; "
                f"çizim {units.sure(sure)}. Komşu sayfalar arka planda "
                "hazırlanıyor.", "sure")

    def _sayfa_etiketi_guncelle(self):
        o = self.oturum
        if o is None:
            return
        if o.gorunum is not None:
            self.sayfa_etiket.configure(
                text=f"SIRALI GÖRÜNÜM — {units.sayi(len(o.gorunum))} kayıt "
                     f"({self.sirala_kolon.get()}, "
                     f"{'azalan' if self.sirala_yon.get().startswith('Azalan') else 'artan'})")
            return
        bas, adet = self._sayfa_araligi(self.sayfa)
        isaret = "" if o.kesin_mi() else "≈"
        self.sayfa_etiket.configure(
            text=f"Sayfa {units.sayi(self.sayfa + 1)} / {isaret}"
                 f"{units.sayi(o.sayfa_sayisi())}   "
                 f"(satır {units.sayi(bas + self.tablo.taban)} – "
                 f"{units.sayi(bas + adet - 1 + self.tablo.taban)})")

    def _sirali_gorunumde_mi(self, eylem):
        """Sıralı görünümde sayfa gezinmesi anlamsızdır; kullanıcıyı bilgilendir."""
        if self.oturum is not None and self.oturum.gorunum is not None:
            messagebox.showinfo(
                "Sıralı görünüm",
                f"{eylem} sıralı görünümde kullanılamaz: sayfalar kaynak "
                "sırasına göre tanımlıdır. Önce 'Kaynak sırasına dön' deyin.")
            return True
        return False

    def _onceki_sayfa(self):
        if self._sirali_gorunumde_mi("Sayfa geçişi"):
            return
        if self.oturum and self.sayfa > 0:
            self._sayfaya_git(self.sayfa - 1)

    def _sonraki_sayfa(self):
        if self._sirali_gorunumde_mi("Sayfa geçişi"):
            return
        if self.oturum and self.sayfa + 1 < self.oturum.sayfa_sayisi():
            self._sayfaya_git(self.sayfa + 1)

    def _sinir_asildi(self, yon):
        """Sayfa sınırında kaydırma: bir sonraki/önceki sayfaya geç."""
        o = self.oturum
        if o is None:
            return False
        if yon > 0 and self.sayfa + 1 < o.sayfa_sayisi():
            self._sayfaya_git(self.sayfa + 1, ust=0)
            return True
        if yon < 0 and self.sayfa > 0:
            _, onceki_adet = self._sayfa_araligi(self.sayfa - 1)
            self._sayfaya_git(self.sayfa - 1,
                              ust=max(0, onceki_adet - self.tablo.gorunur))
            return True
        return False

    def _taban_degisti(self):
        self.tablo.taban = 1 if self.taban_degisken.get() else 0
        if self.oturum:
            self.tablo.yenile()
            self._sayfa_etiketi_guncelle()
            self._sonuc_tablosunu_yenile()

    def _git(self):
        o = self.oturum
        if o is None:
            return
        ham = self.git_degisken.get().strip().replace(".", "").replace(" ", "")
        if not ham:
            return
        try:
            istenen = int(ham)
        except ValueError:
            messagebox.showwarning("Geçersiz satır",
                                   f"'{self.git_degisken.get()}' bir satır "
                                   "numarası değil.")
            return
        hedef = istenen - self.tablo.taban
        if hedef < 0:
            messagebox.showwarning(
                "Geçersiz satır",
                f"Satır numarası en az {self.tablo.taban} olmalıdır.")
            return
        if o.kesin_mi() and hedef >= o.toplam_satir():
            messagebox.showwarning(
                "Aralık dışı",
                f"Dosyada {units.sayi(o.toplam_satir())} satır var; "
                f"{units.sayi(istenen)} numaralı satır yok.")
            return
        self._satira_git(hedef, kaynak="Satıra git")

    def _satira_git(self, hedef, kaynak="Satıra git"):
        """Mutlak (0 tabanlı) bir satıra gider; indeks oraya varmadıysa sıraya alır."""
        o = self.oturum
        t0 = time.perf_counter()
        if not o.index.erisilebilir(hedef):
            self.bekleyen_git = hedef
            bilinen = o.bilinen_satir()
            # YALNIZCA hedefe kadar tara: dosyanın geri kalanı okunmaz.
            o.indeksi_ilerlet(hedef + o.yukleyici.pencere)
            okunacak = max(0, int((hedef - bilinen) * o.bicim.ort_satir_bayt))
            self.git_notu.configure(
                text=f"⏳ {units.sayi(hedef + self.tablo.taban)} hazırlanıyor")
            self.konsol.yaz(
                f"{kaynak}: kayıt {units.sayi(hedef + self.tablo.taban)} için "
                f"konum bilinmiyor. N. kaydın yeri ancak bilinen bir noktadan "
                f"satır sayarak bulunabilir; bu yüzden {units.sayi(bilinen)}. "
                f"kayıttan hedefe kadar (~{units.bayt(okunacak)}) taranıyor — "
                "dosyanın tamamı DEĞİL. Varılınca otomatik gidilecek; bu sırada "
                "gezinmeye ve aramaya devam edebilirsiniz.", "islem")
            return

        sayfa = o.sayfa_no(hedef)
        bas, adet = self._sayfa_araligi(sayfa)
        ust = max(0, min(hedef - bas - self.tablo.gorunur // 2,
                         max(0, adet - self.tablo.gorunur)))
        self.sayfa = sayfa
        self.tablo.aralik_ayarla(bas, adet, ust=ust)
        self.tablo.satira_git(hedef, ortala=True)
        self._sayfa_etiketi_guncelle()
        o.sayfa_onyukle(sayfa + 1)
        self.bekleyen_git = None
        self.git_notu.configure(text="")
        sure = time.perf_counter() - t0
        self.konsol.yaz(
            f"{kaynak}: satır {units.sayi(hedef + self.tablo.taban)} → sayfa "
            f"{units.sayi(sayfa + 1)}; konumlandırma {units.sure(sure)}.", "sure")

    # ==================================================================
    # Satır sağlayıcı (sanal tablo buradan besleniyor)
    # ==================================================================
    def _satir_saglayici(self, bas, adet):
        """Tablonun veri kaynağı.

        Sıralı bir görünüm varsa gösterim konumu doğrudan kayıt numarası
        değildir: görünümden okunur ve kayıtlar DAĞINIK olarak getirilir.
        Tablo yine kayıt numarasını gösterir, böylece "Satır #" sütunu her
        zaman kaydın gerçek kimliğini verir.
        """
        if self.oturum is None:
            return []
        gorunum = self.oturum.gorunum
        if gorunum is None:
            ham = self.oturum.satirlar(bas, adet)
        else:
            dilim = gorunum[bas:bas + adet]
            ham = self.oturum.kayitlar(dilim)
        if self.gorunur_kolonlar is None:
            return ham
        # Kolon gizleme aktif: her satırı yalnızca görünür kolonlara indirger
        # (bkz. `_kolon_gorunurlugunu_uygula` -- SanalTablo'ya da AYNI
        # sırayla, yalnızca görünür kolon adları verilmiştir).
        sonuc = []
        for no, degerler in ham:
            if degerler is None:
                sonuc.append((no, None))
            else:
                sonuc.append((no, [degerler[i] if i < len(degerler) else ""
                                   for i in self.gorunur_kolonlar]))
        return sonuc

    def _secim_degisti(self, mutlak):
        pass

    # ==================================================================
    # Çoklu seçim ("işaretleme")
    #
    # Tk'nin kendi tekli satır seçiminden (yukarıdaki secili_mutlak/
    # secim_degisti -- Base64/ayrıntı gibi TEK kaydı hedefleyen eylemler
    # içindir) tamamen ayrı bir mekanizmadır. Burada tutulan tek doğruluk
    # kaynağı `oturum.secim` (bkz. selection.py); tablo yalnızca onu sorar.
    # ==================================================================
    def _secili_mi(self, kayit_no):
        if self.oturum is None:
            return False
        return kayit_no in self.oturum.secim

    def _secim_degistir(self, kayit_no):
        if self.oturum is None:
            return
        sonuc = self.oturum.secim.degistir(kayit_no)
        if sonuc is None:
            messagebox.showwarning(
                "Seçim tavanı",
                f"En fazla {units.sayi(selection.EN_FAZLA_SECIM)} kayıt "
                "seçilebilir (sınırsız büyüyen bir seçim, dosya boyutundan "
                "bağımsız RAM tavanını kullanıcı eylemiyle aşabilirdi). Önce "
                "bazı kayıtları kaldırın ya da 'Seçimi Temizle' ile baştan "
                "başlayın.")
        self._secim_etiketini_guncelle()

    def _secim_etiketini_guncelle(self):
        n = len(self.oturum.secim) if self.oturum is not None else 0
        self.secim_etiket.configure(text=f"Seçili: {units.sayi(n)} kayıt")

    def _sayfayi_sec(self):
        """O an ekranda temsil edilen aralığın (sayfa ya da sıralı görünümün
        tamamının) kayıt NUMARALARINI seçime ekler.

        Yalnızca numaraları ekler -- hiçbir kaydın DEĞERİNİ okumaz; bu
        yüzden 100.000 kayıtlık bir sayfa bile anında ve bedavaya eklenir.
        """
        o = self.oturum
        if o is None:
            return
        ekstra_not = ""
        if o.gorunum is not None:
            adaylar = list(o.gorunum)
            kaynak = "Sıralı görünüm"
        else:
            bas, adet = self._sayfa_araligi(self.sayfa)
            adaylar = range(bas, bas + adet)
            kaynak = f"Sayfa {units.sayi(self.sayfa + 1)}"
            # Sayfanın yalnızca EKRANDA GÖRÜLEN kısmı otomatik taranmış
            # olabilir; kalanı ekranda hiç görünmemiş olsa da seçime
            # eklenir. Bu kayıtların DEĞERLERİ daha sonra ('Seçilenleri
            # Göster' penceresinde) okunabilsin diye sayfanın sonuna kadar
            # indeksi ilerletiyoruz -- aksi hâlde henüz taranmamış kayıtlar
            # kalıcı olarak "…" görünürdü.
            if o.indeksi_ilerlet(bas + adet):
                ekstra_not = (" Sayfanın taranmamış kısmı arka planda "
                             "taranıyor; değerleri birazdan görünür olacak.")
        eklenen, doldu = o.secim.coklu_ekle(adaylar)
        self._secim_etiketini_guncelle()
        self.tablo.yenile()
        mesaj = f"{kaynak}: {units.sayi(eklenen)} kayıt seçime eklendi.{ekstra_not}"
        if doldu:
            mesaj += (f" Seçim tavanına ({units.sayi(selection.EN_FAZLA_SECIM)}) "
                     "ulaşıldığı için kalanlar eklenmedi.")
        self.konsol.yaz(mesaj, "uyari" if doldu else "tamam")

    def _secimi_temizle(self):
        o = self.oturum
        if o is None or len(o.secim) == 0:
            return
        n = len(o.secim)
        o.secim.temizle()
        self._secim_etiketini_guncelle()
        self.tablo.yenile()
        self.konsol.yaz(f"Seçim temizlendi ({units.sayi(n)} kayıt kaldırıldı).",
                        "islem")

    def _secilenleri_goster(self):
        o = self.oturum
        if o is None:
            return
        if len(o.secim) == 0:
            messagebox.showinfo(
                "Seçim yok",
                "Henüz hiçbir kayıt seçilmedi. Tablodaki satırların "
                "solundaki kutucuğu (ya da Boşluk tuşunu) kullanarak "
                "seçebilir, 'Sayfayı Seç' ile bir sayfanın tamamını "
                "ekleyebilirsiniz.")
            return
        self.konsol.yaz(
            f"Seçili veriler penceresi açıldı — {units.sayi(len(o.secim))} "
            "kayıt. Değerler yalnızca bu pencere açıkken, dağınık erişimle "
            "getirilir; diske hiçbir şey yazılmaz.", "islem")
        SeciliVerilerPenceresi(self.root, o, taban=self.tablo.taban,
                              degisiklik_geri_cagrisi=self._secim_degisince)

    def _secim_degisince(self):
        """Seçili Veriler penceresinden bir kayıt kaldırıldığında çağrılır."""
        self._secim_etiketini_guncelle()
        self.tablo.yenile()

    # ==================================================================
    # Sıralama
    # ==================================================================
    def _kapsam_degisti(self):
        """'En iyi N' kutusu yalnızca tüm dosya kapsamında anlamlıdır."""
        tum = self.sirala_kapsam.get() == KAPSAM_TUM
        durum = "normal" if tum else "disabled"
        self.sirala_k_giris.configure(state=durum)
        self.sirala_k_etiket.configure(
            foreground=renkler.govde_metin() if tum else renkler.ikincil())

    def _siralama_ayarlari(self):
        """Arayüzdeki seçimleri sorting modülünün değerlerine çevirir."""
        try:
            kolon = self.oturum.kolonlar.index(self.sirala_kolon.get())
        except ValueError:
            raise ValueError("Önce bir kolon seçin.")
        yon = sorting.AZALAN if self.sirala_yon.get().startswith("Azalan") \
            else sorting.ARTAN
        tur = sorting.TUR_SAYI if self.sirala_tur.get() == "Sayı" \
            else sorting.TUR_METIN
        return kolon, yon, tur

    def _sirala(self):
        o = self.oturum
        if o is None:
            return
        if o.siralama_calisiyor():
            messagebox.showinfo("Sıralama sürüyor", "Önce süren sıralamayı durdurun.")
            return
        if o.arama_calisiyor():
            messagebox.showinfo(
                "Arama sürüyor",
                "Arama ve sıralama ikisi de dosyayı baştan sona okur; aynı anda "
                "çalıştırmak ikisini de yavaşlatır. Önce aramayı bitirin.")
            return
        try:
            kolon, yon, tur = self._siralama_ayarlari()
        except ValueError as e:
            messagebox.showwarning("Sıralama", str(e))
            return

        kapsam = self.sirala_kapsam.get()
        self.konsol.bolum("Sıralama")
        kolon_adi = self.sirala_kolon.get()
        yon_adi = "azalan" if yon == sorting.AZALAN else "artan"

        if kapsam == KAPSAM_ARAMA:
            if not self.eslesmeler:
                messagebox.showinfo(
                    "Arama sonucu yok",
                    "Önce bir arama yapın; bu kapsam arama sonuçlarını sıralar.")
                return
            kayitlar = [e.satir for e in self.eslesmeler]
            o.sirala_liste(kolon, yon, tur, kayitlar)
            self.konsol.yaz(
                f"{units.sayi(len(kayitlar))} arama sonucu '{kolon_adi}' kolonuna "
                f"göre {yon_adi} sıralanıyor. Kayıtlar tek tek okunuyor; "
                "dosyanın tamamı taranmaz.", "islem")
        elif kapsam == KAPSAM_SAYFA:
            bas, adet = self._sayfa_araligi(self.sayfa)
            if self.oturum.gorunum is not None:
                messagebox.showinfo(
                    "Sıralı görünüm",
                    "Şu an sıralı bir görünümdesiniz. Sayfa sıralaması için önce "
                    "'Kaynak sırasına dön' deyin.")
                return
            o.indeksi_ilerlet(bas + adet)
            o.sirala_sayfa(kolon, yon, tur, bas, adet)
            self.konsol.yaz(
                f"Sayfa {units.sayi(self.sayfa + 1)} ({units.sayi(adet)} kayıt) "
                f"'{kolon_adi}' kolonuna göre {yon_adi} sıralanıyor. Yalnızca bu "
                "sayfa okunur — sonuç dosyanın geneli için değil, BU SAYFA için "
                "geçerlidir.", "islem")
        else:
            try:
                k = int(self.sirala_k.get().replace(".", "").strip())
            except ValueError:
                messagebox.showwarning("Sıralama", "'En iyi N' bir sayı olmalı.")
                return
            if not (1 <= k <= 200_000):
                messagebox.showwarning(
                    "Sıralama", "'En iyi N' 1 ile 200.000 arasında olmalı. "
                    "Daha büyük değerler RAM tavanını zorlar.")
                return
            o.sirala_topk(kolon, yon, tur, k)
            uc = "en büyük" if yon == sorting.AZALAN else "en küçük"
            self.konsol.yaz(
                f"Tüm dosyada '{kolon_adi}' kolonuna göre {uc} "
                f"{units.sayi(k)} kayıt aranıyor ({units.bayt(o.bicim.veri_bayt)} "
                "okunacak). Bellekte yalnızca en iyi N tutulur; dosya ne kadar "
                "büyük olursa olsun RAM sabittir.", "islem")

        self.sirala_dugme.configure(state="disabled")
        self.sirala_dur_dugme.configure(state="normal")
        self.islem_etiket.configure(text="Sıralama:")
        self.arama_cubuk["value"] = 0

    def _siralamayi_durdur(self):
        if self.oturum is not None:
            self.oturum.siralamayi_durdur()
            self.konsol.yaz("Sıralama iptal ediliyor…", "islem")

    def _siralamayi_sifirla(self):
        """Sıralı görünümü bırakıp kaynak sırasına döner."""
        o = self.oturum
        if o is None or o.gorunum is None:
            return
        o.gorunum_temizle()
        self.konsol.yaz("Kaynak sırasına dönüldü.", "tamam")
        self._sayfaya_git(self.sayfa, gunlukle=False)

    def _siralama_ilerleme(self, olay):
        toplam = olay["toplam"] or 1
        oran = units.yuzde(olay["ilerleme"], toplam)
        self.arama_cubuk["value"] = oran * 10
        kalan = olay.get("kalan_sure")
        self.arama_ilerleme_etiket.configure(
            text=f"%{oran:.1f} · {units.sayi(olay['incelenen'])} kayıt incelendi · "
                 f"{units.bayt(olay['bayt'])} · "
                 f"{units.hiz_bayt(olay['bayt'], olay['gecen'])} · "
                 f"kalan ≈{units.sure(kalan) if kalan else '—'}")

    def _siralama_bitti(self, olay):
        self.sirala_dugme.configure(state="normal" if self.oturum else "disabled")
        self.sirala_dur_dugme.configure(state="disabled")
        self.islem_etiket.configure(text="Arama:")
        if self.oturum is not None:
            self.oturum.siralama_bitti()
        kayitlar = olay["kayitlar"]
        self.arama_cubuk["value"] = 0 if olay["iptal"] else 1000

        if not kayitlar:
            self.konsol.yaz(
                "Sıralama sonucu boş: seçilen kolonda karşılaştırılabilir değer "
                f"bulunamadı ({units.sayi(olay['bos_anahtar'])} kayıtta değer "
                "okunamadı). Kolon ya da tür (Metin/Sayı) seçimini gözden "
                "geçirin.", "uyari")
            return

        self.oturum.gorunum_ayarla(kayitlar)
        self.tablo.vurgulu_satir = None
        self.tablo.secili_mutlak = None
        self.tablo.aralik_ayarla(0, len(kayitlar), ust=0)
        self._sayfa_etiketi_guncelle()

        durum = "iptal edildi" if olay["iptal"] else "tamamlandı"
        self.konsol.yaz(
            f"Sıralama {durum}: {units.sayi(len(kayitlar))} kayıt sıralandı "
            f"({units.sayi(olay['incelenen'])} kayıt incelendi, "
            f"{units.bayt(olay['bayt'])} okundu, {units.sure(olay['sure'])}).",
            "uyari" if olay["iptal"] else "tamam", kalin=True)
        if olay["bos_anahtar"]:
            self.konsol.yaz(
                f"{units.sayi(olay['bos_anahtar'])} kayıtta bu kolonun değeri "
                "okunamadı (boş ya da sayıya çevrilemedi); bunlar sonuca "
                "alınmadı.", "uyari")
        if olay["iptal"]:
            self.konsol.yaz(
                "İptal edildiği için sonuç YALNIZCA okunan bölüm içindir; "
                "dosyanın tamamının en iyileri olmayabilir.", "uyari")
        if olay.get("tavan_asildi"):
            self.konsol.yaz(
                "Sayfa beklenenden çok kayıt içerdi; sıralama üst sınırda "
                "kesildi.", "uyari")
        self.konsol.yaz(
            "Tablo artık SIRALI görünümde. 'Satır #' sütunu kaydın kaynak "
            "dosyadaki gerçek numarasını gösterir. Kaynak sırasına dönmek için "
            "'Kaynak sırasına dön'.", "bilgi")

    def _secili_kaydi_al(self):
        """Seçili kaydın (numara, alanlar) çiftini döner; yoksa None.

        Değerler Treeview'den DEĞİL, oturumdan okunur: Tk, öğe değerlerini
        geri verirken sayıya benzeyen metinleri tamsayıya çevirebilir ve bu,
        Base64 yükünü bozar.
        """
        if self.oturum is None or self.tablo.secili_mutlak is None:
            return None
        mutlak = self.tablo.secili_mutlak
        satirlar = self.oturum.satirlar(mutlak, 1)
        if not satirlar or satirlar[0][1] is None:
            return None
        return mutlak, list(satirlar[0][1])

    def _indeksi_tamamla(self):
        """Dosyanın tamamını indeksler (istek üzerine)."""
        o = self.oturum
        if o is None:
            return
        if o.index.tamam:
            messagebox.showinfo("İndeks hazır",
                                "Dosya zaten tamamen indekslenmiş; her kayda "
                                "anında gidilebilir.")
            return
        if not o.indeksi_tamamla():
            return
        kalan = o.bicim.veri_bayt - o.index.taranan_bayt
        self.konsol.bolum("Tam indeksleme")
        self.konsol.yaz(
            f"Dosyanın tamamı indeksleniyor: {units.bayt(kalan)} okunacak. "
            "Bitince her kayda anında gidilebilir ve kesin kayıt sayısı "
            "belirlenir. Bu sırada gezinme ve arama çalışmaya devam eder.",
            "islem")

    def _base64_coz(self):
        """Seçili kaydın alanlarından Base64 çözme penceresini açar."""
        if self.oturum is None:
            return
        secim = self._secili_kaydi_al()
        if secim is None:
            messagebox.showinfo(
                "Kayıt seçilmedi",
                "Önce tablodan bir satır seçin. (Satır henüz yüklenmediyse "
                "birkaç saniye bekleyip yeniden deneyin.)")
            return
        mutlak, hucreler = secim
        self.konsol.yaz(
            f"Base64 çözme penceresi açıldı — kayıt "
            f"{units.sayi(mutlak + self.tablo.taban)}, {len(hucreler)} alan. "
            "Çözme tamamen bellekteki değerler üzerinde yapılır; diske "
            "gidilmez.", "islem")
        Base64Penceresi(self.root, mutlak, hucreler, self.oturum.kolonlar,
                        taban=self.tablo.taban)

    def _detay_goster(self):
        """Seçili satırın TÜM hücrelerini (gizli kolonlar dâhil) ayrı bir
        pencerede gösterir.

        `self.tablo.secili_degerler()` DEĞİL, `oturum.satirlar()` kullanılır
        -- tablo "Kolonlar…" ile filtrelenmiş olabilir, ama ayrıntı görünümü
        her zaman kaydın TAMAMINI göstermelidir (bkz. `_secili_kaydi_al`'daki
        aynı gerekçe).
        """
        if self.oturum is None or self.tablo.secili_mutlak is None:
            return
        secim = self._secili_kaydi_al()
        if secim is None:
            return
        mutlak, degerler = secim
        pencere = tk.Toplevel(self.root)
        pencere.title(f"Satır {units.sayi(mutlak + self.tablo.taban)}")
        pencere.geometry("900x460")
        metin = tk.Text(pencere, wrap="word", font=("Consolas", 10))
        kaydir = ttk.Scrollbar(pencere, orient="vertical", command=metin.yview)
        metin.configure(yscrollcommand=kaydir.set)
        metin.pack(side="left", fill="both", expand=True)
        kaydir.pack(side="right", fill="y")
        kolonlar = self.oturum.kolonlar
        metin.insert("end", f"Satır numarası: {units.sayi(mutlak + self.tablo.taban)}\n")
        metin.insert("end", "─" * 70 + "\n")
        for i, deger in enumerate(degerler):
            ad = kolonlar[i] if i < len(kolonlar) else f"(fazla alan {i + 1})"
            metin.insert("end", f"{ad}:\n{deger}\n\n")
        metin.configure(state="disabled")
        ttk.Button(pencere, text="Base64 Çöz", width=14,
                   command=lambda: (pencere.destroy(), self._base64_coz())
                   ).pack(side="bottom", pady=6)

    # ==================================================================
    # Arama
    # ==================================================================
    def _ara(self):
        o = self.oturum
        if o is None:
            return
        metin = self.arama_degisken.get()
        if not metin.strip():
            messagebox.showwarning("Boş arama", "Aranacak metni yazın.")
            return
        if o.arama_calisiyor():
            messagebox.showinfo("Arama sürüyor",
                                "Önce süren aramayı durdurun.")
            return

        self._sonuclari_temizle()
        self.konsol.bolum("Arama")
        try:
            desen = o.ara(metin, duyarli=self.duyarli_degisken.get(),
                          en_fazla=EN_FAZLA_SONUC, regex=self.regex_degisken.get())
        except ValueError as e:
            messagebox.showwarning("Geçersiz arama", str(e))
            return
        self.arama_deseni = desen

        self.ara_dugme.configure(state="disabled")
        self.arama_dur_dugme.configure(state="normal")
        self.alt_defter.select(1)

        self.konsol.yaz(
            f"Aranan: {metin!r} · "
            f"{'büyük/küçük harfe duyarlı' if desen.duyarli else 'harfe duyarsız'}"
            f"{' · regex' if desen.regex else ''}"
            f" · kaynak dosyanın TAMAMI taranacak "
            f"({units.bayt(o.bicim.veri_bayt)}).", "islem")
        if desen.yaklasik:
            self.konsol.yaz(
                "Aranan metin ASCII dışı karakter içeriyor. Bayt düzeyinde tam "
                "Unicode büyük/küçük kıvrımı yapılamadığı için metnin "
                f"{len(desen.desenler)} yaygın yazılış çeşidi (küçük/BÜYÜK/İlk "
                "harf büyük, Türkçe i-İ ve ı-I kuralları dâhil) ayrı ayrı "
                "aranıyor. Kesinlik için 'Büyük/küçük harfe duyarlı' seçeneğini "
                "kullanın.", "uyari")
        self.konsol.yaz("İndeks taraması, arama süresince duraklatıldı "
                        "(ikisi de aynı diski kullanıyor).", "bilgi")

    def _arama_durdur(self):
        if self.oturum is not None:
            self.oturum.aramayi_durdur()
            self.konsol.yaz("Arama iptal ediliyor…", "islem")

    def _sonuclari_temizle(self):
        self.eslesmeler = []
        self.eslesme_idx = -1
        for iid in self.sonuc_tablo.get_children():
            self.sonuc_tablo.delete(iid)
        self.eslesme_etiket.configure(text="eşleşme yok")
        self.arama_cubuk["value"] = 0
        self.arama_ilerleme_etiket.configure(text="—")

    def _eslesme_ekle(self, eslesmeler):
        for e in eslesmeler:
            i = len(self.eslesmeler)
            self.eslesmeler.append(e)
            onizleme = e.onizleme.replace("\t", " ")
            if e.kirpik:
                onizleme = "… " + onizleme
            self.sonuc_tablo.insert(
                "", "end", iid=f"e{i}",
                values=(units.sayi(e.satir + self.tablo.taban), onizleme))
        self._eslesme_etiketi_guncelle()

    def _eslesme_etiketi_guncelle(self):
        n = len(self.eslesmeler)
        if not n:
            self.eslesme_etiket.configure(text="eşleşme yok")
            return
        if self.eslesme_idx < 0:
            self.eslesme_etiket.configure(text=f"{units.sayi(n)} eşleşme")
        else:
            self.eslesme_etiket.configure(
                text=f"{units.sayi(self.eslesme_idx + 1)} / {units.sayi(n)} eşleşme")

    def _eslesme_gez(self, yon):
        if not self.eslesmeler:
            return
        self.eslesme_idx = (self.eslesme_idx + yon) % len(self.eslesmeler)
        self._eslesmeye_git(self.eslesme_idx)

    def _eslesmeye_git(self, i):
        e = self.eslesmeler[i]
        self.eslesme_idx = i
        self.sonuc_tablo.selection_set(f"e{i}")
        self.sonuc_tablo.see(f"e{i}")
        self._eslesme_etiketi_guncelle()
        self._satira_git(e.satir, kaynak=f"Eşleşme {i + 1}")

    def _sonuc_secildi(self, _event):
        sec = self.sonuc_tablo.selection()
        if not sec:
            return
        try:
            i = int(sec[0][1:])
        except ValueError:
            return
        if i != self.eslesme_idx and 0 <= i < len(self.eslesmeler):
            self._eslesmeye_git(i)

    def _sonuc_tablosunu_yenile(self):
        for i, e in enumerate(self.eslesmeler):
            self.sonuc_tablo.set(f"e{i}", "satir",
                                 units.sayi(e.satir + self.tablo.taban))

    # ==================================================================
    # Olay kuyruğu
    # ==================================================================
    def _kuyrugu_isle(self):
        try:
            islenen = 0
            while islenen < 200:
                try:
                    olay = self.kuyruk.get_nowait()
                except queue.Empty:
                    break
                islenen += 1
                self._olay(olay)
        finally:
            self.root.after(KUYRUK_ARALIGI, self._kuyrugu_isle)

    def _olay(self, olay):
        tur = olay.get("tur")
        if tur == rowindex.OLAY_ILERLEME:
            self._indeks_ilerleme(olay)
        elif tur == rowindex.OLAY_BITTI:
            self._indeks_bitti(olay)
        elif tur == rowindex.OLAY_HEDEF:
            self._indeks_hedefe_ulasti(olay)
        elif tur == rowindex.OLAY_UYARI:
            self.konsol.yaz(olay["mesaj"], "uyari")
        elif tur == rowindex.OLAY_HATA:
            self.konsol.yaz(f"İndeks taraması hata verdi: {olay['hata']}", "hata")
            messagebox.showerror("İndeks hatası", str(olay["hata"]))
        elif tur == loader.OLAY_PENCERE:
            self._pencere_geldi(olay)
        elif tur == loader.OLAY_HATA:
            self.konsol.yaz(f"Satır yükleyici hata verdi: {olay['hata']}", "hata")
        elif tur == finder.OLAY_ESLESME:
            self._eslesme_ekle(olay["eslesmeler"])
        elif tur == finder.OLAY_ILERLEME:
            self._arama_ilerleme(olay)
        elif tur == finder.OLAY_BITTI:
            self._arama_bitti(olay)
        elif tur == sorting.OLAY_ILERLEME:
            self._siralama_ilerleme(olay)
        elif tur == sorting.OLAY_BITTI:
            self._siralama_bitti(olay)
        elif tur == sorting.OLAY_HATA:
            self.konsol.yaz(f"Sıralama hata verdi: {olay['hata']}", "hata")
            self.sirala_dugme.configure(state="normal" if self.oturum else "disabled")
            self.sirala_dur_dugme.configure(state="disabled")
            self.islem_etiket.configure(text="Arama:")
        elif tur == finder.OLAY_HATA:
            self.konsol.yaz(f"Arama hata verdi: {olay['hata']}", "hata")
            self._arama_kontrollerini_sifirla()

    # -- indeks --------------------------------------------------------
    def _indeks_ilerleme(self, olay):
        if self.oturum is None:
            return
        toplam = olay["toplam_bayt"] or 1
        oran = units.yuzde(olay["bayt"], toplam)
        self.indeks_cubuk["value"] = oran * 10
        kalan = olay.get("kalan_sure")
        hedef = self.oturum.tarayici.hedef_satir if self.oturum else None
        hedef_notu = (f" · hedef {units.sayi(hedef)}. kayıt" if hedef else "")
        self.indeks_etiket.configure(
            text=f"%{oran:.1f} · {units.sayi(olay['satir'])} kayıt · "
                 f"{units.bayt(olay['bayt'])} / {units.bayt(toplam)} · "
                 f"{units.hiz_bayt(olay['bayt'], olay['gecen'])} · "
                 f"kalan ≈{units.sure(kalan) if kalan else '—'}{hedef_notu}")

        simdi = time.perf_counter()
        if simdi - self._son_konsol_ilerleme >= KONSOL_ILERLEME_ARALIGI:
            self._son_konsol_ilerleme = simdi
            self.konsol.yaz(
                f"İndeks %{oran:.1f} — {units.sayi(olay['satir'])} satır, "
                f"{units.bayt(olay['bayt'])} okundu, "
                f"{units.hiz_bayt(olay['bayt'], olay['gecen'])}, kalan "
                f"≈{units.sure(kalan) if kalan else '—'}.", "islem")

        # Bekleyen "satıra git" isteği artık karşılanabiliyor mu?
        if (self.bekleyen_git is not None
                and self.oturum.index.erisilebilir(self.bekleyen_git)):
            hedef = self.bekleyen_git
            self.bekleyen_git = None
            self.konsol.yaz(
                f"İndeks {units.sayi(hedef + self.tablo.taban)} numaralı satıra "
                "ulaştı; bekleyen istek uygulanıyor.", "tamam")
            self._satira_git(hedef, kaynak="Bekleyen satıra git")
            return

        # Görünür alanda yer tutucu varsa yeniden dene (bölge artık okunabilir).
        self._gerekirse_yenile()

    def _indeks_hedefe_ulasti(self, olay):
        """İstenen kayda kadar tarandı; tarayıcı durdu (gerisi okunmadı)."""
        if self.oturum is None:
            return
        self.oturum.indeks_hedefe_ulasti()
        self.konsol.yaz(
            f"İstenen kayda ulaşıldı: {units.sayi(olay['satir'])} kayıt "
            f"indekslendi ({units.bayt(olay['bayt'])} okundu, "
            f"{units.sure(olay['gecen'])}). Tarama DURDURULDU — dosyanın geri "
            "kalanı okunmadı.", "tamam")
        self.indeks_etiket.configure(
            text=f"durduruldu · {units.sayi(olay['satir'])} kayıt indeksli · "
                 f"{units.bayt(olay['bayt'])} okundu")
        if self.bekleyen_git is not None:
            hedef = self.bekleyen_git
            self.bekleyen_git = None
            self._satira_git(hedef, kaynak="Bekleyen satıra git")
        else:
            self.git_notu.configure(text="")
            self.tablo.yenile()

    def _indeks_bitti(self, olay):
        if self.oturum is None:
            return
        if olay.get("iptal"):
            self.konsol.yaz(
                f"İndeks taraması durduruldu ({units.sayi(olay['satir'])} "
                "satıra kadar geldi).", "uyari")
            return
        sure = olay["sure"]
        satir = olay["satir"]
        bayt = olay.get("bayt", 0)
        self.indeks_cubuk["value"] = 1000
        self.indeks_etiket.configure(
            text=f"TAMAM · {units.sayi(satir)} satır · {units.bayt(bayt)} · "
                 f"{units.sure(sure)} · {units.hiz_bayt(bayt, sure)}")
        self.konsol.bolum("İndeks tamamlandı")
        self.konsol.yaz(
            f"Kesin satır sayısı: {units.sayi(satir)}. Tarama {units.sure(sure)} "
            f"sürdü ({units.hiz_bayt(bayt, sure)}, "
            f"{units.hiz_satir(satir, sure)}).", "tamam", kalin=True)
        self.konsol.yaz(
            f"İndeks {units.sayi(olay.get('cipa', 0))} çıpa tutuyor ve "
            f"{units.bayt(olay.get('bellek', 0))} RAM kullanıyor. Artık her "
            "satıra anında gidilebilir.", "bilgi")

        # Dosya başlığı bir kayıt sayısı bildiriyorsa, gerçekten sayılan
        # değerle karşılaştır: bedava bir bütünlük denetimi. Tutmaması,
        # dosyanın eksik/bozuk olduğunu ya da bazı kayıtların birden çok
        # satıra yayıldığını gösterir.
        beyan = self.oturum.bicim.beyan_edilen_kayit
        if beyan:
            if beyan == satir:
                self.konsol.yaz(
                    f"Bütünlük denetimi: dosyanın bildirdiği kayıt sayısı "
                    f"({units.sayi(beyan)}) sayılan değerle BİREBİR tutuyor.",
                    "tamam")
            else:
                fark = satir - beyan
                self.konsol.yaz(
                    f"Bütünlük denetimi: dosya {units.sayi(beyan)} kayıt "
                    f"bildiriyor ama {units.sayi(satir)} kayıt sayıldı "
                    f"(fark {fark:+,}).".replace(",", ".")
                    + " Dosya eksik/fazla satır içeriyor ya da bazı kayıtlar "
                      "birden çok satıra yayılmış olabilir.", "uyari")
        self._sayfa_etiketi_guncelle()
        self.tablo.aralik_ayarla(*self._sayfa_araligi(self.sayfa),
                                 ust=self.tablo.ust)
        if self.bekleyen_git is not None:
            hedef = self.bekleyen_git
            self.bekleyen_git = None
            self._satira_git(hedef, kaynak="Bekleyen satıra git")

    # -- yükleyici -----------------------------------------------------
    def _pencere_geldi(self, olay):
        self._pencere_sayaci += 1
        self._pencere_sure += olay["sure"]
        bas = olay["bas"]
        son = bas + olay["adet"]
        gor_bas, gor_adet = self.tablo.gorunur_aralik()
        if son > gor_bas and bas < gor_bas + gor_adet:
            self.tablo.yenile()

        simdi = time.perf_counter()
        if simdi - self._son_pencere_ozeti >= 2.0 and self._pencere_sayaci:
            self._son_pencere_ozeti = simdi
            ort = self._pencere_sure / self._pencere_sayaci
            self.konsol.yaz(
                f"{self._pencere_sayaci} satır penceresi kaynaktan okundu "
                f"(ortalama {units.sure(ort)}; toplam "
                f"{units.sayi(self._pencere_sayaci * self.oturum.yukleyici.pencere)} "
                "satır).", "sure")
            self._pencere_sayaci = 0
            self._pencere_sure = 0.0

    def _gerekirse_yenile(self):
        """Görünür alanda yer tutucu ('…') varsa tabloyu yeniden çizer."""
        if self.oturum is None:
            return
        bas, adet = self.tablo.gorunur_aralik()
        if adet <= 0:
            return
        yk = self.oturum.yukleyici
        for pid in range(bas // yk.pencere, (bas + adet - 1) // yk.pencere + 1):
            if yk.onbellekten(pid) is None:
                self.tablo.yenile()
                return

    # -- arama ---------------------------------------------------------
    def _arama_ilerleme(self, olay):
        if olay.get("doldu"):
            self.konsol.yaz(
                f"Sonuç listesi üst sınıra ({units.sayi(EN_FAZLA_SONUC)}) ulaştı; "
                "eşleşmeler saymaya devam ediyor ama listeye eklenmiyor. "
                "Daha dar bir arama metni deneyin.", "uyari")
            return
        toplam = olay["toplam"] or 1
        oran = units.yuzde(olay["bayt"], toplam)
        self.arama_cubuk["value"] = oran * 10
        kalan = olay.get("kalan_sure")
        self.arama_ilerleme_etiket.configure(
            text=f"%{oran:.1f} · {units.sayi(olay['eslesme'])} eşleşme · "
                 f"{units.bayt(olay['bayt'])} / {units.bayt(toplam)} · "
                 f"{units.hiz_bayt(olay['bayt'], olay['gecen'])} · "
                 f"kalan ≈{units.sure(kalan) if kalan else '—'}")

    def _arama_bitti(self, olay):
        self._arama_kontrollerini_sifirla()
        if self.oturum is not None:
            self.oturum.arama_bitti()
        sure = olay["sure"]
        bayt = olay["bayt"]
        durum = "iptal edildi" if olay["iptal"] else "tamamlandı"
        seviye = "uyari" if olay["iptal"] else "tamam"
        self.arama_cubuk["value"] = 0 if olay["iptal"] else 1000
        self.konsol.yaz(
            f"Arama {durum}: {units.sayi(olay['eslesme'])} eşleşme "
            f"({units.sayi(olay['saklanan'])} listelendi). "
            f"{units.bayt(bayt)} tarandı, {units.sure(sure)} sürdü "
            f"({units.hiz_bayt(bayt, sure)}).", seviye, kalin=True)
        if not olay["iptal"] and olay["eslesme"] == 0:
            self.konsol.yaz("Hiçbir eşleşme bulunamadı.", "uyari")
        elif self.eslesmeler and self.eslesme_idx < 0:
            self.konsol.yaz(
                "İlk eşleşmeye gitmek için ▶ düğmesini kullanın ya da "
                "'Arama sonuçları' sekmesinden bir satıra tıklayın.", "bilgi")
        if self.oturum is not None and not self.oturum.index.tamam:
            self.konsol.yaz("İndeks taraması kaldığı yerden sürdürülüyor.",
                            "bilgi")

    def _arama_kontrollerini_sifirla(self):
        self.ara_dugme.configure(state="normal" if self.oturum else "disabled")
        self.arama_dur_dugme.configure(state="disabled")

    # ==================================================================
    # Durum satırı
    # ==================================================================
    def _durum_dongusu(self):
        try:
            self._durum_guncelle()
        finally:
            self.root.after(DURUM_ARALIGI, self._durum_dongusu)

    def _durum_guncelle(self):
        o = self.oturum
        if o is None:
            return
        self._dosya_degisikligini_denetle(o)
        ozet = o.bellek_ozeti()
        bekleyen = o.yukleyici.bekleyen_sayisi()
        if o.arama_calisiyor():
            durum = "arama sürüyor"
        elif o.index.tamam:
            durum = "hazır (tam indeksli)"
        elif o.indeks_calisiyor():
            durum = "indeks ilerletiliyor"
        elif o.index.taranan_satir:
            durum = (f"hazır · indeks {units.sayi(o.index.taranan_satir)} "
                     "kayda kadar")
        else:
            durum = "hazır (indeks yok — gerekince oluşturulur)"
        if bekleyen:
            durum += f" · {bekleyen} pencere kuyrukta"
        onek = "⚠ KAYNAK DOSYA DEĞİŞTİ — YENİDEN AÇIN   |   " if self._dosya_degisti_uyarildi else ""
        self.durum_etiket.configure(
            text=f"{onek}Durum: {durum}   |   RAM: indeks {units.bayt(ozet['indeks_bayt'])} "
                 f"({units.sayi(ozet['cipa'])} çıpa) + satır önbelleği "
                 f"{ozet['onbellek_pencere']}/{o.yukleyici.onbellek_tavani} pencere "
                 f"({units.sayi(ozet['onbellek_satir'])} satır, tavan "
                 f"{units.sayi(ozet['onbellek_tavan_satir'])})   |   "
                 f"Diske yazılan: 0 bayt",
            foreground=renkler.hata() if self._dosya_degisti_uyarildi else renkler.islem_rengi())

    def _dosya_degisikligini_denetle(self, o):
        """Kaynak dosya oturum açıldığından beri değiştiyse KALICI olarak uyarır.

        `oturum.index`'teki bayt konumları (çıpalar) açılış anındaki dosya
        üzerinden hesaplanmıştır; dosya değişirse (üzerine yazılırsa,
        başka bir işlem tarafından yeniden oluşturulursa) bu konumlar
        SESSİZCE yanlış olur -- ekranda yanlış/bozuk satırlar görünebilir.
        Bu denetim onu tespit edip kullanıcıyı BİR KEZ (popup) ve SÜREKLİ
        (durum çubuğunda, dosya kapatılana kadar) uyarır.
        """
        if self._dosya_degisti_uyarildi or not o.dosya_degisti_mi():
            return
        self._dosya_degisti_uyarildi = True
        self.konsol.yaz(
            "KAYNAK DOSYA DEĞİŞTİ! Oturum açıldığından beri dosyanın boyutu "
            "ya da değiştirilme zamanı değişti. Şu andan sonra okunan "
            "satırlar YANLIŞ ya da BOZUK olabilir — lütfen dosyayı KAPATIP "
            "yeniden açın.", "hata", kalin=True)
        messagebox.showwarning(
            "Kaynak dosya değişti",
            "Açık olan dosya, bu oturum başladığından beri değişmiş "
            "görünüyor (boyutu ya da değiştirilme zamanı farklı).\n\n"
            "İndekslenmiş konumlar artık YANLIŞ olabilir; bu andan sonra "
            "görülen satırlar hatalı olabilir.\n\n"
            "Lütfen dosyayı kapatıp yeniden açın.")

    # ==================================================================
    # Web arayüzü (Django) -- aynı çekirdeği tarayıcıdan da açar
    #
    # "🌐 Web Arayüzü" düğmesi masaüstü uygulamasını KAPATMAZ; ayrıca bir
    # `manage.py runserver` süreci başlatıp (zaten çalışmıyorsa) varsayılan
    # tarayıcıyı açar. Sunucunun hazır olmasını BEKLEME işi ayrı bir arka
    # plan thread'inde yapılır -- Tk ana döngüsü asla bloklanmaz. Şu an
    # açık bir dosya varsa, tarayıcı doğrudan AYNI dosyayla açılır (bkz.
    # `?yol=&ac=1` -- `gorunum/static/gorunum/app.js`'deki URL parametresi
    # desteğiyle eşleşir).
    # ==================================================================
    def _web_kok_dizini(self):
        """Bu dosyadan (livedata/ui/app.py) proje köküne çıkar (manage.py'nin
        bulunduğu dizin)."""
        return os.path.dirname(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))))

    def _web_sunucu_hazir_mi(self):
        try:
            urllib.request.urlopen(WEB_URL, timeout=0.5)
            return True
        except Exception:
            return False

    def _web_arayuzunu_ac(self):
        self.web_ac_dugme.configure(state="disabled")
        self.konsol.yaz("Web arayüzü açılıyor…", "islem")
        threading.Thread(target=self._web_arka_planda_ac, daemon=True).start()

    def _web_arka_planda_ac(self):
        url = WEB_URL
        if self.oturum is not None:
            url += "?" + urllib.parse.urlencode(
                {"yol": self.oturum.yol, "ac": "1"})

        if not self._web_sunucu_hazir_mi():
            if self._web_surec is None or self._web_surec.poll() is not None:
                try:
                    self._web_surec = subprocess.Popen(
                        [sys.executable, "manage.py", "runserver",
                         f"127.0.0.1:{WEB_PORT}", "--noreload"],
                        cwd=self._web_kok_dizini(),
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                        creationflags=(subprocess.CREATE_NO_WINDOW
                                      if os.name == "nt" else 0))
                except OSError as e:
                    self.root.after(0, lambda: self._web_ac_hata(str(e)))
                    return

            baslangic = time.perf_counter()
            while time.perf_counter() - baslangic < WEB_BASLAMA_ZAMAN_ASIMI:
                if self._web_sunucu_hazir_mi():
                    break
                time.sleep(0.2)
            else:
                self.root.after(0, lambda: self._web_ac_hata(
                    f"{WEB_BASLAMA_ZAMAN_ASIMI:.0f} saniyede hazır olmadı."))
                return

        self.root.after(0, lambda: self._web_ac_tamam(url))

    def _web_ac_tamam(self, url):
        webbrowser.open(url)
        self.konsol.yaz(f"Web arayüzü tarayıcıda açıldı: {url}", "tamam")
        self.web_ac_dugme.configure(state="normal")

    def _web_ac_hata(self, mesaj):
        self.konsol.yaz(f"Web sunucusu başlatılamadı: {mesaj}", "hata")
        messagebox.showerror(
            "Web arayüzü başlatılamadı",
            f"{mesaj}\n\nElle denemek için proje kök dizininde:\n"
            "python manage.py runserver 127.0.0.1:8000 --noreload\n\n"
            "ya da 'webde_goruntule.bat' dosyasına çift tıklayın.")
        self.web_ac_dugme.configure(state="normal")

    # ==================================================================
    def _cikis(self):
        if self.oturum is not None:
            self.oturum.kapat()
        if self._web_surec is not None and self._web_surec.poll() is None:
            self._web_surec.terminate()
        self.root.destroy()

    def calistir(self):
        self.root.mainloop()
