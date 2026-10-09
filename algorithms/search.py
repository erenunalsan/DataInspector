"""Kendi KMP (Knuth-Morris-Pratt) tabanlı metin arama implementasyonumuz.

Hazır alt-dize arama fonksiyonlarına (str.find/in/re) bırakılmaz. Sorgunun
ön işlem (failure) tablosu bir arama işlemi başına yalnızca bir kez kurulur;
taranan her hücre için yeniden hesaplanmaz. İlk sürüm büyük/küçük harfe
duyarlıdır (case-sensitive).
"""
from models import MISSING, format_value


def build_failure_table(pattern: str) -> list:
    """KMP'nin ön işlem (failure/prefix) tablosunu kurar. O(m)."""
    table = [0] * len(pattern)
    length = 0
    i = 1
    while i < len(pattern):
        if pattern[i] == pattern[length]:
            length += 1
            table[i] = length
            i += 1
        elif length != 0:
            length = table[length - 1]
        else:
            table[i] = 0
            i += 1
    return table


def kmp_contains(text: str, pattern: str, failure_table: list) -> bool:
    """pattern, text içinde geçiyor mu? O(n) (failure_table önceden kurulmuş olmalı)."""
    if not pattern:
        return False
    n, m = len(text), len(pattern)
    if m > n:
        return False
    i = j = 0
    while i < n:
        if text[i] == pattern[j]:
            i += 1
            j += 1
            if j == m:
                return True
        elif j != 0:
            j = failure_table[j - 1]
        else:
            i += 1
    return False


def find_matches(dataset, view_order: list, query: str) -> list:
    """Sorguyu, mevcut view_order sırasındaki tüm kayıtların tüm
    kolonlarındaki format_value metninde arar. Bir satırda en az bir
    kolonda eşleşme varsa o satırın row_id'si bir kez sonuç listesine
    eklenir. Sonuç, view_order sırasını izler. Boş sorgu için boş liste
    döner (çağıran taraf bunu "sonuçları temizle" olarak yorumlayabilir).
    """
    if not query:
        return []

    failure_table = build_failure_table(query)
    rows_by_id = {row.row_id: row for row in dataset.rows}

    matches = []
    for row_id in view_order:
        row = rows_by_id[row_id]
        for column in dataset.columns:
            text = format_value(row.raw.get(column, MISSING))
            if kmp_contains(text, query, failure_table):
                matches.append(row_id)
                break
    return matches
