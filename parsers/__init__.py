"""Dosya uzantısına göre uygun parser'ı seçen giriş noktası.

.json, .csv, .yaml/.yml ve .xml destekler.
"""
import os

from models import Dataset

from . import common
from . import csv_parser
from . import json_parser
from . import xml_parser
from . import yaml_parser

_SUPPORTED_EXTENSIONS = {".json", ".csv", ".yaml", ".yml", ".xml"}


def load(path: str) -> Dataset:
    """Dosyayı okur, ayrıştırır ve normalize ederek bir Dataset döner.

    Üç adım (dosya okuma, ayrıştırma, normalizasyon) bilerek ayrı fonksiyon
    çağrıları olarak tutulur; ileride her biri time.perf_counter() ile ayrı
    ölçülecektir.
    """
    ext = os.path.splitext(path)[1].lower()
    if ext not in _SUPPORTED_EXTENSIONS:
        raise common.ParseError(
            f"Desteklenmeyen dosya uzantısı: '{ext}'. Desteklenenler: "
            ".json, .csv, .yaml/.yml, .xml"
        )

    if ext == ".json":
        text = common.read_text_file(path)              # 1) dosya okuma
        records = json_parser.parse(text)                  # 2) ayrıştırma
        return common.normalize(records)                     # 3) normalizasyon

    if ext == ".csv":
        # newline="" ile hücre içi CRLF değişmeden korunur.
        text = common.read_text_file(path, newline="")
        records, headers = csv_parser.parse(text)
        return common.normalize(records, known_columns=headers)

    if ext in (".yaml", ".yml"):
        text = common.read_text_file(path)
        records = yaml_parser.parse(text)
        return common.normalize(records)

    # ext == ".xml"
    text = common.read_text_file(path)
    records = xml_parser.parse(text)
    return common.normalize(records)
