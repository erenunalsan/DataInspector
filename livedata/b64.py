"""Seçili kaydın alanlarından Base64 çözümleme.

Bu, kriptografik bir şifre çözme DEĞİLDİR; yalnızca bir kodlama
dönüşümüdür. Base64, ikili veriyi metinle taşımak için kullanılır ve
herkesin çözebileceği açık bir kodlamadır.

Neden ayrı bir modül?
---------------------
Base64 yükü çoğu zaman tek bir hücrede durmaz:

  - Birden çok kolona BÖLÜNMÜŞ olabilir; parçaların doğru sırayla
    birleştirilmesi gerekir.
  - Her parçanın başında taşıyıcı bir ÖNEK bulunabilir (ör. kaynak
    dosyadaki `16481845_0_½_` gibi bir satır/kolon damgası).
  - Sonda bir SONEK olabilir.

Bu modül bu üç durumu tek bir sözleşmede toplar ve hiçbirini tahmin etmek
zorunda bırakmaz: `Ayar` ile ne yapılacağı açıkça söylenir. Kolaylık için
`otomatik_ayar()` bir kaydı inceleyip makul bir ayar ÖNERİR -- ama öneri,
kullanıcının onayına sunulur ve her alanı elle değiştirilebilir.

Ayıklama kuralları (bilinçli):
  - Önek/sonek ayıklaması `str.strip()` ile YAPILMAZ. `strip()` bir karakter
    KÜMESİ siler; ör. `"abc".strip("ab")` -> `"c"` beklenirken `"_x_".strip("_")`
    her iki uçtaki tüm `_`leri siler. Burada her zaman birebir alt-dize
    eşleşmesi kullanılır.
  - `İŞARETÇİ` kipinde önek, metnin BAŞINDA olmak zorunda değildir: metinde
    aranır ve işaretçiye kadarki kısım (işaretçi dâhil) atılır. Kaynak
    dosyadaki `<satır>_<kolon>_½_<yük>` düzeni tam olarak bunu gerektirir --
    her hücrenin öneki farklıdır ama ortak bir işaretçi vardır.
  - Çözümlemenin sonucu HER ZAMAN bytes'tır. Metne çevirmek ayrı ve isteğe
    bağlı bir adımdır; ikili bir yük (resim, zip) metin değildir ve öyleymiş
    gibi gösterilmez.
"""
import base64
import binascii
import re

# Standart Base64 alfabesi (RFC 4648 §4) ve URL-güvenli değişkesi (§5).
ALFABE_STANDART = set(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/=")
ALFABE_URL = set(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_=")

# Önek kipleri
KIP_YOK = "yok"              # hiçbir şey atılmaz
KIP_BASLANGIC = "baslangic"  # metin tam olarak önekle BAŞLAMALIDIR
KIP_ISARETCI = "isaretci"    # önek metin İÇİNDE aranır, oraya kadarki kısım atılır

# Uygulama yeri
UYGULA_PARCA = "parca"       # önek/sonek her parçaya ayrı ayrı
UYGULA_BIRLESIK = "birlesik"  # önek/sonek birleştirilmiş metne bir kez

# Otomatik öneride bir adayın "anlamlı" sayılması için gereken en az yük
# uzunluğu: 4 karakterlik bir Base64 yükü 3 bayt eder ve rastgele veriyle
# kolayca karıştırılır.
EN_AZ_YUK = 8


class CozmeHatasi(Exception):
    """Base64 çözümleme sırasında oluşan, kullanıcıya gösterilebilir hata.

    Mesajlarda kaynak dosyadaki GERÇEK hücre içeriği yer almaz; yalnızca
    kullanıcının kendi girdiği yapılandırma metni (önek/sonek) ve konum
    bilgisi geçer.
    """


class Ayar:
    """Bir kaydın hangi alanlarının nasıl Base64 çözüleceğini tanımlar.

    kolonlar  -- kullanılacak kolon indeksleri, İSTENEN SIRAYLA (0 tabanlı)
    onek      -- atılacak önek/işaretçi metni
    onek_kipi -- KIP_YOK | KIP_BASLANGIC | KIP_ISARETCI
    sonek     -- atılacak sonek metni ("" ise atlanır)
    uygula    -- UYGULA_PARCA | UYGULA_BIRLESIK
    bosluk_at -- birleştirmeden önce boşluk/satır sonu karakterlerini at
    url_alfabe-- URL-güvenli alfabeyle çöz (- ve _ yerine + ve /)
    isaretci_son -- işaretçi birden çok geçiyorsa sonuncusu esas alınsın
    """

    def __init__(self, kolonlar, onek="", onek_kipi=KIP_YOK, sonek="",
                 uygula=UYGULA_PARCA, bosluk_at=True, url_alfabe=False,
                 isaretci_son=False):
        self.kolonlar = list(kolonlar)
        self.onek = onek
        self.onek_kipi = onek_kipi
        # İşaretçi metinde birden çok kez geçiyorsa hangisi esas alınsın?
        # False -> ilk geçiş, True -> son geçiş. Ayrımı kullanıcıya bırakmak
        # gerekir: "_" gibi kısa bir işaretçide ilk ve son geçiş bambaşka
        # yerlerdir ve hangisinin doğru olduğunu yalnızca veri bilir.
        self.isaretci_son = isaretci_son
        self.sonek = sonek
        self.uygula = uygula
        self.bosluk_at = bosluk_at
        self.url_alfabe = url_alfabe

    def ozet(self):
        parcalar = [f"kolon {', '.join(str(k + 1) for k in self.kolonlar)}"]
        if self.onek_kipi == KIP_ISARETCI:
            nere = "son" if self.isaretci_son else "ilk"
            parcalar.append(f"{nere} {self.onek!r} işaretçisinden sonrası")
        elif self.onek_kipi == KIP_BASLANGIC:
            parcalar.append(f"önek {self.onek!r} atılarak")
        if self.sonek:
            parcalar.append(f"sonek {self.sonek!r} atılarak")
        parcalar.append("her parçaya" if self.uygula == UYGULA_PARCA
                        else "birleşik metne")
        if self.url_alfabe:
            parcalar.append("URL-güvenli alfabe")
        return " · ".join(parcalar)


class Sonuc:
    """Çözümleme sonucu."""

    def __init__(self, veri, b64_metin, ayar, metin=None, kodlama=None):
        self.veri = veri              # bytes -- ham çözüm sonucu
        self.b64_metin = b64_metin    # çözümlenen Base64 metni (ayıklanmış)
        self.ayar = ayar
        self.metin = metin            # metne çevrilebildiyse str, yoksa None
        self.kodlama = kodlama        # metni üreten kodlama adı

    @property
    def metin_mi(self):
        return self.metin is not None


def _onek_sonek_at(metin, ayar, etiket):
    """Bir metin parçasından önek/işaretçi ve soneki ayıklar."""
    if ayar.onek_kipi == KIP_BASLANGIC and ayar.onek:
        if not metin.startswith(ayar.onek):
            raise CozmeHatasi(
                f"{etiket}: metin beklenen önekle başlamıyor ({ayar.onek!r}). "
                "Önek kipini 'İşaretçi' yapmayı deneyin — işaretçi metnin "
                "başında olmak zorunda değildir.")
        metin = metin[len(ayar.onek):]
    elif ayar.onek_kipi == KIP_ISARETCI:
        if not ayar.onek:
            raise CozmeHatasi("İşaretçi kipinde işaretçi metni boş olamaz.")
        yer = (metin.rfind(ayar.onek) if ayar.isaretci_son
               else metin.find(ayar.onek))
        if yer < 0:
            raise CozmeHatasi(
                f"{etiket}: belirtilen işaretçi bulunamadı ({ayar.onek!r}).")
        metin = metin[yer + len(ayar.onek):]

    if ayar.sonek:
        if not metin.endswith(ayar.sonek):
            raise CozmeHatasi(
                f"{etiket}: metin beklenen sonekle bitmiyor ({ayar.sonek!r}).")
        metin = metin[:len(metin) - len(ayar.sonek)]
    return metin


def b64_metni_cikar(hucreler, ayar):
    """Seçili hücrelerden çözülecek Base64 metnini üretir (henüz çözmez)."""
    if not ayar.kolonlar:
        raise CozmeHatasi("En az bir kolon seçilmelidir.")

    parcalar = []
    for k in ayar.kolonlar:
        if k < 0 or k >= len(hucreler):
            raise CozmeHatasi(
                f"Kolon {k + 1} bu kayıtta yok (kayıtta {len(hucreler)} alan var).")
        parca = hucreler[k]
        if ayar.uygula == UYGULA_PARCA:
            parca = _onek_sonek_at(parca, ayar, f"Kolon {k + 1}")
        parcalar.append(parca)

    metin = "".join(parcalar)
    if ayar.uygula == UYGULA_BIRLESIK:
        metin = _onek_sonek_at(metin, ayar, "Birleşik metin")
    if ayar.bosluk_at:
        metin = re.sub(r"\s+", "", metin)
    return metin


def coz(hucreler, ayar, metin_kodlamalari=("utf-8", "cp1254", "latin-1")):
    """Seçili hücreleri Base64 olarak çözer ve `Sonuc` döner.

    Dolgu ('=') eksikse tamamlanır: bir kaydın son parçası bazen dolgusuz
    saklanır ve bu, çözümlemeyi gereksiz yere başarısız kılar.
    """
    b64 = b64_metni_cikar(hucreler, ayar)
    if not b64:
        raise CozmeHatasi("Ayıklama sonrası çözülecek metin kalmadı.")

    gecerli = ALFABE_URL if ayar.url_alfabe else ALFABE_STANDART
    disarda = {c for c in b64 if c not in gecerli}
    if disarda:
        ornek = "".join(sorted(disarda)[:6])
        raise CozmeHatasi(
            f"Metin Base64 alfabesine ait olmayan {len(disarda)} farklı karakter "
            f"içeriyor (ör. {ornek!r}). Önek/işaretçi ayarı yanlış olabilir ya da "
            "bu alan Base64 değildir."
            + ("" if ayar.url_alfabe else
               " Veri URL-güvenli Base64 ise ('-' ve '_') o seçeneği işaretleyin."))

    # Dolgu tamamlama. Dolgusuz bir Base64 metninin uzunluğu 4'e bölündüğünde
    # 0, 2 ya da 3 kalanını verebilir; kalan 1 hiçbir zaman geçerli değildir
    # (tek bir Base64 karakteri 6 bit taşır, bu da bir bayt etmez). Kalan 1,
    # eksik tamamlanacak 3 dolgu karakteri demektir -- yani `eksik == 3` hata
    # durumudur. Kaynak dosyalarda son parça çoğu zaman dolgusuz saklandığı
    # için 2 ve 3 kalanları sessizce tamamlanır.
    eksik = (-len(b64)) % 4
    if eksik == 3:
        raise CozmeHatasi(
            f"Base64 uzunluğu geçersiz ({len(b64)} karakter): 4'e bölümünden "
            "kalan 1 olamaz. Parçalar eksik ya da sıraları yanlış olabilir.")
    b64_dolgulu = b64 + "=" * eksik

    cozucu = base64.urlsafe_b64decode if ayar.url_alfabe else base64.b64decode
    try:
        veri = cozucu(b64_dolgulu.encode("ascii"))
    except (binascii.Error, ValueError) as e:
        raise CozmeHatasi(f"Base64 çözümlenemedi: {e}") from e

    metin, kodlama = _metne_cevir(veri, metin_kodlamalari)
    return Sonuc(veri, b64, ayar, metin, kodlama)


def _metne_cevir(veri, kodlamalar):
    """Çözülen baytları metne çevirmeyi dener; olmuyorsa (None, None) döner.

    İkili bir yük (resim, arşiv) metin değildir; zorla metne çevirmek yerine
    açıkça "ikili" olarak gösterilir.
    """
    for kodlama in kodlamalar:
        try:
            metin = veri.decode(kodlama)
        except (UnicodeDecodeError, LookupError):
            continue
        if _metin_gibi(metin):
            return metin, kodlama
    return None, None


def _metin_gibi(metin, esik=0.90):
    """Metnin okunabilir olup olmadığını kaba biçimde ölçer."""
    if not metin:
        return False
    okunabilir = sum(1 for c in metin if c.isprintable() or c in "\n\r\t")
    return okunabilir / len(metin) >= esik


# ======================================================================
# Otomatik öneri
# ======================================================================
def _b64_son_ek(metin, alfabe):
    """Metnin, yalnızca Base64 karakterlerinden oluşan EN UZUN sonekini döner."""
    i = len(metin)
    while i > 0 and metin[i - 1] in alfabe:
        i -= 1
    return metin[i:]


def _ortak_sonek(metinler):
    """Verilen metinlerin en uzun ORTAK SONEKİNİ döner (yoksa "")."""
    if not metinler:
        return ""
    en_kisa = min(len(m) for m in metinler)
    i = 0
    while i < en_kisa:
        karakter = metinler[0][-(i + 1)]
        if any(m[-(i + 1)] != karakter for m in metinler):
            break
        i += 1
    return metinler[0][len(metinler[0]) - i:] if i else ""


def otomatik_ayar(hucreler):
    """Bir kaydı inceleyip makul bir çözme ayarı ÖNERİR.

    Döner: (ayar, sonuc, aciklama) ya da (None, None, aciklama).

    Denenen stratejiler, en güvenilirden en zayıfa:

      1. ORTAK İŞARETÇİ: tüm hücrelerde ortak, Base64'e ait olmayan bir
         ayraçtan sonra gelen yükler. Kaynak dosyadaki `..._½_<yük>` düzeni
         budur.
      2. TÜM HÜCRELER: hücrelerin tamamı, olduğu gibi birleştirilir.
      3. TEK HÜCRE: yalnızca Base64 gibi görünen tek bir hücre.

    Bir aday ancak çözülüp ANLAMLI METİN verirse önerilir. Rastgele altı
    onaltılık karakter de geçerli Base64'tür ve çöp bayta çözülür; böyle bir
    "başarı" öneri olarak sunulmaz -- öneri yoksa kullanıcı ayarı elle yapar.
    """
    if not hucreler:
        return None, None, "Kayıtta alan yok."

    adaylar = []

    # 1) Ortak işaretçi. Her hücrenin Base64 yükü, o hücrenin en uzun
    # Base64-karakterli sonekidir; geri kalan kısım o hücrenin taşıyıcı
    # önekidir (ör. "16481845_0_½_"). Önekler hücreden hücreye değişir ama
    # ORTAK BİR SONLARI vardır ("_½_") -- işaretçi işte budur. Tek bir
    # karakter (ör. "_") işaretçi olarak alınırsa metinde birden çok kez
    # geçer ve yanlış yerden kesilir; ortak sonek bu belirsizliği giderir.
    for url in (False, True):
        alfabe = ALFABE_URL if url else ALFABE_STANDART
        yukler = [_b64_son_ek(h, alfabe) for h in hucreler]
        dolu = [i for i, y in enumerate(yukler) if len(y) >= EN_AZ_YUK]
        if not dolu:
            continue
        onekler = [hucreler[i][:len(hucreler[i]) - len(yukler[i])] for i in dolu]
        if all(not o for o in onekler):
            adaylar.append(Ayar(dolu, url_alfabe=url))
            continue
        isaretci = _ortak_sonek(onekler)
        if isaretci:
            # İşaretçi bazı hücrelerde birden çok geçiyorsa son geçişi al.
            coklu = any(hucreler[i].count(isaretci) > 1 for i in dolu)
            adaylar.append(Ayar(dolu, onek=isaretci, onek_kipi=KIP_ISARETCI,
                                uygula=UYGULA_PARCA, url_alfabe=url,
                                isaretci_son=coklu))

    # 2) Tüm hücreler olduğu gibi
    adaylar.append(Ayar(range(len(hucreler))))
    # 3) Tek tek her hücre
    for i in range(len(hucreler)):
        adaylar.append(Ayar([i]))

    for ayar in adaylar:
        try:
            sonuc = coz(hucreler, ayar)
        except CozmeHatasi:
            continue
        # Öneri ölçütü UTF-8 GEÇERLİLİĞİDİR, yalnızca "okunabilirlik" değil.
        # cp1254/latin-1 gibi tek baytlı kodlamalar HER bayt dizisini
        # okunabilir bir metne çevirir; o ölçütle rastgele veri de "çözüldü"
        # sanılır. UTF-8 ise kendi kendini doğrulayan bir kodlamadır: rastgele
        # baytların geçerli UTF-8 olma olasılığı çok düşüktür. Bu yüzden
        # otomatik öneri yalnızca UTF-8 çıkan sonuçlara verilir; tek baytlı
        # kodlamalar ELLE çözmede gösterim için kullanılmaya devam eder.
        if sonuc.metin_mi and sonuc.kodlama == "utf-8" and len(sonuc.veri) >= 4:
            return ayar, sonuc, "Otomatik öneri: " + ayar.ozet()

    return None, None, (
        "Bu kayıtta kendiliğinden çözülebilen bir Base64 yükü bulunamadı. "
        "Kolonları, işaretçiyi ve öneki aşağıdan elle ayarlayıp deneyebilirsiniz.")


def onizleme_metni(veri, en_fazla=4096):
    """Çözülen baytların onaltılık + ASCII dökümünü üretir (ikili yükler için)."""
    kesik = veri[:en_fazla]
    satirlar = []
    for ofset in range(0, len(kesik), 16):
        parca = kesik[ofset:ofset + 16]
        onaltilik = " ".join(f"{b:02x}" for b in parca)
        ascii_ = "".join(chr(b) if 32 <= b < 127 else "." for b in parca)
        satirlar.append(f"{ofset:08x}  {onaltilik:<47}  {ascii_}")
    if len(veri) > en_fazla:
        satirlar.append(f"... ({len(veri) - en_fazla} bayt daha)")
    return "\n".join(satirlar)


def tur_tahmini(veri):
    """Çözülen baytların dosya türünü imzasından tahmin eder (gösterim için)."""
    imzalar = [
        (b"\x89PNG\r\n\x1a\n", "PNG görüntü"),
        (b"\xff\xd8\xff", "JPEG görüntü"),
        (b"GIF87a", "GIF görüntü"), (b"GIF89a", "GIF görüntü"),
        (b"%PDF-", "PDF belge"),
        (b"PK\x03\x04", "ZIP arşivi (docx/xlsx/jar olabilir)"),
        (b"\x1f\x8b", "GZIP arşivi"),
        (b"BZh", "BZIP2 arşivi"),
        (b"7z\xbc\xaf\x27\x1c", "7-Zip arşivi"),
        (b"OggS", "OGG ses/video"),
        (b"RIFF", "RIFF (WAV/AVI)"),
        (b"\x00\x00\x01\x00", "ICO simge"),
    ]
    for imza, ad in imzalar:
        if veri.startswith(imza):
            return ad
    return None
