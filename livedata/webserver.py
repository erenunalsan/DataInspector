"""Seçili verileri yerel bir HTTP adresinde (localhost) yayınlayan sunucu.

Üç kural burada da geçerlidir:
  1) Diske hiçbir şey yazılmaz -- ana sayfa VE dışa aktarım dosyaları (Excel/
     Word/PDF) tamamen bellekte üretilir, `http.server` bunları bellekteki
     bayt dizilerinden doğrudan sunar. Kullanıcı "İndir" bağlantısına
     tıkladığında dosya TARAYICI ÜZERİNDEN kullanıcının kendi bilgisayarına
     iner -- bu sunucu hiçbir zaman kendisi disk yazmaz.
  2) Kaynak dosya belleğe alınmaz -- burada sunulan veri kullanıcının zaten
     seçtiği (genelde küçük) kayıt kümesidir (`SeciliVerilerPenceresi`
     tarafından `VeriOturumu.kayitlar()` ile arka planda, parça parça
     toplanmıştır).
  3) Arayüz kilitlenmez -- sunucu ayrı bir daemon iş parçacığında çalışır;
     Tkinter ana döngüsü hiçbir zaman beklemez. Excel/Word/PDF üretimi de
     yalnızca istek geldiğinde, o isteği işleyen arka plan thread'inde olur.
"""
import html
import http.server
import threading

from . import exporters

__all__ = ["sayfa_uret", "WebYayini"]

# Yol -> (üretici fonksiyon, MIME türü, indirilecek dosya adı).
_DISA_AKTAR_ROTALARI = {
    "/disa-aktar/excel": (exporters.xlsx_uret,
                          "application/vnd.openxmlformats-officedocument."
                          "spreadsheetml.sheet",
                          "secili_veriler.xlsx"),
    "/disa-aktar/word": (exporters.docx_uret,
                         "application/vnd.openxmlformats-officedocument."
                         "wordprocessingml.document",
                         "secili_veriler.docx"),
    "/disa-aktar/pdf": (exporters.pdf_uret, "application/pdf",
                        "secili_veriler.pdf"),
}


def sayfa_uret(baslik, kolon_adlari, nolar, veri, disa_aktarim_var=True):
    """Toplanmış kayıtlardan tek dosyalık, bağımsız bir HTML tablo sayfası üretir.

    `nolar`  -- gösterilecek kayıt numaraları, sıralı.
    `veri`   -- {kayit_no: [deger, ...]} biçiminde önceden toplanmış değerler
                (henüz gelmemiş / silinmiş kayıtlar için anahtar bulunmayabilir).
    `disa_aktarim_var` -- True ise sayfaya Excel/Word/PDF indirme bağlantıları
                eklenir (sunucu tarafında `_DISA_AKTAR_ROTALARI` ile eşleşir).
    """
    satir_html = []
    for no in nolar:
        degerler = veri.get(no)
        if degerler is None:
            continue
        hucreler = "".join(f"<td>{html.escape(str(d))}</td>" for d in degerler)
        satir_html.append(f"<tr><td class=\"no\">{no}</td>{hucreler}</tr>")

    baslik_hucreleri = "".join(f"<th>{html.escape(ad)}</th>" for ad in kolon_adlari)
    baslik_esc = html.escape(baslik)

    disa_aktarim_html = ""
    if disa_aktarim_var:
        disa_aktarim_html = (
            '<div class="disa-aktar">\n'
            '  <a class="buton excel" href="/disa-aktar/excel">⬇ Excel (.xlsx)</a>\n'
            '  <a class="buton word" href="/disa-aktar/word">⬇ Word (.docx)</a>\n'
            '  <a class="buton pdf" href="/disa-aktar/pdf">⬇ PDF (.pdf)</a>\n'
            "</div>\n"
        )

    govde = (
        "<!DOCTYPE html>\n"
        '<html lang="tr">\n<head>\n<meta charset="utf-8">\n'
        f"<title>{baslik_esc}</title>\n"
        "<style>\n"
        " body { font-family: 'Segoe UI', Arial, sans-serif; margin: 0;"
        " padding: 16px 20px; background:#f7f7f8; color:#1a1a1a; }\n"
        " h1 { font-size: 16px; margin: 0 0 4px; display:inline-block; }\n"
        " p.alt { color:#8a8a8a; font-size: 12px; margin: 0 0 14px; }\n"
        " .ust-satir { display:flex; align-items:flex-start;"
        " justify-content:space-between; flex-wrap:wrap; gap:10px; }\n"
        " .disa-aktar { display:flex; gap:8px; flex-wrap:wrap; }\n"
        " .buton { display:inline-block; padding:7px 14px; border-radius:6px;"
        " font-size:13px; font-weight:600; text-decoration:none; color:#fff;"
        " box-shadow:0 1px 2px rgba(0,0,0,.15); }\n"
        " .buton.excel { background:#1a7f37; }\n"
        " .buton.word { background:#1f4e79; }\n"
        " .buton.pdf { background:#b3261e; }\n"
        " .buton:hover { filter:brightness(1.08); }\n"
        " table { border-collapse: collapse; width: 100%; background:#fff;"
        " margin-top:10px; }\n"
        " th, td { border: 1px solid #ddd; padding: 4px 9px; font-size: 13px;"
        " text-align:left; white-space:nowrap; }\n"
        " th { background:#1f4e79; color:#fff; position: sticky; top: 0; }\n"
        " td.no, th.no { color:#888; text-align:right; }\n"
        " tr:nth-child(even) { background:#fafafa; }\n"
        "</style>\n</head>\n<body>\n"
        '<div class="ust-satir">\n'
        "  <div>\n"
        f"    <h1>{baslik_esc}</h1>\n"
        f'    <p class="alt">{len(satir_html)} kayıt · {len(kolon_adlari)} kolon'
        " · Büyük Veri Görüntüleyici tarafından yerel olarak yayınlandı</p>\n"
        "  </div>\n"
        f"  {disa_aktarim_html}"
        "</div>\n"
        "<table>\n<thead><tr><th class=\"no\">#</th>"
        f"{baslik_hucreleri}</tr></thead>\n<tbody>\n"
        + "\n".join(satir_html) +
        "\n</tbody>\n</table>\n</body>\n</html>"
    )
    return govde.encode("utf-8")


class _TekSayfaIsleyici(http.server.BaseHTTPRequestHandler):
    """Ana sayfayı bellekten döner; /disa-aktar/* yollarında dosya üretip indirtir."""

    def do_GET(self):
        yol = self.path.split("?", 1)[0]
        if yol in ("/", ""):
            self._gonder(self.server.sayfa_govdesi, "text/html; charset=utf-8")
            return

        baglam = getattr(self.server, "disa_aktar_baglami", None)
        rota = _DISA_AKTAR_ROTALARI.get(yol)
        if rota is not None and baglam is not None:
            uretici, mime, dosya_adi = rota
            try:
                icerik = uretici(baglam["baslik"], baglam["kolon_adlari"],
                                 baglam["nolar"], baglam["veri"])
            except Exception:
                # http.server hata mesajını latin-1 ile kodlar; ASCII dışı
                # (Türkçe) karakter kullanmak sunucuyu bu noktada çökertir.
                self.send_error(500, "Export failed")
                return
            self._gonder(icerik, mime, dosya_adi=dosya_adi)
            return

        self.send_error(404, "Not found")

    def _gonder(self, govde, mime, dosya_adi=None):
        self.send_response(200)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(govde)))
        if dosya_adi:
            self.send_header("Content-Disposition",
                             f'attachment; filename="{dosya_adi}"')
        self.end_headers()
        self.wfile.write(govde)

    def log_message(self, format, *args):
        pass  # konsol alanını kirletmesin; sunucu sessiz çalışır


class _Sunucu(http.server.ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


class WebYayini:
    """Bellekteki bir HTML sayfasını (ve dışa aktarım rotalarını) localhost'ta,
    ayrı bir iş parçacığında yayınlar.

    Her seferinde tek bir sayfa/sunucu tutar: `baslat()` önce varsa öncekini
    durdurur. Diske hiçbir şey yazılmaz; sayfa ve dışa aktarım verisi
    yalnızca bellekte tutulur.
    """

    def __init__(self):
        self._sunucu = None
        self._iplik = None

    def calisiyor_mu(self):
        return self._sunucu is not None

    def baslat(self, sayfa_govdesi, disa_aktar_baglami=None,
              host="127.0.0.1", port=0):
        """Sunucuyu (yeniden) başlatır ve (host, port) döner. Diske yazmaz.

        `disa_aktar_baglami` verilirse (`{"baslik", "kolon_adlari", "nolar",
        "veri"}`), `/disa-aktar/excel|word|pdf` yolları o veriden anlık
        olarak dosya üretip indirtir; verilmezse bu yollar 404 döner.
        """
        self.durdur()
        sunucu = _Sunucu((host, port), _TekSayfaIsleyici)
        sunucu.sayfa_govdesi = sayfa_govdesi
        sunucu.disa_aktar_baglami = disa_aktar_baglami
        self._sunucu = sunucu
        self._iplik = threading.Thread(target=sunucu.serve_forever, daemon=True)
        self._iplik.start()
        return sunucu.server_address

    def adres(self):
        if self._sunucu is None:
            return None
        host, port = self._sunucu.server_address
        return f"http://{host}:{port}/"

    def durdur(self):
        if self._sunucu is not None:
            self._sunucu.shutdown()
            self._sunucu.server_close()
            self._sunucu = None
            self._iplik = None
