"""Sayı, bayt ve süre değerlerini Türkçe biçimde metne çeviren yardımcılar.

Hiçbir projenin modülüne bağımlı değildir; yalnızca gösterim içindir.
"""

_BYTE_UNITS = ("B", "KB", "MB", "GB", "TB", "PB")


def sayi(n) -> str:
    """1234567 -> '1.234.567' (binlik ayracı nokta)."""
    if n is None:
        return "-"
    return f"{int(n):,}".replace(",", ".")


def bayt(n) -> str:
    """38400000000 -> '35,8 GB'."""
    if n is None:
        return "-"
    n = float(n)
    for unit in _BYTE_UNITS:
        if abs(n) < 1024.0 or unit == _BYTE_UNITS[-1]:
            if unit == "B":
                return f"{int(n)} B"
            return f"{n:.1f} {unit}".replace(".", ",")
        n /= 1024.0
    return f"{n:.1f} PB"


def sure(saniye) -> str:
    """0.0431 -> '43,1 ms';  91.4 -> '1 dk 31 sn'."""
    if saniye is None:
        return "-"
    if saniye < 1.0:
        return f"{saniye * 1000:.1f} ms".replace(".", ",")
    if saniye < 60.0:
        return f"{saniye:.2f} sn".replace(".", ",")
    dakika, kalan = divmod(int(saniye), 60)
    if dakika < 60:
        return f"{dakika} dk {kalan:02d} sn"
    saat, dakika = divmod(dakika, 60)
    return f"{saat} sa {dakika:02d} dk {kalan:02d} sn"


def hiz_bayt(bayt_sayisi, saniye) -> str:
    """Saniyede okunan bayt: '1,2 GB/sn'."""
    if not saniye or saniye <= 0:
        return "-"
    return bayt(bayt_sayisi / saniye) + "/sn"


def hiz_satir(satir_sayisi, saniye) -> str:
    """Saniyede işlenen satır: '3.400.000 satır/sn'."""
    if not saniye or saniye <= 0:
        return "-"
    return sayi(int(satir_sayisi / saniye)) + " satır/sn"


def yuzde(bolum, tam) -> float:
    if not tam:
        return 0.0
    return max(0.0, min(100.0, 100.0 * bolum / tam))
