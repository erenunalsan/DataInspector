"""Tema-duyarlı renkler (sv-ttk açık/koyu ile uyumlu).

sv-ttk, standart ttk widget'larının (Button, Label, Treeview gövdesi vb.)
renklerini otomatik değiştirir. Ama bu proje bazı yerlerde -- durum
etiketleri (başarı/uyarı/hata), konsol satır renkleri, tablo satır
vurguları (seçili/bekleyen/uyumsuz) -- belirli renkleri SABİT (hardcode)
kullanıyordu. Koyu temaya geçildiğinde bunlar ya görünmez olur (ör. koyu
lacivert yazı, koyu zemin üstünde) ya da göz yorar (ör. açık sarı bir satır
zemini, koyu bir arayüzün ortasında parlar).

Bu modül tek bir doğruluk kaynağıdır: `koyu_mu()` o an aktif sv-ttk temasını
sorar, diğer tüm fonksiyonlar buna göre uygun tonu döner. Bir widget'ın
rengi tema değiştikten SONRA da doğru kalsın istiyorsak, o widget'ı
güncelleyen kod bu fonksiyonları HER ÇAĞRIDA yeniden çağırmalıdır (statik
bir sabite atamak yerine) -- bkz. `console.py`'deki `tema_yenile()` ve
`virtualtable.py`'deki `tema_yenile()`.
"""
import sv_ttk


def koyu_mu():
    try:
        return sv_ttk.get_theme() == "dark"
    except Exception:
        return False


# -- durum/metin renkleri (etiketler, konsol satırları) -------------------
def vurgu():
    return "#5b9bd5" if koyu_mu() else "#1f4e79"


def basari():
    return "#5fb85f" if koyu_mu() else "#1a7f37"


def uyari():
    return "#e3ac41" if koyu_mu() else "#9a6700"


def hata():
    return "#e5645c" if koyu_mu() else "#b42318"


def sure_rengi():
    return "#a98fe0" if koyu_mu() else "#6b4fa0"


def islem_rengi():
    return "#cfcfcf" if koyu_mu() else "#444444"


def ikincil():
    # Orta ton gri; hem açık hem koyu zeminde kabul edilebilir kontrastta
    # olduğundan tema değişse de tek bir değer yeterlidir.
    return "#9a9a9a"


def govde_metin():
    """Normal okunabilir gövde metni -- sabit siyah/beyaz yerine."""
    return "#e6e6e6" if koyu_mu() else "#1a1a1a"


# -- tablo satır renkleri ---------------------------------------------------
def tablo_renkleri():
    """Satır zebra deseni ve durum vurguları için tam bir renk sözlüğü."""
    if koyu_mu():
        return {
            "tek": "#1e1e1e", "cift": "#252525",
            "bekliyor_zemin": "#3a331a", "bekliyor_metin": "#c9ad63",
            "uyumsuz": "#3a2222",
            "vurgu": "#1f3c56",
            "isaretli": "#4a3f18",
            "bos_zemin": "#232323", "bos_metin": "#6f6f6f",
        }
    return {
        "tek": "#ffffff", "cift": "#f5f7fa",
        "bekliyor_zemin": "#fff8e1", "bekliyor_metin": "#8a6d1f",
        "uyumsuz": "#fdeaea",
        "vurgu": "#d8ecff",
        "isaretli": "#fff3cd",
        "bos_zemin": "#fafafa", "bos_metin": "#c0c0c0",
    }


# -- konsol seviyeleri -------------------------------------------------------
def konsol_seviyeleri():
    """seviye -> (işaret harfi, renk). `console.py` bunu her tema
    değişiminde yeniden çağırıp tag'leri tazeler."""
    return {
        "bilgi": ("i", vurgu()),
        "tamam": ("+", basari()),
        "uyari": ("!", uyari()),
        "hata": ("X", hata()),
        "sure": ("t", sure_rengi()),
        "islem": ("»", islem_rengi()),
    }


def konsol_zemin():
    return "#1e1e1e" if koyu_mu() else "#fbfbfd"


def konsol_metin():
    return "#e6e6e6" if koyu_mu() else "#1a1a1a"
