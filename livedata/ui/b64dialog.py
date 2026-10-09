"""Seçili kaydın alanlarından Base64 çözme penceresi.

Çözme işlemi tamamen BELLEKTEKİ kayıt değerleri üzerinde yapılır: pencere
açıldığında kaydın alanları zaten yüklenmiştir, dolayısıyla diske gidilmez,
hiçbir şey yazılmaz ve işlem anlıktır.

Pencere iki şeyi birden sunar:

  - **Otomatik öneri**: kayıt incelenip makul bir ayar önerilir ve hemen
    uygulanır. Kaynak dosyadaki `<satır>_<kolon>_½_<yük>` düzeni gibi çok
    kolona bölünmüş yükler böylece tek tıkla çözülür.
  - **Elle ayar**: kolon seçimi ve SIRASI, önek/işaretçi, sonek, uygulama
    yeri ve alfabe -- hepsi değiştirilebilir. Otomatik öneri bir kolaylıktır,
    bir dayatma değildir.

Sonuç her zaman önce BAYT'tır; metne çevrilebiliyorsa metin sekmesinde,
çevrilemiyorsa (resim, arşiv gibi ikili yükler) onaltılık dökümde gösterilir.
"""
import tkinter as tk
from tkinter import messagebox, ttk

from .. import b64, units
from . import renkler

ISARETLI = "☑"
ISARETSIZ = "☐"


class Base64Penceresi(tk.Toplevel):
    """Tek bir kaydın alanlarından Base64 çözen pencere."""

    def __init__(self, ana, kayit_no, hucreler, kolon_adlari, taban=0):
        super().__init__(ana)
        self.title(f"Base64 Çöz — Kayıt {units.sayi(kayit_no + taban)}")
        self.geometry("1000x700")
        self.minsize(760, 560)
        self.transient(ana)

        self.hucreler = list(hucreler)
        self.kolon_adlari = list(kolon_adlari)
        self.sonuc = None
        # Kolon sırası: kullanıcı değiştirebilir. (indeks, seçili_mi)
        self.sira = [[i, True] for i in range(len(self.hucreler))]

        self.columnconfigure(0, weight=1)
        # Alan listesi, sonuç alanından daha çok yer alır: kullanıcının önce
        # HANGİ alanların hangi sırayla kullanıldığını görmesi gerekir.
        self.rowconfigure(0, weight=3)
        self.rowconfigure(2, weight=2)

        self._alanlar_bolgesi()
        self._ayar_bolgesi()
        self._sonuc_bolgesi()
        self._listeyi_ciz()

        self.bind("<Escape>", lambda e: self.destroy())
        self.after(60, self._otomatik)

    # ------------------------------------------------------------------
    def _alanlar_bolgesi(self):
        cerceve = ttk.LabelFrame(
            self, text="Kullanılacak alanlar (yukarıdan aşağıya birleştirilir)",
            padding=(8, 4))
        cerceve.grid(row=0, column=0, sticky="nsew", padx=8, pady=(8, 4))
        cerceve.columnconfigure(0, weight=1)
        cerceve.rowconfigure(0, weight=1)

        self.liste = ttk.Treeview(cerceve, show="headings", selectmode="browse",
                                  columns=("sec", "no", "ad", "deger"), height=8)
        self.liste.heading("sec", text="")
        self.liste.column("sec", width=34, anchor="center", stretch=False)
        self.liste.heading("no", text="#")
        self.liste.column("no", width=40, anchor="e", stretch=False)
        self.liste.heading("ad", text="Kolon")
        self.liste.column("ad", width=130, anchor="w", stretch=False)
        self.liste.heading("deger", text="Değer")
        self.liste.column("deger", width=620, anchor="w")
        kaydir = ttk.Scrollbar(cerceve, orient="vertical", command=self.liste.yview)
        self.liste.configure(yscrollcommand=kaydir.set)
        self.liste.grid(row=0, column=0, sticky="nsew")
        kaydir.grid(row=0, column=1, sticky="ns")
        self.liste.bind("<Button-1>", self._tikla)
        self.liste.tag_configure("secili_degil", foreground="#9a9a9a")

        dugmeler = ttk.Frame(cerceve)
        dugmeler.grid(row=0, column=2, sticky="ns", padx=(6, 0))
        ttk.Button(dugmeler, text="▲", width=4,
                   command=lambda: self._tasi(-1)).pack(pady=(0, 3))
        ttk.Button(dugmeler, text="▼", width=4,
                   command=lambda: self._tasi(1)).pack(pady=3)
        ttk.Button(dugmeler, text="Tümü", width=6,
                   command=lambda: self._hepsi(True)).pack(pady=(10, 3))
        ttk.Button(dugmeler, text="Hiçbiri", width=6,
                   command=lambda: self._hepsi(False)).pack(pady=3)

    def _ayar_bolgesi(self):
        cerceve = ttk.LabelFrame(self, text="Ayıklama", padding=(8, 4))
        cerceve.grid(row=1, column=0, sticky="ew", padx=8, pady=4)

        ust = ttk.Frame(cerceve)
        ust.pack(fill="x")
        ttk.Label(ust, text="Önek:").pack(side="left")
        self.kip = tk.StringVar(value=b64.KIP_YOK)
        for etiket, deger in (("Yok", b64.KIP_YOK),
                              ("Metnin başında", b64.KIP_BASLANGIC),
                              ("İşaretçiden sonrası", b64.KIP_ISARETCI)):
            ttk.Radiobutton(ust, text=etiket, value=deger, variable=self.kip,
                            command=self._kip_degisti).pack(side="left", padx=(6, 0))

        self.onek = tk.StringVar()
        ttk.Label(ust, text="  Metin:").pack(side="left", padx=(10, 0))
        self.onek_giris = ttk.Entry(ust, textvariable=self.onek, width=16)
        self.onek_giris.pack(side="left", padx=3)
        self.son_gecis = tk.BooleanVar(value=False)
        self.son_kutu = ttk.Checkbutton(ust, text="son geçişi",
                                        variable=self.son_gecis)
        self.son_kutu.pack(side="left", padx=(2, 0))

        ttk.Label(ust, text="  Sonek:").pack(side="left", padx=(10, 0))
        self.sonek = tk.StringVar()
        ttk.Entry(ust, textvariable=self.sonek, width=12).pack(side="left", padx=3)

        alt = ttk.Frame(cerceve)
        alt.pack(fill="x", pady=(6, 0))
        ttk.Label(alt, text="Uygula:").pack(side="left")
        self.uygula = tk.StringVar(value=b64.UYGULA_PARCA)
        ttk.Radiobutton(alt, text="Her parçaya ayrı", value=b64.UYGULA_PARCA,
                        variable=self.uygula).pack(side="left", padx=(6, 0))
        ttk.Radiobutton(alt, text="Birleşik metne", value=b64.UYGULA_BIRLESIK,
                        variable=self.uygula).pack(side="left", padx=(6, 0))

        self.bosluk_at = tk.BooleanVar(value=True)
        ttk.Checkbutton(alt, text="Boşlukları at",
                        variable=self.bosluk_at).pack(side="left", padx=(16, 0))
        self.url_alfabe = tk.BooleanVar(value=False)
        ttk.Checkbutton(alt, text="URL-güvenli alfabe (- _)",
                        variable=self.url_alfabe).pack(side="left", padx=(10, 0))

        ttk.Button(alt, text="Çöz", width=10,
                   command=self._coz).pack(side="right", padx=(6, 0))
        ttk.Button(alt, text="Otomatik Öner", width=14,
                   command=self._otomatik).pack(side="right")
        self._kip_degisti()

    def _sonuc_bolgesi(self):
        cerceve = ttk.LabelFrame(self, text="Sonuç", padding=(8, 4))
        cerceve.grid(row=2, column=0, sticky="nsew", padx=8, pady=(4, 8))
        cerceve.columnconfigure(0, weight=1)
        cerceve.rowconfigure(1, weight=1)

        ust = ttk.Frame(cerceve)
        ust.grid(row=0, column=0, sticky="ew")
        self.durum = ttk.Label(ust, text="Kayıt inceleniyor…", foreground=renkler.vurgu())
        self.durum.pack(side="left")

        self.gorunum = tk.StringVar(value="metin")
        ttk.Radiobutton(ust, text="Onaltılık döküm", value="onaltilik",
                        variable=self.gorunum,
                        command=self._goster).pack(side="right", padx=(6, 0))
        ttk.Radiobutton(ust, text="Metin", value="metin", variable=self.gorunum,
                        command=self._goster).pack(side="right")
        ttk.Button(ust, text="Panoya Kopyala", width=16,
                   command=self._kopyala).pack(side="right", padx=(0, 12))

        self.cikti = tk.Text(cerceve, wrap="word", font=("Consolas", 10),
                             state="disabled", background="#fbfbfd",
                             relief="solid", borderwidth=1)
        kaydir = ttk.Scrollbar(cerceve, orient="vertical", command=self.cikti.yview)
        self.cikti.configure(yscrollcommand=kaydir.set)
        self.cikti.grid(row=1, column=0, sticky="nsew", pady=(4, 0))
        kaydir.grid(row=1, column=1, sticky="ns", pady=(4, 0))

    # ------------------------------------------------------------------
    def _listeyi_ciz(self):
        secili = self.liste.selection()
        self.liste.delete(*self.liste.get_children())
        for konum, (indeks, isaretli) in enumerate(self.sira):
            ad = (self.kolon_adlari[indeks] if indeks < len(self.kolon_adlari)
                  else f"Kolon {indeks + 1}")
            deger = self.hucreler[indeks]
            self.liste.insert("", "end", iid=str(konum),
                              values=(ISARETLI if isaretli else ISARETSIZ,
                                      indeks + 1, ad, deger),
                              tags=() if isaretli else ("secili_degil",))
        if secili:
            try:
                self.liste.selection_set(secili)
            except tk.TclError:
                pass

    def _tikla(self, olay):
        satir = self.liste.identify_row(olay.y)
        if not satir:
            return
        if self.liste.identify_column(olay.x) == "#1":   # seçim sütunu
            konum = int(satir)
            self.sira[konum][1] = not self.sira[konum][1]
            self._listeyi_ciz()
            self.liste.selection_set(satir)
            return "break"

    def _tasi(self, yon):
        secim = self.liste.selection()
        if not secim:
            return
        konum = int(secim[0])
        yeni = konum + yon
        if not (0 <= yeni < len(self.sira)):
            return
        self.sira[konum], self.sira[yeni] = self.sira[yeni], self.sira[konum]
        self._listeyi_ciz()
        self.liste.selection_set(str(yeni))
        self.liste.see(str(yeni))

    def _hepsi(self, deger):
        for satir in self.sira:
            satir[1] = deger
        self._listeyi_ciz()

    def _kip_degisti(self):
        isaretci = self.kip.get() == b64.KIP_ISARETCI
        durum = "normal" if self.kip.get() != b64.KIP_YOK else "disabled"
        self.onek_giris.configure(state=durum)
        self.son_kutu.configure(state="normal" if isaretci else "disabled")

    # ------------------------------------------------------------------
    def _ayari_oku(self):
        kolonlar = [i for i, isaretli in self.sira if isaretli]
        return b64.Ayar(kolonlar, onek=self.onek.get(), onek_kipi=self.kip.get(),
                        sonek=self.sonek.get(), uygula=self.uygula.get(),
                        bosluk_at=self.bosluk_at.get(),
                        url_alfabe=self.url_alfabe.get(),
                        isaretci_son=self.son_gecis.get())

    def _ayari_yaz(self, ayar):
        """Önerilen ayarı denetimlere yansıtır (kullanıcı görsün ve değiştirebilsin)."""
        secili = set(ayar.kolonlar)
        self.sira = [[i, i in secili] for i in ayar.kolonlar] + \
                    [[i, False] for i in range(len(self.hucreler)) if i not in secili]
        self.kip.set(ayar.onek_kipi)
        self.onek.set(ayar.onek)
        self.sonek.set(ayar.sonek)
        self.uygula.set(ayar.uygula)
        self.bosluk_at.set(ayar.bosluk_at)
        self.url_alfabe.set(ayar.url_alfabe)
        self.son_gecis.set(ayar.isaretci_son)
        self._kip_degisti()
        self._listeyi_ciz()

    def _otomatik(self):
        ayar, sonuc, aciklama = b64.otomatik_ayar(self.hucreler)
        if ayar is None:
            self.sonuc = None
            self.durum.configure(text="Otomatik çözülemedi", foreground=renkler.uyari())
            self._metni_yaz(aciklama)
            return
        self._ayari_yaz(ayar)
        self.sonuc = sonuc
        self._durumu_yaz(sonuc, onek=aciklama + "\n")
        self._goster()

    def _coz(self):
        ayar = self._ayari_oku()
        try:
            self.sonuc = b64.coz(self.hucreler, ayar)
        except b64.CozmeHatasi as e:
            self.sonuc = None
            self.durum.configure(text="Çözülemedi", foreground=renkler.hata())
            self._metni_yaz(str(e))
            return
        self._durumu_yaz(self.sonuc)
        self._goster()

    def _durumu_yaz(self, sonuc, onek=""):
        tur = b64.tur_tahmini(sonuc.veri)
        parcalar = [f"{units.sayi(len(sonuc.veri))} bayt çözüldü"]
        if sonuc.metin_mi:
            parcalar.append(f"metin ({sonuc.kodlama})")
        else:
            parcalar.append("ikili veri — metne çevrilemiyor")
        if tur:
            parcalar.append(tur)
        self.durum.configure(text=" · ".join(parcalar), foreground=renkler.basari())
        self._acilis_onek = onek
        if not sonuc.metin_mi:
            self.gorunum.set("onaltilik")

    def _goster(self):
        if self.sonuc is None:
            return
        onek = getattr(self, "_acilis_onek", "")
        if self.gorunum.get() == "onaltilik" or not self.sonuc.metin_mi:
            govde = b64.onizleme_metni(self.sonuc.veri)
            if not self.sonuc.metin_mi and self.gorunum.get() == "metin":
                onek += ("Çözülen veri geçerli bir metin değil; onaltılık "
                         "döküm gösteriliyor.\n\n")
        else:
            govde = self.sonuc.metin
        self._metni_yaz(onek + govde)

    def _metni_yaz(self, metin):
        self.cikti.configure(state="normal")
        self.cikti.delete("1.0", "end")
        self.cikti.insert("1.0", metin)
        self.cikti.configure(state="disabled")

    def _kopyala(self):
        icerik = self.cikti.get("1.0", "end-1c")
        if not icerik.strip():
            return
        self.clipboard_clear()
        self.clipboard_append(icerik)
        messagebox.showinfo("Kopyalandı",
                            f"{len(icerik)} karakter panoya kopyalandı.",
                            parent=self)
