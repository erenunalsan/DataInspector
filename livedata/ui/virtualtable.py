"""Sanal tablo: 100.000 satırlık bir sayfayı, yalnızca GÖRÜNEN satırları
gerçekleyerek gösteren ttk.Treeview sarmalayıcısı.

Neden sanal?
------------
ttk.Treeview'e 100.000 satır eklemek hem saniyeler sürer hem de her satır
için Tk tarafında nesne ayırdığından yüzlerce MB RAM yer. Oysa ekranda aynı
anda en fazla ~40 satır görünür. Bu bileşen Treeview'de YALNIZCA görünen
satır kadar öğe tutar (ör. 40 adet) ve kaydırma sırasında bu öğelerin
DEĞERLERİNİ günceller -- öğe ekleyip silmez. Sonuç:

  - Kaydırma sabit maliyetlidir (sayfa 100.000 da olsa 400 milyon da olsa).
  - Tk tarafındaki bellek kullanımı ekran boyuyla sınırlıdır.
  - Kaydırma çubuğu, gerçek öğe sayısından bağımsız olarak elle sürülür.

Veri, `saglayici(bas, adet)` geri çağrısıyla istenir. Sağlayıcı henüz
yüklenmemiş satırlar için None döndürebilir; o satırlar "…" yer tutucusuyla
çizilir ve veri geldiğinde `yenile()` ile yerine oturur. Böylece arayüz
hiçbir zaman veri beklemez.

İşaretleme (çoklu seçim) sütunu
--------------------------------
`secili_mi`/`secim_degistir` verilirse tabloya, kaydın SEÇİM DURUMUNU
gösteren tıklanabilir bir sütun eklenir (☑/☐). Bu, Tk'nin kendi tekli satır
seçiminden (`tree.selection()`, "browse" kipi -- ayrıntı/Base64 gibi TEK bir
kaydı hedefleyen eylemler için kullanılır) tamamen ayrı bir mekanizmadır:
kayıt NUMARASINA bağlıdır, ekranda o an görünüp görünmediğinden bağımsız
olarak kalıcıdır (kaydırma, sayfa değişimi, sıralama arasında korunur).
Durumun kendisi bu bileşende TUTULMAZ -- her `yenile()`'de `secili_mi(no)`
sorularak yeniden çizilir; böylece tek doğruluk kaynağı çağıranın elindeki
küme olur (bkz. selection.py).
"""
from tkinter import ttk

from . import renkler

SATIR_YUKSEKLIGI = 20
BASLIK_YUKSEKLIGI = 26
TEKER_SATIR = 3            # fare tekerinin bir tıkında kayılacak satır

ISARETLI = "☑"
ISARETSIZ = "☐"


class SanalTablo(ttk.Frame):
    """Sabit sayıda Treeview öğesiyle sınırsız satır gösteren tablo."""

    def __init__(self, parent, saglayici, sinir_asildi=None,
                 secim_degisti=None, secili_mi=None, secim_degistir=None,
                 **kw):
        super().__init__(parent, **kw)
        self.saglayici = saglayici
        self.sinir_asildi = sinir_asildi      # (yon) -> bool: sayfa değiştirildi mi
        self.secim_degisti = secim_degisti
        # İşaretleme sütunu yalnızca ikisi de verilmişse eklenir.
        self.secili_mi = secili_mi
        self.secim_degistir = secim_degistir
        self.isaretleme_aktif = secili_mi is not None and secim_degistir is not None

        self.kolonlar = []
        self.aralik_bas = 0        # bu görünümün ilk MUTLAK satırı
        self.aralik_adet = 0       # görünümün kapsadığı satır sayısı (sayfa boyu)
        self.ust = 0               # aralık içindeki ilk görünür satır (göreli)
        # Başlangıçta küçük: <Configure> olayında kullanılabilir yüksekliğe
        # göre büyütülür. Büyük başlarsa grid, pencereye sığmayan bir asgari
        # yükseklik ister ve alttaki ilerleme bölgesi kırpılır.
        self.gorunur = 6
        self.taban = 0             # satır numarası gösteriminde 0 ya da 1
        self.vurgulu_satir = None  # arama sonucu vb. için mutlak satır
        self.secili_mutlak = None

        stil = ttk.Style(self)
        stil.configure("Sanal.Treeview", rowheight=SATIR_YUKSEKLIGI,
                       font=("Consolas", 9))
        stil.configure("Sanal.Treeview.Heading", font=("Segoe UI", 9, "bold"))

        # DİKKAT: Treeview'in `height` seçeneği yalnızca İSTENEN boyutu
        # belirler; widget `sticky="nsew"` ile hücresine zaten yayılır ve
        # kaç satır çizeceğini GERÇEK pikselinden bulur. Bu yüzden `height`
        # kalıcı olarak 1'de tutulur. Aksi hâlde "kullanılabilir alana göre
        # height'ı büyüt" bir geri besleme döngüsü kurar: tablo büyür ->
        # PanedWindow daha çok yükseklik ister -> grid, en alttaki ilerleme
        # bölgesini pencereden dışarı taşırır.
        self.tree = ttk.Treeview(self, show="headings", selectmode="browse",
                                 style="Sanal.Treeview", height=1)
        self.dikey = ttk.Scrollbar(self, orient="vertical", command=self._kaydir)
        self.yatay = ttk.Scrollbar(self, orient="horizontal",
                                   command=self.tree.xview)
        self.tree.configure(xscrollcommand=self.yatay.set)

        self.tree.grid(row=0, column=0, sticky="nsew")
        self.dikey.grid(row=0, column=1, sticky="ns")
        self.yatay.grid(row=1, column=0, sticky="ew")
        self.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)

        self.tema_yenile()

        # Yeniden boyutlanmayı çerçeveden değil, Treeview'in KENDİ
        # pikselinden dinle: görünür satır sayısı buradan tam çıkar.
        self.tree.bind("<Configure>", self._yeniden_boyutla)
        self.tree.bind("<MouseWheel>", self._teker)
        self.tree.bind("<Button-4>", lambda e: self._satir_kaydir(-TEKER_SATIR))
        self.tree.bind("<Button-5>", lambda e: self._satir_kaydir(TEKER_SATIR))
        self.tree.bind("<Up>", lambda e: self._tus(-1))
        self.tree.bind("<Down>", lambda e: self._tus(1))
        self.tree.bind("<Prior>", lambda e: self._tus(-self.gorunur))
        self.tree.bind("<Next>", lambda e: self._tus(self.gorunur))
        self.tree.bind("<Home>", lambda e: self._tus(-10 ** 12))
        self.tree.bind("<End>", lambda e: self._tus(10 ** 12))
        self.tree.bind("<<TreeviewSelect>>", self._secim)
        if self.isaretleme_aktif:
            # Instance seviyesindeki bu binding, Treeview'in kendi sınıf
            # binding'inden ÖNCE çalışır (Tk bindtag sırası); işaretleme
            # sütununa tıklanınca "break" ile sınıf binding'ini durdurup
            # o tıklamanın "current row"u değiştirmesini önler.
            self.tree.bind("<Button-1>", self._tikla)
            self.tree.bind("<space>", self._bosluk_tus)

        self._ogeleri_kur()

    # -- kurulum -------------------------------------------------------
    def tema_yenile(self):
        """Satır etiketlerinin (zebra deseni, bekliyor/uyumsuz/vurgu/
        işaretli) rengini o anki açık/koyu temaya göre tazeler (bkz.
        `renkler.py`). Açılışta bir kez, tema değiştirildiğinde de tekrar
        çağrılmalıdır -- aksi hâlde ör. koyu temada tablo satırları açık
        pastel renklerde kalırdı."""
        r = renkler.tablo_renkleri()
        self.tree.tag_configure("tek", background=r["tek"])
        self.tree.tag_configure("cift", background=r["cift"])
        self.tree.tag_configure("bekliyor", background=r["bekliyor_zemin"],
                                foreground=r["bekliyor_metin"])
        self.tree.tag_configure("uyumsuz", background=r["uyumsuz"])
        self.tree.tag_configure("vurgu", background=r["vurgu"])
        self.tree.tag_configure("bos", background=r["bos_zemin"],
                                foreground=r["bos_metin"])
        # İşaretli satır: vurgu (arama sonucu) rengiyle karışmasın diye ayrı
        # ve göze çarpan bir renk; tag sırası nedeniyle "vurgu"dan SONRA
        # eklenir ki ikisi birden geçerliyse işaretli rengi kazansın.
        self.tree.tag_configure("isaretli", background=r["isaretli"])

    def kolonlari_ayarla(self, kolonlar, genislikler=None):
        self.kolonlar = list(kolonlar)
        kimlikler = (["#isaret"] if self.isaretleme_aktif else []) + \
            ["#satir"] + [f"k{i}" for i in range(len(self.kolonlar))]
        self.tree["displaycolumns"] = ()
        self.tree["columns"] = kimlikler
        self.tree["displaycolumns"] = kimlikler

        if self.isaretleme_aktif:
            self.tree.heading("#isaret", text=ISARETSIZ,
                              command=self._basliktan_isaretle)
            self.tree.column("#isaret", width=28, minwidth=26, anchor="center",
                             stretch=False)
        self.tree.heading("#satir", text="Satır #")
        self.tree.column("#satir", width=110, minwidth=70, anchor="e",
                         stretch=False)
        for i, ad in enumerate(self.kolonlar):
            kid = f"k{i}"
            self.tree.heading(kid, text=ad)
            g = 160
            if genislikler and i < len(genislikler):
                g = max(60, min(460, genislikler[i]))
            self.tree.column(kid, width=g, minwidth=50, anchor="w", stretch=False)
        self._ogeleri_kur()

    def _bos_degerler(self):
        n = len(self.kolonlar) + 1 + (1 if self.isaretleme_aktif else 0)
        return [""] * n

    def _ogeleri_kur(self):
        """Treeview'de tam olarak `gorunur` adet öğe bulundurur."""
        mevcut = self.tree.get_children()
        gerek = self.gorunur
        if len(mevcut) > gerek:
            for iid in mevcut[gerek:]:
                self.tree.delete(iid)
        elif len(mevcut) < gerek:
            bos = self._bos_degerler()
            for i in range(len(mevcut), gerek):
                self.tree.insert("", "end", iid=f"s{i}", values=bos)

    def _yeniden_boyutla(self, event):
        """Treeview'in gerçek yüksekliğinden görünür satır sayısını türetir."""
        n = max(1, (event.height - BASLIK_YUKSEKLIGI) // SATIR_YUKSEKLIGI)
        if n == self.gorunur:
            return
        self.gorunur = n
        self._ogeleri_kur()
        self.yenile()

    # -- konumlandırma -------------------------------------------------
    def aralik_ayarla(self, bas, adet, ust=0):
        """Görünümün kapsadığı MUTLAK satır aralığını belirler (bir sayfa)."""
        self.aralik_bas = bas
        self.aralik_adet = max(0, adet)
        self.ust = max(0, min(ust, self._en_fazla_ust()))
        self.yenile()

    def _en_fazla_ust(self):
        return max(0, self.aralik_adet - self.gorunur)

    def ust_ayarla(self, yeni_ust, sinir_kontrol=True):
        """Görünür pencerenin üst satırını (aralığa göreli) değiştirir."""
        if sinir_kontrol and self.sinir_asildi is not None:
            if yeni_ust < 0:
                if self.sinir_asildi(-1):
                    return
            elif yeni_ust > self._en_fazla_ust():
                if self.sinir_asildi(+1):
                    return
        yeni_ust = max(0, min(yeni_ust, self._en_fazla_ust()))
        if yeni_ust == self.ust:
            self._kaydirici_guncelle()
            return
        self.ust = yeni_ust
        self.yenile()

    def satira_git(self, mutlak_satir, ortala=True):
        """Mutlak bir satırı görünür yapar (aralık içinde olmalıdır)."""
        goreli = mutlak_satir - self.aralik_bas
        if ortala:
            hedef = goreli - self.gorunur // 2
        else:
            hedef = goreli
        self.vurgulu_satir = mutlak_satir
        self.secili_mutlak = mutlak_satir
        self.ust_ayarla(hedef, sinir_kontrol=False)

    def gorunur_aralik(self):
        """Şu anda ekranda olan (ilk_mutlak, adet)."""
        return self.aralik_bas + self.ust, min(self.gorunur,
                                               self.aralik_adet - self.ust)

    # -- olaylar -------------------------------------------------------
    def _teker(self, event):
        adim = -1 if event.delta > 0 else 1
        self._satir_kaydir(adim * TEKER_SATIR)
        return "break"

    def _satir_kaydir(self, miktar):
        self.ust_ayarla(self.ust + miktar)

    def _tus(self, miktar):
        self._satir_kaydir(miktar)
        return "break"

    def _kaydir(self, *args):
        if not args:
            return
        if args[0] == "moveto":
            oran = float(args[1])
            self.ust_ayarla(int(round(oran * self.aralik_adet)))
        elif args[0] == "scroll":
            miktar = int(args[1])
            birim = args[2]
            if birim == "units":
                self._satir_kaydir(miktar)
            else:
                self._satir_kaydir(miktar * self.gorunur)

    def _kaydirici_guncelle(self):
        toplam = max(1, self.aralik_adet)
        ilk = min(1.0, self.ust / toplam)
        son = min(1.0, (self.ust + self.gorunur) / toplam)
        if son <= ilk:
            son = min(1.0, ilk + 1e-4)
        self.dikey.set(ilk, son)

    def _secim(self, _event):
        sec = self.tree.selection()
        if not sec:
            return
        try:
            i = int(sec[0][1:])
        except ValueError:
            return
        mutlak = self.aralik_bas + self.ust + i
        if mutlak >= self.aralik_bas + self.aralik_adet:
            return
        self.secili_mutlak = mutlak
        if self.secim_degisti:
            self.secim_degisti(mutlak)

    def _satir_no_at(self, satir_iid, olay_x=None):
        """'s7' gibi bir öğe kimliğinden MUTLAK kayıt numarasını üretir."""
        try:
            i = int(satir_iid[1:])
        except ValueError:
            return None
        mutlak = self.aralik_bas + self.ust + i
        if mutlak >= self.aralik_bas + self.aralik_adet:
            return None
        return mutlak

    def _tikla(self, olay):
        """İşaretleme sütununa tıklanınca kaydın seçim durumunu değiştirir.

        Yalnızca işaretleme sütunundaki tıklamalarda "break" döner; diğer
        sütunlardaki tıklamalar Treeview'in kendi (tekli) satır seçimine
        olduğu gibi devam eder.
        """
        satir_iid = self.tree.identify_row(olay.y)
        if not satir_iid:
            return None
        sutun_id = self.tree.identify_column(olay.x)
        try:
            konum = int(sutun_id[1:]) - 1
            kimlik = self.tree["displaycolumns"][konum]
        except (ValueError, IndexError):
            return None
        if kimlik != "#isaret":
            return None
        mutlak = self._satir_no_at(satir_iid)
        if mutlak is not None:
            self.secim_degistir(mutlak)
            self.yenile()
        return "break"

    def _bosluk_tus(self, _olay):
        """Boşluk tuşu: o an odaklı (Tk 'current') satırın işaretini değiştirir."""
        if self.secili_mutlak is not None:
            self.secim_degistir(self.secili_mutlak)
            self.yenile()
        return "break"

    def _basliktan_isaretle(self):
        """İşaretleme sütununun başlığına tıklamak, o an EKRANDA GÖRÜNEN
        satırların tümünü tek seferde işaretler/kaldırır (çoğunluğa göre)."""
        if not self.isaretleme_aktif:
            return
        kalan = max(0, self.aralik_adet - self.ust)
        adet = min(self.gorunur, kalan)
        if adet <= 0:
            return
        veri = self.saglayici(self.aralik_bas + self.ust, adet)
        nolar = [no for no, _ in veri]
        if not nolar:
            return
        hepsi_isaretli = all(self.secili_mi(no) for no in nolar)
        for no in nolar:
            simdi = self.secili_mi(no)
            if hepsi_isaretli and simdi:
                self.secim_degistir(no)
            elif not hepsi_isaretli and not simdi:
                self.secim_degistir(no)
        self.yenile()

    # -- çizim ---------------------------------------------------------
    def yenile(self):
        """Görünür satırları sağlayıcıdan alıp öğelerin değerlerini günceller."""
        if not self.kolonlar:
            self._kaydirici_guncelle()
            return
        kalan = max(0, self.aralik_adet - self.ust)
        adet = min(self.gorunur, kalan)
        veri = self.saglayici(self.aralik_bas + self.ust, adet) if adet else []
        kolon_sayisi = len(self.kolonlar)
        bos = self._bos_degerler()

        for i in range(self.gorunur):
            iid = f"s{i}"
            if i >= len(veri):
                self.tree.item(iid, values=bos, tags=("bos",))
                continue
            satir_no, degerler = veri[i]
            numara = satir_no + self.taban
            isaret_hucre = []
            isaretli = False
            if self.isaretleme_aktif:
                isaretli = self.secili_mi(satir_no)
                isaret_hucre = [ISARETLI if isaretli else ISARETSIZ]

            if degerler is None:
                # Bekleyen (henüz yüklenmemiş) satırda "bekliyor" rengi her
                # zaman kazanır -- veri gelene kadar işaretli olsa bile
                # kullanıcı önce "yükleniyor" durumunu görmelidir.
                self.tree.item(
                    iid, values=isaret_hucre + [numara] + ["…"] * kolon_sayisi,
                    tags=("bekliyor",))
                continue
            uyumsuz = len(degerler) != kolon_sayisi
            if uyumsuz:
                hucreler = list(degerler[:kolon_sayisi])
                hucreler += [""] * (kolon_sayisi - len(hucreler))
            else:
                hucreler = degerler
            if satir_no == self.vurgulu_satir:
                etiket = "vurgu"
            elif uyumsuz:
                etiket = "uyumsuz"
            else:
                etiket = "cift" if (satir_no % 2) else "tek"
            # "isaretli" SON sırada: aynı satır hem vurgulu/uyumsuz hem
            # işaretliyse, işaretli rengi (kullanıcının kendi eylemi) diğer
            # otomatik renklerin üzerine çıkar.
            etiketler = (etiket, "isaretli") if isaretli else (etiket,)
            self.tree.item(iid, values=isaret_hucre + [numara] + list(hucreler),
                           tags=etiketler)

        # Seçimi (varsa) görünür öğeye yeniden bağla.
        if self.secili_mutlak is not None:
            i = self.secili_mutlak - (self.aralik_bas + self.ust)
            if 0 <= i < adet:
                self.tree.selection_set(f"s{i}")
            else:
                self.tree.selection_remove(*self.tree.selection())

        self._kaydirici_guncelle()

    def secili_degerler(self):
        """Seçili satırın (mutlak_satir, degerler) çiftini döner; yoksa None."""
        if self.secili_mutlak is None:
            return None
        i = self.secili_mutlak - (self.aralik_bas + self.ust)
        if not (0 <= i < self.gorunur):
            return None
        veri = self.tree.item(f"s{i}", "values")
        if not veri:
            return None
        kayma = 1 if self.isaretleme_aktif else 0
        return self.secili_mutlak, list(veri[1 + kayma:])
