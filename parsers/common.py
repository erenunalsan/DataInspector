"""Parser'lar arası ortak normalizasyon, düzleştirme ve hata türleri.

Bu modül Row/Dataset modelini models.py'den alır; parser'a özel ayrıştırma
mantığı (json_parser.py, csv_parser.py, ...) burada değil, ilgili dosyada yaşar.
"""
from typing import Any

from models import Dataset, MISSING, Row


class ParseError(Exception):
    """Dosya okuma, ayrıştırma veya normalizasyon sırasında oluşan anlaşılır hata."""


def read_text_file(path: str) -> str:
    """Dosyayı UTF-8 (BOM'lu ya da BOM'suz) metin olarak okur.

    Yalnızca dosya okuma adımıdır; ayrıştırma yapmaz. Böylece dosya okuma
    süresi, ayrıştırma süresinden ayrı ölçülebilir.
    """
    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            return f.read()
    except FileNotFoundError as e:
        raise ParseError(f"Dosya bulunamadı: {path}") from e
    except UnicodeDecodeError as e:
        raise ParseError(f"Dosya UTF-8 olarak okunamadı: {path} ({e})") from e
    except OSError as e:
        raise ParseError(f"Dosya okunamadı: {path} ({e})") from e


def _flatten_field(value: Any, path: tuple) -> dict:
    """Tek bir alanı, iç içe nesneleri nokta ayraçlı yola çözerek düzleştirir.

    Liste ve skaler değerler (metin, sayı, bool, None) birer yapraktır ve
    olduğu gibi korunur. Boş bir iç içe nesne ({}) de düzleştirilecek alt
    anahtarı olmadığı için yaprak sayılır ve kaybolmadan {} olarak kalır.
    """
    if isinstance(value, dict):
        if not value:
            return {path: {}}
        result: dict = {}
        for key, sub in value.items():
            result.update(_flatten_field(sub, path + (key,)))
        return result
    return {path: value}


def _flatten_record(record: dict) -> dict:
    """Bir kaydın (üst düzey JSON/YAML nesnesi) tüm alanlarını
    {alan_yolu_tuple: ham_değer} eşlemesine düzleştirir."""
    result: dict = {}
    for key, value in record.items():
        result.update(_flatten_field(value, (key,)))
    return result


def normalize(records: list) -> Dataset:
    """Ham kayıt listesini (dict listesi) düzleştirip kolon birleşimini
    hesaplayarak bir Dataset üretir.

    Kolon sırası, alanların veri kümesi genelinde ilk görülme sırasını izler.
    Kolon adı çakışması, kayıt içinde ya da kayıtlar arasında aynı kolon adının
    farklı alan yollarından üretilip üretilmediğine bakılarak (özgün alan yolu
    karşılaştırması) tespit edilir; böyle bir çakışma sessizce birleştirilmez,
    ParseError fırlatılır.
    """
    column_order: list = []
    column_paths: dict = {}
    flat_records: list = []

    for record in records:
        flat = _flatten_record(record)
        row_columns: dict = {}
        for path, value in flat.items():
            column_name = ".".join(path)
            existing_path = column_paths.get(column_name)
            if existing_path is None:
                column_paths[column_name] = path
                column_order.append(column_name)
            elif existing_path != path:
                raise ParseError(
                    "Kolon adı çakışması: '{0}' hem {1} hem {2} alan "
                    "yolundan üretiliyor".format(column_name, existing_path, path)
                )
            row_columns[column_name] = value
        flat_records.append(row_columns)

    rows = []
    for row_id, row_columns in enumerate(flat_records):
        raw = {col: row_columns.get(col, MISSING) for col in column_order}
        rows.append(Row(row_id=row_id, raw=raw))

    return Dataset(columns=column_order, rows=rows)
