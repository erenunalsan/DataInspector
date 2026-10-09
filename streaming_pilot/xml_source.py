"""ElementTree.iterparse tabanlı, yapılandırılabilir "yol" (path) seçicili
akış kaynağı XML için. `csv_source.py`/`streaming_source.py`'den bağımsız,
XML'e özgü tek bir küçük modüldür.

Kurallar (mevcut `parsers/xml_parser.py` -- bellek modu -- ile TUTARLI, ama
akış/disk odaklı; ayrıca bkz. `import_job.py`'nin bu modülü nasıl kullandığı):

  - `xml.etree.ElementTree.iterparse` kullanılır; belgenin tamamını
    belleğe alan `parse()`/`fromstring()` YOKTUR. Kaynak dosya, çağıran
    tarafından (ImportJob) `rb` modunda açılmış, bayt-bütçeli bir okuyucu
    (`BudgetedBinaryReader`, JSON tarafındakiyle AYNI sınıf) olarak
    verilir -- bu modül dosyayı KENDİSİ açmaz/kapatmaz.
  - **Kayıt seçici**: kullanıcı tarafından verilen, kök elemanın altında
    (1 tabanlı derinlikte) tekrar eden kayıt elementini belirten BASİT bir
    yol: `{"mode": "path", "value": ["item"]}` (kökün doğrudan çocuğu,
    "sadece etiket" hâli) ya da `{"mode": "path", "value": ["container",
    "item"]}` (iç içe -- kökün "container" adlı çocuğunun "item" adlı
    çocukları). Sabit kodlanmış hiçbir gerçek etiket adı YOKTUR; wildcard,
    attribute koşulu ya da XPath desteklenmez (kasıtlı olarak "basit
    kökten-path" kapsamıyla sınırlıdır). Birden fazla üst eleman (ör.
    birden fazla "container") aynı yolu paylaşıyorsa HEPSİNİN altındaki
    eşleşen kayıtlar toplanır -- "TEK bir container'ı bul" varsayımı
    YOKTUR; her aday eleman, üst zincirinin (ata etiketlerinin) yol
    parçalarıyla eşleşip eşleşmediğine bakılarak bağımsız değerlendirilir.
  - **Namespace eşleştirme kuralı (AÇIK ve BELGELİ)**: ElementTree,
    namespace'li etiketleri "Clark notation" (`{namespace-uri}yerel-ad`)
    ile temsil eder. Bir yol parçası (segment):
      * `{` ile BAŞLIYORSA: TAM Clark notation eşleşmesi aranır (ör.
        kullanıcı `{http://ornek.com/ns}item` yazarsa, YALNIZCA tam o
        namespace'teki "item" eşleşir).
      * `{` ile başlamıyorsa (düz bir ad, ör. "item"): elementin YEREL
        adı (namespace URI'si yoksayılarak) karşılaştırılır -- bu,
        kullanıcının namespace URI'sini bilmesini/yazmasını GEREKTİRMEDEN
        (ör. `<ns:item>` ya da `<item>` fark etmeksizin) basit bir ad
        girebilmesini sağlar. İki farklı namespace'te aynı yerel ada
        sahip elementleri AYIRT ETMEK gerekiyorsa kullanıcı Clark
        notation'ı açıkça girmelidir.
  - **Veri dönüşümü**: tamamlanan her kayıt elementi, mevcut küçük XML
    parser'ın (`parsers/xml_parser.py`) `_element_to_value` fonksiyonu
    DOĞRUDAN YENİDEN KULLANILARAK dönüştürülür -- attribute'lar `@ad`,
    alt elemanlar düz adla, tekrarlanan alt elemanlar liste, karma içerik
    (metin + attribute/alt eleman birlikte) reddedilir -- KÜÇÜK PARSER İLE
    BİREBİR AYNI kurallar, kod tekrarı YOKTUR. Kaydın kendisi hiçbir alan
    (attribute/alt eleman) içermiyorsa (bare metin/boş element), küçük
    parser'daki gibi reddedilir (ParseError -> STOP_PARSE_ERROR).
  - **Bellek yönetimi**: tamamlanan HER element (kayıt olsun ya da
    olmasın -- ör. eşleşmeyen kardeş elementler, üst (ata) elementler)
    kendi "end" olayında hem `clear()` edilir HEM DE üst elementinden
    (`parent.remove(...)`) kaldırılır; böylece kök ya da ata elementler
    milyonlarca (artık boş) alt element referansı biriktirmez. Bir kaydın
    KENDİ İÇİNDEKİ alt elemanları, kayıt henüz kapanmadan (yani
    `_element_to_value` onu tüketmeden) ASLA temizlenmez/kaldırılmaz --
    aksi hâlde kaydın verisi kaybolurdu.
  - **Derinlik/boyut sınırları AKIŞ SIRASINDA uygulanır**: ElementTree'nin
    kendi iç ağaç kurucusu bizim kontrolümüzde olmasa da, `iterparse`
    HER elementin kendi start/end olayını bize ayrıca verir; bu olaylar
    üzerinden KENDİ derinlik sayacımızı ve yaklaşık bayt sayacımızı
    tutarız -- bir kaydın derinliği/boyutu sınırı aşar aşmaz (kayıt
    TAMAMEN kapanmadan, `_element_to_value` hiç çağrılmadan) istisna
    fırlatılır; yarım kalan bir kayıt ASLA üretilmez.
  - Bayt bütçesi (yalnızca Önizleme modu) `BudgetedBinaryReader` ile
    JSON'daki AYNI mekanizmayla uygulanır. Bütçe bir kaydın ortasında
    dolarsa, expat (ElementTree'nin C ayrıştırıcısı) beklenmedik bir EOF
    görüp `ET.ParseError` fırlatır; bu durum -- JSON'daki `_classify_stop`
    ile TUTARLI biçimde -- `budget_hit` her zaman önceliklendirilerek
    gerçek bir ayrıştırma hatasından AYRILIR (bütçe/önizleme sınırı olarak
    sınıflandırılır, "bozuk XML" ile karıştırılmaz).
  - **"Tamamlandı" belirlemesi JSON'dakinden DAHA BASİTTİR**: XML
    belgesinin kendisi zaten TEK bir kök elemandır (JSON'daki gibi ayrı
    bir "hedef dizi kapandı, şimdi belgenin geri kalanını doğrula" aşaması
    yoktur) -- `iter_records`, kayıt sınırına/iptale/hataya/bütçeye
    çarpmadığı sürece belgenin TAMAMINI (kök kapanana, gerçek dosya sonuna
    kadar) doğal olarak tüketir. Bu yüzden ayrı bir `drain_to_eof`
    parametresi YOKTUR; `stop_reason == STOP_SOURCE_REAL_EOF` (bütçe/hata
    yok) tek başına "belge sonuna kadar geçerli biçimde tamamlandı"
    anlamına gelir.
"""
import xml.etree.ElementTree as ET

from parsers.common import ParseError
from parsers.xml_parser import _element_to_value

STOP_RECORD_LIMIT = "kayit_siniri"
STOP_BYTE_BUDGET = "bayt_siniri"
STOP_SOURCE_REAL_EOF = "kaynak_dosyasi_tamamen_bitti"
STOP_PARSE_ERROR = "ayristirma_hatasi"
STOP_SOURCE_IO_ERROR = "kaynak_okuma_hatasi"
STOP_RECORD_TOO_LARGE = "kayit_cok_buyuk"
STOP_RECORD_TOO_DEEP = "kayit_cok_derin"

# tamamlandi_mi=True sayilan tek durma nedeni (butce/hata yok, belge
# gercekten sonuna kadar gecerli bicimde okundu).
COMPLETE_STOP_REASONS = (STOP_SOURCE_REAL_EOF,)


class XmlRecordTooLargeError(Exception):
    """Tek bir kaydın akış sırasında ölçülen (yaklaşık) boyutu, yapılandırılan sınırı aştı."""


class XmlRecordTooDeepError(Exception):
    """Tek bir kaydın iç içe geçme derinliği yapılandırılan sınırı aştı."""


def _local_name(tag: str) -> str:
    """Clark notation '{uri}yerel' -> 'yerel'; namespace yoksa değişmez."""
    if tag.startswith("{"):
        return tag.split("}", 1)[1]
    return tag


def _tag_matches(tag: str, segment: str) -> bool:
    """Bkz. modül docstring'indeki "Namespace eşleştirme kuralı"."""
    if segment.startswith("{"):
        return tag == segment
    return _local_name(tag) == segment


def _chain_matches(stack: list, path_segments: list) -> bool:
    """stack[0] köktür; stack[1..len(path_segments)] elemanlarının
    etiketlerinin, sırasıyla path_segments ile eşleşip eşleşmediğini
    kontrol eder. Yalnızca len(stack) - 1 == len(path_segments) iken
    (yani tam hedef derinlikteyken) çağrılmalıdır."""
    for i, segment in enumerate(path_segments):
        if not _tag_matches(stack[i + 1].tag, segment):
            return False
    return True


def _approx_open_bytes(elem) -> int:
    """Bir elementin AÇILIŞ anındaki (start olayı) yaklaşık bayt katkısı:
    etiket adı + attribute anahtar/değerleri. Tam serileştirme YAPMAZ;
    ucuz, yaklaşık bir üst sınır tahminidir (JSON tarafındaki
    _approx_scalar_bytes ile aynı ruhta)."""
    n = len(elem.tag.encode("utf-8", "ignore")) + 8
    for k, v in elem.attrib.items():
        n += len(k.encode("utf-8", "ignore")) + len(str(v).encode("utf-8", "ignore")) + 8
    return n


def _approx_close_bytes(elem) -> int:
    """Bir elementin KAPANIŞ anındaki (end olayı) yaklaşık ek bayt katkısı:
    doğrudan metni (varsa)."""
    text = elem.text or ""
    return len(text.encode("utf-8", "ignore")) + 8


class XmlStreamSource:
    """selector örneği: {"mode": "path", "value": ["item"]} ya da
    {"mode": "path", "value": ["container", "item"]}.

    max_record_bytes/max_depth verilirse, bu sınırlar HER KAYIT için akış
    sırasında (inşa edilirken) uygulanır -- bkz. modül docstring'i."""

    def __init__(self, budgeted_reader, selector: dict,
                 max_record_bytes: int = None, max_depth: int = None):
        self.reader = budgeted_reader
        self.selector = selector
        self.max_record_bytes = max_record_bytes
        self.max_depth = max_depth
        self.stop_reason = None
        self.error_type_name = None  # yalnızca istisna SINIF adı; asla mesaj metni
        self.element_kind_counts: dict = {}
        self.completed_count = 0
        self.first_segment_matched = False  # yolun İLK parçası en az bir kez görüldü mü?

    def iter_records(self, max_records: int):
        """Seçilen yola uyan kayıt elementlerini teker teker (dict olarak)
        üretir. En fazla max_records tam kayıt üretildikten sonra durur.
        Bitiş nedeni `self.stop_reason` alanında raporlanır (yarım kalan
        bir kayıt hiçbir zaman üretilmez)."""
        if self.selector.get("mode") != "path":
            raise ValueError(f"Bilinmeyen XML seçici modu: {self.selector.get('mode')!r}")
        path_segments = self.selector["value"]
        target_depth = len(path_segments)

        root = None
        stack = []  # stack[0] = kok; sonrasi acik alt elemanlar
        recording = False
        record_start_depth = None
        size_tracker = 0

        try:
            for event, elem in ET.iterparse(self.reader, events=("start", "end")):
                if event == "start":
                    if root is None:
                        root = elem
                        stack = [root]
                        continue
                    stack.append(elem)
                    cur_depth = len(stack) - 1
                    if cur_depth == 1 and _tag_matches(elem.tag, path_segments[0]):
                        self.first_segment_matched = True
                    if not recording and cur_depth == target_depth and _chain_matches(stack, path_segments):
                        recording = True
                        record_start_depth = cur_depth
                        size_tracker = 0
                    if recording:
                        rel_depth = cur_depth - record_start_depth
                        if self.max_depth is not None and rel_depth > self.max_depth:
                            raise XmlRecordTooDeepError(
                                f"İç içe yapı derinliği sınırı aşıldı (sınır {self.max_depth})"
                            )
                        size_tracker += _approx_open_bytes(elem)
                        if self.max_record_bytes is not None and size_tracker > self.max_record_bytes:
                            raise XmlRecordTooLargeError(
                                f"Kayıt boyutu (yaklaşık, akış sırasında ölçülen) sınırı aştı "
                                f"({size_tracker} > {self.max_record_bytes} bayt)"
                            )
                    continue

                # event == "end"
                if elem is root:
                    continue
                cur_depth = len(stack) - 1

                if recording:
                    size_tracker += _approx_close_bytes(elem)
                    if self.max_record_bytes is not None and size_tracker > self.max_record_bytes:
                        raise XmlRecordTooLargeError(
                            f"Kayıt boyutu (yaklaşık, akış sırasında ölçülen) sınırı aştı "
                            f"({size_tracker} > {self.max_record_bytes} bayt)"
                        )

                if recording and cur_depth == target_depth and elem is stack[-1]:
                    # Bu KAYIT elementinin kendisi kapaniyor.
                    parent = stack[-2]
                    value = _element_to_value(elem)
                    if not isinstance(value, dict):
                        # Kucuk parser'daki (parsers/xml_parser.py) AYNI kural:
                        # hicbir alan (attribute/alt eleman) icermeyen bir
                        # kayit reddedilir.
                        raise ParseError(
                            f"Desteklenmeyen XML kaydı: <{elem.tag}> hiçbir alan "
                            "(attribute/alt eleman) içermiyor"
                        )
                    parent.remove(elem)
                    elem.clear()
                    stack.pop()
                    recording = False

                    if self.completed_count >= max_records:
                        self.stop_reason = STOP_RECORD_LIMIT
                        return
                    self.element_kind_counts["nesne"] = self.element_kind_counts.get("nesne", 0) + 1
                    self.completed_count += 1
                    yield value
                    if self.completed_count >= max_records:
                        self.stop_reason = STOP_RECORD_LIMIT
                        return
                    continue

                if recording:
                    # Kayit HENUZ kapanmadi; kendi ic alt elemani kapaniyor
                    # -- kaydin verisini kaybetmemek icin TEMIZLENMEZ/
                    # KALDIRILMAZ (kayit kapaninca _element_to_value zaten
                    # tum alt agacini tuketip clear() ile serbest birakacak).
                    stack.pop()
                    continue

                # recording DEGILKEN kapanan bir eleman (eslesmeyen kardes
                # ya da bir ata/container) -- bellek birikmesin diye
                # HEMEN temizle ve kendi ustunden kaldir.
                parent = stack[-2]
                parent.remove(elem)
                elem.clear()
                stack.pop()
        except ET.ParseError as e:
            self.error_type_name = type(e).__name__
            self.stop_reason = STOP_BYTE_BUDGET if self.reader.budget_hit else STOP_PARSE_ERROR
            return
        except ParseError as e:
            self.error_type_name = type(e).__name__
            self.stop_reason = STOP_PARSE_ERROR
            return
        except XmlRecordTooLargeError as e:
            self.error_type_name = type(e).__name__
            self.stop_reason = STOP_RECORD_TOO_LARGE
            return
        except XmlRecordTooDeepError as e:
            self.error_type_name = type(e).__name__
            self.stop_reason = STOP_RECORD_TOO_DEEP
            return
        except OSError as e:
            self.error_type_name = type(e).__name__
            self.stop_reason = STOP_SOURCE_IO_ERROR
            return

        # Dongu StopIteration ile dogal bitti (butce ya da gercek EOF).
        self.stop_reason = STOP_BYTE_BUDGET if self.reader.budget_hit else STOP_SOURCE_REAL_EOF
