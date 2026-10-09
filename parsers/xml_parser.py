"""XML dosyalarını ayrıştırma (v1 kapsamı).

Bu modül yalnızca ayrıştırma yapar; dosya okuma (parsers.common.read_text_file)
ve normalizasyon (parsers.common.normalize) ayrı adımlardır.

v1 kuralları (bkz. ARCHITECTURE.md 6.2):
  - Kök elemanın doğrudan alt elemanları birer kayıt sayılır.
  - Attribute'lar "@ad" biçiminde alan olur; alt elemanlar düz adla alan olur.
  - Aynı kayıt içinde aynı isimli birden fazla alt eleman liste olarak korunur.
  - Karma içerik (bir elemanın hem doğrudan metni hem attribute/alt eleman
    birlikte barındırması) desteklenmez; açıklayıcı ParseError verilir.
"""
import xml.etree.ElementTree as ET

from .common import ParseError


def parse(text: str) -> list:
    """XML metnini ayrıştırır ve kayıt listesi (dict listesi) döner."""
    try:
        root = ET.fromstring(text)
    except ET.ParseError as e:
        raise ParseError(f"Bozuk XML: {e}") from e

    records = []
    for child in root:
        value = _element_to_value(child)
        if not isinstance(value, dict):
            raise ParseError(
                f"Desteklenmeyen XML kaydı: <{child.tag}> hiçbir alan "
                "(attribute/alt eleman) içermiyor"
            )
        records.append(value)
    return records


def _element_to_value(element):
    """Bir XML elemanını ham bir değere çevirir: attribute/alt eleman yoksa
    düz metin (yaprak), varsa {"@attr": ..., "alt_eleman": ...} biçiminde
    bir sözlük. Aynı isimli birden fazla alt eleman listeye toplanır."""
    raw_text = element.text
    text = (raw_text or "").strip()
    has_children = len(element) > 0
    has_attribs = bool(element.attrib)

    if text and (has_children or has_attribs):
        raise ParseError(
            f"Desteklenmeyen XML yapısı: <{element.tag}> hem metin hem "
            "attribute/alt eleman içeriyor (karma içerik desteklenmiyor)"
        )

    if not has_children and not has_attribs:
        return raw_text if raw_text is not None else ""

    result: dict = {}
    for key, value in element.attrib.items():
        result["@" + key] = value

    for child in element:
        child_value = _element_to_value(child)
        if child.tag in result:
            existing = result[child.tag]
            if isinstance(existing, list):
                existing.append(child_value)
            else:
                result[child.tag] = [existing, child_value]
        else:
            result[child.tag] = child_value

    return result
