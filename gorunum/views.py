"""livedata web arayüzü — API görünümleri.

Her görünüm, `livedata/ui/app.py`'deki bir Tkinter olay metodunun ince bir
web karşılığıdır (ör. `ac` ~= `_ac()`, `satirlar` ~= `_satir_saglayici()`).
İş mantığının TAMAMI `livedata` çekirdeğinde kalır; bu dosya yalnızca
JSON <-> Python çevirisi ve oturum kaydına yönlendirmedir.

Diske hiçbir şey yazılmaz: dışa aktarım dosyaları (`disa_aktar.py`) ve web
sayfasının kendisi tamamen bellekte üretilir.
"""
import json
import os
import time

from django.http import HttpResponse, JsonResponse
from django.shortcuts import render
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from livedata import selection, son_dosyalar, sorting, units
from livedata.formats import BicimHatasi

from . import disa_aktar
from .kayit import KAYIT

EN_FAZLA_SONUC = 5000
DESTEKLENEN_UZANTI = (".csv", ".tsv", ".txt", ".json", ".jsonl", ".ndjson",
                      ".xml", ".yaml", ".yml")


# ======================================================================
# Yardımcılar
# ======================================================================
def _govde(request):
    if not request.body:
        return {}
    try:
        return json.loads(request.body.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return {}


def _hata(mesaj, kod=400):
    return JsonResponse({"hata": mesaj}, status=kod)


def _oturum_veya_404(oid):
    oturum, takipci = KAYIT.al(oid)
    if oturum is None:
        return None, None, _hata("Oturum bulunamadı (kapatılmış ya da hiç açılmamış).", 404)
    return oturum, takipci, None


def _bicim_json(b):
    return {
        "tur": b.tur, "boyut": b.boyut, "kolonlar": list(b.kolonlar),
        "ozet": b.ozet(), "kodlama": b.kodlama,
        "veri_basi": b.veri_basi, "veri_sonu": b.veri_sonu,
        "veri_bayt": b.veri_bayt,
        "beyan_edilen_kayit": b.beyan_edilen_kayit,
        "tahmini_satir": b.tahmini_satir_sayisi(),
        "baslik_var": getattr(b, "baslik_var", True),
        "ayrac": getattr(b, "ayrac", None),
    }


def _oturum_ozet_json(oturum):
    return {
        "toplam_satir": oturum.toplam_satir(),
        "kesin": oturum.kesin_mi(),
        "sayfa_satir": oturum.sayfa_satir,
        "sayfa_sayisi": oturum.sayfa_sayisi(),
        "gorunum_var": oturum.gorunum_var(),
        "gorunum_uzunluk": oturum.gorunum_uzunlugu(),
        "secili_sayi": len(oturum.secim),
        "bellek": oturum.bellek_ozeti(),
    }


# ======================================================================
# Sayfa iskeleti
# ======================================================================
def ana_sayfa(request):
    return render(request, "gorunum/ana.html", {
        "secim_tavani": selection.EN_FAZLA_SECIM,
    })


# ======================================================================
# Dosya sistemi gezinme (yerel yol seçimi için basit bir yardımcı --
# tarayıcının <input type=file> ile 60-120 GB'lık dosyaları "yüklemesi"
# hem imkânsız hem gereksizdir; sunucu dosyayı zaten yerinde okur, kullanıcı
# yalnızca YOLU seçer/yazar).
# ======================================================================
def _surucu_listesi():
    """Windows'ta bağlı sürücü harflerini döner (ör. ["C:\\\\", "D:\\\\"]).

    `os.path.dirname()` bir kökten (`C:\\`) YUKARI çıkaramaz -- yalnızca
    ".." ile gezinmek kullanıcıyı C: sürücüsüne hapseder, D:'ye hiç
    geçemez. Bu yüzden sürücüler ayrıca, doğrudan atlanabilir bir liste
    olarak sunulur. Windows dışında boş döner (yalnızca bu projenin hedef
    platformunda anlamlıdır).
    """
    if os.name != "nt":
        return []
    import string
    return [f"{h}:\\" for h in string.ascii_uppercase
           if os.path.exists(f"{h}:\\")]


@require_GET
def gozat(request):
    dizin = request.GET.get("dizin") or os.path.expanduser("~")
    dizin = os.path.abspath(dizin)
    if not os.path.isdir(dizin):
        return _hata(f"Dizin bulunamadı: {dizin}", 404)
    try:
        girdiler = list(os.scandir(dizin))
    except OSError as e:
        return _hata(str(e), 403)

    dizinler, dosyalar = [], []
    for g in girdiler:
        try:
            if g.is_dir():
                dizinler.append(g.name)
            elif g.name.lower().endswith(DESTEKLENEN_UZANTI):
                boyut = g.stat().st_size
                dosyalar.append({"ad": g.name, "boyut": boyut,
                                 "boyut_metin": units.bayt(boyut)})
        except OSError:
            continue
    dizinler.sort(key=str.lower)
    dosyalar.sort(key=lambda d: d["ad"].lower())

    ust = os.path.dirname(dizin)
    return JsonResponse({
        "dizin": dizin, "ust": ust if ust != dizin else None,
        "dizinler": dizinler, "dosyalar": dosyalar,
        "surucular": _surucu_listesi(),
    })


@require_GET
def son_dosyalar_liste(request):
    return JsonResponse({"dosyalar": son_dosyalar.oku()})


@csrf_exempt
@require_POST
def son_dosyalar_temizle(request):
    son_dosyalar.temizle()
    return JsonResponse({"tamam": True})


# ======================================================================
# Oturum: açma / kapama
# ======================================================================
@csrf_exempt
@require_POST
def ac(request):
    veri = _govde(request)
    yol = (veri.get("yol") or "").strip().strip('"')
    if not yol:
        return _hata("Dosya yolu boş olamaz.")
    if not os.path.isfile(yol):
        return _hata(f"Dosya bulunamadı: {yol}", 404)

    KAYIT.bosta_kalanlari_kapat()

    t0 = time.perf_counter()
    try:
        oid, oturum = KAYIT.olustur(
            yol, ayrac=veri.get("ayrac"), kodlama=veri.get("kodlama"),
            baslik_var=veri.get("baslik_var"),
            tirnak_duyarli=veri.get("tirnak_duyarli"))
    except (BicimHatasi, OSError, ValueError) as e:
        return _hata(str(e))
    tespit_sure = time.perf_counter() - t0
    son_dosyalar.ekle(yol)

    _, takipci = KAYIT.al(oid)
    takipci.dis_mesaj(f"Dosya açıldı: {yol} ({units.bayt(oturum.bicim.boyut)})",
                      "tamam")
    takipci.dis_mesaj(
        f"Biçim tespiti {units.sure(tespit_sure)} sürdü → {oturum.bicim.ozet()}",
        "sure")
    takipci.dis_mesaj(
        "İndeks taraması BAŞLATILMADI — bu ekran dosyayı açmak için tarama "
        "gerektirmez; yalnızca uzak bir kayda gidildiğinde o kayda kadar "
        "taranır.", "bilgi")

    return JsonResponse({
        "oid": oid, "bicim": _bicim_json(oturum.bicim),
        "oturum": _oturum_ozet_json(oturum),
    })


@csrf_exempt
@require_POST
def kapat(request, oid):
    KAYIT.kapat(oid)
    return JsonResponse({"tamam": True})


# ======================================================================
# Satırlar (sanal tablonun veri kaynağı)
# ======================================================================
EN_FAZLA_PENCERE = 2000


@require_GET
def satirlar(request, oid):
    oturum, _t, hata = _oturum_veya_404(oid)
    if hata:
        return hata
    try:
        bas = int(request.GET.get("bas", 0))
        adet = int(request.GET.get("adet", 100))
    except ValueError:
        return _hata("bas/adet tam sayı olmalı.")
    bas = max(0, bas)
    adet = max(0, min(adet, EN_FAZLA_PENCERE))

    if oturum.gorunum is not None:
        dilim = oturum.gorunum[bas:bas + adet]
        satir_listesi = oturum.kayitlar(dilim)
    else:
        satir_listesi = oturum.satirlar(bas, adet)

    secim = oturum.secim
    return JsonResponse({
        "satirlar": [[no, deger, no in secim] for no, deger in satir_listesi],
        "oturum": _oturum_ozet_json(oturum),
    })


# ======================================================================
# Durum / ilerleme (polling)
# ======================================================================
@require_GET
def durum(request, oid):
    oturum, takipci, hata = _oturum_veya_404(oid)
    if hata:
        return hata
    konsol_sonrasi = int(request.GET.get("konsol_sonrasi", 0) or 0)
    eslesme_sonrasi = int(request.GET.get("eslesme_sonrasi", 0) or 0)
    goruntu = takipci.anlik_goruntu(konsol_sonrasi, eslesme_sonrasi)
    goruntu["oturum"] = _oturum_ozet_json(oturum)
    # Yalnızca burada (400ms'de bir), /satirlar gibi çok sık çağrılan uç
    # noktalarda DEĞİL -- os.stat() ucuzdur ama gereksiz yere her kaydırma
    # tıkında tekrarlanmamalı. Kaynak dosya değişmişse (üzerine yazılmış,
    # yeniden oluşturulmuşsa) indekslenmiş bayt konumları SESSİZCE yanlış
    # olur; istemci bunu bir kez uyarıp durum çubuğunda kalıcı gösterir.
    goruntu["dosya_degisti"] = oturum.dosya_degisti_mi()
    return JsonResponse(goruntu)


# ======================================================================
# Satıra git
# ======================================================================
@csrf_exempt
@require_POST
def satira_git(request, oid):
    oturum, takipci, hata = _oturum_veya_404(oid)
    if hata:
        return hata
    veri = _govde(request)
    try:
        hedef = int(veri.get("hedef"))
    except (TypeError, ValueError):
        return _hata("'hedef' bir tam sayı olmalı.")
    if hedef < 0:
        return _hata("'hedef' negatif olamaz.")
    if oturum.kesin_mi() and hedef >= oturum.toplam_satir():
        return _hata(f"Dosyada {oturum.toplam_satir()} satır var; "
                     f"{hedef} numaralı satır yok.", 404)

    if not oturum.index.erisilebilir(hedef):
        oturum.indeksi_ilerlet(hedef + oturum.yukleyici.pencere)
        return JsonResponse({
            "hazir": False, "bilinen": oturum.bilinen_satir(),
            "hedef": hedef,
        })

    sayfa = oturum.sayfa_no(hedef)
    bas = sayfa * oturum.sayfa_satir
    return JsonResponse({"hazir": True, "sayfa": sayfa, "bas": bas,
                        "hedef": hedef})


# ======================================================================
# İndeksleme
# ======================================================================
@csrf_exempt
@require_POST
def indeksle(request, oid):
    oturum, takipci, hata = _oturum_veya_404(oid)
    if hata:
        return hata
    if oturum.index.tamam:
        return JsonResponse({"basladi": False, "neden": "zaten_tamam"})
    oturum.indeksi_tamamla()
    takipci.dis_mesaj(
        f"Dosyanın tamamı indeksleniyor: "
        f"{units.bayt(oturum.bicim.veri_bayt - oturum.index.taranan_bayt)} "
        "okunacak.", "islem")
    return JsonResponse({"basladi": True})


# ======================================================================
# Arama
# ======================================================================
@csrf_exempt
@require_POST
def ara(request, oid):
    oturum, takipci, hata = _oturum_veya_404(oid)
    if hata:
        return hata
    veri = _govde(request)
    metin = (veri.get("metin") or "").strip()
    if not metin:
        return _hata("Aranacak metin boş olamaz.")
    if oturum.arama_calisiyor():
        return _hata("Zaten süren bir arama var.", 409)

    try:
        desen = oturum.ara(metin, duyarli=bool(veri.get("duyarli")),
                           en_fazla=EN_FAZLA_SONUC, regex=bool(veri.get("regex")))
    except ValueError as e:
        return _hata(str(e))

    takipci.dis_mesaj(
        f"Aranan: {metin!r} · {'regex · ' if desen.regex else ''}"
        f"kaynak dosyanın TAMAMI taranacak "
        f"({units.bayt(oturum.bicim.veri_bayt)}).", "islem")
    if desen.yaklasik:
        takipci.dis_mesaj(
            "Aranan metin ASCII dışı karakter içeriyor; metnin yaygın "
            f"yazılış çeşitleri ({len(desen.desenler)} adet) ayrı ayrı "
            "aranıyor.", "uyari")
    return JsonResponse({"basladi": True, "yaklasik": desen.yaklasik})


@csrf_exempt
@require_POST
def arama_durdur(request, oid):
    oturum, _t, hata = _oturum_veya_404(oid)
    if hata:
        return hata
    oturum.aramayi_durdur()
    return JsonResponse({"tamam": True})


# ======================================================================
# Sıralama
# ======================================================================
def _siralama_ayarlarini_coz(oturum, veri):
    kolon_adi = veri.get("kolon")
    try:
        kolon = oturum.kolonlar.index(kolon_adi)
    except ValueError:
        raise ValueError(f"Geçersiz kolon: {kolon_adi!r}")
    yon = sorting.AZALAN if veri.get("yon") == "azalan" else sorting.ARTAN
    tur = sorting.TUR_SAYI if veri.get("tur") == "sayi" else sorting.TUR_METIN
    return kolon, yon, tur


@csrf_exempt
@require_POST
def sirala(request, oid):
    oturum, takipci, hata = _oturum_veya_404(oid)
    if hata:
        return hata
    if oturum.siralama_calisiyor():
        return _hata("Zaten süren bir sıralama var.", 409)
    if oturum.arama_calisiyor():
        return _hata("Arama sürüyor; önce aramayı bitirin.", 409)

    veri = _govde(request)
    try:
        kolon, yon, tur = _siralama_ayarlarini_coz(oturum, veri)
    except ValueError as e:
        return _hata(str(e))

    kapsam = veri.get("kapsam")
    kolon_adi = oturum.kolonlar[kolon]

    if kapsam == "arama":
        kayitlar = takipci.eslesme_satirlari()
        if not kayitlar:
            return _hata("Önce bir arama yapın; bu kapsam arama sonuçlarını sıralar.")
        oturum.sirala_liste(kolon, yon, tur, kayitlar)
        takipci.dis_mesaj(
            f"{len(kayitlar)} arama sonucu '{kolon_adi}' kolonuna göre "
            "sıralanıyor.", "islem")
    elif kapsam == "sayfa":
        try:
            sayfa_no = int(veri.get("sayfa_no", 0))
        except (TypeError, ValueError):
            return _hata("'sayfa_no' bir tam sayı olmalı.")
        if oturum.gorunum is not None:
            return _hata("Şu an sıralı bir görünümdesiniz; önce sıralamayı sıfırlayın.")
        bas = sayfa_no * oturum.sayfa_satir
        toplam = oturum.toplam_satir()
        adet = oturum.sayfa_satir
        if oturum.kesin_mi():
            adet = max(0, min(oturum.sayfa_satir, toplam - bas))
        oturum.indeksi_ilerlet(bas + adet)
        oturum.sirala_sayfa(kolon, yon, tur, bas, adet)
        takipci.dis_mesaj(
            f"Sayfa {sayfa_no + 1} ({adet} kayıt) '{kolon_adi}' kolonuna göre "
            "sıralanıyor.", "islem")
    elif kapsam == "tum":
        try:
            k = int(veri.get("k", 10000))
        except (TypeError, ValueError):
            return _hata("'k' bir tam sayı olmalı.")
        if not (1 <= k <= 200_000):
            return _hata("'k' 1 ile 200.000 arasında olmalı.")
        oturum.sirala_topk(kolon, yon, tur, k)
        takipci.dis_mesaj(
            f"Tüm dosyada '{kolon_adi}' kolonuna göre en iyi {k} kayıt "
            f"aranıyor ({units.bayt(oturum.bicim.veri_bayt)} okunacak).",
            "islem")
    else:
        return _hata(f"Geçersiz kapsam: {kapsam!r}")

    return JsonResponse({"basladi": True})


@csrf_exempt
@require_POST
def sirala_durdur(request, oid):
    oturum, _t, hata = _oturum_veya_404(oid)
    if hata:
        return hata
    oturum.siralamayi_durdur()
    return JsonResponse({"tamam": True})


@csrf_exempt
@require_POST
def sirala_sifirla(request, oid):
    oturum, takipci, hata = _oturum_veya_404(oid)
    if hata:
        return hata
    if oturum.gorunum is None:
        return JsonResponse({"tamam": True})
    oturum.gorunum_temizle()
    takipci.dis_mesaj("Kaynak sırasına dönüldü.", "tamam")
    return JsonResponse({"tamam": True, "oturum": _oturum_ozet_json(oturum)})


# ======================================================================
# Seçim
# ======================================================================
@require_GET
def secim_liste(request, oid):
    oturum, _t, hata = _oturum_veya_404(oid)
    if hata:
        return hata
    return JsonResponse({"nolar": oturum.secim.liste(),
                        "kolonlar": list(oturum.kolonlar)})


@csrf_exempt
@require_POST
def secim_degistir(request, oid):
    oturum, _t, hata = _oturum_veya_404(oid)
    if hata:
        return hata
    veri = _govde(request)
    try:
        kayit_no = int(veri.get("kayit_no"))
    except (TypeError, ValueError):
        return _hata("'kayit_no' bir tam sayı olmalı.")
    sonuc = oturum.secim.degistir(kayit_no)
    if sonuc is None:
        return _hata(
            f"En fazla {selection.EN_FAZLA_SECIM} kayıt seçilebilir.", 409)
    return JsonResponse({"secili": sonuc, "secili_sayi": len(oturum.secim)})


@csrf_exempt
@require_POST
def secim_sayfa_sec(request, oid):
    oturum, takipci, hata = _oturum_veya_404(oid)
    if hata:
        return hata
    veri = _govde(request)

    ekstra_not = ""
    if oturum.gorunum is not None:
        adaylar = list(oturum.gorunum)
        kaynak = "Sıralı görünüm"
    else:
        try:
            sayfa_no = int(veri.get("sayfa_no", 0))
        except (TypeError, ValueError):
            return _hata("'sayfa_no' bir tam sayı olmalı.")
        bas = sayfa_no * oturum.sayfa_satir
        toplam = oturum.toplam_satir()
        adet = oturum.sayfa_satir
        if oturum.kesin_mi():
            adet = max(0, min(oturum.sayfa_satir, toplam - bas))
        adaylar = range(bas, bas + adet)
        kaynak = f"Sayfa {sayfa_no + 1}"
        if oturum.indeksi_ilerlet(bas + adet):
            ekstra_not = " Taranmamış kısım arka planda taranıyor."

    eklenen, doldu = oturum.secim.coklu_ekle(adaylar)
    takipci.dis_mesaj(
        f"{kaynak}: {eklenen} kayıt seçime eklendi.{ekstra_not}",
        "uyari" if doldu else "tamam")
    return JsonResponse({"eklenen": eklenen, "doldu": doldu,
                        "secili_sayi": len(oturum.secim)})


@require_GET
def secim_satirlar(request, oid):
    """'Seçilenleri Göster' penceresi için seçili kayıtların DEĞERLERİ.

    Masaüstündeki `SeciliVerilerPenceresi._satir_saglayici` ile aynı yolu
    kullanır: seçim dağınık kayıt numaralarından oluşur, `oturum.kayitlar()`
    ile dağınık erişimle getirilir.
    """
    oturum, _t, hata = _oturum_veya_404(oid)
    if hata:
        return hata
    try:
        bas = int(request.GET.get("bas", 0))
        adet = int(request.GET.get("adet", 200))
    except ValueError:
        return _hata("bas/adet tam sayı olmalı.")
    adet = max(0, min(adet, 500))
    nolar = oturum.secim.liste()
    dilim = nolar[bas:bas + adet]
    satir_listesi = oturum.kayitlar(dilim) if dilim else []
    return JsonResponse({
        "toplam": len(nolar),
        "kolonlar": list(oturum.kolonlar),
        "satirlar": [[no, deger] for no, deger in satir_listesi],
    })


@csrf_exempt
@require_POST
def secim_temizle(request, oid):
    oturum, takipci, hata = _oturum_veya_404(oid)
    if hata:
        return hata
    n = len(oturum.secim)
    oturum.secim.temizle()
    if n:
        takipci.dis_mesaj(f"Seçim temizlendi ({n} kayıt kaldırıldı).", "islem")
    return JsonResponse({"tamam": True})


# ======================================================================
# Dışa aktarım (Excel / Word / PDF) — arka planda toplanır, sonra indirilir
# ======================================================================
@csrf_exempt
@require_POST
def disa_aktar_baslat(request, oid, bicim):
    oturum, takipci, hata = _oturum_veya_404(oid)
    if hata:
        return hata
    if bicim not in ("excel", "word", "pdf"):
        return _hata(f"Bilinmeyen biçim: {bicim!r}", 404)
    nolar = oturum.secim.liste()
    if not nolar:
        return _hata("Seçili kayıt yok.")
    baslik = f"Seçili Veriler — {len(nolar)} kayıt"
    token = disa_aktar.baslat(oturum, nolar, list(oturum.kolonlar), baslik, bicim)
    takipci.dis_mesaj(
        f"{bicim.upper()} dışa aktarımı başladı — {len(nolar)} kayıt "
        "arka planda toplanıyor.", "islem")
    return JsonResponse({"token": token})


@require_GET
def disa_aktar_ilerleme(request, token):
    is_ = disa_aktar.al(token)
    if is_ is None:
        return _hata("İş bulunamadı (bitmiş ve indirilmiş olabilir).", 404)
    return JsonResponse(is_.ilerleme())


@require_GET
def disa_aktar_indir(request, token):
    is_ = disa_aktar.al(token)
    if is_ is None:
        return _hata("İş bulunamadı.", 404)
    if is_.durum == "hata":
        disa_aktar.temizle(token)
        return _hata(f"Dışa aktarım başarısız: {is_.hata}", 500)
    if is_.durum != "hazir":
        return _hata("Henüz hazır değil.", 409)
    yanit = HttpResponse(is_.icerik, content_type=is_.mime)
    yanit["Content-Disposition"] = f'attachment; filename="{is_.dosya_adi}"'
    disa_aktar.temizle(token)
    return yanit


# ======================================================================
# Base64 çözme
# ======================================================================
@csrf_exempt
@require_POST
def base64_coz(request, oid):
    from livedata import b64

    oturum, _t, hata = _oturum_veya_404(oid)
    if hata:
        return hata
    veri = _govde(request)
    hucreler = veri.get("hucreler")
    if not isinstance(hucreler, list) or not hucreler:
        return _hata("'hucreler' boş olmayan bir liste olmalı.")
    hucreler = [str(h) for h in hucreler]

    kolonlar = veri.get("kolonlar")
    if kolonlar:
        try:
            ayar = b64.Ayar(
                kolonlar=[int(k) for k in kolonlar],
                onek=veri.get("onek", ""),
                onek_kipi=veri.get("onek_kipi", b64.KIP_YOK),
                sonek=veri.get("sonek", ""),
                uygula=veri.get("uygula", b64.UYGULA_PARCA),
                bosluk_at=bool(veri.get("bosluk_at", True)),
                url_alfabe=bool(veri.get("url_alfabe", False)),
                isaretci_son=bool(veri.get("isaretci_son", False)))
        except (TypeError, ValueError) as e:
            return _hata(f"Geçersiz ayar: {e}")
        try:
            sonuc = b64.coz(hucreler, ayar)
        except b64.CozmeHatasi as e:
            return _hata(str(e))
        oneri_aciklama = None
    else:
        ayar, sonuc, oneri_aciklama = b64.otomatik_ayar(hucreler)
        if sonuc is None:
            return JsonResponse({"basarili": False, "aciklama": oneri_aciklama})

    tur = b64.tur_tahmini(sonuc.veri)
    return JsonResponse({
        "basarili": True,
        "ayar": {"kolonlar": ayar.kolonlar, "onek": ayar.onek,
                "onek_kipi": ayar.onek_kipi, "sonek": ayar.sonek,
                "uygula": ayar.uygula, "url_alfabe": ayar.url_alfabe,
                "ozet": ayar.ozet()},
        "aciklama": oneri_aciklama,
        "bayt_uzunluk": len(sonuc.veri),
        "metin": sonuc.metin,
        "kodlama": sonuc.kodlama,
        "tur_tahmini": tur,
        "onizleme": b64.onizleme_metni(sonuc.veri) if sonuc.metin is None else None,
    })
