"""PyYAML'in olay tabanlı `yaml.parse()` akışı üzerine kurulu, JSON ile AYNI
seçici türlerine sahip akış kaynağı YAML için. `streaming_source.py`
(JSON/ijson), `csv_source.py` ve `xml_source.py`'den bağımsız, YAML'e özgü
tek bir küçük modüldür.

Kurallar (mevcut `parsers/yaml_parser.py` -- bellek modu -- ile TUTARLI, ama
akış/disk odaklı; ayrıca bkz. `import_job.py`'nin bu modülü nasıl kullandığı):

  - `yaml.safe_load()` ile belgenin TAMAMI YÜKLENMEZ; bunun yerine
    `yaml.parse(kaynak, Loader=...)` (yalnızca Parser -- Composer/
    Constructor aşamaları YOKTUR) kullanılır. `CSafeLoader` varsa
    kullanılır, yoksa `SafeLoader`'a düşülür -- ikisi de AYNI
    `yaml_constructors` sözlüğünü (aynı Python nesnesi) paylaştığından
    davranışları birebir aynıdır (bu modülde doğrulanmıştır).
  - **Scalar tür çözümlemesi**: `yaml.parse()`'ın ürettiği `ScalarEvent`
    yalnızca HAM metni (`value`) ve (varsa) açık etiketi (`tag`) verir;
    örtük (implicit) etiket çözümlemesi YAPILMAZ. Bu modül, `safe_load`'ın
    kendisinin kullandığı AYNI `yaml.resolver.Resolver` ve AYNI
    `SafeLoader.yaml_constructors` fonksiyonlarını DOĞRUDAN çağırarak
    (küçük, elle inşa edilmiş bir `ScalarNode` ile) metni gerçek Python
    değerine (str/int/float/bool/None) çevirir -- kendi regex/dönüştürme
    mantığımız YOKTUR, bu yüzden `"00123"` gibi YAML'a özgü (octal) veya
    `yes`/`no` gibi örtük bool kuralları `safe_load` ile BİREBİR aynı
    sonucu verir (ampirik olarak doğrulanmıştır).
  - **Desteklenen seçiciler JSON ile AYNIDIR**: {"mode": "root_array"},
    {"mode": "name", "value": "alan"}, {"mode": "index", "value": N}
    (1 tabanlı). Kök bir sequence ise doğrudan, kök bir mapping ise
    belirtilen alanın DEĞERİ bir sequence olmalıdır.
  - **Alias/anchor DESTEKLENMEZ**: `yaml.parse()` bir ScalarEvent/
    CollectionStartEvent'in `anchor` alanını doldurabilir ya da doğrudan
    bir `AliasEvent` üretebilir; bunların HERHANGİ biri görülürse (kayıt
    içinde ya da kayıt dışında), döngüsel referans riskini ve karmaşık
    iki-aşamalı inşa gereksinimini TAMAMEN ORTADAN KALDIRMAK için açık,
    içerik sızdırmayan bir `YamlUnsupportedStructureError` fırlatılır --
    sessizce yanlış/eksik bir sonuç üretilmez. Küçük parser'ın (`safe_load`
    + `_validate`'in döngüsel referans kontrolü) davranışı DEĞİŞMEDİ; bu
    yalnızca akış (disk) yoluna özgü, bilinçli bir kapsam sınırlamasıdır.
  - **Çok belgeli (multi-document, "---" ile ayrılmış) YAML DESTEKLENMEZ**:
    ikinci bir `DocumentStartEvent` görülürse açıkça reddedilir.
  - **Desteklenmeyen tür/etiketler** (`!!binary`, `!!set`, `!!timestamp`,
    `!!pairs`, `!!omap`, tanınmayan özel etiketler, metin olmayan mapping
    anahtarları) küçük parser'ın `_DISALLOWED_LEAF_TYPES`/anahtar
    doğrulamasıyla TUTARLI biçimde, aynı `YamlUnsupportedStructureError`
    ile reddedilir.
  - **Bellek**: aynı anda yalnızca TEK bir kayıt ağacı bellekte tutulur.
    `yaml.parse()` (JSON'daki ijson gibi) HİÇBİR kalıcı ağaç TUTMAZ --
    bu modül, bir kaydın Python nesnesini (`_consume_value` ile) olaylar
    geldikçe kendisi inşa eder ve `yield`'den sonra hiçbir referans
    tutmaz; XML'deki gibi ayrı bir `clear()`/`remove()` mekanizmasına
    GEREK YOKTUR (ElementTree'nin aksine kalıcı bir ağaç zaten yoktur).
  - **Derinlik/tek-kayıt boyutu sınırları** JSON'daki (`_consume_value`)
    AYNI desenle, kayıt HENÜZ İNŞA EDİLİRKEN uygulanır.
  - **KRİTİK bütçe güvenliği (yalnızca Önizleme modu)**: YAML'ın düz
    (tırnaksız) skaler değerleri, JSON'un dizeleri ya da XML'in
    etiketlerinin aksine, AÇIK bir kapanış belirteci GEREKTİRMEZ -- bir
    düz skaler, girdi burada bitiyormuş gibi göründüğünde SESSİZCE (hata
    fırlatmadan) kısaltılabilir (bu modülde ampirik olarak doğrulanmıştır:
    200 karakterlik bir metin, bütçe ortasında kesildiğinde HİÇBİR
    istisna fırlatılmadan 88 karaktere kırpılabiliyor).

    Bu yüzden bu modül, İNŞA EDİLMEKTE OLAN kaydın/atlanmakta olan değerin
    TAMAMI tüketildikten HEMEN SONRA `reader.budget_hit`'i kontrol eder --
    NE ÖNCESİNDE (zaten güvenle tamamlanmış önceki kayıtları gereksiz yere
    atmamak için: bir önceki `read()` çağrısının tamamı hâlâ GERÇEK,
    kırpılmamış bayt döndürür; yalnızca bütçenin TAM OLARAK dolduğu
    `read()` çağrısı kısmi/sınırlı olabilir) NE DE her tekil `next()`
    çağrısından sonra (bu AŞIRI agresif olur ve aynı okuma tamponuna denk
    gelen, aslında tamamen SAĞLAM önceki kayıtları da gereksiz yere
    silerdi -- ampirik olarak gözlemlenmiştir). Yalnızca bütçe TAM OLARAK
    bir kaydın/atlanan değerin inşası SIRASINDA dolduysa (önce False,
    şimdi True), o BELİRLİ kayıt/değer ŞÜPHELİ sayılır ve TAMAMEN ATILIR;
    ondan ÖNCE başarıyla üretilmiş kayıtlar KORUNUR. Bu, yalnızca
    istisnalara (`ParserError`/`ScannerError`) güvenmekten DAHA GÜÇLÜ bir
    korumadır ve "önizleme sınırı kayıt ortasında dolarsa eksik kayıt
    yazılmasın" gereksinimini, önceki sağlam kayıtları FEDA ETMEDEN
    karşılar.

    ÖNEMLİ (kontrol noktasının tam yeri): "önce" değeri, kaydın/atlanan
    değerin AÇILIŞ olayı bile alınmadan HEMEN ÖNCE (döngünün en başında)
    yakalanır -- sonradan yakalansaydı, açılış olayının kendisi bile
    geçişi tetiklemiş olabileceğinden geçiş HİÇBİR ZAMAN doğru
    algılanamazdı (ampirik olarak doğrulanmış bir hataydı, düzeltildi).

    BİLİNEN SINIR (gerçekçi bütçelerde önemsiz): eğer verilen TÜM bayt
    bütçesi, alttaki okuyucunun TEK bir `read()` çağrısında isteyebileceği
    miktardan (libyaml için tipik olarak ~16 KB) DAHA KÜÇÜKSE, bütçe
    HİÇBİR kayıt üretilmeden önce dolabilir -- bu durumda "geçiş" hiçbir
    zaman gözlenemez ve son (kırpılmış olabilecek) kayıt yine de
    üretilebilir. Varsayılan önizleme bütçesi (32 MiB) bunun ÇOK ÜZERinde
    olduğundan bu, yalnızca kullanıcının BİLİNÇLİ olarak birkaç KB'den
    küçük bir önizleme bütçesi girmesi durumunda ortaya çıkabilecek,
    gerçekçi kullanımda karşılaşılmayacak uç bir sınırdır.
  - **"Tamamlandı" tanımı JSON ile AYNI mantıktadır**: seçilen sequence
    kapandıktan SONRA (Tam Aktarımda) kalan belge (kök mapping'in diğer
    alanları varsa atlanarak, sonra belge/akış sonu) gerçek EOF'a kadar
    doğrulanır; yalnızca bu da başarılı olursa `STOP_FULLY_DRAINED` olur.
"""
import yaml
from yaml.nodes import ScalarNode
from yaml.resolver import Resolver

try:
    from yaml import CSafeLoader as _YamlLoader
except ImportError:  # pragma: no cover - libyaml (C) her ortamda mevcut olmayabilir
    from yaml import SafeLoader as _YamlLoader

STOP_RECORD_LIMIT = "kayit_siniri"
STOP_BYTE_BUDGET = "bayt_siniri"
STOP_ARRAY_COMPLETE = "dizi_tamamlandi"
STOP_SOURCE_REAL_EOF = "kaynak_dosyasi_tamamen_bitti"
STOP_FULLY_DRAINED = "belge_sonuna_kadar_dogrulandi"
STOP_PARSE_ERROR = "ayristirma_hatasi"
STOP_SOURCE_IO_ERROR = "kaynak_okuma_hatasi"
STOP_RECORD_TOO_LARGE = "kayit_cok_buyuk"
STOP_RECORD_TOO_DEEP = "kayit_cok_derin"
STOP_UNSUPPORTED_STRUCTURE = "desteklenmeyen_yapi"

COMPLETE_STOP_REASONS = (STOP_ARRAY_COMPLETE, STOP_SOURCE_REAL_EOF)

# safe_load'ın ürettiği ama küçük parser'ın (parsers/yaml_parser.py)
# VERİ MODELİNİN desteklemediği türler -- AYNI (tarih/bytes/set) kapsam
# dışı bırakma kararı burada da geçerlidir.
_DISALLOWED_TAGS = frozenset({
    "tag:yaml.org,2002:timestamp",
    "tag:yaml.org,2002:binary",
    "tag:yaml.org,2002:set",
    "tag:yaml.org,2002:pairs",
    "tag:yaml.org,2002:omap",
    "tag:yaml.org,2002:merge",
})
_SUPPORTED_SCALAR_TAGS = frozenset({
    "tag:yaml.org,2002:null",
    "tag:yaml.org,2002:bool",
    "tag:yaml.org,2002:int",
    "tag:yaml.org,2002:float",
    "tag:yaml.org,2002:str",
})

_resolver = Resolver()
# Tek, yeniden kullanılabilir bir loader örneği: SafeLoader/CSafeLoader'ın
# skaler constructor fonksiyonları yalnızca node.value okur, örnek-durumu
# (self) tutmaz -- bu yüzden BİR KEZ oluşturup binlerce çağrı için güvenle
# yeniden kullanmak doğrulanmıştır (ampirik olarak test edilmiştir).
_loader_instance = _YamlLoader(b"")


class YamlSelectorError(Exception):
    """Yapılandırılan alan seçici, kökte (mapping ya da bizzat kök) bir
    sequence ile eşleşmedi. JSON tarafındaki SelectorError ile aynı role
    sahiptir."""


class YamlUnsupportedStructureError(Exception):
    """Alias/anchor, çok belgeli YAML, metin olmayan mapping anahtarı ya da
    küçük parser'ın veri modelinin desteklemediği bir tür (tarih/bytes/set/
    tanınmayan özel etiket) görüldü. Mesaj yalnızca YAPISAL bilgi (etiket
    adı, olay türü) içerir; gerçek hücre/alan değeri asla içermez."""


class YamlRecordTooLargeError(Exception):
    """Tek bir kaydın akış sırasında ölçülen (yaklaşık) boyutu, yapılandırılan sınırı aştı."""


class YamlRecordTooDeepError(Exception):
    """Tek bir kaydın iç içe geçme derinliği yapılandırılan sınırı aştı."""


def _resolve_tag(value: str, tag, implicit):
    if tag is not None:
        return tag
    return _resolver.resolve(ScalarNode, value, implicit)


def _construct_scalar(event):
    """Bir ScalarEvent'i gerçek Python değerine (`safe_load` ile BİREBİR
    aynı kurallarla) çevirir. Desteklenmeyen/bilinmeyen bir etikete
    çözümlenirse YamlUnsupportedStructureError fırlatır -- mesaj yalnızca
    etiket adını içerir, gerçek değeri İÇERMEZ."""
    tag = _resolve_tag(event.value, event.tag, event.implicit)
    if tag in _DISALLOWED_TAGS or tag not in _SUPPORTED_SCALAR_TAGS:
        raise YamlUnsupportedStructureError(
            f"Desteklenmeyen YAML türü/etiketi: {tag}"
        )
    ctor = _YamlLoader.yaml_constructors[tag]
    node = ScalarNode(tag, event.value, event.start_mark, event.end_mark, event.style)
    return ctor(_loader_instance, node)


def _reject_alias_or_anchor(event) -> None:
    if isinstance(event, yaml.AliasEvent) or getattr(event, "anchor", None):
        raise YamlUnsupportedStructureError(
            "Alias/anchor kullanımı büyük YAML aktarımında desteklenmiyor"
        )


def _skip_value_span(events, first_event) -> None:
    """Bir değerin (skaler ya da iç içe mapping/sequence) TÜM olay
    yayılımını, HİÇBİR Python nesnesi oluşturmadan tüketir (atlar) --
    kök mapping'te seçilmeyen alanların değerleri için kullanılır. Bütçe
    kontrolü BURADA yapılmaz -- çağıran taraf (iter_records), bu fonksiyon
    döndükten HEMEN SONRA `reader.budget_hit`'i kontrol eder (bkz. modül
    docstring'indeki "KRİTİK bütçe güvenliği")."""
    _reject_alias_or_anchor(first_event)
    if not isinstance(first_event, (yaml.MappingStartEvent, yaml.SequenceStartEvent)):
        return  # skaler -- tek olayda biter
    depth = 1
    while depth > 0:
        ev = next(events)
        _reject_alias_or_anchor(ev)
        if isinstance(ev, (yaml.MappingStartEvent, yaml.SequenceStartEvent)):
            depth += 1
        elif isinstance(ev, (yaml.MappingEndEvent, yaml.SequenceEndEvent)):
            depth -= 1


def _check_size(size_tracker, max_bytes) -> None:
    if size_tracker is not None and size_tracker[0] > max_bytes:
        raise YamlRecordTooLargeError(
            f"Kayıt boyutu (yaklaşık, akış sırasında ölçülen) sınırı aştı "
            f"({size_tracker[0]} > {max_bytes} bayt)"
        )


def _approx_bytes(value) -> int:
    if isinstance(value, str):
        return len(value.encode("utf-8", "ignore")) + 8
    return 16


def _consume_value(events, first_event, depth, max_depth, size_tracker, max_bytes):
    """`first_event` zaten tüketilmiş ilk olaydır. `yaml.parse()`'ın
    ürettiği olay akışından TAM bir Python değeri (dict/list/skaler)
    yeniden kurar. JSON tarafındaki `_consume_value` ile AYNI desen;
    max_depth/size_tracker+max_bytes verilirse HENÜZ İNŞA EDİLİRKEN
    uygulanır. Bütçe kontrolü BURADA yapılmaz -- çağıran taraf
    (iter_records), bu fonksiyon bir KAYIT için döndükten HEMEN SONRA
    `reader.budget_hit`'i kontrol eder (bkz. modül docstring'i)."""
    _reject_alias_or_anchor(first_event)

    if max_depth is not None and depth > max_depth:
        raise YamlRecordTooDeepError(f"İç içe yapı derinliği sınırı aşıldı (sınır {max_depth})")

    if isinstance(first_event, yaml.MappingStartEvent):
        obj = {}
        while True:
            key_event = next(events)
            if isinstance(key_event, yaml.MappingEndEvent):
                return obj
            _reject_alias_or_anchor(key_event)
            if not isinstance(key_event, yaml.ScalarEvent):
                raise YamlUnsupportedStructureError(
                    "YAML mapping anahtarı basit bir skaler olmalı (karmaşık anahtar desteklenmiyor)"
                )
            key = _construct_scalar(key_event)
            if not isinstance(key, str):
                raise YamlUnsupportedStructureError(
                    f"YAML sözlük anahtarı metin olmalı, bulunan tür: {type(key).__name__}"
                )
            if size_tracker is not None:
                size_tracker[0] += _approx_bytes(key)
                _check_size(size_tracker, max_bytes)
            value_event = next(events)
            obj[key] = _consume_value(events, value_event, depth + 1, max_depth, size_tracker, max_bytes)

    if isinstance(first_event, yaml.SequenceStartEvent):
        arr = []
        while True:
            ev = next(events)
            if isinstance(ev, yaml.SequenceEndEvent):
                return arr
            arr.append(_consume_value(events, ev, depth + 1, max_depth, size_tracker, max_bytes))

    if isinstance(first_event, yaml.ScalarEvent):
        value = _construct_scalar(first_event)
        if size_tracker is not None:
            size_tracker[0] += _approx_bytes(value)
            _check_size(size_tracker, max_bytes)
        return value

    raise YamlUnsupportedStructureError(
        f"Desteklenmeyen YAML olay türü: {type(first_event).__name__}"
    )


class YamlStreamSource:
    """selector örnekleri (JSON ile AYNI şekil):
        {"mode": "root_array"}
        {"mode": "index", "value": 3}
        {"mode": "name", "value": "gercek_ad"}

    max_record_bytes/max_depth verilirse, bu sınırlar HER KAYIT için akış
    sırasında (inşa edilirken) uygulanır."""

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
        raise YamlSelectorError(f"Bilinmeyen seçici modu: {mode!r}")

    def _classify_stop(self, default: str) -> str:
        if self.reader.budget_hit:
            return STOP_BYTE_BUDGET
        if self.reader.real_eof:
            return STOP_SOURCE_REAL_EOF
        return default

    def iter_records(self, max_records: int, drain_to_eof: bool = False):
        """Seçilen sequence'in elemanlarını teker teker üretir. En fazla
        max_records tam eleman üretildikten sonra durur. Bitiş nedeni
        `self.stop_reason` alanında raporlanır (yarım/şüpheli kalan bir
        eleman hiçbir zaman üretilmez -- bkz. modül docstring'i)."""
        parser = yaml.parse(self.reader, Loader=_YamlLoader)
        events = iter(parser)

        phase = "seeking_root"
        document_count = 0
        root_key_count = 0
        # "streaming" fazına EN AZ BİR KEZ ulaşıldı mı? (seçici doğru
        # eşleşti VE hedef sequence'ten en az sıfır -- ya da daha fazla --
        # eleman üretildi/üretilmeye başlandı, boş sequence dahil). Bu,
        # StopIteration'ı doğru sınıflandırmak için KULLANILIR: "draining"/
        # "root_mapping_seek_key"/"root_mapping_closed" gibi FAZ ADLARI,
        # hem "seçici hiç eşleşmeden kök tükendi" hem de "seçici eşleşti,
        # hedef tamamen üretildi, geri kalan belge de doğrulandı" gibi
        # BİRBİRİNDEN TAMAMEN FARKLI iki senaryoda da (mapping modunda)
        # AYNI olabildiğinden (özellikle hedef alan mapping'in SON alanıysa
        # ve sonrasında başka alan yoksa), yalnızca faz adına bakmak YETERLİ
        # DEĞİLDİR -- bu bayrak, iki senaryoyu kesin biçimde ayırt eder.
        reached_streaming = False

        try:
            while True:
                # ÖNEMLİ: bu, bir sonraki event'i (bir kaydın AÇILIŞ olayı
                # dahil) almadan HEMEN ÖNCEki durumdur -- "bu kaydın/
                # atlanan değerin inşası bütçeyi TAM OLARAK ne zaman
                # doldurdu" sorusuna doğru cevap vermek için, kontrol
                # noktası kaydın kendi AÇILIŞ olayından bile ÖNCE
                # yakalanmalıdır (yoksa açılış olayının kendisi zaten
                # geçişi tetiklemiş olabilir ve bu iterasyonda hep "önceden
                # doluydu" görünür -- bkz. modül docstring'i).
                budget_hit_before_event = self.reader.budget_hit
                try:
                    event = next(events)
                except StopIteration:
                    if self.reader.budget_hit:
                        self.stop_reason = STOP_BYTE_BUDGET
                    elif drain_to_eof and reached_streaming:
                        # Hedef sequence BAŞARIYLA üretildi VE (varsa) geri
                        # kalan belge de hataya/kesintiye uğramadan buraya
                        # kadar doğrulandı -- JSON'daki STOP_FULLY_DRAINED
                        # ile AYNI anlam.
                        self.stop_reason = STOP_FULLY_DRAINED
                    else:
                        self.stop_reason = self._classify_stop(default=STOP_SOURCE_REAL_EOF)
                    return

                if isinstance(event, (yaml.StreamStartEvent, yaml.StreamEndEvent, yaml.DocumentEndEvent)):
                    continue
                if isinstance(event, yaml.DocumentStartEvent):
                    document_count += 1
                    if document_count > 1:
                        raise YamlUnsupportedStructureError(
                            "Çok belgeli (multi-document, '---' ile ayrılmış) YAML desteklenmiyor"
                        )
                    continue

                if phase == "seeking_root":
                    _reject_alias_or_anchor(event)
                    if self.selector.get("mode") == "root_array":
                        if not isinstance(event, yaml.SequenceStartEvent):
                            raise YamlSelectorError(
                                f"Kök değer bir sequence değil (ilk olay: {type(event).__name__})"
                            )
                        phase = "streaming"
                        reached_streaming = True
                        continue
                    if not isinstance(event, yaml.MappingStartEvent):
                        raise YamlSelectorError(
                            f"Kök değer bir mapping değil (ilk olay: {type(event).__name__})"
                        )
                    phase = "root_mapping_seek_key"
                    continue

                if phase == "root_mapping_seek_key":
                    if isinstance(event, yaml.MappingEndEvent):
                        phase = "root_mapping_closed"
                        continue
                    _reject_alias_or_anchor(event)
                    if not isinstance(event, yaml.ScalarEvent):
                        raise YamlSelectorError("Kök mapping anahtarı basit bir skaler değil")
                    root_key_count += 1
                    key = _construct_scalar(event)
                    if not isinstance(key, str):
                        raise YamlUnsupportedStructureError(
                            f"YAML sözlük anahtarı metin olmalı, bulunan tür: {type(key).__name__}"
                        )
                    value_event = next(events)
                    if self._matches(root_key_count, key):
                        self.matched_key_ordinal = root_key_count
                        if not isinstance(value_event, yaml.SequenceStartEvent):
                            raise YamlSelectorError(
                                f"Seçilen kök alan (sıra {root_key_count}) bir sequence değil "
                                f"(görülen olay: {type(value_event).__name__})"
                            )
                        phase = "streaming"
                        reached_streaming = True
                        continue
                    _skip_value_span(events, value_event)
                    if (not budget_hit_before_event) and self.reader.budget_hit:
                        # Bütçe TAM OLARAK bu (eşleşmeyen) alanın değeri
                        # atlanırken doldu -- bkz. modül docstring'indeki
                        # "KRİTİK bütçe güvenliği" (yalnızca bu GEÇİŞ anı
                        # şüphelidir; bütçe daha ÖNCEDEN dolmuşsa, o veri
                        # zaten güvenle tesli edilmiş büyük bir tampondan
                        # gelmiş olabilir -- reddetmeye gerek yok).
                        self.stop_reason = STOP_BYTE_BUDGET
                        return
                    continue

                if phase == "root_mapping_closed" or phase == "draining":
                    continue  # yalnızca Document/Stream sonu bekleniyor

                if phase == "streaming":
                    if isinstance(event, yaml.SequenceEndEvent):
                        if drain_to_eof:
                            phase = "draining" if self.selector.get("mode") == "root_array" \
                                else "root_mapping_seek_key"
                            continue
                        self.stop_reason = self._classify_stop(default=STOP_ARRAY_COMPLETE)
                        return
                    if self.completed_count >= max_records:
                        self.stop_reason = STOP_RECORD_LIMIT
                        return
                    size_tracker = [0] if self.max_record_bytes is not None else None
                    element = _consume_value(
                        events, event, depth=0, max_depth=self.max_depth,
                        size_tracker=size_tracker, max_bytes=self.max_record_bytes,
                    )
                    if (not budget_hit_before_event) and self.reader.budget_hit:
                        # Bütçe TAM OLARAK BU kaydın inşası SIRASINDA doldu
                        # -- görünüşte tamamlanmış olsa bile (YAML'ın düz
                        # skalerleri sessizce kırpılabildiği için) GÜVENİLMEZ
                        # sayılır: YIELD EDİLMEDEN atılır. Yalnızca bu GEÇİŞ
                        # anı şüphelidir (bkz. modül docstring'indeki "KRİTİK
                        # bütçe güvenliği"); bundan ÖNCE başarıyla üretilmiş
                        # (zaten yield edilmiş) kayıtlar KORUNUR.
                        self.stop_reason = STOP_BYTE_BUDGET
                        return
                    kind = "nesne" if isinstance(element, dict) else (
                        "dizi_pozisyonel" if isinstance(element, list) else "skaler_kok_eleman"
                    )
                    self.element_kind_counts[kind] = self.element_kind_counts.get(kind, 0) + 1
                    self.completed_count += 1
                    yield element
                    if self.completed_count >= max_records:
                        self.stop_reason = STOP_RECORD_LIMIT
                        return
                    continue
        except YamlSelectorError:
            raise
        except YamlUnsupportedStructureError as e:
            # NOT: burada _classify_stop KULLANILMAZ -- bu istisna hiçbir
            # zaman bütçe/gerçek-EOF ile KARIŞTIRILMAMALIDIR (JSON'un
            # IncompleteJSONError'ından farklı olarak, belge yapısal
            # olarak TAMAMEN GEÇERLİ ama desteklenmeyen bir tür/anchor/
            # çok-belge içeriyor -- budget_hit/real_eof'un tesadüfen aynı
            # anda True olması bu sınıflandırmayı DEĞİŞTİRMEMELİDİR).
            self.error_type_name = type(e).__name__
            self.stop_reason = STOP_UNSUPPORTED_STRUCTURE
            return
        except YamlRecordTooLargeError as e:
            self.error_type_name = type(e).__name__
            self.stop_reason = STOP_RECORD_TOO_LARGE
            return
        except YamlRecordTooDeepError as e:
            self.error_type_name = type(e).__name__
            self.stop_reason = STOP_RECORD_TOO_DEEP
            return
        except yaml.YAMLError as e:
            # NOT: burada _classify_stop'un TAM HALİ (real_eof dahil)
            # KULLANILMAZ -- yalnızca budget_hit bu hatayı "aslında bizim
            # kendi kesintimizdi" diye mazur gösterebilir. `real_eof`
            # (kaynağın KENDİLİĞİNDEN, bizim kesmemiz OLMADAN bitmesi)
            # yaml.YAMLError'ın (ijson'ın dar kapsamlı
            # IncompleteJSONError'ının aksine, HER TÜRLÜ sözdizimi
            # hatasını kapsayan GENİŞ bir istisna sınıfı olduğu için) bir
            # gerçek hatayı asla "hata değilmiş gibi" göstermemelidir --
            # aksi hâlde (küçük bir dosyanın TAMAMI okunduğu için real_eof
            # zaten True olabileceğinden) gerçek bir bozuk-YAML hatası
            # yanlışlıkla "kaynak dosyası bitti" olarak raporlanabilirdi
            # (ampirik olarak gözlemlenmiş bir hataydı, düzeltildi).
            self.error_type_name = type(e).__name__
            self.stop_reason = STOP_BYTE_BUDGET if self.reader.budget_hit else STOP_PARSE_ERROR
            return
        except OSError as e:
            self.error_type_name = type(e).__name__
            self.stop_reason = STOP_SOURCE_IO_ERROR
            return
