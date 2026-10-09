"""CSV dosyalarını ayrıştırma.

Bu modül yalnızca ayrıştırma yapar; dosya okuma (parsers.common.read_text_file)
ve normalizasyon (parsers.common.normalize) ayrı adımlardır.

v1 kapsamı: ayraç virgül (","), alıntılama karakteri çift tırnak ('"').
Ayraç/başlık tahmini (sniffing) yapılmaz; noktalı virgül/tab desteği
sonraya bırakılmıştır.
"""
import csv
import io

from .common import ParseError


def parse(text: str) -> tuple:
    """CSV metnini ayrıştırır ve (records, headers) döner.

    - İlk boş olmayan kayıt başlık satırı kabul edilir; başlık sırası korunur.
    - Tekrarlanan, boş veya yalnızca boşluk içeren başlıklar ParseError'dır.
      Geçerli başlıklar olduğu gibi (kırpılmadan) kolon adı olur.
    - Tamamen boş fiziksel satırlar (csv.reader'ın [] döndürdüğü satırlar)
      atlanır. Ayraç veya tırnakla belirtilmiş boş hücrelerden oluşan
      kayıtlar bu kapsamda DEĞİLDİR; normal veri kaydı olarak işlenir.
    - Alan sayısı başlık sayısıyla uyuşmayan kayıtlar ParseError'dır.
    - Tüm hücre değerleri metin olarak kalır; hiçbir dönüştürme yapılmaz,
      baştaki/sondaki boşluklar korunur.
    - Boş dosya (records=[], headers=[]) ve yalnızca başlık içeren dosya
      (records=[], headers=[...]) geçerli, ayrı durumlardır.
    """
    reader = csv.reader(io.StringIO(text), delimiter=",", quotechar='"', strict=True)

    try:
        headers = _read_header_row(reader)
        if headers is None:
            return [], []

        _validate_headers(headers)

        records = []
        for row in reader:
            if row == []:
                continue
            if len(row) != len(headers):
                raise ParseError(
                    "CSV kaydındaki alan sayısı başlıkla uyuşmuyor (fiziksel "
                    f"satır {reader.line_num}): beklenen {len(headers)}, "
                    f"bulunan {len(row)}"
                )
            records.append(dict(zip(headers, row)))
        return records, headers
    except csv.Error as e:
        raise ParseError(f"Bozuk CSV (fiziksel satır {reader.line_num}): {e}") from e


def _read_header_row(reader):
    """İlk boş olmayan ([] olmayan) kaydı başlık satırı olarak döner.
    Yalnızca tamamen boş fiziksel satırlardan oluşan ya da hiç satırı
    olmayan bir dosya için None döner (boş dosya durumu)."""
    for row in reader:
        if row == []:
            continue
        return row
    return None


def _validate_headers(headers: list) -> None:
    seen = set()
    for header in headers:
        if not header.strip():
            raise ParseError(f"Boş veya yalnızca boşluk içeren kolon başlığı: {header!r}")
        if header in seen:
            raise ParseError(f"Tekrarlanan kolon başlığı: '{header}'")
        seen.add(header)
