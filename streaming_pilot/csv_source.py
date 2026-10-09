"""CSV dosyalarını satır satır (dosyanın tamamını belleğe almadan) okuyan
akış kaynağı. Python'ın standart `csv.reader`'ı kullanılır; ijson tabanlı
streaming_source.py'den bağımsız, CSV'ye özgü tek bir küçük modüldür.

Kurallar (mevcut parsers/csv_parser.py -- bellek modu -- ile TUTARLI, ama
akış/disk odaklı; ayrıca bkz. import_job.py'nin bu modülü nasıl kullandığı):
  - Ayraç ",", tırnak karakteri '"', strict=True.
  - Kaynak dosya çağıran tarafından (ImportJob) newline="" ve
    encoding="utf-8-sig" ile TEXT modunda açılır (BOM'lu/BOM'suz UTF-8
    ikisi de desteklenir; utf-8-sig varsa BOM'u sessizce düşer, yoksa
    düz UTF-8 gibi davranır); bu modül dosyayı KENDİSİ açmaz/kapatmaz --
    dosya nesnesi (zaten açık) parametre olarak verilir, böylece kapanış
    her zaman çağıranın `with` bloğunda, deterministik biçimde olur.
  - Geçersiz UTF-8 baytları (`UnicodeDecodeError`) sessizce atlanmaz;
    stop_reason = STOP_PARSE_ERROR olarak raporlanır.
  - İlk boş olmayan fiziksel kayıt başlık kabul edilir; başlık sırası/metni
    AYNEN korunur (kırpma/yeniden adlandırma yok).
  - Boş/yalnızca boşluk ya da tekrarlanan başlıklar CsvHeaderError ile
    reddedilir (ImportJob'a kadar yükselir -- bkz. aşağı).
  - Tamamen boş fiziksel kayıtlar ATLANIR; ayraç/tırnakla belirtilmiş boş
    hücreli kayıtlar (",,," gibi) atlanmaz.
  - Başlıktan az/fazla alan içeren kayıt, fiziksel satır numarasıyla
    birlikte CsvRowError ile reddedilir (yalnızca sayım/satır no içerir,
    GERÇEK HÜCRE DEĞERİ asla mesaja yazılmaz).
  - Tüm hücreler METİN olarak kalır; hiçbir dönüştürme yapılmaz.
  - Tek bir hücrenin büyüklüğü `csv.field_size_limit` ile sınırlanır
    (yapılandırılabilir, bkz. DEFAULT_MAX_FIELD_BYTES).

Yaşam döngüsü / global durum yönetimi (ÖNEMLİ): `csv.field_size_limit` bir
GLOBAL modül ayarıdır (tek bir CsvStreamSource'a özel değildir). Bu sınıf
bunu YALNIZCA açık bir `close()` çağrısında (ya da `with CsvStreamSource(...)
as source:` bloğunun çıkışında) eski değerine döndürür -- bir generator'ın
kendi `finally` bloğuna, CPython'ın referans sayımına ya da çöp toplayıcının
(GC) NE ZAMAN çalıştığına ASLA güvenilmez. `iter_rows()` yarıda bırakılsa
(iptal edilse), tüketilmeden bırakılsa ya da dışarıda bir yerde REFERANSI
TUTULMAYA devam etse bile -- `close()` çağrıldığı anda durum HER ZAMAN geri
yüklenir. Bu yüzden bu sınıfı kullanan taraf (bkz. import_job.py._run_csv)
HER ZAMAN `with` ile (ya da eşdeğer bir try/finally ile) kullanmalıdır.

Bayt bütçesi (yalnızca Önizleme modu için; Tam Aktarımda anlamsız derecede
büyük bir bütçe kullanılır, tıpkı JSON tarafında olduğu gibi): CSV'de
"kayıt" doğal olarak bir ya da daha fazla FİZİKSEL satırdan oluşabilir
(tırnak içi çok satırlı hücreler). Bu yüzden bütçe rastgele bir bayt
sınırında değil, FİZİKSEL SATIR sınırında uygulanır -- bir satırın ortasında
asla kesilmez. Bir kaydın (birden fazla fiziksel satırdan oluşan) ortasında
bütçe dolarsa, csv modülü bunu "tırnak kapanmadı" hatası olarak görebilir;
bu durum -- ijson tarafındaki _classify_stop ile TUTARLI biçimde -- gerçek
bir ayrıştırma hatası değil, bütçe/EOF olarak sınıflandırılır (budget_hit
her zaman önceliklidir).
"""
import csv

STOP_RECORD_LIMIT = "kayit_siniri"
STOP_BYTE_BUDGET = "bayt_siniri"
STOP_SOURCE_REAL_EOF = "kaynak_dosyasi_tamamen_bitti"
STOP_PARSE_ERROR = "ayristirma_hatasi"
STOP_SOURCE_IO_ERROR = "kaynak_okuma_hatasi"
STOP_FIELD_TOO_LARGE = "hucre_cok_buyuk"

# tamamlandi_mi=True sayilan tek durma nedeni (butce/hata yok, gercekten
# dosya sonuna kadar okundu).
COMPLETE_STOP_REASONS = (STOP_SOURCE_REAL_EOF,)

# Tek bir CSV hücresinin akış sırasında ölçülen boyutu için güvenlik sınırı
# -- yapılandırılabilir (bkz. ImportJob(max_csv_field_bytes=...)),
# çok büyük tek bir hücrenin belleği tüketmesini önler. csv modülünün
# kendi field_size_limit() mekanizmasına eşlenir.
DEFAULT_MAX_FIELD_BYTES = 10 * 1024 * 1024  # 10 MB / hücre


class CsvHeaderError(Exception):
    """Başlık satırı geçersiz (boş/yalnızca boşluk ya da tekrarlanan başlık).
    JSON tarafındaki SelectorError ile aynı role sahiptir: kaynağın temel
    yapısı/yapılandırması geçersizdir, akışı ImportJob'a kadar yükselir ve
    kendi ayrı outcome kategorisini alır (bkz. import_job.py)."""


class CsvRowError(Exception):
    """Bir veri kaydının alan sayısı başlıkla uyuşmuyor. Mesaj yalnızca
    fiziksel satır numarası ve beklenen/bulunan alan SAYISINI içerir;
    gerçek hücre değerlerini asla içermez."""


def _read_header_row(reader):
    """İlk boş olmayan ([] olmayan) fiziksel kaydı başlık satırı olarak
    döner. Yalnızca tamamen boş fiziksel satırlardan oluşan ya da hiç
    satırı olmayan bir kaynak için None döner (boş dosya durumu)."""
    for row in reader:
        if row == []:
            continue
        return row
    return None


def _validate_headers(headers: list) -> None:
    seen = set()
    for header in headers:
        if not header.strip():
            raise CsvHeaderError(f"Boş veya yalnızca boşluk içeren kolon başlığı: {header!r}")
        if header in seen:
            raise CsvHeaderError(f"Tekrarlanan kolon başlığı: '{header}'")
        seen.add(header)


class _BudgetedLineSource:
    """Bir metin dosyasının FİZİKSEL SATIR satır okunmasını sarar (csv
    modülünün beklediği gibi -- tırnak içi çok satırlı hücrelerin satır
    sınırlarını KENDİSİ, bu sınıfa hiç danışmadan yönetir); okunan toplam
    baytı (UTF-8 kodlanmış yaklaşık uzunluk) bir bütçeyle sınırlar.
    BudgetedBinaryReader'ın (budgeted_reader.py) metin-modu eşdeğeridir;
    csv.reader bir dosya nesnesi yerine SATIR ÜRETEN bir yineleyici
    beklediği için ayrı, küçük bir sınıf olarak tutulur.

    Bu sınıf hiçbir kaynağın SAHİBİ değildir: verilen dosya nesnesini
    (fileobj) ne açar ne kapatır, hiçbir global durumu değiştirmez --
    yalnızca üzerinden geçen bayt sayısını sayan ince bir yineleyicidir.
    Bu yüzden ayrı bir close()/context-manager'a ihtiyacı YOKTUR; dosyanın
    ve global field_size_limit durumunun yaşam döngüsü CsvStreamSource'ta
    yönetilir (bkz. aşağı)."""

    def __init__(self, fileobj, budget_bytes: int):
        self._f = fileobj
        self.budget_bytes = budget_bytes
        self.bytes_read = 0
        self.budget_hit = False
        self.real_eof = False

    def __iter__(self):
        return self

    def __next__(self):
        if self.budget_hit:
            raise StopIteration
        try:
            line = next(self._f)
        except StopIteration:
            self.real_eof = True
            raise
        self.bytes_read += len(line.encode("utf-8", "surrogatepass"))
        if self.bytes_read >= self.budget_bytes:
            self.budget_hit = True
        return line


class CsvStreamSource:
    """selector kavramı YOKTUR (CSV'de her satır zaten bir kayıttır; kök
    dizi/alan adı/alan sırası seçimi JSON'a özgüdür). `fileobj`, ÇAĞIRAN
    tarafından zaten açılmış bir TEXT dosyasıdır (newline="",
    encoding="utf-8-sig") -- bu sınıf onu açmaz/kapatmaz; kapanış çağıranın
    `with` bloğunda deterministik olarak gerçekleşir (iptal/erken çıkışta
    bile FD sızıntısı olmaz).

    ÖNEMLİ -- global durum yaşam döngüsü: `csv.field_size_limit`, TEK bir
    örneğe değil tüm `csv` modülüne ait GLOBAL bir ayardır. Bu sınıf, eski
    değeri __init__'te (ilk anda) kaydeder ve YENİ sınırı HEMEN uygular;
    eski değeri geri yüklemek için ise `close()`'un AÇIKÇA çağrılmasını
    gerektirir -- bunu bir generator'ın `finally`'sine, referans sayımına
    ya da GC zamanlamasına bırakmaz. `with CsvStreamSource(...) as source:`
    biçiminde kullanılması (bkz. import_job.py._run_csv), başarı, kullanıcı
    iptali, başlık hatası, csv.Error/UnicodeDecodeError, yazma hatası ve
    beklenmeyen herhangi bir exception dahil TÜM çıkış yollarında `close()`
    çağrılmasını Python'ın `with` ifadesinin kendi garantisiyle sağlar."""

    def __init__(self, fileobj, max_bytes: int, max_field_bytes: int = DEFAULT_MAX_FIELD_BYTES):
        self.fileobj = fileobj
        self.max_bytes = max_bytes
        self.max_field_bytes = max_field_bytes
        self.headers = None
        self.stop_reason = None
        self.error_type_name = None
        self.row_error_detail = None
        self.completed_count = 0
        self.bytes_read = 0

        self._closed = False
        # Eski deger HEMEN (constructor'da) kaydedilir ve yeni sinir HEMEN
        # uygulanir -- close() cagrilana kadar (ya da hic cagrilmazsa)
        # bu nesne omru boyunca gecerlidir. Cagiran taraf close()'u
        # (ya da 'with'i) atlarsa bu deger GERI YUKLENMEZ -- bu KASITLIDIR;
        # sessiz/otomatik bir geri donus (ör. __del__ ile) yerine acik
        # cagriyi ZORUNLU kilmak, gercek hatalari gizlemek yerine ortaya
        # cikarir.
        self._old_field_size_limit = csv.field_size_limit()
        csv.field_size_limit(self.max_field_bytes)

    def close(self) -> None:
        """csv.field_size_limit GLOBAL durumunu eski değerine döndürür.
        Birden çok kez çağırmak güvenlidir (ikinci ve sonraki çağrılar
        no-op'tur). `iter_rows()` üretici (generator) nesnesi ne kadar
        tüketilmiş/tüketilmemiş ya da hâlâ referanslı olursa olsun, bu
        metod çağrıldığı anda durum HER ZAMAN geri yüklenir."""
        if self._closed:
            return
        csv.field_size_limit(self._old_field_size_limit)
        self._closed = True

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
        return False

    def iter_rows(self, max_records: int):
        """Başlık dışındaki her veri kaydını sıralı bir metin listesi
        (positional row) olarak üretir. self.headers, başlık satırı
        okunduktan hemen sonra atanır (ilk next() çağrısı sırasında).

        CsvHeaderError DIŞARI YÜKSELİR (kaynağın temel yapısı geçersiz --
        JSON'daki SelectorError ile aynı rol). Diğer tüm akış-içi sorunlar
        (geçersiz UTF-8, bozuk CSV, alan sayısı uyuşmazlığı, kaynak I/O
        hatası) burada YAKALANIR; self.stop_reason'a yazılır, üretim
        sessizce durur (JSON'daki IncompleteJSONError/RecordTooLarge
        yaklaşımıyla aynı).

        NOT: field_size_limit'in ayarlanması/geri yüklenmesi burada
        YAPILMAZ -- bu, nesnenin __init__/close() yaşam döngüsüne aittir
        (bkz. sınıf docstring'i); bu metod yalnızca satır üretimiyle
        ilgilenir."""
        budgeted = _BudgetedLineSource(self.fileobj, self.max_bytes)
        reader = csv.reader(budgeted, delimiter=",", quotechar='"', strict=True)

        try:
            header_row = _read_header_row(reader)
        except UnicodeDecodeError as e:
            self.error_type_name = type(e).__name__
            self.stop_reason = STOP_BYTE_BUDGET if budgeted.budget_hit else STOP_PARSE_ERROR
            return
        except csv.Error as e:
            self.error_type_name = type(e).__name__
            self.stop_reason = STOP_BYTE_BUDGET if budgeted.budget_hit else STOP_PARSE_ERROR
            return
        except OSError as e:
            self.error_type_name = type(e).__name__
            self.stop_reason = STOP_SOURCE_IO_ERROR
            return

        if header_row is None:
            # Fiziksel satırların TAMAMI ([] olanlar dahil) tuketildi,
            # hicbir baslik bulunamadi -- bos dosya (ya da yalnizca
            # bos fiziksel satirlardan olusan dosya).
            self.headers = []
            self.stop_reason = STOP_BYTE_BUDGET if budgeted.budget_hit else STOP_SOURCE_REAL_EOF
            return

        _validate_headers(header_row)  # CsvHeaderError -> disariya yukselir
        self.headers = header_row

        try:
            for row in reader:
                if row == []:
                    continue
                if self.completed_count >= max_records:
                    self.stop_reason = STOP_RECORD_LIMIT
                    return
                if len(row) != len(self.headers):
                    raise CsvRowError(
                        "CSV kaydındaki alan sayısı başlıkla uyuşmuyor "
                        f"(fiziksel satır {reader.line_num}): beklenen "
                        f"{len(self.headers)}, bulunan {len(row)}"
                    )
                self.completed_count += 1
                self.bytes_read = budgeted.bytes_read
                yield row
                if self.completed_count >= max_records:
                    self.stop_reason = STOP_RECORD_LIMIT
                    return
            self.stop_reason = STOP_BYTE_BUDGET if budgeted.budget_hit else STOP_SOURCE_REAL_EOF
        except UnicodeDecodeError as e:
            self.error_type_name = type(e).__name__
            self.stop_reason = STOP_BYTE_BUDGET if budgeted.budget_hit else STOP_PARSE_ERROR
        except csv.Error as e:
            self.error_type_name = type(e).__name__
            if "field larger than field limit" in str(e):
                self.stop_reason = STOP_FIELD_TOO_LARGE
            else:
                self.stop_reason = STOP_BYTE_BUDGET if budgeted.budget_hit else STOP_PARSE_ERROR
        except CsvRowError as e:
            self.error_type_name = type(e).__name__
            self.row_error_detail = str(e)
            self.stop_reason = STOP_PARSE_ERROR
        except OSError as e:
            self.error_type_name = type(e).__name__
            self.stop_reason = STOP_SOURCE_IO_ERROR
        finally:
            self.bytes_read = budgeted.bytes_read
