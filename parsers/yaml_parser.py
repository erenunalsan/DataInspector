"""YAML dosyalarını ayrıştırma ve desteklenen kök yapılarının doğrulanması.

Bu modül yalnızca ayrıştırma yapar; dosya okuma (parsers.common.read_text_file)
ve normalizasyon (parsers.common.normalize) ayrı adımlardır.

Kök yapı kuralları JSON ile aynıdır (bkz. json_parser.parse): kök bir nesne
ise tek kayıt, elemanları nesne olan bir liste ise çoklu kayıt, boş liste
sıfır kayıt, diğer kökler ParseError.

yaml.safe_load kullanılır (keyfi Python nesnesi deserileştirmeyi önler).
Buna rağmen safe_load; tarih (timestamp), bytes (!!binary) ve set (!!set)
gibi standart YAML türlerini üretebildiğinden, bu modülün veri modeli
bunları desteklemez ve açıkça reddeder. Metin olmayan sözlük anahtarları
(ör. YAML'da tamsayı/boolean anahtar) ve döngüsel (kendine referans veren)
alias yapıları da reddedilir.
"""
import datetime

import yaml

from .common import ParseError

_DISALLOWED_LEAF_TYPES = (datetime.date, datetime.time, bytes, bytearray, set, frozenset)


def _validate(value, stack: frozenset) -> None:
    """value içindeki tüm alt yapıyı özyinelemeli olarak doğrular:
    döngüsel referans, metin olmayan anahtar, desteklenmeyen tür."""
    if isinstance(value, dict):
        vid = id(value)
        if vid in stack:
            raise ParseError(
                "YAML içinde döngüsel (kendine referans veren) alias yapısı desteklenmiyor"
            )
        stack = stack | {vid}
        for key, sub in value.items():
            if not isinstance(key, str):
                raise ParseError(
                    f"YAML sözlük anahtarı metin olmalı, bulunan tür: {type(key).__name__} ({key!r})"
                )
            _validate(sub, stack)
        return

    if isinstance(value, list):
        vid = id(value)
        if vid in stack:
            raise ParseError(
                "YAML içinde döngüsel (kendine referans veren) alias yapısı desteklenmiyor"
            )
        stack = stack | {vid}
        for item in value:
            _validate(item, stack)
        return

    if isinstance(value, _DISALLOWED_LEAF_TYPES):
        raise ParseError(f"Desteklenmeyen YAML türü: {type(value).__name__} ({value!r})")


def parse(text: str) -> list:
    """YAML metnini ayrıştırır ve kayıt listesi (dict listesi) döner."""
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as e:
        raise ParseError(f"Bozuk YAML: {e}") from e

    if isinstance(data, dict):
        records = [data]
    elif isinstance(data, list):
        if not data:
            return []
        for item in data:
            if not isinstance(item, dict):
                raise ParseError(
                    "Desteklenmeyen YAML kök yapısı: kök liste yalnızca "
                    f"nesnelerden oluşmalı, bulunan öğe türü: {type(item).__name__}"
                )
        records = data
    else:
        raise ParseError(f"Desteklenmeyen YAML kök yapısı: {type(data).__name__}")

    for record in records:
        _validate(record, frozenset())

    return records
