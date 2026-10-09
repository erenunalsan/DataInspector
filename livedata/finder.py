"""Kaynak dosya üzerinde akışlı metin arama.

Arama, indeksten BAĞIMSIZDIR: indeks taraması daha dosyanın başındayken bile
tüm dosyada arama yapılabilir. Çünkü arama zaten baştan sona okuyarak
ilerler ve okurken satırları da sayar -- yani her eşleşmenin satır numarasını
kendisi hesaplar.

Hız
---
Eşleşme arama tamamen C düzeyinde `bytes.find` (memchr/two-way) ile yapılır;
satır sayımı da `bytes.count` iledir. Python döngüsü yalnızca EŞLEŞME BAŞINA
çalışır, bayt başına değil. Pratikte hız diskle sınırlıdır (ölçülen ~0,37
GiB/sn), CPU ile değil.

Akış
----
Eşleşmeler bulundukça (parça parça) kuyruğa yazılır; arayüz beklemeden
göstermeye başlar. İlerleme, okunan bayt üzerinden bildirilir.

Büyük/küçük harf duyarsız arama
-------------------------------
İki yol vardır:

  - Aranan metin tamamen ASCII ise: parçanın `bytes.lower()` kopyası üzerinde
    aranır. ASCII harflerin TÜM büyük/küçük yazılışlarını eksiksiz bulur.
  - Aranan metin ASCII dışı karakter içeriyorsa (ör. "Şirket"): bayt
    düzeyinde tam bir Unicode kıvrımı yapılamaz. Bunun yerine metnin
    yaygın yazılış çeşitleri (yazıldığı gibi / küçük / BÜYÜK / İlk harf
    büyük) ayrı ayrı aranır. Bu bir yaklaşımdır ve arayüzde kullanıcıya
    açıkça bildirilir.
"""
import re
import threading
import time

from . import rowscan

VARSAYILAN_BLOK = 8 << 20
# Regex kipinde tek bir eşleşmenin en fazla bu kadar bayt sürebileceği
# varsayılır (parça sınırını aşan eşleşmeleri yakalamak için ne kadar
# geriye taranacağını belirler). Düz metin aramada tam desen uzunluğu
# bilindiğinden bu gerekmez; regex'te eşleşme uzunluğu SINIRSIZ olabileceği
# için bu, herhangi bir akışlı (streaming) arama aracının kaçınamayacağı bir
# ödünleşimdir -- bu payı aşan bir eşleşme parça sınırında kaçırılabilir.
REGEX_TASMA_PAYI = 4096
# Eşleşmenin bulunduğu satırın başını görebilmek için önceki parçadan
# taşınan bayt miktarı. Satır bundan uzunsa önizleme kırpılır (eşleşmenin
# satır NUMARASI yine de doğrudur).
GERI_BAK = 64 << 10
ILERLEME_ARALIGI = 0.20
ONIZLEME_BAYT = 600

OLAY_ESLESME = "eslesme"
OLAY_ILERLEME = "arama_ilerleme"
OLAY_BITTI = "arama_bitti"
OLAY_HATA = "arama_hata"


class Eslesme:
    """Tek bir arama isabeti."""

    __slots__ = ("satir", "ofset", "satir_basi", "onizleme", "kirpik")

    def __init__(self, satir, ofset, satir_basi, onizleme, kirpik=False):
        self.satir = satir              # 0 tabanlı veri satırı numarası
        self.ofset = ofset              # eşleşmenin mutlak bayt konumu
        self.satir_basi = satir_basi    # satırın mutlak bayt başlangıcı
        self.onizleme = onizleme        # satırın metin önizlemesi
        self.kirpik = kirpik


def tr_buyuk(metin):
    """Türkçe kurallarıyla büyük harfe çevirir (i -> İ, ı -> I).

    Python'ın `str.upper()`'ı yerel bağımsızdır ve 'i' harfini 'I' yapar;
    Türkçe metinlerde doğrusu 'İ'dir. Büyük/küçük harf duyarsız aramanın
    "ŞİRKET" gibi yazılışları da bulabilmesi için gereklidir.
    """
    return metin.replace("i", "İ").replace("ı", "I").upper()


def tr_kucuk(metin):
    """Türkçe kurallarıyla küçük harfe çevirir (I -> ı, İ -> i)."""
    return metin.replace("I", "ı").replace("İ", "i").lower()


class Desen:
    """Aranacak metnin bayt karşılık(lar)ı ve parça içinde arama mantığı."""

    def __init__(self, metin, duyarli, kodlama="utf-8", regex=False):
        # Satır sonu içeren bir desen, satır-içi eşleşme varsayımını bozar.
        # (Regex kipinde kullanıcı bilinçli olarak \n gibi bir kalıp
        # yazabileceğinden bu temizlik YALNIZCA düz metin aramada yapılır.)
        if not regex:
            metin = metin.replace("\r", " ").replace("\n", " ")
        if not metin:
            raise ValueError("Aranacak metin boş olamaz.")
        self.metin = metin
        self.duyarli = duyarli
        self.kodlama = kodlama
        self.ascii_kivrim = False
        self.yaklasik = False
        self.regex = regex

        if regex:
            # MULTILINE ZORUNLUDUR: aksi hâlde ^/$ yalnızca TARANAN PARÇANIN
            # (birden çok satırı birden içeren tampon) başında/sonunda
            # eşleşir, her SATIRIN başında/sonunda değil -- kullanıcı "^id;"
            # gibi bir desen yazdığında hiçbir eşleşme bulunamaz ya da parça
            # sınırına göre değişken sonuçlar çıkardı.
            bayrak = re.MULTILINE if duyarli else re.MULTILINE | re.IGNORECASE
            try:
                self.regex_desen = re.compile(metin.encode(kodlama, "replace"), bayrak)
            except re.error as e:
                raise ValueError(f"Geçersiz düzenli ifade: {e}") from e
            self.desenler = []
            self.uzunluk = REGEX_TASMA_PAYI
            return

        if duyarli:
            self.desenler = [metin.encode(kodlama, "replace")]
        elif metin.isascii():
            # ASCII: parçayı lower()'layıp tek desenle aramak hem eksiksiz
            # hem de en hızlı yoldur.
            self.ascii_kivrim = True
            self.desenler = [metin.lower().encode("ascii")]
        else:
            # ASCII dışı: bayt düzeyinde tam Unicode kıvrımı yapılamaz.
            # Yaygın yazılış çeşitleri (Türkçe i/İ ve ı/I kuralları dâhil)
            # ayrı ayrı aranır.
            kucuk = tr_kucuk(metin)
            cesitler = {
                metin,
                metin.lower(), metin.upper(), metin.capitalize(),
                kucuk, tr_buyuk(metin),
                kucuk[:1].upper() + kucuk[1:],          # İlk harf büyük
                tr_buyuk(kucuk[:1]) + kucuk[1:],        # Türkçe ilk harf büyük
            }
            self.desenler = sorted({c.encode(kodlama, "replace")
                                    for c in cesitler if c})
            self.yaklasik = True

        self.uzunluk = max(len(d) for d in self.desenler)

    def bul(self, veri, bas):
        """veri[bas:] içindeki eşleşme başlangıçlarını ARTAN sırada döner."""
        if self.regex:
            return [m.start() for m in self.regex_desen.finditer(veri, bas)]
        saman = veri.lower() if self.ascii_kivrim else veri
        if len(self.desenler) == 1:
            d = self.desenler[0]
            sonuc = []
            p = saman.find(d, bas)
            while p >= 0:
                sonuc.append(p)
                p = saman.find(d, p + 1)
            return sonuc
        sonuc = []
        for d in self.desenler:
            p = saman.find(d, bas)
            while p >= 0:
                sonuc.append(p)
                p = saman.find(d, p + 1)
        sonuc.sort()
        # Farklı çeşitler aynı konumda eşleşebilir; tekrarları at.
        return [p for i, p in enumerate(sonuc) if i == 0 or p != sonuc[i - 1]]


class SearchJob(threading.Thread):
    """Kaynağı akışla tarayan arama işi. Kendi dosya tanıtıcısını açar."""

    def __init__(self, bicim, index, desen, olay_kuyrugu,
                 bas_ofset=None, bas_satir=0, en_fazla=5000,
                 blok=VARSAYILAN_BLOK, geri_bak=GERI_BAK):
        super().__init__(name="livedata-search", daemon=True)
        self.bicim = bicim
        self.index = index
        self.desen = desen
        self.kuyruk = olay_kuyrugu
        self.bas_ofset = bicim.veri_basi if bas_ofset is None else bas_ofset
        self.bas_satir = bas_satir
        self.en_fazla = en_fazla
        self.blok = blok
        # Geriye bakma penceresi (a) bloktan büyük olmamalı -- aksi hâlde
        # tampon her turda büyür; (b) desenin uzunluğundan (nlen-1) KÜÇÜK
        # olmamalı -- aksi hâlde parça sınırındaki eşleşmeler ya kaçırılır
        # ya da (daha kötüsü) YİNELENİR: `tarama_bas = k - (nlen-1)` negatife
        # düşüp 0'a kenetlenirse, taranmış bir bölge yeniden taranır ve aynı
        # eşleşme iki kez bildirilir. Regex'te (`nlen` = REGEX_TASMA_PAYI)
        # bu, çağıranın fark etmeden çok küçük bir `geri_bak` geçmesi hâlinde
        # kolayca tetiklenirdi; bu yüzden burada KENDİLİĞİNDEN garanti edilir.
        gereken_en_az = min(blok, max(0, desen.uzunluk - 1))
        self.geri_bak = max(gereken_en_az, min(geri_bak, blok))

        self._iptal = threading.Event()
        self.eslesme_sayisi = 0
        self.saklanan = 0
        self.okunan_bayt = 0
        self.sure = None

    def iptal(self):
        self._iptal.set()

    def run(self):
        try:
            self._ara()
        except Exception as e:                      # noqa: BLE001
            self.kuyruk.put({"tur": OLAY_HATA, "hata": e})

    def _ara(self):
        bicim = self.bicim
        desen = self.desen
        nlen = desen.uzunluk
        tirnak_duyarli = bicim.tirnak_duyarli
        quote = ord(bicim.tirnak) if bicim.tirnak else rowscan.QUOTE

        t0 = time.perf_counter()
        son_bildirim = 0.0
        satir_no = self.bas_satir
        parity = 0
        konum = self.bas_ofset          # bir sonraki okumanın mutlak konumu
        kuyruk_bayt = b""               # önceki parçanın son GERI_BAK baytı
        kuyruk_basi = self.bas_ofset    # kuyruk_bayt'ın mutlak başlangıcı
        # Arama da kuyruk satırlarına taşmaz: kayıt bölgesiyle sınırlıdır.
        veri_sonu = getattr(bicim, "veri_sonu", bicim.boyut)
        toplam = max(0, veri_sonu - self.bas_ofset)
        dolu_bildirildi = False

        with open(bicim.yol, "rb") as f:
            f.seek(konum)
            while not self._iptal.is_set():
                kalan = veri_sonu - konum
                if kalan <= 0:
                    break
                yeni = f.read(min(self.blok, kalan))
                if not yeni:
                    break
                konum += len(yeni)
                self.okunan_bayt = konum - self.bas_ofset

                veri = kuyruk_bayt + yeni
                k = len(kuyruk_bayt)        # veri[k:] == yeni
                # Parça sınırını aşan eşleşmeleri yakalamak için biraz geriden
                # başla; daha gerisi önceki turda zaten tarandı.
                tarama_bas = k - (nlen - 1)
                if tarama_bas < 0:
                    tarama_bas = 0

                konumlar = desen.bul(veri, tarama_bas)

                yeni_eslesmeler = []
                # Satır sayımı YALNIZCA yeni baytlar üzerinde ilerler; kuyruk
                # bölgesi önceki turda sayıldı.
                sayim_pos = k
                sinir_satiri = satir_no     # parça sınırındaki satır numarası

                for p in konumlar:
                    if self._iptal.is_set():
                        break
                    self.eslesme_sayisi += 1
                    if self.saklanan >= self.en_fazla:
                        if not dolu_bildirildi:
                            dolu_bildirildi = True
                            self.kuyruk.put({
                                "tur": OLAY_ILERLEME, "doldu": True,
                                "eslesme": self.eslesme_sayisi,
                                "bayt": self.okunan_bayt, "toplam": toplam,
                                "gecen": time.perf_counter() - t0,
                            })
                        continue

                    if p < k:
                        # Sınırı aşan eşleşme: desende satır sonu olmadığı
                        # için eşleşme tek bir satırın içindedir ve o satır
                        # parça sınırındaki satırdır.
                        e_satir = sinir_satiri
                    else:
                        adet, parity = rowscan.count_rows(
                            veri, sayim_pos, p, parity, tirnak_duyarli, quote)
                        satir_no += adet
                        sayim_pos = p
                        e_satir = satir_no

                    bas_i = rowscan.row_start_before(veri, p, 0)
                    # İki ayrı durum: (a) satırın gerçek başlangıcı elimizdeki
                    # pencereden önce kaldı -> konum BİLİNMİYOR, indekse ipucu
                    # verilemez; (b) satır çok uzun olduğu için önizleme
                    # kısaltıldı -> konum yine de doğru bilinir.
                    basi_bilinmiyor = bas_i == 0 and kuyruk_basi > self.bas_ofset
                    kirpik = basi_bilinmiyor
                    son_i = veri.find(rowscan.NL, p)
                    if son_i < 0:
                        son_i = len(veri)
                    if son_i - bas_i > ONIZLEME_BAYT:
                        son_i = bas_i + ONIZLEME_BAYT
                        kirpik = True
                    onizleme = veri[bas_i:son_i].decode(bicim.kodlama, "replace")

                    satir_basi_mutlak = kuyruk_basi + bas_i
                    e = Eslesme(e_satir, kuyruk_basi + p, satir_basi_mutlak,
                                onizleme, kirpik)
                    yeni_eslesmeler.append(e)
                    self.saklanan += 1
                    # Bulunan konumu indekse ipucu olarak ver: kullanıcı
                    # indeks oraya varmamış olsa bile eşleşmeye atlayabilsin.
                    # Yalnızca satırın GERÇEK başlangıcını bildiğimizde;
                    # önizlemenin kısaltılmış olması buna engel değildir.
                    if not basi_bilinmiyor:
                        self.index.ipucu_ekle(e_satir, satir_basi_mutlak)

                # Parçanın kalanındaki satırları say (bir sonraki tur için).
                adet, parity = rowscan.count_rows(
                    veri, sayim_pos, len(veri), parity, tirnak_duyarli, quote)
                satir_no += adet

                if yeni_eslesmeler:
                    self.kuyruk.put({"tur": OLAY_ESLESME,
                                     "eslesmeler": yeni_eslesmeler})

                simdi = time.perf_counter()
                if simdi - son_bildirim >= ILERLEME_ARALIGI:
                    son_bildirim = simdi
                    gecen = simdi - t0
                    hiz = self.okunan_bayt / gecen if gecen > 0 else 0
                    self.kuyruk.put({
                        "tur": OLAY_ILERLEME,
                        "bayt": self.okunan_bayt,
                        "toplam": toplam,
                        "satir": satir_no,
                        "eslesme": self.eslesme_sayisi,
                        "gecen": gecen,
                        "hiz": hiz,
                        "kalan_sure": ((toplam - self.okunan_bayt) / hiz
                                       if hiz > 0 else None),
                    })

                # Sonraki tur için kuyruğu hazırla.
                if len(veri) > self.geri_bak:
                    kuyruk_bayt = veri[-self.geri_bak:] if self.geri_bak else b""
                    kuyruk_basi = konum - self.geri_bak
                else:
                    kuyruk_bayt = veri
                    kuyruk_basi = konum - len(veri)

        self.sure = time.perf_counter() - t0
        self.kuyruk.put({
            "tur": OLAY_BITTI,
            "iptal": self._iptal.is_set(),
            "eslesme": self.eslesme_sayisi,
            "saklanan": self.saklanan,
            "bayt": self.okunan_bayt,
            "sure": self.sure,
            "son_satir": satir_no,
        })
