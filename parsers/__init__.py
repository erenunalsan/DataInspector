"""Dosya uzantısına göre uygun parser'ı seçen giriş noktası.

Şimdilik yalnızca .json destekler; diğer uzantılar STEP 2'nin sonraki
parçalarında (CSV/YAML/XML) eklenecektir.
"""
import os

from models import Dataset

from . import common
from . import json_parser

_SUPPORTED_EXTENSIONS = {".json"}


def load(path: str) -> Dataset:
    """Dosyayı okur, ayrıştırır ve normalize ederek bir Dataset döner.

    Üç adım (dosya okuma, ayrıştırma, normalizasyon) bilerek ayrı fonksiyon
    çağrıları olarak tutulur; ileride her biri time.perf_counter() ile ayrı
    ölçülecektir.
    """
    ext = os.path.splitext(path)[1].lower()
    if ext not in _SUPPORTED_EXTENSIONS:
        raise common.ParseError(
            f"Desteklenmeyen dosya uzantısı: '{ext}'. Şu an yalnızca .json destekleniyor."
        )

    text = common.read_text_file(path)          # 1) dosya okuma
    records = json_parser.parse(text)             # 2) ayrıştırma
    return common.normalize(records)                # 3) normalizasyon
