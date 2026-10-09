# DataInspector — Mimari Doküman

Bu doküman, DataInspector projesinin STEP 1 (Mimari) aşamasında alınan kararları kayıt altına alır; geliştirme ilerledikçe güncellenmiştir.

**MVP finalizasyon notu:** Bu belge, MVP'nin son (finalizasyon) turu itibarıyla gerçek koda göre güncellenmiştir. Belgedeki "STEP N'de ele alınacak/tanımlanacak" gibi ileriye dönük ifadeler artık geçerli değildir — bu MVP'den sonra planlanan yeni bir geliştirme aşaması yoktur; ilgili kararlar ya kesinleşmiş (aşağıda belirtildiği gibi) ya da bilinçli olarak kapsam dışı bırakılmış (bölüm 15) sayılmalıdır.

**Güncel durum (çalışan ilk sürüm):** Bu belgede anlatılan tüm bölümler uygulanmış ve test edilmiştir — `models.py`; dört parser (`json_parser.py`, `csv_parser.py`, `yaml_parser.py`, `xml_parser.py`) ve ortak `parsers/common.py`; `algorithms/search.py` (KMP, bellek modu) ve `algorithms/sorting.py` (stabil Merge Sort); `decoder/base64_decoder.py`; `utils/performance.py`; ve `python main.py` ile çalışan bir Tkinter/ttk GUI (`gui/`). Kapsam dışı bırakılanlar ve ilk sürüm sınırlamaları için README.md'ye ve bu belgenin son bölümüne bakın.

**Son finalizasyon turu notu (bu tur):** Bu turda yeni bir büyük özellik EKLENMEMİŞTİR; amaç mevcut dört formatın (JSON/CSV/XML/YAML) hem normal hem büyük veri desteğini bütünleştirmek, GUI metinlerini/davranışını buna göre doğrulamak ve bu belge ile README.md'yi artık geçerli olmayan "yalnızca büyük JSON/CSV desteklenir" ifadelerinden arındırmaktır. Bu turda yapılanlar: (1) tam test paketi art arda İKİ KEZ çalıştırılmış, ikisinde de 356/356 test geçmiştir; (2) dört format için de (JSON/CSV/XML/YAML) 5600 kayıtlık sentetik bir kaynak dosyayla Tam Aktarım yapılıp oluşan depolarda ilk/son sayfa, satıra git, disk araması (bulunan + iptal), disk sıralaması, kaynak sırasına dönüş ve Base64 (hem prefix hem işaretçi modu) programatik olarak doğrulanmıştır — GUI/Tkinter tıklaması KULLANILMAMIŞTIR, `ImportJob`/`RecordReader`/`DiskSearchJob`/`DiskSortJob`/`decoder.base64_decoder` doğrudan çağrılmıştır; (3) JSON kaynağı üzerinde kasıtlı bir iptal senaryosuyla kısmi depo tutarlılığı ve yeniden açma ayrıca doğrulanmıştır; (4) gerçek, erişilebilir ~121 GB'lık XML ve ~91 GB'lık YAML dosyaları üzerinde YALNIZCA bütçeli (1000 kayıt/32 MiB) bir ÖNİZLEME çalıştırılmış, kaynak dosyaların değişmediği (boyut+değişiklik zamanı karşılaştırılarak) doğrulanmış, Tam Aktarım hiçbir zaman başlatılmamıştır. Ayrıntılar için README.md'nin "Bu finalizasyon turunda hangi büyük-dosya doğrulamaları GERÇEKTEN yapıldı?" bölümüne bakın.

**Ek: 300 GB ölçeği için disk modu.** DuckDB kullanılmadı; bunun yerine `streaming_pilot/` (ijson tabanlı akışlı JSON okuma + `csv.reader` tabanlı akışlı CSV okuma + `ET.iterparse` tabanlı akışlı XML okuma + `yaml.parse()` tabanlı akışlı YAML okuma + ortak JSONL/ikili-indeks/manifest disk deposu) ve GUI'nin **İşlenmiş Veriyi Aç** yoluyla bu depoyu sayfalı okuması eklendi. Disk modunda metin arama da uygulanmıştır: `algorithms/disk_search.py`, açık depronun TAMAMINI dosyadan sırayla (Python'ın `in` operatörüyle, büyük/küçük harfe duyarlı) tarar; kendi arama algoritmamızı kullanma zorunluluğu bu yol için kaldırılmıştır. Eşleşen (görünüm konumu, kaynak kayıt kimliği) çiftleri RAM'de listede tutulmaz, ayrı bir geçici ikili dosyaya yazılır. **Disk modunda sıralama da uygulanmıştır**: `algorithms/disk_sorting.py`, `sorted()` (parça içi) ve `heapq.merge` (parçalar arası, bütçeli fan-in ile) kullanan harici (external) bir sıralamadır — kendi algoritmamızı yazma zorunluluğu bu yol için de kaldırılmıştır. **GUI'den büyük veri aktarımı** (`streaming_pilot/import_job.py` + **Büyük Veri Aktar (JSON/CSV/XML/YAML)** düğmesi) da eklendi: kaynağı akışla mevcut JSONL+indeks biçimine yazar; Önizleme (kasıtlı kısmi) ve Tam Aktarım (kayıt/bayt sınırı yok; JSON/YAML'de tamamlanma dizi kapanışı + kaynağın kalanının EOF'a kadar geçerliliğiyle, CSV/XML'de kaynağın gerçek EOF'una ulaşılmasıyla sayılır) ayrımı vardır. **Büyük CSV desteği** (`streaming_pilot/csv_source.py`) JSON ile aynı disk deposu biçimini (JSONL+ikili indeks+manifest) paylaşır; kayıtlar sıralı metin listesi (pozisyonel) olarak yazılır, gerçek başlıklar yalnızca `manifest.json`'da bir kez tutulur. **Büyük XML desteği** (`streaming_pilot/xml_source.py`) yapılandırılabilir bir path seçiciyle (namespace-toleranslı) kayıt elementlerini akışla okur, mevcut küçük XML parser'ın alan-dönüşüm fonksiyonunu yeniden kullanır. **Büyük YAML desteği** (`streaming_pilot/yaml_source.py`) JSON ile aynı üç seçici türünü kabul eder, `yaml.parse()`'ın olay akışı üzerinden `safe_load` ile birebir aynı skaler dönüşüm kurallarını uygular ve YAML'a özgü bir bütçe-güvenliği sorununu (tırnaksız skalerlerin sessiz kırpılması) ele alır. Ayrıntılar için bölüm 7.1/7.2/7.3/7.4/7.5/7.6 ve README.md'ye bakın.

## 1. Amaç ve Kapsam

DataInspector, JSON, CSV, YAML ve XML dosyalarını okuyup Tkinter + ttk arayüzünde tablo biçiminde gösteren ve bu veri üzerinde inceleme işlemleri yapılmasını sağlayan bir masaüstü uygulamasıdır.

Planlanan temel özellikler:

1. Dosya seçme ve ayrı bir "getir" eylemiyle yükleme.
2. Verileri kolon başlıklarıyla tabloda gösterme.
3. Satır numarasına gitme.
4. Metin arama.
5. Kolon ve artan/azalan yön seçerek sıralama.
6. Seçilen satırdaki Base64 verisini çözümleme.
7. Prefix ve postfix yapılarını ayırma.
8. Birden fazla kolona bölünmüş Base64 parçalarını doğru sırada birleştirerek çözümleme.
9. Çözümlenen sonucu ayrı bir pencerede gösterme.
10. İşlem sürelerini kullanıcıya gösterme.

Metin arama ve sıralamanın çekirdek algoritmaları (KMP tabanlı arama, Merge Sort) eğitim amacıyla projeye özel yazılacaktır; hazır `sorted()`, `list.sort()` veya alt-dize arama fonksiyonlarına bırakılmayacaktır. Base64 çözümleme, kriptografik şifre çözme değildir; yalnızca bir kodlama/biçim dönüşümüdür.

## 2. Planlanan Dosya/Klasör Yapısı

```
DataInspector/
  main.py
  models.py               # Row, Dataset, format_value() — proje-içi başka hiçbir modüle bağımlı değil
  gui/
    main_window.py          # Dosya Seç / Getir ayrımı, worker+queue orkestrasyonu, "tek anda tek uzun işlem" kontrolü
    table_view.py             # view_order yönetimi, sayfalama, satıra gitme, seçim koruma
    dialogs.py                  # arama, sıralama, decode-config, decode-sonuç, hata dialogları
  parsers/
    __init__.py                 # dosya uzantısına göre parser seçimi, common.normalize() çağrısı
    common.py                    # flatten, kolon birleşimi, veri kümesi geneli çakışma tespiti, ParseError
    json_parser.py
    csv_parser.py                    # ayraç ",", tırnak '"'; başlık satırından (records, headers) döner
    yaml_parser.py                 # yaml.safe_load kullanır
    xml_parser.py
  algorithms/
    search.py                      # KMP tabanlı arama
    sorting.py                       # stabil Merge Sort
  decoder/
    base64_decoder.py                 # tam prefix/postfix eşleşmesi, bytes sonuç
  utils/
    performance.py                      # Timer
  tests/
  requirements.txt
  README.md
```

## 3. Modül Sorumlulukları ve Bağımlılık Yönü

```
models.py  (bağımsız)
   ├─▶ parsers/common.py     (parser'lara özel: flatten, çakışma tespiti, ParseError → Dataset üretir)
   │       ├─▶ json_parser.py / csv_parser.py / yaml_parser.py / xml_parser.py
   │       └─▶ parsers/__init__.py   (uzantıya göre dispatch, load(path) -> Dataset)
   ├─▶ algorithms/search.py, algorithms/sorting.py   (Dataset alır, row_id listesi döndürür; parser'ları bilmez)
   ├─▶ decoder/base64_decoder.py                       (Row.raw'dan değer okur; parser'ları bilmez)
   └─▶ gui/*                                             (parsers, algorithms, decoder'ı doğrudan çağırır)
```

- `models.py`, hiçbir parser'a veya GUI'ye bağımlı değildir; bu sayede `algorithms/` ve `decoder/` parser detaylarından habersiz kalır ve GUI'siz test edilebilir.
- GUI ile çekirdek mantık arasında ayrı bir controller/service katmanı yoktur; `main_window.py` ilgili fonksiyonları doğrudan çağırır. Tek pencereli, tek kullanıcılı bir masaüstü uygulamasında bu katmanın getirisi maliyetinden azdır.

## 4. Ortak Veri Modeli (models.py)

**Row** — tek bir kaydı temsil eder:

| Alan | Açıklama |
|---|---|
| `row_id` | Kaydın, ait olduğu `Dataset` içinde yükleme anında atanan ve o `Dataset` yaşadığı sürece **değişmeyen** kimliği. Kaynak dosyanın fiziksel satır numarasıyla ilgisi yoktur. |
| `raw` | Kolon adı → ham değer eşlemi. Değer şunlardan biri olabilir: `MISSING` (bu kayıtta alan hiç yok), `None` (kaynakta açık null), boş metin `""`, metin, sayı, mantıksal (bool), liste, veya boş sözlük `{}` (yalnızca boş bir iç içe nesne alanı için). İç içe nesneler düzleştirme sırasında çözülür ve dot-path kolonlarına dağıtılır; yalnızca **boş** bir iç içe nesnenin düzleştirilecek alt anahtarı olmadığı için olduğu gibi (`{}`) korunması istisnadır — bu durumda alan kaybolmaz. |

**Dataset** — bir dosyadan yüklenen tüm veriyi temsil eder:

| Alan | Açıklama |
|---|---|
| `columns` | Veri kümesindeki tüm kayıtların alan yollarının birleşimi (union); yükleme anında hesaplanır. |
| `rows` | Kayıtların listesi, **orijinal yükleme sırasıyla**. Bu sıra hiçbir sıralama/arama işleminden etkilenmez; yalnızca yükleme sırasında oluşur. |

**format_value(değer) → metin** — ham bir değeri, gösterim ve arama sırasında ortak kullanılacak metne çevirir:

- `MISSING` veya `None` → boş metin (`""`)
- liste veya sözlük (yalnızca boş iç içe nesne alanlarından gelebilir) → JSON biçiminde metne çevrilir (`json.dumps`); bu sayede metin elemanları tırnaklı kalır, elemanlar arasındaki sınır açık olur, listedeki `None` değerleri `null` olarak görünür, iç içe nesne/liste elemanları olduğu gibi korunur; boş liste `[]`, boş nesne `{}` olarak gösterilir
- diğer değerler → doğrudan metin karşılığı (`str(value)`)

İkinci bir tam "display" sözlüğü **tutulmayacaktır**. Hem tablo gösterimi hem arama, aynı `format_value` fonksiyonunu kullanır; böylece ekranda görünen ile aranan metin arasında hiçbir zaman fark oluşmaz ve büyük veri kümelerinde ikinci bir string kopyasının bellek maliyeti ortadan kalkar.

**view_order** — `table_view` tarafından tutulan, o an gösterilecek sırayı belirten `row_id` listesi. `Dataset.rows`'tan bağımsızdır; sıralama işlemi yalnızca bu listeyi günceller, `Dataset.rows`'a asla dokunmaz.

## 5. Veri Akışı

```
Dosya Seç (yol seçimi)  →  Getir (ayrı eylem)
   → worker thread: parsers.load(path)
        → uzantıya göre ilgili parser çağrılır
        → parser ham kayıtları üretir (dosya okuma + ayrıştırma ayrı ölçülür)
        → parsers/common.py: flatten + veri kümesi geneli çakışma kontrolü + Dataset oluşturma (normalizasyon, ayrı ölçülür)
   → queue üzerinden ana thread'e teslim, Tkinter güncellemeleri yalnız ana thread'de yapılır
   → table_view: ilk sayfayı (500 kayıt) Treeview'e basar

Kullanıcı etkileşimi:
   Arama     → algorithms.search (KMP)       → view_order sırasında sonraki/önceki eşleşmeye gider
   Sıralama  → algorithms.sorting (Merge Sort) → view_order güncellenir, Dataset.rows değişmez
   Satıra git → table_view (view_order içindeki 1 tabanlı konum; gerekirse sayfa değiştirir)
   Base64     → seçili satırın raw değerleri + kullanıcının seçtiği kolon/sıra/prefix/postfix
             → decoder.base64_decoder → bytes → ayrı pencerede gösterilir
```

## 6. Parser Sözleşmesi

### 6.1 JSON / YAML kök yapısı

- Kök bir **liste** ve elemanları **nesne (dict)** ise: her nesne ayrı bir kayıttır (çoklu kayıt).
- Kök **tek bir nesne** ise: bu nesnenin tamamı **tek bir kayıt** olarak alınır.
- Bir kaydın (nesnenin) içinde **liste değerli alanlar bulunması ret sebebi değildir**. Örn. `{"name": "...", "tags": ["a", "b"]}` geçerli, tek bir kayıttır; `tags` alanı ham veride liste olarak kalır.
- Bir sarmalayıcı nesnenin içinde kayıt listesi bulunması durumunda (örn. `{"records": [...], "meta": ...}`), bu iç liste **otomatik olarak ayrı kayıtlara açılmaz**; dıştaki nesnenin tamamı (liste değerli alan dahil) tek kayıt olarak kalır.
- Kök bir liste olup elemanları nesne değilse (skaler liste, karışık liste) veya kök doğrudan skaler bir değerse (sayı, metin, bool, null): açıklayıcı bir hata (`ParseError`) üretilir, sessizce dönüştürülmez.

### 6.2 XML (v1 kapsamı)

- Kök elemanın **doğrudan alt elemanları** birer kayıt sayılır.
- Attribute'lar `@ad` biçiminde alan olur (örn. `id` attribute'u → `@id` kolonu); alt elemanlar düz adla alan olur.
- Aynı kayıt içinde **aynı isimli birden fazla alt eleman** varsa, bunlar tek bir alanda **liste** olarak korunur; birbirinin üzerine yazılmaz.
- **Karma içerik** (bir elemanın hem doğrudan metni hem alt elemanları birlikte barındırması) ilk sürümde desteklenmez; böyle bir yapıyla karşılaşıldığında sessizce yoksayılmaz, açıklayıcı bir hata verilir.
- Bu kurallar, ilk sürümün (v1) desteklediği XML yapısını tanımlar; daha karmaşık XML yapıları kapsam dışıdır ve ileride ayrıca ele alınabilir.

### 6.3 Düzleştirme ve kolon çakışması

- Kolon adları, iç içe alanların nokta ayracıyla birleştirilmesiyle üretilir (örn. `adres.sehir`).
- Çakışma kontrolü **tek bir kayıtla sınırlı değildir**: veri kümesindeki tüm kayıtlar taranarak, farklı kökenden gelen ama aynı kolon adına düşen alan yolları tespit edilir (örn. bir kayıttaki düz `"a.b"` alanı ile başka bir kayıttaki iç içe `a → b` yapısı).
- Böyle bir çakışma tespit edilirse yükleme durur ve açıklayıcı bir `ParseError` verilir; iki farklı kökenden gelen alan **sessizce aynı kolonda birleştirilmez**.

### 6.4 Ham veri koruma kuralları

- `MISSING` (alan yok), `None` (açık null) ve `""` (boş metin) birbirinden ayrı ham durumlar olarak korunur.
- CSV ve XML kaynaklı metinler **hiçbir zaman otomatik olarak sayıya çevrilmez** (örn. `"00123"` baştaki sıfırlarıyla korunur).
- Listeler (ve içlerindeki iç içe nesneler) ham veride olduğu gibi korunur; gösterimde JSON biçimi kullanıldığı için metin tırnakları, eleman sınırları ve `null` değerleri korunur, boş liste `[]` olarak gösterilir. Boş bir iç içe nesne alanı da (`{}`) düzleştirme sırasında kaybolmaz, olduğu gibi korunur ve `{}` olarak gösterilir.
- YAML ayrıştırmasında `yaml.safe_load` kullanılır. Tarih, bytes, set gibi YAML'a özgü ek türler ve metin olmayan sözlük anahtarları desteklenmez; `ParseError` ile reddedilir (kesinleşmiş karar, bkz. bölüm 14).
- Dosyalar UTF-8 (BOM'lu ya da BOM'suz) olarak okunur. Dosya bu şekilde çözülemiyorsa (geçersiz UTF-8 baytları) hatalı baytlar yok sayılmaz veya değiştirilmez; açıklayıcı bir `ParseError` fırlatılır.
- JSON'a özgü olarak: standart JSON dışı `NaN`/`Infinity`/`-Infinity` sabitleri (kökte, iç içe nesne veya liste içinde her nerede geçerse) sessizce özel bir float değerine çevrilmez, `ParseError` ile reddedilir. Aynı şekilde, sayısal aralığı aşan bir sayı harfi (ör. `1e400`, `-1e400`) `float()` dönüşümünde sessizce sonsuzluğa taşmaz; bu da `ParseError` ile reddedilir. Bu iki kontrol yalnızca JSON parser'ına özgüdür; CSV'de hücreler zaten hiçbir zaman sayıya çevrilmez (bkz. yukarı), YAML/XML için bu MVP'de ayrı bir NaN/Infinity kontrolü eklenmemiştir.

### 6.5 CSV (v1 kapsamı)

- Ayraç virgül (`,`), alıntılama karakteri çift tırnak (`"`) olarak sabittir; ayraç/başlık tahmini (sniffing) yapılmaz. Noktalı virgül/tab desteği sonraya bırakılmıştır.
- İlk boş olmayan (`[]` olmayan) kayıt başlık satırı kabul edilir; başlık sırası korunur.
- Tekrarlanan başlıklar, boş veya yalnızca boşluk içeren başlıklar `ParseError` ile reddedilir. Geçerli başlıklar olduğu gibi (kırpılmadan) kolon adı olur.
- Tamamen boş fiziksel satırlar atlanır; ayraç veya tırnakla belirtilmiş boş hücrelerden oluşan kayıtlar (ör. `,,,` ya da `"","",""`) bu kapsamda **değildir** ve normal veri kaydı olarak işlenir.
- Bir kaydın alan sayısı başlık sayısıyla uyuşmuyorsa `ParseError` fırlatılır.
- Tüm hücre değerleri metin olarak kalır; `"00123"`, `"true"`, `"NaN"` gibi içerikler hiçbir zaman dönüştürülmez, baştaki/sondaki boşluklar korunur.
- Boş dosya boş bir `Dataset` üretir. Yalnızca başlık satırı olan bir dosya, kolonları korunmuş ve sıfır satırlı bir `Dataset` üretir (sahte veri satırı eklenmez).
- Tırnak içindeki virgül, çiftlenmiş tırnak (`""` → `"`) ve çok satırlı hücreler desteklenir; hücre içindeki LF/CRLF karakterleri yükleme boyunca değişmeden korunur (bu nedenle CSV dosyası `newline=""` ile okunur; JSON'un evrensel satır sonu davranışı değişmez).
- `csv.reader` `strict=True` ile çalıştırılır; kapanmamış tırnak gibi durumlarda oluşan `csv.Error`, asıl hata korunarak (`from e`) `ParseError`'a çevrilir. Hata mesajında geçen fiziksel CSV satır numarası, `Row.row_id` ile karıştırılmaz — ikisi farklı kavramlardır.
- Bu kurallar için `common.normalize()`'a küçük bir arayüz eklentisi yapılmıştır: opsiyonel `known_columns` parametresi, kayıtlardan bağımsız olarak bilinen düz kolon adlarını (CSV başlıkları) tohumlar. Bu, sıfır kayıtlı ama başlığı bilinen bir `Dataset`'in kolonlarını kaybetmeden üretebilmek içindir; varsayılan (`None`) JSON'un mevcut davranışını değiştirmez. Benzer şekilde `common.read_text_file()`'a opsiyonel `newline` parametresi eklenmiştir (varsayılan `None`, JSON için değişiklik yok; CSV `newline=""` geçer).

## 7. Algoritmalar

### 7.1 Arama

**Bellek modu (KMP) — küçük dosyalar:**
- Arama, o an yüklü veri kümesindeki **tüm kayıtlarda ve tüm kolonlarda** çalışacak şekilde tasarlanmıştır.
- Sorgu metni için ön işlem (prefix/failure) tablosu, bir arama işlemi başına **yalnızca bir kez** hazırlanır; taranan her hücre için yeniden hesaplanmaz.
- Eşleştirme, her hücrenin `format_value` ile üretilen metni üzerinde yapılır.
- Sonraki/önceki eşleşmeye geçiş, o an geçerli olan `view_order` sırasını izler.

**Disk modu (`algorithms/disk_search.py`) — İşlenmiş Veriyi Aç ile açılan depolar:**
- Kendi arama algoritmamızı kullanma zorunluluğu bu yol için kaldırılmıştır; büyük/küçük harfe duyarlı düz metin içerme araması doğrudan Python'ın `in` operatörüyle yapılır.
- Kayıtlar depodan `RecordReader.read_record()` ile **sırayla, tek tek** okunur; tüm kayıtlar ya da metinleri belleğe toplanmaz. Kullanıcının sorgu metni kırpılmaz; yalnızca tamamen boş sorgu reddedilir.
- Bir kaydın **her hücresi ayrı** değerlendirilir (`format_value` ile) — hücreler asla birleştirilmez, bu sayede farklı hücrelerin birleşiminden sahte eşleşme oluşmaz. Aynı satırda birden fazla hücre eşleşse de satır sonuçlara **bir kez** eklenir. Pozisyonel kayıtlarda ekranda o an bilinen sayfa kolonlarıyla sınırlı kalınmaz, kaydın tüm hücreleri taranır.
- Eşleşen kayıt kimlikleri (0 tabanlı depo indeksleri) RAM'de büyüyen bir listede **tutulmaz**; `DiskSearchJob` bunları sırayla ayrı bir geçici ikili dosyaya (8 bayt/uint64) yazar; `SearchResultsStore` sonuç sayısını ve istenen konumdaki kimliği doğrudan bu dosyadan okur.
- Arama bir arka plan thread'inde (`DiskSearchJob.run`) çalışır; ilerleme (taranan/bulunan sayaçları) Tk widget'larına dokunmadan basit int alanlarda tutulur, ana thread bunları periyodik olarak (yaklaşık gösterge olarak, kilitsiz) okuyup durum satırına yazar — **kayıt başına kuyruk mesajı üretilmez**, ilerleme bildirimleri bellekte birikmez.
- **Aramayı İptal Et** ile iptal edilebilir; iptal edilen arama tamamlanmış gibi sunulmaz (ayrı bir "[İPTAL EDİLDİ]" notuyla belirtilir) ama o ana kadar bulunan eşleşmeler kullanılabilir kalır. Yeni bir arama, farklı bir depo açılması ve uygulama kapanışı, önceki geçici sonuç dosyasını temizler; depo değiştiğinde hâlâ süren eski bir aramanın sonucu (nesil sayacıyla karşılaştırılarak) yeni tabloyu etkilemez.
- Önceki/Sonraki eşleşme, doğru tablo sayfasına (disk üzerinden, worker üzerinden) geçip ilgili satırı seçer; tablo depoyu sayfalamaya devam eder (arama sonucu tüm depoyu belleğe almaz).
- Kısmi bir depoda arama tamamlanması, kaynak dosyanın tamamının tarandığı anlamına gelmez; bu, disk modu aktifken sürekli görünen bir notla belirtilir. Disk modunda sıralama bu aşamada pasiftir.

### 7.2 Sıralama

**Bellek modu (Merge Sort) — küçük dosyalar:**
- Sıralama için `sorted()`/`list.sort()` değil, projeye özel **stabil** bir Merge Sort implementasyonu kullanılır.
- Sıralama yalnızca `view_order` listesini günceller; `Dataset.rows` hiçbir zaman yeniden sıralanmaz.
- Karşılaştırma tip gruplarına göre yapılır, gruplar arası öncelik sırası: **Bool → Sayı → Metin → Karmaşık (liste)**. Artan/azalan yön yalnızca **aynı grup içindeki** karşılaştırmaya uygulanır; gruplar arası öncelik yönden etkilenmez.
- `MISSING`, `None` ve `NaN`, sıralama yönünden bağımsız olarak **her zaman sonda** yer alır; bu üç durum kendi aralarında, sıralamaya girdikleri mevcut görünümdeki göreli sırasını korur.
- İki yönde de eşit değerli kayıtlar, sıralamaya girdikleri mevcut görünümdeki göreli sırasını korur (stabilite).
- Metinler varsayılan olarak metin (ordinal) biçiminde karşılaştırılır. Bir metin kolonunun sayısal olarak yorumlanması gerektiğinde ham veri **değiştirilmez**; bunun yerine sıralama sırasında geçici bir karşılaştırma anahtarı üretilir. Tüm değerleri float'a zorlamak yerine hassasiyeti koruyan seçenekler (int, Decimal gibi) bellek modu için bu MVP'de eklenmemiştir (kapsam dışı, bkz. bölüm 15); disk modunda ise Decimal desteği vardır (aşağıya bakın).

**Disk modu (`algorithms/disk_sorting.py`, harici/external sıralama) — İşlenmiş Veriyi Aç ile açılan depolar:**
- Kendi sıralama algoritmamızı kullanma zorunluluğu bu yol için kaldırılmıştır: parça-içi sıralama `list.sort()`, parçalar arası birleştirme `heapq.merge` ile yapılır (ikisi de stdlib).
- Kayıtlar küçük gruplar (chunk) halinde işlenir. Geçici parça (run) dosyalarında yalnızca **sıralama anahtarı + önceki görünüm konumu + kaynak kayıt kimliği** bulunur; ham kayıtlar hiçbir zaman kopyalanmaz. Anahtarların tip ve hassasiyeti (Decimal dahil) `pickle` ile korunur.
- Bellek bütçesi yalnızca kayıt adediyle sınırlanmaz: bir grubun anahtarlarının toplam (pickle ile ölçülen) bayt boyutu da izlenir; iki sınırdan (kayıt adedi / bayt) hangisine önce ulaşılırsa grup diske yazılır. Tek bir anahtar yapılandırılabilir bir sınırı (`max_key_bytes`, varsayılan 1 MB) aşarsa açıklayıcı bir `SortConfigError` fırlatılır. **Bu bütçe, sürecin TAMAMININ bu sınırla kalacağının garantisi değildir** — Python nesne ek yükü, dosya arabellekleri ve GC davranışı gerçek süreç belleğini bu nominal bütçenin üzerine çıkarabilir.
- Birleştirmede aynı anda açık parça dosyası sayısı `max_open_runs` (varsayılan 8) ile sınırlıdır; parça sayısı bunu aşarsa **birden fazla birleştirme turu** kullanılır (gruplar halinde ara-birleştirme, parça sayısı sınırın altına inene kadar tekrarlanır). Hiçbir aşamada tüm parça dosyaları aynı anda açılmaz.
- Karşılaştırma kuralları bellek modundakiyle **aynıdır** (tip-grup önceliği, MISSING/None/NaN her yönde sonda), yalnızca **Decimal desteği eklenmiştir** (ayrı bir sayısal rank'ta, float'a çevrilmeden). Kararlılık (eşit anahtarlarda önceki görünüm sırasının korunması), tek bir parça içinde olduğu kadar **farklı parça dosyaları ve farklı birleştirme turları arasında da** geçerlidir — bu, anahtara son eleman olarak eklenen "önceki görünüm konumu" ile sağlanır (heapq.merge bu tam sırayı korur).
- Sonuç, diskte sabit boyutlu (8 bayt/uint64) bir `view_order.seq` dosyasıdır: dosyadaki i'inci kayıt, yeni görünümün i'inci (0 tabanlı) konumundaki KAYNAK KAYIT KİMLİĞİDİR. Bu dosya asla RAM listesine çevrilmez; GUI bir sayfa istediğinde yalnızca o sayfanın en fazla 500 kimliği okunur. Görünüm sıralandığında, sayfadaki kayıtlar depoda ardışık olmayabileceğinden `RecordReader.read_record()` ile tek tek okunur (kaynak sırasındayken kullanılan tek-bloklu `read_page()` optimizasyonunun yerini alır).
- Treeview satır kimliği (`iid`) **her zaman kaynak kayıt kimliğidir** (görünüm konumu değil); bu sayede sıralama sonrası seçili satırın Base64 işlemi her zaman doğru ham kaydı kullanır, "satıra git" ise mevcut sıralı görünümdeki 1 tabanlı konumu ifade eder.
- **Kaynak Sırasına Dön** ile görünüm, hiçbir dosya gerektirmeden kaynak sırasına (kimlik = konum) döner.
- Sıralama **başarıyla** değiştiğinde eski arama sonuçları geçersiz kılınır (arama sonuçları görünüm konumuna göre kayıtlıydı). Yeni bir arama, mevcut (varsa sıralanmış) görünüm sırasını izler.
- Sıralama worker'da, widget güncellemeleri ana thread'de çalışır; ilerleme (taranan/toplam, birleştirme turu) ve geçen süre periyodik olarak (kayıt başına kuyruk mesajı üretmeden) gösterilir. **Sıralamayı İptal Et** vardır. Yeni sıra yalnızca **tamamen başarıyla** üretildikten sonra etkinleşir; iptal, hata ya da disk dolması durumunda önceki görünüm kullanılabilir kalır — bunu sağlamak için sürmekte olan işin geçici klasörü, eski (aktif) klasörden AYRI tutulur ve eski klasör yalnızca yeni sıralama başarıyla bittikten sonra silinir. Depo değişikliği veya uygulama kapanışında geçici klasörler temizlenir; sürmekte olan bir işin sonucu, bittiğinde depo zaten değişmişse yeni tabloya uygulanmaz.

### 7.3 Büyük JSON Aktarımı (`streaming_pilot/import_job.py`, GUI: Büyük Veri Aktar (JSON/CSV))

- Kaynağı TEK SEFER, salt okunur açar; `parsers.load()` çağrılmaz, dosya tamamen belleğe alınmaz. Mevcut `streaming_pilot` okuyucu/yazıcı altyapısı (`RecordWriter`, `RecordReader`, `StreamingArraySource`, `BudgetedBinaryReader`) yeniden kullanılır; aktarım iş mantığı yalnızca `ImportJob` sınıfında yaşar, `MainWindow` yalnızca işi başlatır/izler/sonucu açar.
- **Kayıt dizisi seçimi** üç açık yoldan biriyle yapılır: kökün kendisi zaten bir dizi (`{"mode": "root_array"}` — `StreamingArraySource`'a bu sürümde eklenmiştir), kök bir nesnede **alan adıyla**, ya da **alan sırasıyla** (1 tabanlı, arayüzde açıkça böyle etiketlenir). "İlk bulunan dizi" sezgisi (`first_array`) bu ekranda SUNULMAZ; hiçbir gerçek alan adı koda sabit kodlanmaz.
- **Önizleme** (kayıt/bayt sınırı yapılandırılabilir, varsayılan 1000/32 MiB) ile **Tam Aktarım** (kayıt/bayt sınırı YOKTUR — bu iki sınır gizlice uygulanmaz) ayrı, açık modlardır. Kaynak/kayıt-adedi sınırları (yalnızca önizlemeye özgü), tek-kayıt güvenlik sınırlarından (`max_record_bytes` varsayılan 200 MB, `max_depth` varsayılan 1000 — hem önizleme hem tam aktarımda geçerli) tamamen AYRI ayarlardır.
- **Tek kayıt sınırları akış sırasında (inşa edilirken) uygulanır**, kayıt tamamlandıktan SONRA yapılan bir ölçüm değildir: `StreamingArraySource._consume_value`, her olay geldikçe artan bir derinlik sayacı ve yaklaşık bir bayt sayacı tutar, sınır aşılır aşılmaz (kayıt tamamlanmadan) `RecordTooDeepError`/`RecordTooLargeError` fırlatır. Bayt sayacı `pickle`/tam serileştirme YAPMAZ; ucuz, yaklaşık bir tahmindir (bu açıkça belgelenmiştir).
- **"Tamamlandı" tanımı (Tam Aktarım için) kesindir**: dizinin kapanması TEK BAŞINA yeterli değildir. Üç şart birden gerekir: (1) hedef dizi bulunmalı, (2) tüm elemanları yazılmalı, (3) kaynağın geri kalanı da dosya sonuna kadar geçerli biçimde ayrıştırılmalıdır. Bu, `StreamingArraySource.iter_records(drain_to_eof=True)` ile sağlanır: dizi kapandıktan sonra hiçbir eleman daha üretmeden, kalan belgeyi (kökün diğer alanları, kapanış parantezleri) gerçek EOF'a kadar sözdizimsel olarak doğrulamaya devam eder; yalnızca bu da başarılı olursa `STOP_FULLY_DRAINED` (ve buna bağlı olarak `tamamlandi_mi=True`) oluşur. Önizleme modu, sınır aşılmasa bile HİÇBİR ZAMAN "tamamlandı" sayılmaz — bu ayrı, kasıtlı bir kategoridir.
- Sonuç kategorileri (`outcome`) birbirinden açıkça ayrı tutulur: önizleme, tam-aktarım-tamamlandı, kullanıcı iptali, hedef-dizi-bulunamadı, tek-kayıt-sınırı-aşıldı, ayrıştırma-hatası (dizi kapandı ama devamı bozuk dahil), kaynak-okuma-hatası (kaynak bağlantısı kesilmesi gibi), çıkış-yazma-hatası, çıkış-diskinde-yetersiz-alan, seçici-hatası, beklenmeyen-hata.
- Çıktı diskinin boş alanı aktarım BAŞLAMADAN önce ve aktarım sırasında periyodik (varsayılan her 500 kayıtta bir) kontrol edilir; kaynak dosya boyutu çıktı boyutunun kesin bir tahmini olarak KULLANILMAZ (yalnızca kaba bir ön kontrol). Yazma sırasında gerçek bir `OSError` (disk doldu) de ayrıca yakalanıp açık biçimde raporlanır.
- Her aktarım, verilen çıktı klasörünün altında **zaman damgalı YENİ bir alt klasöre** yazılır; mevcut depoların üzerine asla yazılmaz. Bu sürümde **kaldığı yerden devam etme yoktur**: her deneme kaynağın başından yeni bir depoya aktarım yapar; ijson'ın tamponlanmış dosya konumundan güvenilir bir devam noktası çıkarılabileceği varsayılmaz.
- İptalde ya da hatada, o ana kadar TAMAMLANMIŞ kayıtlar tutarlı, kullanılabilir bir kısmi depo olarak kalır (yarım JSONL kaydı ya da yarım indeks girdisi asla oluşmaz — `RecordWriter.write_record`'ın JSONL'yi indeksten ÖNCE yazması ve her adımın ya hep ya hiç tamamlanması sayesinde); bu kısmi depo istenirse doğrudan (klasör seçme diyaloğu atlanarak) açılabilir.
- Worker'da çalışır, widget güncellemeleri ana thread'de yapılır; ilerleme (okunan bayt, tamamlanan kayıt, yazılan bayt, geçen süre) periyodik gösterilir (kayıt başına kuyruk mesajı üretilmez), **Aktarımı İptal Et** vardır.

### 7.4 Büyük CSV Aktarımı (`streaming_pilot/csv_source.py`, GUI: Büyük Veri Aktar (JSON/CSV) — kaynak uzantısı `.csv` seçildiğinde)

- Kaynak, JSON'daki gibi TEK SEFER salt okunur açılır (`newline=""`, `encoding="utf-8-sig"` — BOM'lu/BOM'suz UTF-8 ikisi de desteklenir); dosya tamamen belleğe alınmaz, Python'ın standart `csv.reader`'ı ile **fiziksel satır satır** okunur. Ayraç virgül (`,`), tırnak karakteri çift tırnak (`"`), `strict=True` — bellek modundaki (`parsers/csv_parser.py`) kurallarla TUTARLIDIR.
- **Seçici kavramı YOKTUR**: CSV'de her satır zaten bir kayıttır; JSON'a özgü kök-dizi/alan-adı/alan-sırası seçimi bu yolda geçerli değildir ve GUI'de pasifleştirilir.
- İlk boş olmayan fiziksel kayıt başlık kabul edilir; başlık sırası/metni AYNEN korunur. Boş/yalnızca boşluk ya da tekrarlanan başlıklar `CsvHeaderError` ile reddedilir (JSON'daki `SelectorError` ile aynı rol: kaynağın temel yapısı geçersizdir, kendi `outcome` kategorisini alır: `baslik_hatasi`). Tamamen boş fiziksel satırlar atlanır; ayraç/tırnakla belirtilmiş boş hücreli kayıtlar atlanmaz. Başlıktan az/fazla alan içeren kayıt, fiziksel satır numarasıyla birlikte (gerçek hücre değeri İÇERMEYEN bir mesajla) reddedilir. Tüm hücreler METİN kalır; hiçbir dönüştürme yapılmaz.
- **Kayıtlar depoda SIRALI METİN LİSTESİ (pozisyonel) olarak yazılır** — başlıklar her satırda TEKRARLANMAZ (95M+ satırlık bir depoda ciddi yer kazancı sağlar); gerçek başlıklar yalnızca `manifest.json`'da **bir kez** (`kolonlar` alanı) tutulur. Bu, mevcut `RecordWriter`/`RecordReader` (JSONL + ikili indeks) biçimini HİÇ DEĞİŞTİRMEDEN yeniden kullanır. GUI, bir CSV deposu açıldığında kolon adlarını sayfa içeriğinden DEĞİL, HER ZAMAN manifest'teki bu listeden alır (`gui/table_view.py`'nin `known_columns` parametresi) — böylece yalnızca başlık içeren (sıfır kayıtlı) bir depoda bile kolonlar kaybolmaz. Aynı şekilde disk modunda sıralama (`algorithms/disk_sorting.py`) da gerçek başlık adını bu listeyle bir pozisyona çözer (JSON'un sayfa-bağlamına dayanan "Kolon N" davranışı hiç değişmedi, yalnızca CSV için ayrı, opsiyonel bir yol eklendi).
- **Tek bir hücrenin boyutu** `csv.field_size_limit` ile sınırlanır (yapılandırılabilir, `ImportJob(max_csv_field_bytes=...)`, varsayılan 10 MB). Bu GLOBAL bir `csv` modülü ayarı olduğu için yaşam döngüsü AÇIKÇA yönetilir: `CsvStreamSource`, eski değeri constructor'da kaydedip yeni sınırı hemen uygular; eski değeri yalnızca **açık bir `close()` çağrısında** (ya da `with CsvStreamSource(...) as source:` bloğunun çıkışında) geri yükler — bir generator'ın kendi `finally` bloğuna, CPython referans sayımına ya da çöp toplayıcının ne zaman çalıştığına ASLA güvenilmez. `ImportJob._run_csv`, dosya + `CsvStreamSource` + `RecordWriter`'ı TEK bir `with` zincirinde açar; bu sayede başarı, kullanıcı iptali, başlık hatası, `csv.Error`/`UnicodeDecodeError`, yazma hatası ve BEKLENMEYEN herhangi bir exception dahil TÜM çıkış yollarında `close()` (dolayısıyla `field_size_limit`'in eski değerine dönmesi) Python'ın `with` ifadesinin kendi garantisiyle deterministik olarak gerçekleşir.
- Bayt bütçesi (yalnızca Önizleme modu) rastgele bir bayt sınırında değil, FİZİKSEL SATIR sınırında uygulanır (bir satırın ortası asla kesilmez); Tam Aktarımda JSON'daki gibi anlamsız derecede büyük bir bütçe kullanılır.
- "Tamamlandı" (Tam Aktarım için), kaynağın gerçek EOF'una (bütçe/hata olmadan) ulaşılmasıyla sayılır — JSON'daki "dizi kapandı + kaynağın kalanı da EOF'a kadar geçerli" üç şartlı tanımından daha basittir, çünkü CSV'de sarmalayıcı bir kök yapı/dizi kapanışı yoktur; kaynağın tamamı zaten kayıt akışının kendisidir.
- İptalde ya da hatada, o ana kadar TAMAMLANMIŞ kayıtlar JSON'daki ile AYNI garantiyle (yarım JSONL kaydı/indeks girdisi asla oluşmaz) tutarlı, kullanılabilir bir kısmi depo olarak kalır.
- Manifest'e `kaynak_format: "csv"` ve `kolonlar` (başlık listesi) eklenir; eski (CSV özelliğinden önceki) JSON manifestleri bu alanlara sahip değildir ve GUI bunu `manifest.get("kaynak_format") == "csv"` kontrolüyle güvenle ayırt eder (eksikse JSON pozisyonel davranışı hiç değişmeden sürer).

### 7.5 Büyük XML Aktarımı (`streaming_pilot/xml_source.py`, GUI: Büyük Veri Aktar (JSON/CSV/XML/YAML) — kaynak uzantısı `.xml` seçildiğinde)

- Kaynak, `xml.etree.ElementTree.iterparse` ile akışla okunur; belgenin tamamını belleğe alan `ET.parse()`/`fromstring()` KULLANILMAZ. `BudgetedBinaryReader` (JSON tarafındakiyle AYNI sınıf) çağıran (`ImportJob`) tarafından `rb` modunda açılır; bu modül dosyayı kendisi açmaz/kapatmaz.
- **Seçici**: kullanıcı, kök elemanın altında (1 tabanlı derinlikte) tekrar eden kayıt elementini basit bir yol ile belirtir: `{"mode": "path", "value": ["item"]}` (kökün doğrudan çocuğu) ya da `{"mode": "path", "value": ["kayitlar", "item"]}` (iç içe). Sabit kodlanmış hiçbir gerçek etiket adı YOKTUR; wildcard/attribute-koşulu/XPath desteklenmez. Birden fazla üst eleman aynı yolu paylaşıyorsa HEPSİNİN altındaki eşleşen kayıtlar toplanır.
- **Namespace eşleştirme kuralı**: bir yol parçası `{` ile başlıyorsa tam Clark notation (`{uri}yerel-ad`) eşleşmesi aranır; başlamıyorsa yalnızca elementin YEREL adı (namespace yok sayılarak) karşılaştırılır — kullanıcının namespace URI'sini bilmesini gerektirmez.
- **Veri dönüşümü**: mevcut küçük XML parser'ın (`parsers/xml_parser.py`) `_element_to_value` fonksiyonu DOĞRUDAN yeniden kullanılır — attribute'lar `@ad`, alt elemanlar düz adla, tekrarlanan alt elemanlar liste, karma içerik reddedilir; küçük parser ile birebir aynı kurallar, kod tekrarı yoktur. **CSV'deki gibi, XML metinleri de HİÇBİR ZAMAN otomatik olarak sayıya çevrilmez** — `"00123"` gibi değerler metin olarak kalır (bu, disk modunda XML'e göre sıralamanın METİN sırasıyla yapıldığı anlamına gelir, bkz. bölüm 7.2).
- **Bellek yönetimi**: tamamlanan HER element (kayıt olsun ya da olmasın) kendi "end" olayında hem `clear()` edilir hem de üst elementinden `parent.remove(...)` ile kaldırılır; kök/ata elementler milyonlarca artık-boş alt element referansı biriktirmez. Bir kaydın kendi henüz kapanmamış alt elemanları bu temizlikten muaftır (veri kaybı olmasın diye).
- Derinlik/boyut sınırları (`max_depth`/`max_record_bytes`) akış sırasında, kayıt henüz inşa edilirken uygulanır (JSON'daki `_consume_value` ile aynı desen).
- Bayt bütçesi (yalnızca Önizleme) dolarsa expat beklenmedik EOF görüp `ET.ParseError` fırlatır; bu, `budget_hit` önceliklendirilerek gerçek bir ayrıştırma hatasından ayrılır.
- **"Tamamlandı" tanımı JSON'dakinden daha basittir**: XML belgesinin kendisi zaten tek bir kök elemandır — ayrı bir "hedef dizi kapandı, şimdi geri kalanı doğrula" aşaması yoktur; `stop_reason == STOP_SOURCE_REAL_EOF` (bütçe/hata yok) tek başına "belge sonuna kadar geçerli biçimde tamamlandı" anlamına gelir; ayrı bir `drain_to_eof` parametresi YOKTUR.

### 7.6 Büyük YAML Aktarımı (`streaming_pilot/yaml_source.py`, GUI: Büyük Veri Aktar (JSON/CSV/XML/YAML) — kaynak uzantısı `.yaml`/`.yml` seçildiğinde)

- `yaml.safe_load()` ile belgenin TAMAMI YÜKLENMEZ; bunun yerine `yaml.parse()` (yalnızca Parser aşaması — Composer/Constructor YOKTUR) kullanılır. `CSafeLoader` varsa kullanılır, yoksa `SafeLoader`'a düşülür — ikisi de AYNI `yaml_constructors` sözlüğünü paylaştığından davranışları birebir aynıdır.
- **Seçici JSON ile AYNIDIR**: `{"mode": "root_array"}`, `{"mode": "name", "value": "alan"}`, `{"mode": "index", "value": N}` (1 tabanlı) — `gui/dialogs.py`'de JSON ile birebir aynı fonksiyon (`_build_json_selector`) yeniden kullanılır.
- **Scalar tür çözümlemesi**: `yaml.parse()`'ın ürettiği olaylar yalnızca ham metni verir (örtük etiket çözümlemesi yapılmaz); bu modül `safe_load`'ın kendisinin kullandığı AYNI `Resolver` ve `yaml_constructors` fonksiyonlarını doğrudan çağırarak (elle inşa edilmiş bir `ScalarNode` ile) metni gerçek değere çevirir — `"00123"` gibi octal ya da `yes`/`no` gibi örtük bool kuralları `safe_load` ile birebir aynı sonucu verir (ampirik olarak doğrulanmıştır). Bu, YAML'da (JSON/XML/CSV'nin aksine) sayısal görünümlü bir alanın **gerçek sayı** olarak tutulabildiği (ve dolayısıyla disk modunda sayısal sırayla sıralanabildiği) anlamına gelir.
- **Alias/anchor DESTEKLENMEZ**; **çok belgeli (multi-document) YAML DESTEKLENMEZ**; standart-dışı türler (`!!binary`/`!!set`/`!!timestamp`/`!!pairs`/`!!omap`) ve metin olmayan mapping anahtarları reddedilir — hepsi açık, içerik sızdırmayan bir `YamlUnsupportedStructureError` ile.
- **Bellek**: aynı anda yalnızca TEK bir kayıt ağacı bellekte tutulur; `yaml.parse()` (ijson gibi) kalıcı bir ağaç TUTMAZ, XML'deki gibi ayrı bir `clear()`/`remove()` mekanizmasına gerek yoktur.
- **KRİTİK bütçe güvenliği (yalnızca Önizleme)**: YAML'ın tırnaksız (plain) skaler değerleri açık bir kapanış belirteci gerektirmez — bir bütçe tam olarak bir skalerin ortasında dolarsa, YAML BUNU SESSİZCE (istisna fırlatmadan) kabul edebilir (ampirik olarak doğrulanmıştır: 200 karakterlik bir metin, bütçe ortasında kesildiğinde hiçbir istisna fırlatılmadan 88 karaktere kırpılabiliyor). Bu modül, inşa edilmekte olan kaydın/atlanmakta olan değerin TAMAMI tüketildikten HEMEN SONRA bütçenin tam olarak O SIRADA (önce False, şimdi True) dolup dolmadığını kontrol eder; yalnızca bu GEÇİŞ anında dolduysa o kayıt/değer şüpheli sayılıp TAMAMEN ATILIR, önceki başarılı kayıtlar korunur. Kontrol noktası, kaydın kendi AÇILIŞ olayı alınmadan HEMEN ÖNCE (döngünün en başında) yakalanır — sonradan yakalansaydı geçiş asla doğru algılanamazdı. **Bilinen sınır**: bütçe, alttaki okuyucunun tek bir okuma çağrısında isteyebileceği miktardan (libyaml için tipik ~16 KB) küçükse bu geçiş hiç gözlenemeyebilir; varsayılan 32 MiB önizleme bütçesi bunun çok üzerindedir.
- **"Tamamlandı" tanımı JSON ile AYNIDIR**: seçilen sequence kapandıktan SONRA (Tam Aktarımda) kalan belge de gerçek EOF'a kadar doğrulanır; yalnızca bu da başarılı olursa `STOP_FULLY_DRAINED` olur.

## 8. Decoder Yaklaşımı (Base64)

- Veri `PREFIX + BASE64 + POSTFIX` biçiminde, tek kolonda veya birden fazla kolona bölünmüş olarak bulunabilir. Decoder belirli kolon adlarına veya sabit bir parça sırasına bağımlı olmayacak biçimde tasarlanır; hangi kolonların hangi sırayla kullanılacağı ve prefix/postfix değerleri kullanıcı tarafından çalışma zamanında belirlenir.
- Prefix/postfix ayıklaması **tam eşleşme kontrolüyle** yapılır (metnin belirtilen prefix ile başladığı / postfix ile bittiği doğrulanarak). `str.strip()`, `lstrip()`, `rstrip()` bu amaçla **kullanılmaz** — bu fonksiyonlar literal bir alt diziyi değil, verilen karakter kümesindeki herhangi bir karakteri siler.
- **İki bağımsız eksen**: (1) `prefix_mode` — `"starts_with"` (klasik: metnin en başındaki prefix, tam eşleşmeyle kaldırılır) ya da `"marker"` (metin-içi işaretçi: verilen işaretçi metin İÇİNDE herhangi bir yerde aranır, bulunduğunda işaretçiye kadarki her şey işaretçiyle birlikte atılır — `_find_marker_and_strip`); (2) `apply_to` — `"joined"` (kolonlar birleştirildikten SONRA) ya da `"parts"` (birleştirmeden ÖNCE her parçaya ayrı ayrı). Bu iki eksen TAMAMEN BAĞIMSIZDIR; dördü de (starts_with×joined, starts_with×parts, marker×joined, marker×parts) geçerli kombinasyonlardır.
- Prefix/postfix'in **birleştirilmiş tek metne mi yoksa her parçaya ayrı ayrı mı** uygulanacağı, GUI'deki Base64 diyaloğunda kullanıcının açıkça seçtiği bir seçenektir (`apply_to`); kod bunu varsaymaz (kesinleşmiş karar, bkz. bölüm 14).
- Base64 çözümlemesinin sonucu **bytes** türünde tutulur. Baytların metne (örn. UTF-8) çevrilmesi ayrı, isteğe bağlı bir adımdır; başarılı bir Base64 çözümü, sonucun geçerli bir UTF-8 metni olacağını garanti etmez.
- Base64 çözümleme kriptografik şifre çözme değildir; geçersiz/bozuk veri bir "yanlış anahtar" durumu değil, bir biçim hatasıdır ve kullanıcıya açık bir hata mesajıyla bildirilir.

## 9. Performans Ölçümü

Aşağıdaki süreler **ayrı ayrı** ölçülür:

| Ölçüm | Kapsam |
|---|---|
| Dosya okuma | Dosyayı diskten belleğe alma |
| Ayrıştırma (parsing) | Bellekteki içeriği ham kayıt listesine çevirme |
| Normalizasyon | flatten + kolon birleşimi + `Row`/`Dataset` oluşturma |
| Toplam yükleme | Yukarıdaki üçünün başlangıç-bitiş üzerinden toplamı |
| Tabloya satır ekleme | Yalnızca o an gösterilen sayfanın Treeview `insert` döngüsü — ekranın tüm çizim/repaint süreci **değildir** |
| Arama | Ön işlem tablosu kurulumu + tüm hücre taraması |
| Sıralama | Tüm Merge Sort süresi |
| Base64 çözümleme | Prefix/postfix doğrulama + birleştirme + çözümleme |

- Arama, sıralama ve Base64 çözümleme worker içinde çalıştırıldığında, bu sürelerin ölçümü **yalnızca ilgili fonksiyonun çalışması etrafında** yapılır; işlemin kuyrukta bekleme süresi ölçüme dahil edilmez.
- Ölçüm sonuçları alt durum satırında "işlem adı + süre (ms) + ilgili kayıt sayısı" biçiminde gösterilir (kesinleşmiş biçim, bkz. bölüm 14 örneği).

## 10. Eşzamanlılık (Worker + Queue)

- Yükleme, ve uzun sürebilecek arama/sıralama işlemleri worker thread + queue + Tkinter `after()` düzeninde çalışır.
- Aynı anda yalnızca **tek bir uzun işlem** yürütülür; bir işlem sürerken çakışabilecek diğer eylemler arayüzde devre dışı bırakılır.
- Tkinter bileşenleri yalnızca **ana iş parçacığında** güncellenir; worker thread hiçbir zaman doğrudan widget'a dokunmaz.
- Thread kullanımı yalnızca arayüzün donmasını engeller; Python'ın GIL'i nedeniyle CPU'ya bağlı işlemleri (sıralama, arama gibi) **hızlandırmaz**.

## 11. Satır ve Sayfa Yönetimi

- Sayfa boyutu başlangıçta **500 kayıt** olarak belirlenmiştir; bu değer gerçek veri ve performans ölçümleriyle ilerleyen aşamalarda değiştirilebilir.
- "Satıra git", `view_order` içindeki **1 tabanlı konumu** ifade eder. Hedef konum farklı bir sayfadaysa, önce ilgili sayfa gösterilir, ardından hedef satıra kaydırma/seçim uygulanır — sayfalar arasında kesintisiz çalışır.
- `row_id` her zaman kaynak dosyanın fiziksel satır numarasından bağımsızdır; kayıt kimliği ile fiziksel satır numarası birbirine karıştırılmaz.

## 12. Aşamalı Doğrulama

- Test ve temel hata yönetimi, ilgili özellik geliştirilirken **birlikte** ele alınmıştır: her parser (`test_common.py`, `test_load.py`, `test_csv_parser.py`, `test_yaml_parser.py`, `test_xml_parser.py`), her algoritma (`test_search.py`, `test_sorting.py`, `test_disk_search.py`, `test_disk_sorting.py`), decoder (`test_decoder.py`), büyük JSON aktarım altyapısı (`test_streaming_pilot.py`, `test_import_job.py`), büyük CSV aktarım altyapısı (`test_csv_streaming.py` — BOM/Türkçe karakter, tırnak içi virgül/çift tırnak, çok satırlı hücre+CRLF, boş/tekrarlanan başlık, eksik/fazla alan, geçersiz UTF-8, alan boyutu sınırı, önizleme kayıt/bayt sınırı, iptal/yazma hatası sonrası tutarlılık, `csv.field_size_limit`'in HER çıkış yolunda -- başarı/iptal/başlık hatası/csv.Error/UnicodeDecodeError/yazma hatası/beklenmeyen exception -- geri yüklendiğinin doğrulanması dahil), büyük XML aktarım altyapısı (`test_xml_streaming.py` — path/namespace eşleştirme, karma içerik reddi, derinlik/boyut sınırı, önizleme kayıt/bayt sınırı, iptal/yazma hatası sonrası tutarlılık, eski manifestlerin geriye uyumluluğu), büyük YAML aktarım altyapısı (`test_yaml_streaming.py` — kök sequence/mapping-ad/mapping-sıra seçicileri, alias/anchor/çok-belge/özel-tür reddi, gerçekçi ölçekte bütçe-kırpma güvenliği testi dahil) ve GUI'nin disk modu bağlantıları (`test_gui_disk_mode.py`, `test_csv_streaming.py::TestGuiCsvDiskMode`, `test_yaml_streaming.py::TestGuiYamlDiskMode`) kendi testleriyle birlikte eklenmiştir. Tam paket 356 test içerir.
- Bunlara ek olarak, MVP finalizasyon turunda 5500 kayıtlık sentetik bir büyük-JSON demo dosyası (`samples/buyuk_ornek.json`) üzerinden uçtan uca (tam aktarım → depo açma → sayfalama → satıra gitme → arama → sıralama → kaynağa dönme → Base64) programatik bir doğrulama yapılmıştır; büyük CSV tarafı da benzer bir sentetik uçtan uca doğrulamadan geçmiştir.
- **Bu (dört format bütünleştirme) finalizasyon turunda ayrıca**: tam test paketi art arda İKİ KEZ çalıştırılmış, ikisinde de 356/356 test geçmiştir. Dört format için de (JSON/CSV/XML/YAML) 5600 kayıtlık sentetik kaynak dosyalar üretilip Tam Aktarımla işlenmiş; oluşan her depoda ilk/son sayfa, satıra git, disk araması (bulunan eşleşme + iptal), disk sıralaması (JSON/YAML'de sayısal alan üzerinden, CSV/XML'de metin alan üzerinde -- her ikisi de bağımsız hesaplanmış bir beklenen sırayla karşılaştırılarak), kaynak sırasına dönüş ve Base64 (prefix ve işaretçi modları formatlar arasında dağıtılarak) programatik olarak doğrulanmıştır; JSON kaynağı üzerinde ayrıca kasıtlı bir iptal senaryosuyla kısmi depo tutarlılığı ve yeniden açma doğrulanmıştır. **Bu doğrulamalar GUI/Tkinter tıklaması KULLANMADAN** yapılmıştır — `ImportJob`/`RecordReader`/`DiskSearchJob`/`DiskSortJob`/`decoder.base64_decoder` (GUI'nin de çağırdığı AYNI backend sınıflar) doğrudan Python'dan çağrılmıştır; hiçbir dialog fonksiyonu monkeypatch edilmemiştir (zira GUI hiç başlatılmamıştır). Ayrıca, erişilebilir gerçek ~121 GB'lık bir XML ve ~91 GB'lık bir YAML dosyası üzerinde YALNIZCA bütçeli (1000 kayıt/32 MiB) bir önizleme çalıştırılmış; kaynak dosyaların hiçbir şekilde değişmediği (çalışma öncesi/sonrası boyut+değişiklik-zamanı karşılaştırılarak) doğrulanmış, Tam Aktarım hiçbir zaman başlatılmamıştır. 60+ GB ölçeğinde (herhangi bir formatta) gerçek bir Tam Aktarımın uçtan uca doğrulanması bu turda da **yapılmamıştır** (bkz. bölüm 15 ve README "Bilinen sınırlamalar").

## 13. Kesinleşmiş Kararlar

- Ortak model (`Row`, `Dataset`, `format_value`) `models.py` içinde, proje-içi bağımlılığı olmayan bir modül olarak tutulur.
- JSON/YAML kök yapı kuralları (bölüm 6.1) ve XML v1 kayıt kuralları (bölüm 6.2) yukarıdaki gibi kesinleşmiştir.
- Kolon çakışma kontrolü veri kümesi geneli yapılır, sessiz birleştirme yoktur.
- `MISSING`/`None`/`""` ayrımı, liste-olarak-kalma, sayıya otomatik çevrilmeme kuralları kesinleşmiştir.
- `row_id` sabit, `view_order` ayrı, "satıra git" `view_order` üzerinden 1 tabanlı konum — kesinleşmiştir. Başlangıç sayfa boyutu 500.
- Arama = KMP (sorgu başına tek ön işlem), sıralama = stabil Merge Sort, tip-grup sırası Bool → Sayı → Metin → Karmaşık, MISSING/None/NaN her yönde sonda — kesinleşmiştir.
- Worker+queue düzeni yükleme, arama ve sıralama (hem bellek hem disk modu) için baştan beri geçerlidir; sonraya ertelenmiş bir basitleştirme değildir.
- Base64 sonucu bytes olarak tutulur, metne çevirme ayrı adımdır; prefix/postfix tam eşleşmeyle ayıklanır.
- Büyük veri aktarımı dört formatın (JSON/CSV/XML/YAML) DÖRDÜNDE de desteklenir; her formatın kendi akış modülü (`streaming_pilot/<format>_source.py`) ve kendi seçici kuralı vardır, ama hepsi AYNI JSONL+ikili-indeks+manifest disk deposu biçimini paylaşır (bkz. bölüm 7.3-7.6).
- Test/hata yönetimi her özellikle birlikte geliştirilmiştir (bkz. bölüm 12); kapsamlı entegrasyon doğrulaması, MVP finalizasyon turunda 5500 kayıtlık sentetik demo üzerinden, dört-format bütünleştirme turunda ise dört format için de 5600 kayıtlık sentetik depolar üzerinden uçtan uca yapılmıştır.
- CSV v1 kuralları (bölüm 6.5) kesinleşmiştir: sabit ayraç/tırnak, ilk boş olmayan kayıt başlık, tekrarlanan/boş başlık reddi, alan sayısı uyuşmazlığı reddi, hücrelerin metin olarak korunması, boş dosya/yalnızca-başlık dosyası ayrımı, CRLF korunması.
- `common.normalize()`'daki `known_columns` ve `common.read_text_file()`'daki `newline` parametreleri (ikisi de varsayılan `None`) kalıcı, geriye dönük uyumlu arayüz eklentileridir; JSON tarafında davranış değişikliği yoktur.

## 14. Çalışan İlk Sürümde Alınan Ek Kararlar

- YAML: `safe_load` sonrası tarih/bytes/set türleri ve metin olmayan sözlük anahtarları `ParseError` ile reddedilir; döngüsel (kendine referans veren) alias yapıları özyinelemeli bir "yığın" (stack) takibiyle tespit edilip reddedilir.
- Arama: ilk sürüm **büyük/küçük harfe duyarlıdır** (case-sensitive); bu, arayüzde "Ara (Aa duyarlı)" etiketiyle belirtilir. Sonraki/önceki eşleşme, o an geçerli `view_order` sırasını izler.
- Sıralama: sayısal görünümlü metinler (ör. `"00123"`) bu sürümde **metin olarak** sıralanır; ham veriyi bozmayan bir sayısal karşılaştırma anahtarı (int/Decimal gibi) eklenmemiştir.
- Base64: prefix/postfix'in birleşik metne mi yoksa her parçaya mı uygulanacağı, GUI'deki Base64 diyaloğunda kullanıcının seçtiği bir seçenektir (`apply_to`); kod bunu varsaymaz. Ayrıca (dört-format bütünleştirme turunda eklenen) `prefix_mode` ("starts_with"/"marker") de `apply_to`'dan tamamen bağımsız, kullanıcının seçtiği ikinci bir eksendir; metin-içi işaretçi (marker) modu, prefix'in her zaman metnin en başında olmadığı durumlar için eklenmiştir.
- Büyük XML: seçici basit bir "kökten path" (namespace-toleranslı, yerel-ad eşleştirmeli) olarak sınırlandırılmıştır; wildcard/XPath bilinçli olarak kapsam dışıdır (bkz. bölüm 7.5).
- Büyük YAML: seçici JSON ile birebir aynıdır; alias/anchor, çok belgeli yapı ve standart-dışı türler bilinçli olarak desteklenmez (bkz. bölüm 7.6). YAML'ın tırnaksız skalerlerinin bir önizleme bütçesi tarafından sessizce kırpılabilmesi riski, kaydın tamamı tüketildikten hemen sonra bir "geçiş" kontrolüyle ele alınmıştır; bu, yalnızca bütçenin alttaki okuyucunun tek okuma boyutundan (tipik ~16 KB) küçük olduğu gerçekçi olmayan durumlarda eksik kalabilir.
- Worker/queue yardımcı mekanizması `gui/main_window.py` içinde küçük, tek bir `_run_in_background`/`_poll_queue` çiftı olarak tutulmuştur; ayrı bir dosyaya çıkarılmamıştır (tek kullanım yeri olduğu için gerekli görülmemiştir).
- Performans ölçümleri, alt durum satırında işlem adı + süre (ms) + ilgili kayıt sayısı biçiminde gösterilir (ör. "Sıralama (id, Azalan): 0.03 ms (3 kayıt)").
- Yükleme sırasındaki dosya okuma/ayrıştırma/normalizasyon adımlarının ayrı ayrı ölçülebilmesi için `gui/main_window.py` içinde `parsers.load()`'u sarmalayan küçük bir `_load_with_timings()` yardımcı fonksiyonu vardır; bu, `parsers.load()`'un test edilmiş, tek-`Dataset`-döndüren arayüzünü değiştirmeden aynı üç adımı ayrı ayrı zamanlar.

## 15. MVP Sınırlamaları (Kapsam Dışı Bırakılanlar)

Bu bölüm, DataInspector'ın MVP finalizasyon turu itibarıyla **kesinleşmiş, bilinçli kapsam dışı bırakma** listesidir; hiçbiri "sonraki STEP'te değerlendirilecek" bir taslak değildir. README.md'deki "Bilinen sınırlamalar" bölümüyle tutarlıdır.

- **Büyük dosya (akışla diske aktarım) modu artık dört formatın (JSON/CSV/XML/YAML) DÖRDÜNDE de uygulanmıştır** — bu, önceki bir MVP turunda yalnızca JSON/CSV için geçerliydi; bu kısıtlama bu finalizasyon turunda kaldırılmıştır.
- **60+ GB ölçeğindeki gerçek dosyalarla (herhangi bir formatta) TAM bir Tam Aktarımın uçtan uca doğrulanması bu proje boyunca hiç yapılmamıştır.** Bu turda erişilebilir ~121 GB'lık gerçek bir XML ve ~91 GB'lık gerçek bir YAML dosyası üzerinde YALNIZCA bütçeli bir önizleme çalıştırılmış (kaynak dosyalar değiştirilmemiştir, bkz. bölüm 12); ~64 GB'lık gerçek CSV ve ~67 GB'lık gerçek JSON dosyaları için bu turda hiçbir erişim denenmemiştir. Dört format da yalnızca sentetik dosyalarla (5500-5600 kayıt) uçtan uca ve (önceki turlarda) daha küçük gerçek dosyalarla test edilmiştir.
- **Tam XML ve tam YAML çıktılarının ikisinin birden aynı diske aynı anda sığacağı varsayılmamalıdır.** Bütçeli önizlemeden yapılan kaba bir doğrusal ekstrapolasyona göre tam XML deposu ~110 GB, tam YAML deposu ~91 GB civarında olabilir (gerçek yapı önizlenen kısımdan farklıysa sapabilir); kullanıcıya iletilen gerçek-dosya test planında bu ikisinin AYNI ANDA değil, sırayla ve aradaki boş disk alanı kontrol edilerek çalıştırılması önerilmiştir.
- **Kesintiye uğrayan (iptal edilen ya da hataya uğrayan) bir Tam Aktarım kaldığı bayttan devam etmez**; yeniden başlatma her zaman kaynağın başından yeni bir depoya aktarım yapar (bkz. bölüm 7.3). Kesintiye kadar tamamlanan kısmi depo kullanılabilir kalır.
- **Base64 kolon/prefix/postfix ayarları verinin gerçek yapısına göre kullanıcı tarafından girilir**; uygulama bunları tahmin etmez ya da gerçek kolon adlarını varsaymaz.
- **Disk modunda sıralamanın gerçek, harici bir veri kaynağıyla son elle (manuel) kontrolü bu MVP turunda yapılmamıştır**; yalnızca sentetik verilerle ve programatik uçtan uca kontrollerle doğrulanmıştır.
- 100.000+ satırlık gerçek-veri benchmark senaryoları bellek modunda ayrıntılı ölçülmemiştir; sayfalama (500 kayıt) donmayı önlemek için yeterli kabul edilmiştir.
- Arama yalnızca büyük/küçük harfe duyarlı çalışır; büyük/küçük harf duyarsız seçenek eklenmemiştir.
- Bellek modunda sıralamada sayısal metin yorumlaması (int/Decimal tabanlı anahtar) eklenmemiştir; sayısal görünümlü metinler metin olarak sıralanır (disk modunda Decimal desteği vardır, bkz. bölüm 7.2).
- Görsel ince ayarlar, tema sistemi ve otomatik veri biçimi tahmini yapılmamıştır.
- XML karma içerik ve v1 kapsamı dışındaki daha karmaşık XML yapıları desteklenmez.
- Base64 diyaloğunda kolon seçimi/sırası basit bir virgülle-ayrılmış metin alanıyla yapılır; sürükle-bırak veya çoklu-seçim listesi gibi daha zengin bir arayüz eklenmemiştir.
