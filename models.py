"""DataInspector ortak veri modeli.

Bu modül, projenin başka hiçbir modülüne (parsers, algorithms, decoder, gui) bağımlı değildir.
Row/Dataset, dört parser'ın da üretmesi gereken ortak sözleşmeyi tanımlar.
"""
import json
from dataclasses import dataclass
from typing import Any


class _MissingType:
    """Bir kayıtta ilgili alanın hiç bulunmadığını belirten sentinel değer."""

    def __repr__(self) -> str:
        return "MISSING"

    def __bool__(self) -> bool:
        return False


MISSING = _MissingType()


@dataclass(frozen=True)
class Row:
    row_id: int
    raw: dict


@dataclass
class Dataset:
    columns: list
    rows: list


def format_value(value: Any) -> str:
    """Ham bir değeri, tabloda gösterim ve arama için ortak metne çevirir.

    MISSING ve None boş metin olur. Liste ve sözlük (yalnızca boş iç içe
    nesne alanlarından gelebilir) JSON biçimiyle metne çevrilir; böylece
    metin tırnakları, eleman sınırları ve null değerleri korunur.
    Diğer değerler doğrudan metin karşılığına çevrilir.
    """
    if value is MISSING or value is None:
        return ""
    if isinstance(value, (list, dict)):
        return json.dumps(value, ensure_ascii=False)
    return str(value)
