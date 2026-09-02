"""JSON dosyalarını ayrıştırma ve desteklenen kök yapılarının doğrulanması.

Bu modül yalnızca ayrıştırma yapar; dosya okuma (parsers.common.read_text_file)
ve normalizasyon (parsers.common.normalize) ayrı adımlardır.
"""
import json
import math

from .common import ParseError


def _reject_special_constants(text):
    """json.loads'un parse_constant kancası: NaN/Infinity/-Infinity standart
    JSON dışı, Python'a özgü sabitlerdir. Bu sabitler sessizce float('nan')
    veya float('inf')'e çevrilmez; açıklayıcı bir ParseError fırlatılır.
    Bu kanca, kökte olduğu kadar iç içe nesne ve listelerde de geçerlidir.
    """
    raise ParseError(
        f"JSON sözdizimine uygun olmayan sabit: '{text}' (NaN/Infinity desteklenmiyor)"
    )


def _parse_float(text):
    """json.loads'un parse_float kancası: normal ondalıklı/üslü sayıları
    float'a çevirir; ancak sonuç sonsuzluğa taşarsa (ör. 1e400, -1e400)
    bunu sessizce inf/-inf yapmak yerine açıklayıcı bir ParseError fırlatır.
    Bu kanca da kökte olduğu kadar iç içe nesne ve listelerde geçerlidir.
    """
    value = float(text)
    if math.isinf(value):
        raise ParseError(f"JSON sayısı desteklenen sayısal aralığı aşıyor: {text}")
    return value


def _reject_duplicate_keys(pairs):
    """json.loads'un object_pairs_hook'u: her JSON nesnesinde (kökte, iç içe,
    liste içinde, her derinlikte) anahtar tekrarını denetler. Python'ın
    varsayılan davranışı son değeri sessizce kazandırır; burada bu izin verilmez.
    """
    seen = set()
    result = {}
    for key, value in pairs:
        if key in seen:
            raise ParseError(f"JSON içinde yinelenen anahtar: '{key}'")
        seen.add(key)
        result[key] = value
    return result


def parse(text: str) -> list:
    """JSON metnini ayrıştırır ve kayıt listesi (dict listesi) döner.

    Kök yapı kuralları:
      - Kök bir nesne ise: nesnenin tamamı tek bir kayıttır (nesnenin içindeki
        liste değerli alanlar, kayıtları ayrı ayrı açmak için kullanılmaz).
      - Kök, elemanları nesne olan bir liste ise: her nesne ayrı bir kayıttır.
      - Kök boş liste ise: kayıt yok (boş liste), bu geçerli bir durumdur.
      - Kök, nesne olmayan eleman içeren bir liste ya da skaler bir değerse:
        açıklayıcı ParseError fırlatılır.
    """
    try:
        data = json.loads(
            text,
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_special_constants,
            parse_float=_parse_float,
        )
    except json.JSONDecodeError as e:
        raise ParseError(f"Bozuk JSON: {e}") from e

    if isinstance(data, dict):
        return [data]

    if isinstance(data, list):
        if not data:
            return []
        for item in data:
            if not isinstance(item, dict):
                raise ParseError(
                    "Desteklenmeyen JSON kök yapısı: kök liste yalnızca "
                    f"nesnelerden oluşmalı, bulunan öğe türü: {type(item).__name__}"
                )
        return data

    raise ParseError(f"Desteklenmeyen JSON kök yapısı: {type(data).__name__}")
