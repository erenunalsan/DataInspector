"""Seçili verileri Excel (.xlsx), Word (.docx) ve PDF olarak üreten dışa aktarım.

Hepsi tek bir prensiple çalışır: girdi zaten `SeciliVerilerPenceresi` /
`webserver.py` tarafından bellekte toplanmış küçük bir kayıt kümesidir
({kayit_no: [deger, ...]}), bu modül onu ilgili dosya biçiminin BAYTLARINA
çevirir ve döner -- hiçbir şey diske yazmaz, hiçbir üçüncü taraf kütüphane
gerektirmez (yalnızca standart kütüphane: `zipfile`, `xml`/elle üretilen
XML, elle üretilen PDF nesneleri). Kullanıcı bu baytları tarayıcısı
üzerinden KENDİ bilgisayarına indirir; bu, "diske yazma yok" ilkesinin
ihlali değildir -- o ilke kaynak dosyanın (60-120 GB) gizlice
önbelleklenmesini yasaklar, kullanıcının açıkça istediği küçük bir çıktı
dosyasını değil.

Excel ve Word biçimleri (OOXML = zip + XML) UTF-8 olduğundan Türkçe dahil
her karakteri tam destekler. PDF'in temel 14 fontu (Helvetica, burada
kullanılan) yalnızca WinAnsiEncoding (cp1252) destekler; bu kod sayfasında
ç/Ç, ö/Ö, ü/Ü vardır ama ğ/Ğ, ş/Ş, ı/İ YOKTUR. Bir yazı tipini gömmeden bu
sınırın aşılması mümkün olmadığından, PDF çıktısında yalnızca bu altı harf
en yakın ASCII karşılığına çevrilir (bkz. `_TR_PDF_CEVIRI`); Excel/Word
çıktılarında hiçbir çeviri yapılmaz.
"""
import io
import zipfile

__all__ = ["xlsx_uret", "docx_uret", "pdf_uret"]


# ======================================================================
# Ortak yardımcılar
# ======================================================================
def _xml_kacis(metin):
    return (str(metin)
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;"))


def _hucreler(nolar, veri):
    """(kayit_no, [deger,...]) çiftlerini, eksik olanları atlayarak sıralar."""
    for no in nolar:
        degerler = veri.get(no)
        if degerler is not None:
            yield no, degerler


# ======================================================================
# XLSX (Excel) -- OOXML: zip içinde birkaç küçük XML parçası
# ======================================================================
def _xlsx_sutun_harfi(sifir_tabanli_indeks):
    idx = sifir_tabanli_indeks + 1
    harf = ""
    while idx > 0:
        idx, kalan = divmod(idx - 1, 26)
        harf = chr(65 + kalan) + harf
    return harf


def xlsx_uret(baslik, kolon_adlari, nolar, veri):
    """Tek sayfalık, gerçek (.xlsx) baytlarını döner -- yalnızca stdlib ile."""
    basliklar = ["#"] + list(kolon_adlari)
    satir_xml = []

    def _satir_yaz(satir_no, hucreler, kalin):
        stil = ' s="1"' if kalin else ""
        parcalar = [f'<row r="{satir_no}">']
        for i, deger in enumerate(hucreler):
            ref = f"{_xlsx_sutun_harfi(i)}{satir_no}"
            metin = _xml_kacis(deger)
            parcalar.append(
                f'<c r="{ref}" t="inlineStr"{stil}><is><t xml:space="preserve">'
                f'{metin}</t></is></c>')
        parcalar.append("</row>")
        satir_xml.append("".join(parcalar))

    _satir_yaz(1, basliklar, kalin=True)
    satir_no = 2
    for no, degerler in _hucreler(nolar, veri):
        hucreler = [str(no)] + [
            degerler[i] if i < len(degerler) else "" for i in range(len(kolon_adlari))]
        _satir_yaz(satir_no, hucreler, kalin=False)
        satir_no += 1

    sheet_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        "<sheetData>" + "".join(satir_xml) + "</sheetData></worksheet>"
    )

    content_types = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.'
        'relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxml'
        'formats-officedocument.spreadsheetml.sheet.main+xml"/>'
        '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/'
        'vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxml'
        'formats-officedocument.spreadsheetml.styles+xml"/>'
        "</Types>"
    )
    root_rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/'
        'relationships"><Relationship Id="rId1" Type="http://schemas.openxml'
        'formats.org/officeDocument/2006/relationships/officeDocument" '
        'Target="xl/workbook.xml"/></Relationships>'
    )
    workbook_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        f'<sheets><sheet name="{_xml_kacis(baslik)[:31] or "Veriler"}" sheetId="1" '
        'r:id="rId1"/></sheets></workbook>'
    )
    workbook_rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/'
        'relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/office'
        'Document/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>'
        '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/office'
        'Document/2006/relationships/styles" Target="styles.xml"/>'
        "</Relationships>"
    )
    styles_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        '<fonts count="2"><font><sz val="11"/><name val="Calibri"/></font>'
        '<font><b/><sz val="11"/><name val="Calibri"/></font></fonts>'
        '<fills count="2"><fill><patternFill patternType="none"/></fill>'
        '<fill><patternFill patternType="gray125"/></fill></fills>'
        '<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border>'
        "</borders>"
        '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/>'
        "</cellStyleXfs>"
        '<cellXfs count="2">'
        '<xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>'
        '<xf numFmtId="0" fontId="1" fillId="0" borderId="0" xfId="0" applyFont="1"/>'
        "</cellXfs></styleSheet>"
    )

    arabellek = io.BytesIO()
    with zipfile.ZipFile(arabellek, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", content_types)
        z.writestr("_rels/.rels", root_rels)
        z.writestr("xl/workbook.xml", workbook_xml)
        z.writestr("xl/_rels/workbook.xml.rels", workbook_rels)
        z.writestr("xl/styles.xml", styles_xml)
        z.writestr("xl/worksheets/sheet1.xml", sheet_xml)
    return arabellek.getvalue()


# ======================================================================
# DOCX (Word) -- OOXML: zip içinde tek bir document.xml + tablo
# ======================================================================
def docx_uret(baslik, kolon_adlari, nolar, veri):
    """Başlık + tablo içeren gerçek (.docx) baytlarını döner -- yalnızca stdlib."""
    basliklar = ["#"] + list(kolon_adlari)

    def _hucre_xml(metin, kalin):
        r_props = "<w:rPr><w:b/></w:rPr>" if kalin else ""
        return (
            "<w:tc><w:p><w:r>" + r_props +
            f'<w:t xml:space="preserve">{_xml_kacis(metin)}</w:t></w:r></w:p></w:tc>'
        )

    satirlar_xml = ["<w:tr>" + "".join(
        _hucre_xml(b, kalin=True) for b in basliklar) + "</w:tr>"]
    kayit_sayisi = 0
    for no, degerler in _hucreler(nolar, veri):
        hucreler = [str(no)] + [
            degerler[i] if i < len(degerler) else "" for i in range(len(kolon_adlari))]
        satirlar_xml.append(
            "<w:tr>" + "".join(_hucre_xml(h, kalin=False) for h in hucreler) + "</w:tr>")
        kayit_sayisi += 1

    kenarlik = (
        '<w:tblBorders>'
        '<w:top w:val="single" w:sz="4" w:color="999999"/>'
        '<w:left w:val="single" w:sz="4" w:color="999999"/>'
        '<w:bottom w:val="single" w:sz="4" w:color="999999"/>'
        '<w:right w:val="single" w:sz="4" w:color="999999"/>'
        '<w:insideH w:val="single" w:sz="4" w:color="999999"/>'
        '<w:insideV w:val="single" w:sz="4" w:color="999999"/>'
        "</w:tblBorders>"
    )
    document_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/'
        '2006/main">'
        "<w:body>"
        '<w:p><w:pPr><w:spacing w:after="120"/></w:pPr><w:r><w:rPr><w:b/>'
        f'<w:sz w:val="32"/></w:rPr><w:t xml:space="preserve">{_xml_kacis(baslik)}'
        "</w:t></w:r></w:p>"
        '<w:p><w:pPr><w:spacing w:after="200"/></w:pPr><w:r><w:rPr><w:color w:val='
        f'"666666"/></w:rPr><w:t xml:space="preserve">{kayit_sayisi} kayıt · '
        f'{len(kolon_adlari)} kolon · Büyük Veri Görüntüleyici tarafından dışa '
        'aktarıldı</w:t></w:r></w:p>'
        '<w:tbl><w:tblPr><w:tblW w:w="0" w:type="auto"/>' + kenarlik + "</w:tblPr>"
        + "".join(satirlar_xml) + "</w:tbl>"
        '<w:p/><w:sectPr><w:pgSz w:w="16838" w:h="11906" w:orient="landscape"/>'
        '<w:pgMar w:top="720" w:right="720" w:bottom="720" w:left="720"/></w:sectPr>'
        "</w:body></w:document>"
    )

    content_types = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.'
        'relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/word/document.xml" ContentType="application/vnd.openxml'
        'formats-officedocument.wordprocessingml.document.main+xml"/>'
        "</Types>"
    )
    root_rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/'
        'relationships"><Relationship Id="rId1" Type="http://schemas.openxml'
        'formats.org/officeDocument/2006/relationships/officeDocument" '
        'Target="word/document.xml"/></Relationships>'
    )

    arabellek = io.BytesIO()
    with zipfile.ZipFile(arabellek, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", content_types)
        z.writestr("_rels/.rels", root_rels)
        z.writestr("word/document.xml", document_xml)
    return arabellek.getvalue()


# ======================================================================
# PDF -- elle üretilen, çok sayfalı, tablo düzenli PDF 1.4
# ======================================================================
_TR_PDF_CEVIRI = str.maketrans({
    "ğ": "g", "Ğ": "G",
    "ş": "s", "Ş": "S",
    "ı": "i", "İ": "I",
})

_SAYFA_GENISLIK = 841.89   # A4 yatay (pt)
_SAYFA_YUKSEKLIK = 595.28
_KENAR = 32
_SATIR_YUKSEKLIK = 14
_PUNTO_GOVDE = 8
_PUNTO_BASLIK = 9
_KARAKTER_PT = 0.52        # Helvetica ortalama karakter genişliği ~ punto * bu katsayı


def _pdf_metin_hazirla(deger):
    """Türkçe'ye özgü 6 harfi çevirir, kalanı WinAnsiEncoding'e (cp1252) sığdırır."""
    s = str(deger).translate(_TR_PDF_CEVIRI)
    try:
        s.encode("cp1252")
    except UnicodeEncodeError:
        s = s.encode("cp1252", errors="replace").decode("cp1252")
    return s


def _pdf_kes(metin, maks_pt, punto=_PUNTO_GOVDE):
    maks_karakter = max(1, int(maks_pt / (punto * _KARAKTER_PT)))
    if len(metin) <= maks_karakter:
        return metin
    if maks_karakter <= 1:
        return metin[:maks_karakter]
    return metin[:maks_karakter - 1] + "…"


def _pdf_dize_kacis(metin):
    return metin.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def _sutun_genislikleri(basliklar, satirlar, toplam_genislik):
    uzunluklar = [len(b) for b in basliklar]
    for satir in satirlar:
        for i, hucre in enumerate(satir):
            if len(hucre) > uzunluklar[i]:
                uzunluklar[i] = len(hucre)
    min_pt, maks_pt = 34, 210
    genislikler = [min(max(u * _PUNTO_GOVDE * _KARAKTER_PT + 8, min_pt), maks_pt)
                   for u in uzunluklar]
    toplam = sum(genislikler)
    if toplam > toplam_genislik and toplam > 0:
        olcek = toplam_genislik / toplam
        genislikler = [g * olcek for g in genislikler]
    return genislikler


class _PdfNesneleri:
    """PDF 1.4 nesnelerini biriktirip xref/trailer ile tek bir dosyaya yazar."""

    def __init__(self):
        self._govdeler = []

    def ekle(self, govde_bytes):
        self._govdeler.append(govde_bytes)
        return len(self._govdeler)

    def guncelle(self, num, govde_bytes):
        self._govdeler[num - 1] = govde_bytes

    def yaz(self, kok_num):
        parcalar = [b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n"]
        konum = len(parcalar[0])
        ofsetler = [0] * (len(self._govdeler) + 1)
        for i, govde in enumerate(self._govdeler, start=1):
            ofsetler[i] = konum
            obj = f"{i} 0 obj\n".encode("ascii") + govde + b"\nendobj\n"
            parcalar.append(obj)
            konum += len(obj)
        xref_konum = konum
        satirlar = [f"xref\n0 {len(self._govdeler) + 1}\n".encode("ascii"),
                    b"0000000000 65535 f \n"]
        for i in range(1, len(self._govdeler) + 1):
            satirlar.append(f"{ofsetler[i]:010d} 00000 n \n".encode("ascii"))
        parcalar.extend(satirlar)
        parcalar.append(
            (f"trailer\n<< /Size {len(self._govdeler) + 1} /Root {kok_num} 0 R >>\n"
             f"startxref\n{xref_konum}\n%%EOF").encode("ascii"))
        return b"".join(parcalar)


def pdf_uret(baslik, kolon_adlari, nolar, veri):
    """Çok sayfalı, tablo düzenli gerçek PDF baytlarını döner -- yalnızca stdlib."""
    basliklar = ["#"] + [_pdf_metin_hazirla(k) for k in kolon_adlari]
    satirlar = []
    for no, degerler in _hucreler(nolar, veri):
        hucre = [str(no)] + [
            _pdf_metin_hazirla(degerler[i] if i < len(degerler) else "")
            for i in range(len(kolon_adlari))]
        satirlar.append(hucre)

    toplam_genislik = _SAYFA_GENISLIK - 2 * _KENAR
    genislikler = _sutun_genislikleri(basliklar, satirlar, toplam_genislik)
    x_konumlari = []
    x = _KENAR
    for g in genislikler:
        x_konumlari.append(x)
        x += g

    nesneler = _PdfNesneleri()
    font_govde = nesneler.ekle(
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>")
    font_kalin = nesneler.ekle(
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold "
        b"/Encoding /WinAnsiEncoding >>")

    baslik_hazir = _pdf_metin_hazirla(baslik)
    alt_baslik = (f"{len(satirlar)} kayit, {len(kolon_adlari)} kolon - "
                  "Buyuk Veri Goruntuleyici tarafindan disa aktarildi")
    tercume_notu = ("Not: PDF standart fontu bazi Turkce karakterleri (g,s,i "
                     "noktasiz) tam desteklemedigi icin sadelestirilmistir; "
                     "Excel/Word ciktilarinda tum karakterler tam desteklenir.")

    ust_sinir = _SAYFA_YUKSEKLIK - _KENAR
    baslik_yuksekligi = 30
    satir_no_index = 0
    toplam_sayfa_no = 1
    sayfa_numaralari = []  # (page_num, contents_num) çiftleri sonradan doldurulur
    tum_akislar = []

    def _yeni_sayfa_baslat():
        return [], ust_sinir - baslik_yuksekligi

    def _metin_komutu(x, y, metin, font_ref, punto):
        return (f"BT /{font_ref} {punto} Tf 1 0 0 1 {x:.2f} {y:.2f} Tm "
                f"({_pdf_dize_kacis(metin)}) Tj ET\n")

    akis, y = _yeni_sayfa_baslat()
    ilk_sayfa = True

    def _baslik_bandi_ekle(akis_listesi, ilk_mi):
        nonlocal y
        if ilk_mi:
            akis_listesi.append(_metin_komutu(_KENAR, ust_sinir, baslik_hazir,
                                              "FB", 14))
            akis_listesi.append(_metin_komutu(_KENAR, ust_sinir - 16, alt_baslik,
                                              "F", 8))
        # Kolon başlıkları (her sayfada tekrar edilir).
        for i, b in enumerate(basliklar):
            metin = _pdf_kes(b, genislikler[i], _PUNTO_BASLIK)
            akis_listesi.append(_metin_komutu(x_konumlari[i] + 2, y, metin,
                                              "FB", _PUNTO_BASLIK))
        cizgi_y = y - 3
        akis_listesi.append(
            f"0.6 0.6 0.6 RG {_KENAR:.2f} {cizgi_y:.2f} m "
            f"{_SAYFA_GENISLIK - _KENAR:.2f} {cizgi_y:.2f} l S\n")
        y -= _SATIR_YUKSEKLIK

    _baslik_bandi_ekle(akis, ilk_sayfa)

    def _sayfayi_bitir(akis_listesi):
        icerik = "".join(akis_listesi).encode("cp1252", errors="replace")
        stream_govde = (
            f"<< /Length {len(icerik)} >>\nstream\n".encode("ascii") + icerik +
            b"\nendstream")
        return nesneler.ekle(stream_govde)

    sayfa_icerikleri = []  # contents obj numaraları

    for satir in satirlar:
        if y < _KENAR + _SATIR_YUKSEKLIK:
            sayfa_icerikleri.append(_sayfayi_bitir(akis))
            akis, y = _yeni_sayfa_baslat()
            toplam_sayfa_no += 1
            _baslik_bandi_ekle(akis, ilk_mi=False)
        for i, hucre in enumerate(satir):
            metin = _pdf_kes(hucre, genislikler[i], _PUNTO_GOVDE)
            akis.append(_metin_komutu(x_konumlari[i] + 2, y, metin, "F", _PUNTO_GOVDE))
        y -= _SATIR_YUKSEKLIK

    if not satirlar:
        akis.append(_metin_komutu(_KENAR, y, "kayit yok", "F", _PUNTO_GOVDE))
    akis.append(_metin_komutu(_KENAR, _KENAR / 2, tercume_notu, "F", 6))
    sayfa_icerikleri.append(_sayfayi_bitir(akis))

    pages_num = nesneler.ekle(b"")  # yer tutucu, Kids listesi bilindikten sonra doldurulacak
    sayfa_num_listesi = []
    for icerik_num in sayfa_icerikleri:
        sayfa_num = nesneler.ekle(
            (f"<< /Type /Page /Parent {pages_num} 0 R "
             f"/MediaBox [0 0 {_SAYFA_GENISLIK:.2f} {_SAYFA_YUKSEKLIK:.2f}] "
             f"/Resources << /Font << /F {font_govde} 0 R /FB {font_kalin} 0 R >> >> "
             f"/Contents {icerik_num} 0 R >>").encode("ascii"))
        sayfa_num_listesi.append(sayfa_num)

    kids = " ".join(f"{n} 0 R" for n in sayfa_num_listesi)
    nesneler.guncelle(
        pages_num,
        (f"<< /Type /Pages /Kids [{kids}] /Count {len(sayfa_num_listesi)} >>")
        .encode("ascii"))

    kok_num = nesneler.ekle(
        f"<< /Type /Catalog /Pages {pages_num} 0 R >>".encode("ascii"))

    return nesneler.yaz(kok_num)
