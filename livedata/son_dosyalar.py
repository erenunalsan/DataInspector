"""Son açılan dosyaların küçük bir listesini kalıcı tutar.

Bu, "diske hiçbir şey yazılmaz" ilkesinin bir istisnası DEĞİLDİR -- o ilke
kaynak dosyanın (60-120 GB) gizlice önbelleklenmesini/kopyalanmasını
yasaklar. Burada diske yazılan şey birkaç KB'lık bir tercih dosyasıdır
(yalnızca DOSYA YOLLARI, hiçbir veri satırı), tıpkı herhangi bir masaüstü
uygulamasının "son kullanılanlar" listesi gibi.

Hem masaüstü (Tkinter) hem web (Django) arayüzü bu AYNI modülü kullanır --
ikisi de kullanıcının aynı makinedeki tercihini paylaşır.
"""
import json
import os

EN_FAZLA = 10


def _dosya_yolu():
    taban = os.environ.get("APPDATA") or os.path.expanduser("~")
    dizin = os.path.join(taban, "livedata")
    try:
        os.makedirs(dizin, exist_ok=True)
    except OSError:
        pass
    return os.path.join(dizin, "son_dosyalar.json")


def oku():
    """Var olan dosyaları döner, en son açılan başta. Artık var olmayan ya
    da okunamayan dosyalar sessizce süzülür."""
    try:
        with open(_dosya_yolu(), "r", encoding="utf-8") as f:
            veri = json.load(f)
    except (OSError, ValueError):
        return []
    if not isinstance(veri, list):
        return []
    return [y for y in veri if isinstance(y, str) and os.path.isfile(y)]


def ekle(yol):
    """Bir yolu listenin BAŞINA ekler (zaten varsa öne taşır), EN_FAZLA'ya
    kırpar ve kalıcı hâle getirir. Güncel listeyi döner."""
    yol = os.path.abspath(yol)
    liste = [y for y in oku() if os.path.abspath(y) != yol]
    liste.insert(0, yol)
    liste = liste[:EN_FAZLA]
    try:
        with open(_dosya_yolu(), "w", encoding="utf-8") as f:
            json.dump(liste, f, ensure_ascii=False, indent=2)
    except OSError:
        pass  # kalıcı hâle gelmese de uygulama çalışmaya devam etmeli
    return liste


def temizle():
    try:
        os.remove(_dosya_yolu())
    except OSError:
        pass
