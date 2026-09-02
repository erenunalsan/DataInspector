# DataInspector — Mimari Doküman

Bu doküman, DataInspector projesinin STEP 1 (Mimari) aşamasında alınan kararları kayıt altına alır. Aşağıda anlatılan modüllerin **hiçbiri henüz uygulanmamıştır**; bu belge bir tasarım/sözleşme dokümanıdır, geliştirme ilerledikçe güncellenecektir.

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
    csv_parser.py
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
| `raw` | Kolon adı → ham değer eşlemi. Değer şunlardan biri olabilir: `MISSING` (bu kayıtta alan hiç yok), `None` (kaynakta açık null), boş metin `""`, metin, sayı, mantıksal (bool), veya liste. İç içe nesneler düzleştirme sırasında çözülür; ham değer olarak sözlük (dict) kalmaz. |

**Dataset** — bir dosyadan yüklenen tüm veriyi temsil eder:

| Alan | Açıklama |
|---|---|
| `columns` | Veri kümesindeki tüm kayıtların alan yollarının birleşimi (union); yükleme anında hesaplanır. |
| `rows` | Kayıtların listesi, **orijinal yükleme sırasıyla**. Bu sıra hiçbir sıralama/arama işleminden etkilenmez; yalnızca yükleme sırasında oluşur. |

**format_value(değer) → metin** — ham bir değeri, gösterim ve arama sırasında ortak kullanılacak metne çevirir:

- `MISSING` veya `None` → boş metin (`""`)
- liste → köşeli parantez içinde, elemanlar virgülle ayrılmış, her eleman yine `format_value` ile metne çevrilir (örn. `[a, b, c]`); boş liste `[]` olarak gösterilir
- diğer değerler → doğrudan metin karşılığı

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
- Listeler ham veride liste olarak kalır; gösterimde köşeli parantez ve eleman sınırları korunur; boş liste `[]` olarak gösterilir.
- YAML ayrıştırmasında `yaml.safe_load` kullanılır. Tarih, bytes, set gibi YAML'a özgü ek türlerin destek politikası (metne mi çevrilecek, nasıl ele alınacak) bu doküman kapsamında kesinleştirilmemiştir; STEP 2'de ayrıntılı biçimde tanımlanıp test edilecektir.

## 7. Algoritmalar

### 7.1 Arama (KMP)

- Arama, o an yüklü veri kümesindeki **tüm kayıtlarda ve tüm kolonlarda** çalışacak şekilde tasarlanmıştır.
- Sorgu metni için ön işlem (prefix/failure) tablosu, bir arama işlemi başına **yalnızca bir kez** hazırlanır; taranan her hücre için yeniden hesaplanmaz.
- Eşleştirme, her hücrenin `format_value` ile üretilen metni üzerinde yapılır.
- Sonraki/önceki eşleşmeye geçiş, o an geçerli olan `view_order` sırasını izler.

### 7.2 Sıralama (Merge Sort)

- Sıralama için `sorted()`/`list.sort()` değil, projeye özel **stabil** bir Merge Sort implementasyonu kullanılır.
- Sıralama yalnızca `view_order` listesini günceller; `Dataset.rows` hiçbir zaman yeniden sıralanmaz.
- Karşılaştırma tip gruplarına göre yapılır, gruplar arası öncelik sırası: **Bool → Sayı → Metin → Karmaşık (liste)**. Artan/azalan yön yalnızca **aynı grup içindeki** karşılaştırmaya uygulanır; gruplar arası öncelik yönden etkilenmez.
- `MISSING`, `None` ve `NaN`, sıralama yönünden bağımsız olarak **her zaman sonda** yer alır; bu üç durum kendi aralarında, sıralamaya girdikleri mevcut görünümdeki göreli sırasını korur.
- İki yönde de eşit değerli kayıtlar, sıralamaya girdikleri mevcut görünümdeki göreli sırasını korur (stabilite).
- Metinler varsayılan olarak metin (ordinal) biçiminde karşılaştırılır. Bir metin kolonunun sayısal olarak yorumlanması gerektiğinde ham veri **değiştirilmez**; bunun yerine sıralama sırasında geçici bir karşılaştırma anahtarı üretilir. Tüm değerleri float'a zorlamak yerine hassasiyeti koruyan seçenekler (int, Decimal gibi) STEP 6'da değerlendirilecektir.

## 8. Decoder Yaklaşımı (Base64)

- Veri `PREFIX + BASE64 + POSTFIX` biçiminde, tek kolonda veya birden fazla kolona bölünmüş olarak bulunabilir. Decoder belirli kolon adlarına veya sabit bir parça sırasına bağımlı olmayacak biçimde tasarlanır; hangi kolonların hangi sırayla kullanılacağı ve prefix/postfix değerleri kullanıcı tarafından çalışma zamanında belirlenir.
- Prefix/postfix ayıklaması **tam eşleşme kontrolüyle** yapılır (metnin belirtilen prefix ile başladığı / postfix ile bittiği doğrulanarak). `str.strip()`, `lstrip()`, `rstrip()` bu amaçla **kullanılmaz** — bu fonksiyonlar literal bir alt diziyi değil, verilen karakter kümesindeki herhangi bir karakteri siler.
- Prefix/postfix'in **birleştirilmiş tek metne mi yoksa her parçaya ayrı ayrı mı** uygulanacağı, gerçek veri kuralları netleşene kadar kesinleştirilmez.
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
- Ölçüm sonuçlarının kullanıcıya sunum biçimi (yer, format) STEP 8'de ayrıntılandırılacaktır; bu doküman yalnızca neyin, nerede ve hangi sınırlarla ölçüleceğini tanımlar.

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

- Test ve temel hata yönetimi, ilgili özellik geliştirilirken **birlikte** ele alınır: parser testleri STEP 2'de, arama testleri STEP 5'te, sıralama testleri STEP 6'da, decoder testleri STEP 7'de.
- STEP 10, tüm bileşenlerin bir arada çalıştığı kapsamlı entegrasyon testleri ve 100.000 satırlık senaryo gibi performans doğrulamaları için ayrılmıştır; testlerin başladığı aşama değildir.

## 13. Kesinleşmiş Kararlar

- Ortak model (`Row`, `Dataset`, `format_value`) `models.py` içinde, proje-içi bağımlılığı olmayan bir modül olarak tutulur.
- JSON/YAML kök yapı kuralları (bölüm 6.1) ve XML v1 kayıt kuralları (bölüm 6.2) yukarıdaki gibi kesinleşmiştir.
- Kolon çakışma kontrolü veri kümesi geneli yapılır, sessiz birleştirme yoktur.
- `MISSING`/`None`/`""` ayrımı, liste-olarak-kalma, sayıya otomatik çevrilmeme kuralları kesinleşmiştir.
- `row_id` sabit, `view_order` ayrı, "satıra git" `view_order` üzerinden 1 tabanlı konum — kesinleşmiştir. Başlangıç sayfa boyutu 500.
- Arama = KMP (sorgu başına tek ön işlem), sıralama = stabil Merge Sort, tip-grup sırası Bool → Sayı → Metin → Karmaşık, MISSING/None/NaN her yönde sonda — kesinleşmiştir.
- Worker+queue düzeni yükleme, arama ve sıralama için STEP 1'den itibaren geçerlidir (STEP 11'e ertelenmemiştir).
- Base64 sonucu bytes olarak tutulur, metne çevirme ayrı adımdır; prefix/postfix tam eşleşmeyle ayıklanır.
- Test/hata yönetimi her özellikle birlikte geliştirilir; STEP 10 yalnızca kapsamlı entegrasyon/performans doğrulaması içindir.

## 14. Geliştirme Aşamasında Netleşecek Ayrıntılar

- Prefix/postfix'in parçalara mı birleşik metne mi uygulanacağı ve ayıklama/birleştirme sırası (STEP 7 — gerçek veri kuralları geldiğinde).
- YAML'a özgü ek türlerin (tarih, bytes, set) destek politikası (STEP 2).
- Sayısal metin yorumlaması için hassasiyeti koruyan karşılaştırma anahtarı seçenekleri: int/Decimal gibi (STEP 6).
- Arama işleminde büyük/küçük harf duyarlılığının varsayılan davranışı (STEP 5).
- Worker/queue yardımcı kodunun ayrı bir dosyada mı (`gui/worker.py`) yoksa `main_window.py` içinde mi tutulacağı (STEP 3, implementasyon detayı).
- Performans ölçüm sonuçlarının kullanıcıya sunum biçimi — yer, format (STEP 8).
- XML karma içerik ve v1 kapsamı dışındaki daha karmaşık XML yapılarının ileride nasıl ele alınacağı (kapsam dışı, ileriye dönük not).
