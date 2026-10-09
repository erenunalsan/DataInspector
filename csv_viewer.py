"""Geriye dönük uyumluluk kabuğu.

Bu ekran artık yalnızca CSV değil, CSV/JSON/XML/YAML dosyalarını açar; asıl
giriş noktası `veri_goruntuleyici.py`'dir. Eskiden öğrenilen `csv_viewer.py`
komutu bozulmasın diye bu dosya korunmuştur ve aynı pencereyi açar.
"""
from veri_goruntuleyici import main

if __name__ == "__main__":
    raise SystemExit(main())
