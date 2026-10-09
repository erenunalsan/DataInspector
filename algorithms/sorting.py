"""Kendi stabil Merge Sort implementasyonumuz.

sorted()/list.sort() ana sıralamada kullanılmaz. Sıralama yalnızca
view_order (row_id listesi) üzerinde çalışır; Dataset.rows hiçbir zaman
yeniden sıralanmaz.

Tip grupları (öncelik sırası): Bool -> Sayı -> Metin -> Karmaşık (liste vb.).
Artan/azalan yön yalnızca aynı grup içindeki karşılaştırmaya uygulanır;
gruplar arası öncelik yönden etkilenmez. MISSING/None/NaN, yönden bağımsız
olarak her zaman sonda kalır. Bu sürümde sayısal görünümlü metinler
(ör. "00123") metin olarak sıralanır; ayrı bir sayısal yorumlama yapılmaz.
"""
import math

from models import MISSING


def _is_novalue(value) -> bool:
    if value is MISSING or value is None:
        return True
    if isinstance(value, float) and math.isnan(value):
        return True
    return False


def _type_rank(value) -> int:
    if isinstance(value, bool):
        return 0
    if isinstance(value, (int, float)):
        return 1
    if isinstance(value, str):
        return 2
    return 3  # liste vb. karmaşık türler


def _comparable(value):
    rank = _type_rank(value)
    if rank == 3:
        return (rank, str(value))
    return (rank, value)


def merge_sort_view(dataset, view_order: list, column: str, ascending: bool) -> list:
    """dataset.rows'daki 'column' alanına göre view_order'ın stabil, sıralı
    bir kopyasını döner. dataset.rows'a dokunmaz."""
    rows_by_id = {row.row_id: row for row in dataset.rows}

    def key_of(row_id):
        return rows_by_id[row_id].raw.get(column, MISSING)

    def comes_before(a_id, b_id) -> bool:
        a = key_of(a_id)
        b = key_of(b_id)
        a_novalue = _is_novalue(a)
        b_novalue = _is_novalue(b)
        if a_novalue or b_novalue:
            # MISSING/None/NaN her zaman sonda; ikisi de novalue ise "esit" (False).
            return False if a_novalue else True
        ca, cb = _comparable(a), _comparable(b)
        return ca < cb if ascending else cb < ca

    items = list(view_order)
    _merge_sort(items, comes_before)
    return items


def _merge_sort(items: list, comes_before) -> None:
    """Yerinde, stabil merge sort. comes_before(a, b): a, b'den once mi gelmeli?"""
    if len(items) <= 1:
        return
    mid = len(items) // 2
    left = items[:mid]
    right = items[mid:]
    _merge_sort(left, comes_before)
    _merge_sort(right, comes_before)

    i = j = k = 0
    while i < len(left) and j < len(right):
        if comes_before(right[j], left[i]):
            items[k] = right[j]
            j += 1
        else:
            items[k] = left[i]
            i += 1
        k += 1
    while i < len(left):
        items[k] = left[i]
        i += 1
        k += 1
    while j < len(right):
        items[k] = right[j]
        j += 1
        k += 1
