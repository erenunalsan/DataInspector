"""Dört biçimin (CSV/JSON/XML/YAML) ortak kayıt sözleşmesi.

Bu görüntüleyicinin bütün hızı tek bir varsayıma dayanır:

    **Bir kayıt = bir fiziksel satır.**

Bu doğruyken N. kaydın bayt konumunu bulmak, N. '\\n' baytını bulmakla
aynı şeydir; bu da `bytes.count`/`bytes.find` ile saniyede gigabaytlar
hızında yapılır (ölçülen: 3,7 GiB/sn, yani her zaman diskten hızlı).
Aynı indeks, aynı rastgele erişim ve aynı arama motoru dört biçimde de
DEĞİŞMEDEN çalışır; biçimler arasındaki tek fark üç şeydir:

    1. Kayıtlar dosyanın neresinde başlar   -> `veri_basi`
    2. Nerede biter (kuyruk hariç)          -> `veri_sonu`
    3. Bir satır nasıl hücrelere çevrilir   -> `coz()`

Gerçekten büyük veri dosyaları neredeyse her zaman bu biçimdedir (satır
satır üretilirler). Değilse -- ör. girintili/"pretty" basılmış bir JSON --
bu sessizce yanlış sonuç vermez: `bicim_tespit`, satırların kayıt olarak
çözümlenemediğini görür ve açıklayıcı bir `BicimHatasi` fırlatır.

Tespit yöntemi (biçimden bağımsız): dosyanın başındaki örnekte **kayıt
olarak çözümlenen ilk satır** veri başıdır; sonundaki örnekte **kayıt
olarak çözümlenen son satır** veri sonudur. Aradaki satırların ezici
çoğunluğu kayıt olarak çözümlenebiliyorsa biçim "satır başına bir kayıt"
sayılır. Başlık/kuyruk satırları (ör. `<?xml ...?>`, `]}`) böylece
kendiliğinden dışarıda kalır.
"""

import json

# Tespit için dosyanın başından/sonundan okunacak örnek boyu.
BAS_ORNEK = 1 << 20          # 1 MiB
SON_ORNEK = 256 << 10        # 256 KiB
# Tespitte incelenecek en fazla satır ve kabul için gereken en düşük oran.
ORNEK_SATIR = 200
KABUL_ORANI = 0.9


class BicimHatasi(Exception):
    """Kaynak dosyanın biçimi bu görüntüleyiciyle incelenemez."""


class CozumlemeHatasi(Exception):
    """Tek bir satır kayıt olarak çözümlenemedi."""


class KayitBicimi:
    """Bir kaynak dosyanın kayıt düzeni. Alt sınıflar biçime özgü kısmı verir.

    Alanlar:
      tur          -- 'csv' | 'json' | 'xml' | 'yaml'
      yol, boyut   -- dosya yolu ve bayt boyutu
      kodlama      -- 'utf-8', 'utf-8-sig', 'cp1254', ... (bayt-güvenli olmalı)
      veri_basi    -- ilk KAYIT satırının mutlak bayt konumu
      veri_sonu    -- son kayıt satırının bittiği mutlak bayt konumu
      kolonlar     -- kolon adları
      beyan_edilen_kayit -- dosya başlığı bir kayıt sayısı bildiriyorsa (JSON/XML/
                            YAML başlıklarındaki `count`), yoksa None. Tarama
                            bitince sayılan değerle karşılaştırılıp kullanıcıya
                            bildirilir -- ücretsiz bir bütünlük denetimi.
      ornek_satirlar -- ilk birkaç kaydın çözümlenmiş hâli (kolon genişliği için)
    """

    tur = "?"

    def __init__(self, yol, boyut, kodlama):
        self.yol = yol
        self.boyut = boyut
        self.kodlama = kodlama
        self.veri_basi = 0
        self.veri_sonu = boyut
        self.kolonlar = []
        self.beyan_edilen_kayit = None
        self.ornek_satirlar = []
        self.ort_satir_bayt = 0.0
        # CSV dışındaki biçimlerde satır sınırı koşulsuz '\n'dir; CSV'de
        # tırnak paritesi izlenebilir (bkz. csv_bicim).
        self.tirnak_duyarli = False
        self.ayrac = None
        self.tirnak = '"'

    # -- alt sınıfların doldurduğu kısım -------------------------------
    def coz(self, ham_satir):
        """Tek bir fiziksel satırı (bytes, '\\n' hariç) hücre listesine çevirir.

        Çözümlenemezse CozumlemeHatasi fırlatır.
        """
        raise NotImplementedError

    def kayit_mi(self, ham_satir):
        """Satır geçerli bir kayıt mı? (başlık/kuyruk satırlarını eler)"""
        if not ham_satir.strip():
            return False
        try:
            self.coz(ham_satir)
            return True
        except Exception:                       # noqa: BLE001
            return False

    def coz_liste(self, ham_satir):
        """`coz` sonucunu HER ZAMAN kolon sırasına göre liste olarak döner.

        Kayıt bir sözlükse (JSON nesnesi, YAML eşlemesi) değerler kolon
        sırasına dizilir; böylece üst katmanlar kayıt yapısından habersiz
        kalır ve tablo her biçimde aynı şekilde çizilir.
        """
        deger = self.coz(ham_satir)
        if isinstance(deger, dict):
            return [metin_deger(deger.get(ad, "")) for ad in self.kolonlar]
        return deger

    # -- ortak yardımcılar ---------------------------------------------
    @property
    def veri_bayt(self):
        return max(0, self.veri_sonu - self.veri_basi)

    def tahmini_satir_sayisi(self):
        """Ortalama satır uzunluğundan türetilen KABA tahmin (yalnızca gösterim).

        Dosya bir kayıt sayısı bildiriyorsa o kullanılır -- bildirilen değer
        bir tahminden çok daha iyidir, ama yine de KESİN sayılmaz: kesin sayı
        indeks taramasının sonucudur ve ikisi tarama bitince karşılaştırılır.
        """
        if self.beyan_edilen_kayit:
            return self.beyan_edilen_kayit
        if self.ort_satir_bayt <= 0:
            return 0
        return int(self.veri_bayt / self.ort_satir_bayt)

    def ozet(self):
        ek = f" · {self.ayrac!r} ayraç" if self.ayrac else ""
        beyan = ""
        if self.beyan_edilen_kayit:
            beyan = f" · başlıkta {self.beyan_edilen_kayit:,} kayıt bildirilmiş".replace(",", ".")
        return (f"{self.tur.upper()}{ek} · {len(self.kolonlar)} kolon · "
                f"{self.kodlama}{beyan}")


def metin_deger(deger):
    """Ham bir kayıt değerini tabloda gösterilecek metne çevirir.

    Dört biçimde de aynı kural: None boş metin; bool 'true'/'false'
    (JSON/YAML yazımıyla tutarlı); iç içe liste/sözlük JSON gösterimiyle
    (tırnaklar ve eleman sınırları korunsun diye); diğerleri str().
    """
    if deger is None:
        return ""
    if isinstance(deger, str):
        return deger
    if isinstance(deger, bool):
        return "true" if deger else "false"
    if isinstance(deger, (list, dict)):
        return json.dumps(deger, ensure_ascii=False)
    return str(deger)


def kolon_adlari(ornekler):
    """Çözümlenmiş örnek kayıtlardan kolon adlarını türetir.

    Kayıtlar sözlükse anahtarların ilk-görülme birleşimi, listeyse
    'Kolon 1'..'Kolon N' kullanılır.
    """
    if not ornekler:
        return []
    if all(isinstance(k, dict) for k in ornekler):
        adlar, gorulen = [], set()
        for kayit in ornekler:
            for anahtar in kayit:
                if anahtar not in gorulen:
                    gorulen.add(anahtar)
                    adlar.append(str(anahtar))
        return adlar
    en_uzun = max(len(k) for k in ornekler)
    return [f"Kolon {i + 1}" for i in range(en_uzun)]


def _satirlar(blok, taban_ofset):
    """Bir bayt bloğundaki TAM satırları [(mutlak_ofset, ham_satir), ...] döner.

    Bloğun sonundaki, '\\n' ile bitmeyen kısmi satır atlanır.
    """
    sonuc = []
    pos = 0
    n = len(blok)
    while pos < n:
        nl = blok.find(0x0A, pos)
        if nl < 0:
            break
        sonuc.append((taban_ofset + pos, blok[pos:nl].rstrip(b"\r")))
        pos = nl + 1
    return sonuc


def sinirlari_bul(bicim, bas_ornek=BAS_ORNEK, son_ornek=SON_ORNEK):
    """`veri_basi`, `veri_sonu`, örnek kayıtlar ve ortalama satır boyunu bulur.

    Biçimden bağımsızdır: yalnızca `bicim.kayit_mi()` / `bicim.coz()` kullanır.
    Dosyanın başında kayıt olarak çözümlenen İLK satır veri başı, sonunda
    çözümlenen SON satır veri sonudur.

    Satır başına bir kayıt varsayımı doğrulanamazsa BicimHatasi fırlatır --
    sessizce yanlış bölmektense açıkça reddetmek yeğlenir.
    """
    with open(bicim.yol, "rb") as f:
        bas_blok = f.read(min(bas_ornek, bicim.boyut))
        if bicim.boyut > son_ornek:
            f.seek(bicim.boyut - son_ornek)
            son_taban = bicim.boyut - son_ornek
            son_blok = f.read(son_ornek)
        else:
            son_taban, son_blok = 0, bas_blok

    bas_satirlar = _satirlar(bas_blok, 0)[:ORNEK_SATIR]
    if not bas_satirlar:
        raise BicimHatasi(
            f"Dosyanın ilk {len(bas_blok)} baytında hiç satır sonu yok. Bu "
            "görüntüleyici kayıtların satır satır yazıldığı dosyalar içindir; "
            "tek satıra sıkıştırılmış (minified) ya da girintili basılmış bir "
            "dosya bu ekranda açılamaz.")

    # -- veri başı: kayıt olarak çözümlenen ilk satır
    ilk_index = None
    for i, (ofset, ham) in enumerate(bas_satirlar):
        if bicim.kayit_mi(ham):
            ilk_index = i
            bicim.veri_basi = ofset
            break
    if ilk_index is None:
        raise BicimHatasi(
            f"Dosyanın başındaki {len(bas_satirlar)} satırın hiçbiri geçerli bir "
            f"{bicim.tur.upper()} kaydı olarak çözümlenemedi. Kayıtlar satır satır "
            "yazılmamış olabilir (girintili/'pretty' biçim) ya da dosya beklenen "
            "yapıda değil.")

    # -- satır başına bir kayıt varsayımını doğrula
    aday = bas_satirlar[ilk_index:ilk_index + ORNEK_SATIR]
    kayit_sayisi = sum(1 for _, ham in aday if bicim.kayit_mi(ham))
    if len(aday) >= 5 and kayit_sayisi / len(aday) < KABUL_ORANI:
        raise BicimHatasi(
            f"Dosyanın başındaki {len(aday)} satırın yalnızca {kayit_sayisi} tanesi "
            f"geçerli bir {bicim.tur.upper()} kaydı. Bu ekran 'bir satır = bir "
            "kayıt' düzenindeki dosyalar içindir; kayıtları birden çok satıra "
            "yayılmış bir dosyayı doğru numaralandıramaz.")

    # -- veri sonu: kayıt olarak çözümlenen son satır
    son_satirlar = _satirlar(son_blok, son_taban)
    bicim.veri_sonu = bicim.boyut
    for ofset, ham in reversed(son_satirlar):
        if ofset < bicim.veri_basi:
            break
        if bicim.kayit_mi(ham):
            # Satırın kendisi + sonundaki '\n' (ve varsa '\r')
            bicim.veri_sonu = min(bicim.boyut, ofset + len(ham) + 1)
            with open(bicim.yol, "rb") as f:
                f.seek(bicim.veri_sonu - 1)
                if f.read(1) == b"\r":
                    bicim.veri_sonu += 1
            break

    # -- örnek kayıtlar ve ortalama satır boyu
    ornek_ham = [ham for _, ham in aday if bicim.kayit_mi(ham)][:10]
    bicim.ornek_satirlar = [bicim.coz(ham) for ham in ornek_ham]
    if ornek_ham:
        bicim.ort_satir_bayt = sum(len(h) + 1 for h in ornek_ham) / len(ornek_ham)
    return bicim
