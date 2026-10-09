"""ijson tabanlı, yapılandırılabilir seçicili akış kaynağı.

Kökün kendisi bir dizi (array) olabilir, ya da kök bir nesne (object) olup
onun doğrudan bir alanındaki DİZİNİN elemanları hedeflenebilir. Hangi
alanın seçileceği çağıran tarafından yapılandırılır (sıra numarası -- 1
tabanlı --, gerçek anahtar adı ya da "ilk dizi" sezgisi) — hiçbir gerçek
anahtar adı bu modülün içine sabit kodlanmaz.

Yapı (nesne mi, pozisyonel dizi mi) yalnızca ijson'ın ürettiği olaylara
(start_map/start_array/...) bakılarak belirlenir; satır başlangıcı, elle
parantez sayma ya da rastgele bayt kesme YOKTUR. Tüm sözdizimi kararı
ijson'a aittir; bu modül yalnızca zaten doğru ayrıştırılmış olay akışını
bir Python nesnesine yeniden birleştirir (start_map/start_array'den
end_map/end_array'e kadar).

Tek bir kaydın boyutu/derinliği, o kayıt HENÜZ İNŞA EDİLİRKEN (akış
sırasında, olaylar geldikçe artan bir sayaçla) sınırlanabilir -- bu,
nesne tamamen kurulduktan SONRA yapılan bir ölçüm değil, kurulum
sırasında erken çıkış yapabilen önleyici bir korumadır (yaklaşık/tahmini
bir bayt sayımı kullanır, `pickle`/`json` ile tam serileştirme yapmaz).
"""
from decimal import Decimal

import ijson

STOP_RECORD_LIMIT = "kayit_siniri"
STOP_BYTE_BUDGET = "bayt_siniri"
STOP_ARRAY_COMPLETE = "dizi_tamamlandi"          # secilen dizi tamamen kapandi (butce/sinir asimi yok)
STOP_SOURCE_REAL_EOF = "kaynak_dosyasi_tamamen_bitti"  # ijson tum belgeyi (kok dahil) tuketti
STOP_FULLY_DRAINED = "belge_sonuna_kadar_dogrulandi"     # dizi kapandi VE geri kalan belge de EOF'a kadar gecerli
STOP_PARSE_ERROR = "ayristirma_hatasi"
STOP_SOURCE_IO_ERROR = "kaynak_okuma_hatasi"               # kaynak dosyaya erisim kesildi/okunamadi
STOP_RECORD_TOO_LARGE = "kayit_cok_buyuk"
STOP_RECORD_TOO_DEEP = "kayit_cok_derin"

# tamamlandi_mi=True sayilan durmalar (hicbir budama/hata yok). NOT: bu,
# run_pilot.py gibi BUDANMIS/ornekleme amacli akislar icindir --
# import_job.py'nin "tam aktarim" tanimi daha katidir (yalnizca
# STOP_FULLY_DRAINED), bkz. o modulun kendi mantigi.
COMPLETE_STOP_REASONS = (STOP_ARRAY_COMPLETE, STOP_SOURCE_REAL_EOF)


class SelectorError(Exception):
    """Yapılandırılan alan seçici, kökte (nesne ya da bizzat kök) bir dizi ile eşleşmedi."""


class RecordTooLargeError(Exception):
    """Tek bir kaydın akış sırasında ölçülen (yaklaşık) boyutu, yapılandırılan sınırı aştı."""


class RecordTooDeepError(Exception):
    """Tek bir kaydın iç içe geçme derinliği yapılandırılan sınırı aştı."""


def _classify(value: object) -> str:
    if isinstance(value, dict):
        return "nesne"
    if isinstance(value, list):
        return "dizi_pozisyonel"
    return "skaler_kok_eleman"


def _approx_scalar_bytes(value) -> int:
    """Bir skaler değerin KABA/yaklaşık bayt boyutu -- tam serileştirme
    yapmaz (bu pahalı olurdu); yalnızca akış sırasında ucuz bir üst sınır
    tahminidir."""
    if isinstance(value, str):
        return len(value.encode("utf-8", "ignore")) + 8
    if isinstance(value, bool):
        return 8
    if isinstance(value, int):
        return value.bit_length() // 8 + 16
    if isinstance(value, Decimal):
        return len(str(value)) + 16
    return 16  # float/None/diger kucuk skalerler icin kaba sabit


def _consume_value(events, first, depth=0, max_depth=None, size_tracker=None, max_bytes=None):
    """`first` (prefix, event, value) olarak zaten tüketilmiş ilk olaydır.
    ijson'ın ürettiği (zaten doğru tipe çözülmüş) olay akışından TAM bir
    Python değeri (dict/list/skaler) yeniden kurar. Akış budama/hata
    nedeniyle yarıda keserse, bu fonksiyon hiçbir zaman kısmi bir değer
    DÖNDÜRMEZ — istisna, üst çağırana kadar yükselir ve o ana kadar
    biriktirilen kısmi nesne çöpe gider (asla yield edilmez).

    max_depth/size_tracker+max_bytes verilirse, bu kontroller kayıt HENÜZ
    İNŞA EDİLİRKEN (her olay geldiğinde) uygulanır -- kayıt tamamlandıktan
    sonra yapılan bir ölçüm DEĞİLDİR."""
    prefix, event, value = first

    if max_depth is not None and depth > max_depth:
        raise RecordTooDeepError(
            f"İç içe yapı derinliği sınırı aşıldı (sınır {max_depth}, konum: {prefix})"
        )

    if event == "start_map":
        obj = {}
        pending_key = None
        for ev in events:
            p2, e2, v2 = ev
            if e2 == "end_map":
                return obj
            if e2 == "map_key":
                pending_key = v2
                if size_tracker is not None:
                    size_tracker[0] += _approx_scalar_bytes(v2)
                    if size_tracker[0] > max_bytes:
                        raise RecordTooLargeError(
                            f"Kayıt boyutu (yaklaşık, akış sırasında ölçülen) sınırı aştı "
                            f"({size_tracker[0]} > {max_bytes} bayt)"
                        )
                continue
            obj[pending_key] = _consume_value(events, ev, depth + 1, max_depth, size_tracker, max_bytes)
        raise SelectorError("beklenmeyen akış sonu (nesne kapanmadan)")

    if event == "start_array":
        arr = []
        for ev in events:
            p2, e2, v2 = ev
            if e2 == "end_array":
                return arr
            arr.append(_consume_value(events, ev, depth + 1, max_depth, size_tracker, max_bytes))
        raise SelectorError("beklenmeyen akış sonu (dizi kapanmadan)")

    if size_tracker is not None:
        size_tracker[0] += _approx_scalar_bytes(value)
        if size_tracker[0] > max_bytes:
            raise RecordTooLargeError(
                f"Kayıt boyutu (yaklaşık, akış sırasında ölçülen) sınırı aştı "
                f"({size_tracker[0]} > {max_bytes} bayt)"
            )
    return value


class StreamingArraySource:
    """selector örnekleri:
        {"mode": "root_array"}                 # kokun KENDISI dizi (nesne sarmalayici yok)
        {"mode": "index", "value": 3}           # kokteki 3. dogrudan alan (1-tabanli)
        {"mode": "name", "value": "gercek_ad"}    # gercek anahtar adiyla eslesme
        {"mode": "first_array"}                    # dizi-degerli ilk kok alani (sessiz sezgi;
                                                     # GUI aktarim ekrani bunu SUNMAZ, yalnizca
                                                     # programatik/geriye-donuk kullanim icindir)

    max_record_bytes/max_depth verilirse, bu sınırlar HER KAYIT için akış
    sırasında (inşa edilirken) uygulanır -- bkz. _consume_value.
    """

    def __init__(self, budgeted_reader, selector: dict, max_record_bytes: int = None, max_depth: int = None):
        self.reader = budgeted_reader
        self.selector = selector
        self.max_record_bytes = max_record_bytes
        self.max_depth = max_depth
        self.stop_reason = None
        self.error_type_name = None  # yalnızca istisna SINIF adı; asla mesaj metni
        self.element_kind_counts: dict = {}
        self.completed_count = 0
        self.matched_key_ordinal = None

    def _matches(self, ordinal: int, keyname: str) -> bool:
        mode = self.selector.get("mode")
        if mode == "index":
            return ordinal == self.selector["value"]
        if mode == "name":
            return keyname == self.selector["value"]
        if mode == "first_array":
            return True
        raise SelectorError(f"Bilinmeyen seçici modu: {mode!r}")

    def _classify_stop(self, default: str) -> str:
        """budget_hit/real_eof, gercek nedeni HER ZAMAN budama/dosya-sonu
        lehine gecersiz kilar; hicbiri set degilse `default` kullanilir
        (cagiran taraf, bu 'temiz' cagrinin StopIteration/end_array/
        IncompleteJSONError'dan hangisinden geldigini bilir)."""
        if self.reader.budget_hit:
            return STOP_BYTE_BUDGET
        if self.reader.real_eof:
            return STOP_SOURCE_REAL_EOF
        return default

    def iter_records(self, max_records: int, drain_to_eof: bool = False):
        """Seçilen dizinin elemanlarını teker teker üretir. En fazla
        max_records tam eleman üretildikten sonra durur. Bitiş nedeni
        `self.stop_reason` alanında raporlanır (yarım kalan son eleman
        hiçbir zaman üretilmez).

        drain_to_eof=True ise: hedef dizi kapandıktan SONRA, hiçbir eleman
        daha üretmeden, kalan belgeyi (kökün diğer alanları, kapanış
        parantezleri) gerçek dosya sonuna kadar sözdizimsel olarak
        DOĞRULAMAYA devam eder. Yalnızca bu doğrulama da başarıyla biterse
        `self.stop_reason = STOP_FULLY_DRAINED` olur -- dizinin kapanması
        TEK BAŞINA bunu tetiklemez.
        """
        parser = ijson.parse(self.reader, use_float=False)
        events = iter(parser)

        depth = 0
        root_key_count = 0
        phase = "seeking_root_map"
        array_depth_marker = None

        try:
            while True:
                try:
                    prefix, event, value = next(events)
                except StopIteration:
                    if phase == "draining":
                        # Burada real_eof=True olması KESİNTİ değil, TAM
                        # OLARAK istenen sonuçtur (belge sonuna kadar
                        # doğrulandı) -- bu yüzden _classify_stop'un genel
                        # "real_eof her zaman kesinti" önceliği burada
                        # KASITLI olarak uygulanmaz; yalnızca bütçe
                        # (budget_hit) hâlâ gerçek bir kesinti sayılır.
                        self.stop_reason = STOP_BYTE_BUDGET if self.reader.budget_hit else STOP_FULLY_DRAINED
                    else:
                        self.stop_reason = self._classify_stop(default=STOP_SOURCE_REAL_EOF)
                    return

                if phase == "seeking_root_map":
                    if depth == 0:
                        if self.selector.get("mode") == "root_array":
                            if event != "start_array":
                                raise SelectorError(
                                    f"Kök değer bir dizi (array) değil (ilk olay: {event})"
                                )
                            phase = "streaming"
                            array_depth_marker = 0
                            depth = 1
                            continue
                        if event != "start_map":
                            raise SelectorError(
                                f"Kök değer bir nesne (object) değil (ilk olay: {event})"
                            )
                        depth = 1
                        continue
                    if depth == 1 and event == "map_key":
                        root_key_count += 1
                        if self._matches(root_key_count, value):
                            self.matched_key_ordinal = root_key_count
                            phase = "matched_awaiting_value"
                        continue
                    if event in ("start_map", "start_array"):
                        depth += 1
                        continue
                    if event in ("end_map", "end_array"):
                        depth -= 1
                        continue
                    continue

                if phase == "matched_awaiting_value":
                    if event == "start_array":
                        phase = "streaming"
                        array_depth_marker = depth
                        depth += 1
                        continue
                    if self.selector.get("mode") == "first_array":
                        phase = "seeking_root_map"
                        if event in ("start_map", "start_array"):
                            depth += 1
                        continue
                    raise SelectorError(
                        f"Seçilen kök alan (sıra {self.matched_key_ordinal}) bir dizi değil "
                        f"(görülen olay: {event})"
                    )

                if phase == "streaming":
                    if event == "end_array" and depth == array_depth_marker + 1:
                        if drain_to_eof:
                            phase = "draining"
                            depth -= 1
                            continue
                        self.stop_reason = self._classify_stop(default=STOP_ARRAY_COMPLETE)
                        return
                    if self.completed_count >= max_records:
                        self.stop_reason = STOP_RECORD_LIMIT
                        return
                    size_tracker = [0] if self.max_record_bytes is not None else None
                    element = _consume_value(
                        events, (prefix, event, value), depth=0,
                        max_depth=self.max_depth, size_tracker=size_tracker,
                        max_bytes=self.max_record_bytes,
                    )
                    kind = _classify(element)
                    self.element_kind_counts[kind] = self.element_kind_counts.get(kind, 0) + 1
                    self.completed_count += 1
                    yield element
                    if self.completed_count >= max_records:
                        self.stop_reason = STOP_RECORD_LIMIT
                        return
                    continue

                if phase == "draining":
                    # Kalan belgeyi -- deger insa etmeden -- yalnizca
                    # sozdizimsel olarak dogrulamak icin tuketiyoruz.
                    if event in ("start_map", "start_array"):
                        depth += 1
                        continue
                    if event in ("end_map", "end_array"):
                        depth -= 1
                        continue
                    continue
        except ijson.common.IncompleteJSONError as e:
            self.error_type_name = type(e).__name__
            self.stop_reason = self._classify_stop(default=STOP_PARSE_ERROR)
            return
        except RecordTooLargeError as e:
            self.error_type_name = type(e).__name__
            self.stop_reason = STOP_RECORD_TOO_LARGE
            return
        except RecordTooDeepError as e:
            self.error_type_name = type(e).__name__
            self.stop_reason = STOP_RECORD_TOO_DEEP
            return
        except OSError as e:
            self.error_type_name = type(e).__name__
            self.stop_reason = STOP_SOURCE_IO_ERROR
            return
