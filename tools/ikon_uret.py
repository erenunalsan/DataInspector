"""livedata uygulama ikonunu (masaüstü .ico + web favicon) üretir.

Elle bir tasarım aracı kullanmadan, sade bir "veri tablosu" motifiyle
(yuvarlatılmış mavi zemin + beyaz tablo çizgileri) üretilir; projenin ana
vurgu rengiyle (#1f4e79) birebir uyumludur.

Çalıştırma:
    python tools/ikon_uret.py

Çıktılar:
    livedata/ui/assets/icon.ico   (masaüstü pencere ikonu, çoklu boyut)
    livedata/ui/assets/icon.png   (önizleme)
    gorunum/static/gorunum/favicon.ico  (web sekme ikonu)
"""
from pathlib import Path

from PIL import Image, ImageDraw

KOK = Path(__file__).resolve().parent.parent
BOYUT = 256
MAVI = (31, 78, 121, 255)       # #1f4e79 -- projenin ana vurgu rengi
MAVI_ACIK = (58, 110, 158, 255)
BEYAZ = (255, 255, 255, 255)


def uret():
    img = Image.new("RGBA", (BOYUT, BOYUT), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    d.rounded_rectangle([8, 8, BOYUT - 8, BOYUT - 8], radius=46, fill=MAVI)

    kenar = 46
    ust = 62
    alt = BOYUT - 46
    sol, sag = kenar, BOYUT - kenar
    cerceve_r = 18
    d.rounded_rectangle([sol, ust, sag, alt], radius=cerceve_r, outline=BEYAZ, width=9)

    baslik_alt = ust + 40
    d.rounded_rectangle([sol, ust, sag, baslik_alt], radius=cerceve_r, fill=MAVI_ACIK)
    d.rectangle([sol, baslik_alt - cerceve_r, sag, baslik_alt], fill=MAVI_ACIK)
    d.line([sol + 9, baslik_alt, sag - 9, baslik_alt], fill=BEYAZ, width=9)

    ic_sol, ic_sag = sol + 9, sag - 9
    for x in (ic_sol + (ic_sag - ic_sol) * 1 // 3, ic_sol + (ic_sag - ic_sol) * 2 // 3):
        d.line([x, baslik_alt + 6, x, alt - 9], fill=BEYAZ, width=6)

    for y_oran in (1 / 3, 2 / 3):
        y = baslik_alt + (alt - baslik_alt) * y_oran
        d.line([ic_sol, y, ic_sag, y], fill=BEYAZ, width=5)

    masaustu = KOK / "livedata" / "ui" / "assets"
    masaustu.mkdir(parents=True, exist_ok=True)
    img.save(masaustu / "icon.ico",
            sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    img.save(masaustu / "icon.png")

    web = KOK / "gorunum" / "static" / "gorunum"
    web.mkdir(parents=True, exist_ok=True)
    img.save(web / "favicon.ico", sizes=[(16, 16), (32, 32), (48, 48)])
    img.save(web / "favicon-192.png")

    print(f"Üretildi: {masaustu / 'icon.ico'}")
    print(f"Üretildi: {web / 'favicon.ico'}")


if __name__ == "__main__":
    uret()
