"""livedata giriş noktası: büyük CSV/JSON/XML/YAML dosyalarını yerinde inceler.

Kullanım:

    python veri_goruntuleyici.py                        # boş açılır, dosyayı ekrandan seçin
    python veri_goruntuleyici.py "D:\\veri\\dosya.json"   # açar ve hemen yükler
    python veri_goruntuleyici.py "D:\\veri\\dosya.xml" --bekle   # yolu doldurur, açmaz

Desteklenen uzantılar: .csv .tsv .txt .json .jsonl .ndjson .xml .yaml .yml

Bu ekran, projedeki eski (parsers/ + streaming_pilot/ + gui/) yollardan
bağımsızdır: kaynak dosyayı diske hiçbir şey yazmadan ve belleğe almadan
gösterir. Ayrıntılar için LIVEDATA.md.
"""
import sys

from livedata.ui.app import LiveDataPenceresi


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    bekle = "--bekle" in argv
    yollar = [a for a in argv if not a.startswith("--")]
    baslangic = yollar[0] if yollar else None
    LiveDataPenceresi(baslangic_yolu=baslangic,
                     otomatik_ac=bool(baslangic) and not bekle).calistir()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
