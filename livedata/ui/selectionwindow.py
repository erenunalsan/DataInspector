"""Seçili kayıtları ayrı bir pencerede gösteren, kolon seçilebilen ekran.

Bu pencere, ana tablodan işaretlenen kayıtları (bkz. selection.py) kaynak
dosyadaki gerçek numaralarıyla listeler. Kayıtlar DAĞINIKTIR (dosyanın her
yerinden gelebilir); bu yüzden aynen sıralama sonuçlarında olduğu gibi
`VeriOturumu.kayitlar()` ile arka plandaki pencere yükleyiciden dağınık
erişimle getirilir -- ölçülen maliyet kayıt başına ~0,4 ms'dir, dosya
boyutundan bağımsızdır. Hiçbir kayıt bu pencere için ayrıca diske
yazılmaz ya da kalıcı olarak belleğe alınmaz; `SanalTablo` burada da aynı
"yalnızca görünen satırları gerçekle" ilkesiyle çalışır.

İşaretleme sütunu burada "KALDIR" anlamına gelir: bu listedeki her kayıt
zaten seçili olduğundan kutu her zaman işaretli görünür, tıklamak kaydı
seçimden çıkarır ve listeden anında kaybolur.

Yerel web yayını + dışa aktarım
--------------------------------
"Webde Göster" düğmesi, o an listelenen (görünür kolonlarla filtrelenmiş)
kayıtları arka planda toplayıp `livedata.webserver.WebYayini` ile
localhost üzerinde tek sayfalık bir HTML olarak yayınlar. Veri toplama
mantığı "panoya kopyala" akışıyla aynıdır (parça parça, arayüz hiç
kilitlenmeden). Açılan web sayfasında Excel (.xlsx) / Word (.docx) / PDF
indirme düğmeleri de bulunur (bkz. `livedata.exporters`); dosyalar sunucu
tarafında, aynı toplanmış veriden, istek anında üretilir ve tarayıcı
üzerinden kullanıcının kendi bilgisayarına iner -- bu uygulama hiçbir
zaman kendisi diske yazmaz.
"""
import time
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from .. import exporters, units
from ..webserver import WebYayini, sayfa_uret
from . import renkler
from .virtualtable import SanalTablo

# Dışa aktarım biçimi -> (üretici fonksiyon, dosya uzantısı, dosya süzgeci).
DISA_AKTAR_BICIMLERI = {
    "excel": (exporters.xlsx_uret, ".xlsx", [("Excel dosyası", "*.xlsx")]),
    "word": (exporters.docx_uret, ".docx", [("Word belgesi", "*.docx")]),
    "pdf": (exporters.pdf_uret, ".pdf", [("PDF dosyası", "*.pdf")]),
}

# Bir kerede arka planda istenecek kayıt sayısı (panoya kopyalarken).
KOPYALAMA_PARCA = 2000
KOPYALAMA_ARALIGI_MS = 60
# Bu sayının üzerinde kopyalama isteği onay ister (tahmini süre gösterilir).
KOPYALAMA_ONAY_ESIGI = 20_000
# Kayıt başına kaba süre tahmini (ölçülen dağınık erişim ~0,4 ms/kayıt).
KAYIT_BASINA_TAHMINI_SN = 0.0006


class SeciliVerilerPenceresi(tk.Toplevel):
    """Seçili kayıtları listeleyen, kolon filtreli, kopyalanabilir pencere."""

    def __init__(self, ana, oturum, taban=0, degisiklik_geri_cagrisi=None):
        super().__init__(ana)
        self.oturum = oturum
        self.taban = taban
        self.degisiklik_geri_cagrisi = degisiklik_geri_cagrisi

        self.title(f"Seçili Veriler — {units.sayi(len(oturum.secim))} kayıt")
        self.geometry("1150x680")
        self.minsize(760, 480)
        self.transient(ana)

        # Görüntülenen liste, pencere açıldığı andaki seçim sırasını korur
        # (kaldırma dışında değişmez -- yeni işaretlemeler ana tablodan
        # yapılır, bu pencere yalnızca "geri al" sunar).
        self.nolar = oturum.secim.liste()
        self.kolon_adlari = list(oturum.kolonlar)
        self.kolon_degiskenleri = [tk.BooleanVar(value=True)
                                   for _ in self.kolon_adlari]
        self._kopyalanan = None       # kopyalama sürerken: {kayit_no: degerler}
        self._web_toplanan = None     # web yayını için toplanırken: {kayit_no: degerler}
        self._disa_aktar_toplanan = None  # Excel/Word/PDF için toplanırken
        self._web_yayini = WebYayini()

        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)

        self._ust_bolge()
        self._kolon_bolgesi()
        self._tablo_bolgesi()
        self._alt_bolge()

        self.bind("<Escape>", lambda e: self.destroy())
        self.protocol("WM_DELETE_WINDOW", self._kapatirken)
        self._secili_kolonlar_guncelle()

    def _kapatirken(self):
        # Pencere kapanınca yayındaki sunucuyu da durdur -- arkada
        # unutulmuş bir localhost sunucusu kalmasın.
        self._web_yayini.durdur()
        self.destroy()

    # ------------------------------------------------------------------
    def _ust_bolge(self):
        cerceve = ttk.Frame(self, padding=(10, 8, 10, 4))
        cerceve.grid(row=0, column=0, sticky="ew")
        self.baslik_etiket = ttk.Label(
            cerceve, text=f"{units.sayi(len(self.nolar))} kayıt seçili",
            font=("Segoe UI", 10, "bold"))
        self.baslik_etiket.pack(side="left")
        ttk.Label(
            cerceve, foreground="#8a8a8a",
            text="  ·  İşaret kutusunu tıklamak kaydı seçimden çıkarır."
        ).pack(side="left")
        ttk.Label(
            cerceve, foreground="#8a8a8a",
            text="  ·  \"Webde Göster\" ile bu seçim yerel bir adreste "
                 "(localhost) görüntülenebilir."
        ).pack(side="right")

    def _kolon_bolgesi(self):
        cerceve = ttk.LabelFrame(self, text="Gösterilecek kolonlar",
                                 padding=(8, 4))
        cerceve.grid(row=1, column=0, sticky="ew", padx=8, pady=(4, 4))

        buton_cubugu = ttk.Frame(cerceve)
        buton_cubugu.pack(side="left", padx=(0, 10))
        ttk.Button(buton_cubugu, text="Tümü", width=6,
                  command=lambda: self._kolonlari_ayarla(True)).pack(pady=1)
        ttk.Button(buton_cubugu, text="Hiçbiri", width=6,
                  command=lambda: self._kolonlari_ayarla(False)).pack(pady=1)

        liste_cerceve = ttk.Frame(cerceve)
        liste_cerceve.pack(side="left", fill="x", expand=True)
        for i, ad in enumerate(self.kolon_adlari):
            ttk.Checkbutton(
                liste_cerceve, text=ad, variable=self.kolon_degiskenleri[i],
                command=self._secili_kolonlar_guncelle
            ).pack(side="left", padx=4)

    def _tablo_bolgesi(self):
        self.tablo = SanalTablo(
            self, saglayici=self._satir_saglayici,
            secili_mi=lambda no: True,      # bu listede her satır seçilidir
            secim_degistir=self._kaldir)
        self.tablo.taban = self.taban
        self.tablo.grid(row=2, column=0, sticky="nsew", padx=8, pady=4)

    def _alt_bolge(self):
        cerceve = ttk.Frame(self, padding=(10, 4, 10, 10))
        cerceve.grid(row=3, column=0, sticky="ew")

        self.kopyala_dugme = ttk.Button(cerceve, text="Panoya Kopyala (TSV)",
                                        width=20, command=self._kopyala)
        self.kopyala_dugme.pack(side="left")
        self.web_dugme = ttk.Button(cerceve, text="Webde Göster",
                                    width=15, command=self._webde_goster)
        self.web_dugme.pack(side="left", padx=(6, 0))

        ttk.Separator(cerceve, orient="vertical").pack(side="left", fill="y", padx=8)
        self.excel_dugme = ttk.Button(cerceve, text="⬇ Excel", width=10,
                                      command=lambda: self._disa_aktar("excel"))
        self.excel_dugme.pack(side="left")
        self.word_dugme = ttk.Button(cerceve, text="⬇ Word", width=10,
                                     command=lambda: self._disa_aktar("word"))
        self.word_dugme.pack(side="left", padx=(4, 0))
        self.pdf_dugme = ttk.Button(cerceve, text="⬇ PDF", width=10,
                                    command=lambda: self._disa_aktar("pdf"))
        self.pdf_dugme.pack(side="left", padx=(4, 0))

        self.durum_etiket = ttk.Label(cerceve, text="", foreground=renkler.vurgu())
        self.durum_etiket.pack(side="left", padx=(16, 0))

        ttk.Button(cerceve, text="Kapat", width=10,
                  command=self._kapatirken).pack(side="right")
        ttk.Button(cerceve, text="Tümünü Seçimden Çıkar", width=22,
                  command=self._hepsini_temizle).pack(side="right", padx=(0, 6))

    # -- kolon filtresi --------------------------------------------------
    def _kolonlari_ayarla(self, deger):
        for var in self.kolon_degiskenleri:
            var.set(deger)
        self._secili_kolonlar_guncelle()

    def _secili_kolonlar_guncelle(self):
        """Kolon işaretlerinden görünen tabloyu yeniden kurar.

        En az bir kolon açık kalmak ZORUNDADIR: hiçbir kolon seçili değilken
        tablo boş görünür ve kullanıcı nedenini anlayamaz.
        """
        secili = [i for i, var in enumerate(self.kolon_degiskenleri)
                  if var.get()]
        if not secili:
            # En az bir kolon kalmalı; aksi hâlde tablo boş görünür ve
            # kullanıcı neden hiçbir şey görmediğini anlayamaz. Son
            # kaldırılan kolonu geri işaretleyip kullanıcıyı bilgilendiriyoruz.
            self.kolon_degiskenleri[0].set(True)
            secili = [0]
            self.durum_etiket.configure(
                text="En az bir kolon işaretli kalmalı.", foreground=renkler.uyari())
        self.secili_kolonlar = secili
        self.tablo.kolonlari_ayarla([self.kolon_adlari[i] for i in secili])
        self.tablo.aralik_ayarla(0, len(self.nolar), ust=self.tablo.ust)

    # -- veri sağlama ------------------------------------------------------
    def _satir_saglayici(self, bas, adet):
        dilim = self.nolar[bas:bas + adet]
        if not dilim:
            return []
        ham = self.oturum.kayitlar(dilim)
        sonuc = []
        for no, degerler in ham:
            if degerler is None:
                sonuc.append((no, None))
                continue
            filtreli = [degerler[i] if i < len(degerler) else ""
                       for i in self.secili_kolonlar]
            sonuc.append((no, filtreli))
        return sonuc

    # -- kaldırma ----------------------------------------------------------
    def _kaldir(self, kayit_no):
        if not self.oturum.secim.cikar(kayit_no):
            return
        try:
            self.nolar.remove(kayit_no)
        except ValueError:
            pass
        self.baslik_etiket.configure(
            text=f"{units.sayi(len(self.nolar))} kayıt seçili")
        self.title(f"Seçili Veriler — {units.sayi(len(self.nolar))} kayıt")
        yeni_ust = min(self.tablo.ust, max(0, len(self.nolar) - 1))
        self.tablo.aralik_ayarla(0, len(self.nolar), ust=yeni_ust)
        if self.degisiklik_geri_cagrisi:
            self.degisiklik_geri_cagrisi()

    def _hepsini_temizle(self):
        if not self.nolar:
            return
        if not messagebox.askyesno(
                "Seçimi temizle",
                f"{units.sayi(len(self.nolar))} kayıt seçimden çıkarılacak. "
                "Onaylıyor musunuz?", parent=self):
            return
        self.oturum.secim.temizle()
        self.nolar = []
        self.baslik_etiket.configure(text="0 kayıt seçili")
        self.title("Seçili Veriler — 0 kayıt")
        self.tablo.aralik_ayarla(0, 0)
        if self.degisiklik_geri_cagrisi:
            self.degisiklik_geri_cagrisi()

    # -- panoya kopyalama (arka planda, parça parça) ------------------------
    def _kopyala(self):
        if not self.nolar:
            return
        if len(self.nolar) > KOPYALAMA_ONAY_ESIGI:
            tahmini = len(self.nolar) * KAYIT_BASINA_TAHMINI_SN
            if not messagebox.askyesno(
                    "Büyük kopyalama",
                    f"{units.sayi(len(self.nolar))} kayıt kopyalanacak; "
                    f"tahmini süre {units.sure(tahmini)}. Bu sırada bu "
                    "pencere ile çalışmaya devam edebilirsiniz. Başlatılsın "
                    "mı?", parent=self):
                return
        self.kopyala_dugme.configure(state="disabled")
        self._kopyalanan = {}
        self._kopyalama_baslangic = time.perf_counter()
        self._kopyala_adim()

    def _kopyala_adim(self):
        kalan = [no for no in self.nolar if no not in self._kopyalanan]
        if not kalan:
            self._kopyalamayi_bitir()
            return
        parca = kalan[:KOPYALAMA_PARCA]
        for no, degerler in self.oturum.kayitlar(parca):
            if degerler is not None:
                self._kopyalanan[no] = degerler
        oran = units.yuzde(len(self._kopyalanan), len(self.nolar))
        self.durum_etiket.configure(
            text=f"Kopyalanıyor… %{oran:.0f} "
                 f"({units.sayi(len(self._kopyalanan))}/{units.sayi(len(self.nolar))})")
        self.after(KOPYALAMA_ARALIGI_MS, self._kopyala_adim)

    def _kopyalamayi_bitir(self):
        sure = time.perf_counter() - self._kopyalama_baslangic
        kolon_adlari = [self.kolon_adlari[i] for i in self.secili_kolonlar]
        satirlar = ["\t".join(kolon_adlari)]
        for no in self.nolar:
            degerler = self._kopyalanan.get(no)
            if degerler is None:
                hucreler = [""] * len(self.secili_kolonlar)
            else:
                hucreler = [str(degerler[i]) if i < len(degerler) else ""
                           for i in self.secili_kolonlar]
            satirlar.append("\t".join(hucreler))
        metin = "\n".join(satirlar)
        self.clipboard_clear()
        self.clipboard_append(metin)
        self._kopyalanan = None
        self.kopyala_dugme.configure(state="normal")
        self.durum_etiket.configure(
            text=f"{units.sayi(len(self.nolar))} kayıt panoya kopyalandı "
                 f"({units.sure(sure)})." , foreground=renkler.basari())
        messagebox.showinfo(
            "Kopyalandı",
            f"{units.sayi(len(self.nolar))} kayıt, {len(kolon_adlari)} kolon "
            "panoya kopyalandı (sekme ile ayrılmış metin -- doğrudan Excel "
            "gibi bir tabloya yapıştırılabilir).", parent=self)

    # -- yerel web yayını (arka planda, parça parça) -------------------------
    def _webde_goster(self):
        if not self.nolar:
            return
        if len(self.nolar) > KOPYALAMA_ONAY_ESIGI:
            tahmini = len(self.nolar) * KAYIT_BASINA_TAHMINI_SN
            if not messagebox.askyesno(
                    "Büyük web yayını",
                    f"{units.sayi(len(self.nolar))} kayıt web sayfası için "
                    f"toplanacak; tahmini süre {units.sure(tahmini)}. Bu "
                    "sırada bu pencere ile çalışmaya devam edebilirsiniz. "
                    "Başlatılsın mı?", parent=self):
                return
        self.web_dugme.configure(state="disabled")
        self._web_toplanan = {}
        self._web_baslangic = time.perf_counter()
        self._web_adim()

    def _web_adim(self):
        kalan = [no for no in self.nolar if no not in self._web_toplanan]
        if not kalan:
            self._web_yayinla()
            return
        parca = kalan[:KOPYALAMA_PARCA]
        for no, degerler in self.oturum.kayitlar(parca):
            if degerler is not None:
                self._web_toplanan[no] = degerler
        oran = units.yuzde(len(self._web_toplanan), len(self.nolar))
        self.durum_etiket.configure(
            text=f"Web sayfası hazırlanıyor… %{oran:.0f} "
                 f"({units.sayi(len(self._web_toplanan))}/{units.sayi(len(self.nolar))})")
        self.after(KOPYALAMA_ARALIGI_MS, self._web_adim)

    def _web_yayinla(self):
        sure = time.perf_counter() - self._web_baslangic
        kolon_adlari = [self.kolon_adlari[i] for i in self.secili_kolonlar]
        baslik = f"Seçili Veriler — {units.sayi(len(self.nolar))} kayıt"
        toplanan = self._web_toplanan
        govde = sayfa_uret(baslik, kolon_adlari, self.nolar, toplanan)
        self.web_dugme.configure(state="normal")

        # Excel/Word/PDF dosyaları isteğe bağlı olarak, sunucu tarafında,
        # aynı toplanmış veriden anlık üretilir -- burada tekrar toplama
        # yapılmaz, toplanan veri sunucuya (bellekte) devredilir.
        disa_aktar_baglami = {
            "baslik": baslik, "kolon_adlari": kolon_adlari,
            "nolar": self.nolar, "veri": toplanan,
        }
        self._web_toplanan = None

        host, port = self._web_yayini.baslat(govde, disa_aktar_baglami)
        adres = self._web_yayini.adres()
        self.durum_etiket.configure(
            text=f"Web sayfası yayında: {adres} ({units.sure(sure)}).",
            foreground=renkler.basari())
        self._web_popup_goster(adres)

    def _web_popup_goster(self, adres):
        pencere = tk.Toplevel(self)
        pencere.title("Webde Göster")
        pencere.resizable(False, False)
        pencere.transient(self)

        cerceve = ttk.Frame(pencere, padding=14)
        cerceve.pack(fill="both", expand=True)

        ttk.Label(
            cerceve, text="Seçili veriler yerel ağda yayında:"
        ).pack(anchor="w")

        alt_cerceve = ttk.Frame(cerceve)
        alt_cerceve.pack(fill="x", pady=(8, 4))

        adres_kutusu = ttk.Entry(alt_cerceve, width=32)
        adres_kutusu.insert(0, adres)
        adres_kutusu.configure(state="readonly")
        adres_kutusu.pack(side="left", fill="x", expand=True)

        def _kopyala_adresi():
            pencere.clipboard_clear()
            pencere.clipboard_append(adres)
            kopyala_dugme.configure(text="Kopyalandı!")
            pencere.after(1500, lambda: kopyala_dugme.configure(text="Kopyala"))

        kopyala_dugme = ttk.Button(alt_cerceve, text="Kopyala",
                                   command=_kopyala_adresi, width=10)
        kopyala_dugme.pack(side="left", padx=(6, 0))

        ttk.Label(
            cerceve, foreground="#8a8a8a", wraplength=340,
            text="Bu adres yalnızca bu bilgisayardan (localhost) "
                 "erişilebilir ve bu pencere kapatılınca yayın durur. "
                 "Sayfa diske yazılmaz, tamamen bellekte tutulur. Açılan "
                 "sayfadaki Excel / Word / PDF düğmeleriyle bu veriler "
                 "dosya olarak indirilebilir."
        ).pack(anchor="w", pady=(6, 10))

        ttk.Button(cerceve, text="Kapat", width=10,
                  command=pencere.destroy).pack(anchor="e")

        pencere.bind("<Escape>", lambda e: pencere.destroy())
        adres_kutusu.focus_set()
        adres_kutusu.selection_range(0, "end")

    # -- doğrudan Excel/Word/PDF'e aktarma (arka planda, parça parça) ------
    #
    # "Webde Göster" akışıyla AYNI toplama mantığı (bkz. `_web_adim`), ama
    # sonuç bir localhost sayfasına değil, kullanıcının seçtiği bir dosyaya
    # yazılır. Bu YAZMA bilinçli ve kullanıcı tarafından istenmiştir --
    # "diske hiçbir şey yazılmaz" ilkesi kaynak dosyanın gizlice
    # önbelleklenmesini yasaklar, kullanıcının açıkça istediği bir çıktı
    # dosyasını değil (bkz. `exporters.py` ve `webserver.py`'deki aynı not).
    def _disa_aktar(self, bicim):
        if not self.nolar:
            return
        if len(self.nolar) > KOPYALAMA_ONAY_ESIGI:
            tahmini = len(self.nolar) * KAYIT_BASINA_TAHMINI_SN
            if not messagebox.askyesno(
                    "Büyük dışa aktarım",
                    f"{units.sayi(len(self.nolar))} kayıt dışa aktarılacak; "
                    f"tahmini süre {units.sure(tahmini)}. Bu sırada bu "
                    "pencere ile çalışmaya devam edebilirsiniz. Başlatılsın "
                    "mı?", parent=self):
                return

        uretici, uzanti, filtreler = DISA_AKTAR_BICIMLERI[bicim]
        hedef = filedialog.asksaveasfilename(
            parent=self, title="Dışa aktar", defaultextension=uzanti,
            initialfile=f"secili_veriler{uzanti}", filetypes=filtreler)
        if not hedef:
            return

        self._disa_aktar_dugmelerini_kilitle(True)
        self._disa_aktar_toplanan = {}
        self._disa_aktar_bicim = bicim
        self._disa_aktar_uretici = uretici
        self._disa_aktar_hedef = hedef
        self._disa_aktar_baslangic = time.perf_counter()
        self._disa_aktar_adim()

    def _disa_aktar_dugmelerini_kilitle(self, kilitli):
        durum = "disabled" if kilitli else "normal"
        for dugme in (self.excel_dugme, self.word_dugme, self.pdf_dugme,
                     self.kopyala_dugme, self.web_dugme):
            dugme.configure(state=durum)

    def _disa_aktar_adim(self):
        kalan = [no for no in self.nolar if no not in self._disa_aktar_toplanan]
        if not kalan:
            self._disa_aktar_bitir()
            return
        parca = kalan[:KOPYALAMA_PARCA]
        for no, degerler in self.oturum.kayitlar(parca):
            if degerler is not None:
                self._disa_aktar_toplanan[no] = degerler
        oran = units.yuzde(len(self._disa_aktar_toplanan), len(self.nolar))
        self.durum_etiket.configure(
            text=f"Dışa aktarılıyor… %{oran:.0f} "
                 f"({units.sayi(len(self._disa_aktar_toplanan))}/{units.sayi(len(self.nolar))})",
            foreground=renkler.vurgu())
        self.after(KOPYALAMA_ARALIGI_MS, self._disa_aktar_adim)

    def _disa_aktar_bitir(self):
        sure = time.perf_counter() - self._disa_aktar_baslangic
        kolon_adlari = [self.kolon_adlari[i] for i in self.secili_kolonlar]
        baslik = f"Seçili Veriler — {units.sayi(len(self.nolar))} kayıt"
        try:
            icerik = self._disa_aktar_uretici(baslik, kolon_adlari, self.nolar,
                                              self._disa_aktar_toplanan)
            with open(self._disa_aktar_hedef, "wb") as f:
                f.write(icerik)
        except OSError as e:
            self._disa_aktar_toplanan = None
            self._disa_aktar_dugmelerini_kilitle(False)
            self.durum_etiket.configure(text="Dışa aktarılamadı.",
                                        foreground=renkler.hata())
            messagebox.showerror("Dışa aktarılamadı", str(e), parent=self)
            return

        self._disa_aktar_toplanan = None
        self._disa_aktar_dugmelerini_kilitle(False)
        self.durum_etiket.configure(
            text=f"{units.sayi(len(self.nolar))} kayıt dışa aktarıldı "
                 f"({units.sure(sure)}).", foreground=renkler.basari())
        messagebox.showinfo(
            "Dışa aktarıldı",
            f"{units.sayi(len(self.nolar))} kayıt, {len(kolon_adlari)} kolon "
            f"kaydedildi:\n{self._disa_aktar_hedef}", parent=self)
