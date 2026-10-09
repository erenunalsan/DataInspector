# livedata — büyük veri görüntüleyici (CSV · JSON · XML · YAML)

Yüz milyonlarca kayıtlık dosyaları **kaynağından, yerinde** inceleyen tek bir
masaüstü ekranı. Dört biçim de aynı pencerede, aynı motorla, aynı hızda
açılır; gezinme, satıra gitme ve arama biçimden bağımsızdır.

`livedata/` paketi ve `veri_goruntuleyici.py` giriş noktası, projedeki eski
yollardan (`parsers/`, `streaming_pilot/`, `gui/`) tamamen bağımsızdır.

## Üç kural

1. **Diske hiçbir şey yazılmaz.** Ara dosya, dönüştürülmüş kopya, indeks
   dosyası ya da önbellek klasörü oluşturulmaz. Kaynak dosya salt okunur
   açılır. Durum satırında bu sürekli görünür: *"Diske yazılan: 0 bayt"*.
   (İstisna: kullanıcının AÇIKÇA istediği çıktılar -- Excel/Word/PDF'e
   aktarma, panoya kopyalama, son kullanılan dosyalar listesi. Bunlar veri
   ÜRETMEZ/önbelleklemez; yalnızca zaten okunmuş kayıtları kullanıcının
   belirttiği bir hedefe yazar.)
2. **Dosya belleğe alınmaz.** RAM kullanımı dosya boyutundan bağımsız bir
   tavanla sınırlıdır; 112 GB'lık bir dosya da 600 MB'lık bir dosya da aynı
   belleği kullanır.
3. **Arayüz kilitlenmez.** Uzun süren her iş (indeks taraması, kayıt okuma,
   arama) ayrı bir thread'de çalışır; sonuçlar bir kuyruk üzerinden ana
   thread'e aktarılır.

## Çalıştırma

> **Giriş noktası `veri_goruntuleyici.py`'dir.** Depoda duran `main.py`
> (eski DataInspector ekranı: `gui/`, `parsers/`, `streaming_pilot/`,
> `algorithms/`, `decoder/`) **artık kullanılmamaktadır** ve bakımı
> yapılmamaktadır; tarihsel olarak korunmaktadır.

En kolayı: proje klasöründeki **`veri_goruntuleyici.bat`** dosyasına çift
tıklayın. (Bir veri dosyasını bu .bat üzerine sürükleyip bırakırsanız o dosya
açılışta hemen yüklenir.)

```powershell
python veri_goruntuleyici.py                                # boş açılır
python veri_goruntuleyici.py "D:\ders_eren\eren_json.json"  # açar ve yükler
python veri_goruntuleyici.py "D:\ders_eren\eren_xml.xml" --bekle
```

Desteklenen uzantılar: `.csv` `.tsv` `.txt` `.json` `.jsonl` `.ndjson`
`.xml` `.yaml` `.yml`. (`csv_viewer.py` eski adıyla da çalışmayı sürdürür.)

Gerekli paketler: `pip install -r requirements.txt` (`PyYAML`, görünüm için
`sv-ttk`, dışa aktarım/ikon üretimi için `pillow`; web arayüzü ayrıca
`django`/`waitress` gerektirir -- bkz. `LIVEDATA_WEB.md`).

### Python kurulu olmayan birine dağıtmak (tek dosya .exe)

**`tools/exe_paketle.bat`**'a çift tıklayın (ya da elle:
`pyinstaller --onefile --windowed --icon livedata/ui/assets/icon.ico
--collect-data sv_ttk veri_goruntuleyici.py`). Sonuç:
`dist/LiveDataGoruntuleyici.exe` -- tek bir dosya, ~12 MB, Python kurulumu
GEREKTİRMEZ; herhangi bir Windows bilgisayara kopyalayıp çift tıklamak
yeterlidir. Yalnızca masaüstü ekranını paketler; web arayüzü ayrı bir
Python/Django kurulumu gerektirmeye devam eder.

## Temel fikir: bir kayıt = bir satır

Bu ekranın bütün hızı tek bir özellikten gelir:

> Gerçekten büyük veri dosyaları neredeyse her zaman **satır satır** yazılır.

Bu doğruyken N. kaydın bayt konumunu bulmak, N. `\n` baytını bulmakla aynı
şeydir — ve bu, `bytes.count`/`bytes.find` ile **3,7 GiB/sn** hızında yapılır
(yani her zaman diskten hızlı; darboğaz asla CPU değildir). Böylece indeks,
rastgele erişim ve arama **dört biçimde de aynı koddur**. Biçimler arasındaki
fark yalnızca üç şeydir:

| | Kayıtlar nerede başlar | Nerede biter | Bir satır nasıl çözülür |
|---|---|---|---|
| **CSV** | başlık varsa 2. satır | dosya sonu | ayraçla böl (tırnaklıysa `csv` modülü) |
| **JSON** | `…"rows":[` satırından sonra | `]}` kuyruğundan önce | satır sonu virgülünü at, `json.loads` |
| **XML** | `<?xml…?>` + sarmalayıcıdan sonra | `</rows>` kuyruğundan önce | `ET.fromstring`, çocuk elementlerin metni |
| **YAML** | `rows:` satırından sonra | dosya sonu | `- ` önekini at, `json.loads` (olmazsa `yaml.safe_load`) |

Başlık ve kuyruk satırları **kayıt sayılmaz**: `veri_basi`/`veri_sonu` sınırı
hem indeks taramasında hem aramada geçerlidir, bu yüzden `</rows>` gibi bir
kuyruk metni aramada eşleşmez ve satır numaralarını kaydırmaz.

Bu sınırların bulunuşu biçimden bağımsızdır: dosyanın başında **kayıt olarak
çözümlenen ilk satır** veri başı, sonunda çözümlenen **son satır** veri
sonudur. Başlık/kuyruk satırları kendiliğinden elenir.

### Satır satır yazılmamış dosyalar

Girintili ("pretty") basılmış bir JSON ya da kayıtları birden çok satıra
yayılmış bir XML bu ekranda **sessizce yanlış sonuç vermez**: tespit
aşamasında satırların kayıt olarak çözümlenemediği görülür ve açıklayıcı bir
hata verilir. Doğru satır numarası veremeyecekse hiç açmamak, yanlış numara
göstermekten iyidir.

## Ekran

Ekran, Office uygulamalarındaki **şerit (ribbon)** düzenini izler: üstte her
zaman görünen ince bir hızlı erişim çubuğu, altında sekmeli bir araç şeridi.
Her an yalnızca SEÇİLİ sekmenin düğmeleri görünür; geri kalan dikey alan
tabloya kalır.

```
┌────────────────────────────────────────────────────────────────────────┐
│ [📁 Dosya Seç…] <yol>                    [▶ Aç] [✕ Kapat]  CSV · ',' … │  ← hızlı erişim
├─Dosya─┬─Ana Sayfa─┬─Arama─┬─Sıralama─┬─Seçim──────────────────────────┤  ← şerit sekmeleri
│ [◀][▶] Sayfa 3/2.388 (satır 200.000–…) │ [____][Git] ☐1'den başlat │ … │
│         Sayfa                          │      Satıra git           │   │  ← grup adları
├────────────────────────────────────────────────────────────────────────┤
│ ☑ │  Satır # │  kolon 1  │  kolon 2  │ …   (sanal — yalnızca görünen) │
├────────────────────────────────────────────────────────────────────────┤
│ [Konsol | Arama sonuçları]                                             │
├────────────────────────────────────────────────────────────────────────┤
│ İndeks taraması [░░░░░░░░░░] — (istek üzerine)                         │
│ Arama           [███░░░░░░░] %31 · 17 eşleşme · 780 MB/sn              │
│ Durum: hazır (indeks yok — gerekince oluşturulur) | Diske yazılan: 0 B │
└────────────────────────────────────────────────────────────────────────┘
```

Sekmelerin içeriği:

| Sekme | İçerik | Kısayol |
|---|---|---|
| **Dosya** | CSV biçim seçenekleri: Ayraç, Kodlama, İlk satır başlık, Tırnak | `Ctrl+1` |
| **Ana Sayfa** | Sayfa geçişi, sayfa bilgisi, satıra git, 1'den başlat, Base64 Çöz, Tam indeksle, Kolonlar… (göster/gizle) | `Ctrl+2` |
| **Arama** | Aranan metin, harfe duyarlılık, Regex (düzenli ifade), Ara/Durdur, eşleşmeler arası gezinme | `Ctrl+3` |
| **Sıralama** | Kolon/Yön/Tür, Kapsam, En iyi N, Sırala/Durdur, Kaynak sırasına dön | `Ctrl+4` |
| **Seçim** | Sayfayı Seç, Seçimi Temizle, seçim sayacı, Seçilenleri Göster… | `Ctrl+5` |

Dosya açma (yol kutusu + **Aç** / **Kapat**) sekmelerden bağımsız olarak
hızlı erişim çubuğunda durur — hangi sekmede olunursa olunsun elin altındadır.
Şerit bağlama duyarlıdır: dosya açılınca **Ana Sayfa**, kapanınca **Dosya**
sekmesine geçilir.

"Dosya" sekmesindeki seçenekler (ayraç, başlık satırı, tırnak duyarlılığı)
yalnızca CSV'de anlamlıdır ve dosya AÇILMADAN ÖNCE ayarlanmalıdır; diğer
biçimlerde kayıt sınırı ve alan ayrımı biçimin kendi dilbilgisinden gelir.

**Klavye / fare:** ↑ ↓, PageUp/PageDown, Home/End ve fare tekeri. Bir sayfanın
sonunu aşacak şekilde kaydırırsanız kendiliğinden sonraki sayfaya geçilir. Bir
satıra çift tıklamak, o kaydın bütün alanlarını ayrı bir pencerede gösterir.

**Base64 Çöz:** bir kayıt seçip **Base64 Çöz** düğmesine basın (ya da çift
tıkla açılan ayrıntı penceresinden). Ayrıntılar için aşağıya bakın.

**Görünüm (açık/koyu tema):** hızlı erişim çubuğundaki **🌙 Koyu Tema /
☀ Açık Tema** düğmesi, [sv-ttk](https://github.com/rdbende/Sun-Valley-ttk-theme)
ile tüm arayüzü Windows 11 (Fluent) görünümüne çevirir. Açılışta Windows'un
sistem temasını (Kişiselleştirme → Renkler → Koyu) otomatik algılar. Bu
projenin kendi renkleri (tablo satır vurguları, konsol seviye renkleri,
birkaç durum etiketi) de `livedata/ui/renkler.py` üzerinden temaya göre
ayarlanır -- aksi hâlde ör. koyu temada açık pastel bir tablo satırı ya da
okunmaz koyu lacivert bir etiket kalırdı. Pencere ikonu `tools/ikon_uret.py`
ile üretilmiştir (yeniden üretmek için: `python tools/ikon_uret.py`).

## Nasıl çalışıyor?

### 1. İndeks İSTEĞE BAĞLIDIR

Dosyayı açmak indeks gerektirmez: biçim tespiti ~20 ms sürer ve ilk sayfa
hemen gelir. İndeks yalnızca **iki şey** için gereklidir:

1. Uzak bir kayda atlamak (ör. "kayıt 200.000.000'a git")
2. KESİN toplam kayıt sayısı

Bunların dışında her şey indekssiz çalışır — gezinme, ilk sayfalar ve
**arama** (arama zaten baştan sona okurken kayıtları kendi sayar). Bu yüzden
açılışta **hiçbir bayt taranmaz**.

Uzak bir kayıt istendiğinde indeks **yalnızca o kayda kadar** ilerletilir ve
orada durur. Ölçüm (59,4 GiB'lık CSV):

| İşlem | Okunan | Süre |
|---|---|---|
| Dosyayı açma | 0 bayt | 19 ms |
| İlk 40 kaydı gösterme | ~8 KB | 0,2 ms |
| Tüm dosyada arama | 59,4 GiB (indeks 0 bayt) | akışlı |
| Kayıt 3.000.000'a gitme | 856 MB (**%1,4**) | 842 ms |
| Kayıt 100.000'e gitme | 32 MB | 54 ms |

Dosyanın tamamını indekslemek isterseniz **Tam indeksle** düğmesi var; bitince
her kayda anında (0,41 ms) gidilir ve kesin sayı belirlenir.

N. kaydın yerini bilmenin kestirme yolu **yoktur**: kayıt uzunlukları
değişkendir, dolayısıyla bilinen bir noktadan N tane kayıt sınırı saymak
gerekir. Seçebileceğimiz tek şey *ne kadarını* sayacağımızdır — bu ekran da
gerektiği kadarını sayar.

### 2. Seyrek indeks — "N. kayıt hangi baytta?"

Her kaydın konumunu tutmak 205 milyon kayıt × 8 bayt = **1,6 GB** RAM demek
olurdu. Bunun yerine her **1.000 kayıtta bir** bayt konumu tutulur:

```
205.060.846 kayıt / 1.000 = 205.061 çıpa × 8 bayt ≈ 1,6 MB RAM
```

Bir kayda gitmek için en yakın önceki çıpaya `seek` edilir ve oradan en fazla
999 kayıt ileri okunur. Ölçülen rastgele erişim: **0,41 ms**.

Tarama açılışı **bekletmez**: dosya anında açılır, kullanıcı baştan gezinmeye
başlar, tarama arka planda ilerler. Ulaşılmamış bir kayıt istenirse istek
**sıraya alınır** ve tarama oraya varınca kendiliğinden gidilir.

### 3. Bedava bütünlük denetimi

JSON/XML/YAML dosyaları başlıklarında çoğu zaman bir kayıt sayısı bildirir
(`"count":238758543`, `count="293180461"`, `count: 214088734`). Tarama bitince
bu değer **gerçekten sayılan** kayıt sayısıyla karşılaştırılır ve konsola
yazılır. Tutmaması, dosyanın eksik olduğunu ya da bazı kayıtların birden çok
satıra yayıldığını gösterir — hiçbir ek maliyeti olmayan bir denetim.

Gerçek ölçüm: `eren_json.json` tam tarandığında **238.758.543** kayıt sayıldı;
dosyanın başlığındaki `"count":238758543` değeriyle **birebir** tuttu.

### 4. Tembel yükleme — "yalnızca görünen kayıtlar"

Tablo **sanaldır**: `ttk.Treeview` içinde yalnızca ekranda görünen kadar öğe
tutulur ve kaydırmada bu öğelerin *değerleri* güncellenir. Kaydırma maliyeti
sayfa 100.000 kayıt da olsa 400 milyon da olsa sabittir.

Veri 250 kayıtlık **pencereler** hâlinde arka planda getirilir; görünenler
yüksek öncelikli, komşular ön yükleme önceliklidir. Gelmemiş satırlar `…` yer
tutucusuyla gösterilir. Önbellek **96 pencere = 24.000 kayıt** ile tavanlıdır
(LRU).

### 5. Base64 çözme

Bir kaydı seçip **Base64 Çöz**'e basmak, o kaydın alanlarındaki Base64 yükünü
çözer. İşlem tamamen BELLEKTEKİ kayıt değerleri üzerinde yapılır: kayıt zaten
ekranda olduğu için diske gidilmez ve sonuç anında gelir.

Base64 yükü çoğu zaman tek bir hücrede durmaz; bu yüzden pencere üç şeyi
birden çözer:

- **Çok kolona bölünmüş yükler**: parçalar seçilen SIRAYLA birleştirilir.
  Sıra ▲▼ ile değiştirilebilir, alanlar tek tıkla seçilip bırakılabilir.
- **Taşıyıcı önekler**: her parçanın başında bir damga olabilir (kaynak
  dosyalardaki `<kayıt>_<kolon>_½_` gibi). Üç kip vardır: önek yok, metnin
  başında birebir önek, ya da **işaretçiden sonrası** — işaretçi metnin
  başında olmak zorunda değildir, metin içinde aranır.
- **Sonekler** ve URL-güvenli alfabe (`-` `_`).

**Otomatik öneri:** pencere açılır açılmaz kayıt incelenir ve makul bir ayar
önerilip uygulanır. Öneri, her parçanın en uzun Base64-karakterli sonekini
bulur, geri kalan önekleri karşılaştırır ve bunların ORTAK SONEKİNİ işaretçi
olarak alır — kaynak dosyalarda bu `_½_` çıkar. Tek bir karakter (ör. `_`)
işaretçi seçilseydi metinde birden çok kez geçer ve yanlış yerden kesilirdi.

Öneri **ihtiyatlıdır**: bir aday ancak çözülüp geçerli **UTF-8** metin verirse
sunulur. Rastgele bir onaltılık dizgi de geçerli Base64'tür ve çöp bayta
çözülür; üstelik cp1254/latin-1 gibi tek baytlı kodlamalar HER bayt dizisini
"okunabilir" gösterir. UTF-8 ise kendi kendini doğrulayan bir kodlamadır, bu
yüzden ölçüt odur. Öneri çıkmazsa kullanıcı ayarı elle yapar — yanlış bir
öneri sunmaktansa hiç sunmamak yeğlenir.

Sonuç her zaman önce **bayt**'tır. Metne çevrilebiliyorsa metin olarak,
çevrilemiyorsa (PNG, ZIP, PDF gibi ikili yükler — imzasından türü de
tahmin edilir) onaltılık döküm olarak gösterilir.

Dört kaynak dosyanın **dördünde de** bu düzende gizli birer kayıt bulundu ve
ekrandan çözüldü:

| Dosya | Kayıt |
|---|---|
| `eren_csv.csv` | 16.481.845 |
| `eren_json.json` | 118.380.417 |
| `eren_xml.xml` | 154.569.950 |
| `eren_yaml.yaml` | 191.395.527 |

### 6. Sıralama — permütasyon gerektirmeyen üç kip

205 milyon kaydı sıralı gezmek, "sıralı konum P'de hangi kayıt var?" sorusunun
cevabını -- bir PERMÜTASYONU -- saklamayı gerektirir: kayıt başına 8 bayt,
toplam **1,53 GiB**. Rastgele bir permütasyon tanım gereği sıkıştırılamaz
(bilgi-kuramsal alt sınır ~672 MB). Bu ne RAM tavanına sığar ne de diske
yazılabilir. Bu yüzden ekranda **tam sıralı gezinme yoktur**; bunun yerine
permütasyon GEREKTİRMEYEN üç kip vardır:

| Kapsam | Ne yapar | Maliyet | RAM |
|---|---|---|---|
| **Bu sayfa** | Ekrandaki 100.000'lik sayfayı kendi içinde tam sıralar | sayfayı okur (~30 MB) | ~800 KB |
| **Tüm dosya (en iyi N)** | "X kolonuna göre en büyük/en küçük N kayıt" | tek geçiş | N ile sabit |
| **Arama sonuçları** | Bulunan kayıtları sıralar | kayıtları tek tek okur | sonuç sayısı kadar |

Üçünün de çıktısı aynıdır: **sıralı bir kayıt numarası listesi**. Tablo bunu
bir "görünüm" olarak kullanır; "Satır #" sütunu her zaman kaydın kaynak
dosyadaki gerçek numarasını gösterir.

**Sonuçlar nasıl gösteriliyor?** Top-K sonuçları dosyanın her yerine
dağılmıştır ve indeks oraya ulaşmamışsa okunamazlar -- tüm dosyayı indekslemek
ise sıralamanın kendisi kadar daha sürerdi. Gerek yok: tarama sırasında her
kaydın bayt konumu zaten biliniyor, kazananların konumları indekse ipucu
olarak bırakılıyor. Böylece **Top-K, indeks hiç taranmadan çalışır ve sonuçlar
anında görüntülenir.** Dağınık kayıt erişimi ölçüldü: 0,4 ms/kayıt, ekran
dolusu ~16 ms.

**Anahtar çıkarma — asıl darboğaz.** Sıralamanın maliyeti taramak değil, her
kayıttan anahtarı çıkarmaktır (ölçülen, 3. kolon):

| Biçim | Genel yol | Tüm dosya | Sınırlayan |
|---|---|---|---|
| CSV | 0,35 µs/kayıt | ~1,2 dk | disk |
| JSON | 1,44 µs/kayıt | ~5,7 dk | CPU |
| YAML | 1,74 µs/kayıt | ~6,2 dk | CPU |
| XML (genel) | 8,46 µs/kayıt | **41 dk** | CPU |
| **XML (bayt düzeyi)** | **0,50 µs/kayıt** | **~2,4 dk** | disk |

Bu yüzden XML'de, kaydı hiç çözümlemeden k. çocuk elementin metnini bulan
bayt düzeyinde bir çıkarıcı vardır (17 kat hızlı). XML'de element metni ham
`<` içeremediği için (`&lt;` olarak kaçırılır) bu güvenlidir; beklenmedik bir
yapı görülürse sessizce genel yola düşülür.

**Sıralama düzeni:** metin sıralaması KOD NOKTASI sırasındadır, Türkçe alfabe
sırası değildir ("z" < "ç"). Yerel-duyarlı harmanlama kayıt başına ek maliyet
getirir ve makineden makineye değişen sonuç üretir; öngörülebilirlik
yeğlenmiştir. Sayısal türde hem `1234.56` hem `1.234,56` yazımı okunur.
Değeri okunamayan kayıtlar sonuca ALINMAZ ve sayıları bildirilir.

### 7. Arama — indeksten bağımsız akış

Arama, indeks taraması daha başındayken bile dosyanın tamamında çalışır:
kendisi baştan sona okurken satırları da sayar, yani her eşleşmenin kayıt
numarasını kendi hesaplar. Eşleşme bulma `bytes.find`, sayım `bytes.count`
iledir; Python döngüsü yalnızca **eşleşme başına** çalışır. Bulunan eşleşme
indekse bir **ipucu** bırakır, böylece tarama oraya varmamış olsa bile
eşleşmeye anında gidilebilir. Arama sürerken indeks taraması duraklatılır
(ikisi de aynı diski kullanır).

**Türkçe harf desteği:** duyarsız aramada metin ASCII ise parçanın `lower()`
kopyası üzerinde aranır. ASCII dışı karakter varsa metnin yaygın yazılışları —
**Türkçe i↔İ ve ı↔I kuralları dâhil** — ayrı ayrı aranır.

### 8. Çoklu seçim — işaretle, ayrı pencerede gör, kopyala, webde göster

Tablodaki her satırın solunda bir işaret kutusu (☑/☐) vardır. Tıklamak (ya da
odaklı satırda Boşluk tuşu) o kaydı **kalıcı olarak** işaretler: seçim, kayıt
NUMARASINA bağlıdır ve kaydırma, sayfa değişimi, sıralama ya da arama arasında
korunur — tıpkı arama sonuçlarının ve Top-K sonuçlarının kayıt numaralarıyla
çalışması gibi. Sütun başlığındaki kutuya tıklamak, o an ekranda görünen
satırların tümünü tek seferde işaretler/kaldırır.

**"Sayfayı Seç"** düğmesi, ekrandaki sayfanın (ya da sıralı bir görünümdeyse
görünümün tamamının) **100.000 kayda kadar numarasını** seçime ekler --
hiçbir kaydın değerini OKUMADAN, bu yüzden anında ve bedavadır. Sayfanın
kullanıcının hiç görmediği bir kısmı henüz taranmamışsa (bkz. bölüm 1),
"Sayfayı Seç" o kısmı otomatik olarak arka planda taramaya başlatır ki
değerler daha sonra okunabilsin.

**"Seçilenleri Göster…"** işaretli kayıtları AYRI bir pencerede, kaynak
numaralarıyla listeler. Kayıtlar dosyanın her yerinden gelebileceği için
(dağınık erişim), aynı `VeriOturumu.kayitlar()` yolu kullanılır -- ölçülen
maliyet kayıt başına ~0,4 ms, dosya boyutundan bağımsızdır; bu pencere de
"yalnızca görünen satırları gerçekle" ilkesiyle (aynı `SanalTablo`) çalışır.
Pencerede:

- **Kolon seçimi**: hangi kolonların gösterileceği ayrı ayrı işaretlenebilir
  (en az biri açık kalmalıdır).
- **Kaldırma**: işaret kutusu burada "seçimden çıkar" anlamına gelir --
  tıklamak kaydı hem bu pencereden hem ana seçimden kaldırır (iki yönlü
  senkron: ana tablodaki kutucuk da güncellenir).
- **Panoya Kopyala (TSV)**: seçili kolonlarla, sekmeyle ayrılmış metin olarak
  panoya kopyalar (doğrudan bir tabloya yapıştırılabilir). Büyük seçimlerde
  (>20.000 kayıt) veriler arka planda 2000'lik parçalar hâlinde toplanır;
  arayüz bu sırada kilitlenmez.

**Tavan:** en fazla **200.000 kayıt** işaretlenebilir (Top-K'daki tavanla
aynı büyüklük mertebesi) -- sınırsız büyüyen bir seçim, "RAM tavanı dosya
boyutundan bağımsız olmalı" ilkesini kullanıcının kendi eylemiyle aşabilirdi.
Seçimin kendisi yalnızca kayıt NUMARALARINDAN oluşur (kayıt başına bir Python
`int`); değerler hiçbir zaman kalıcı olarak saklanmaz.

**Webde Göster**: "Seçilenleri Göster…" penceresindeki **Webde Göster**
düğmesi, o an listelenen (kolon filtresi uygulanmış) kayıtları arka planda
2000'lik parçalar hâlinde toplar (aynı kopyalama akışı) ve
`livedata.webserver.WebYayini` ile **localhost** üzerinde tek sayfalık bir
HTML tablosu olarak yayınlar -- sayfa tamamen bellekte üretilir, diske
hiçbir şey yazılmaz (`http.server.ThreadingHTTPServer`, daemon iş
parçacığında). Yayın başlayınca bir **popup** açılır; içinde adres
(`http://127.0.0.1:<port>/`) salt-okunur bir kutuda gösterilir ve yanında
**Kopyala** düğmesi bulunur. Adres yalnızca bu bilgisayardan erişilebilir;
"Seçili Veriler" penceresi kapatılınca (Kapat düğmesi veya pencere
çarpısı) sunucu otomatik durur.

**Excel / Word / PDF'e aktarma**: açılan web sayfasının sağ üst köşesinde
üç indirme düğmesi bulunur -- **Excel (.xlsx)**, **Word (.docx)**,
**PDF (.pdf)**. Tıklandığında `livedata.exporters` ilgili dosyayı, sayfa
için zaten toplanmış olan aynı bellekteki veriden ANINDA üretir (yeniden
tarama/toplama yapılmaz) ve tarayıcı bunu doğrudan kullanıcının kendi
bilgisayarına indirir -- sunucu hiçbir zaman kendisi diske yazmaz, dosya
yalnızca istek anında bellekte oluşup HTTP yanıtı olarak akar. Üç biçim de
**hiçbir üçüncü taraf kütüphane olmadan**, yalnızca standart kütüphaneyle
üretilir:

- **Excel/Word**: OOXML (zip + XML) biçimleri UTF-8 olduğundan Türkçe dahil
  her karakteri tam destekler.
- **PDF**: elle üretilmiş, çok sayfalı (gerekirse otomatik sayfalanan),
  başlık satırı her sayfada tekrarlanan bir tablo raporu. PDF'in temel 14
  fontu (Helvetica) yalnızca WinAnsiEncoding/cp1252 destekler; bu kod
  sayfasında ç/Ç, ö/Ö, ü/Ü vardır ama ğ/Ğ, ş/Ş, ı/İ yoktur -- bir font
  gömmeden bu sınır aşılamayacağından yalnızca bu altı harf en yakın ASCII
  karşılığına çevrilir (ğ→g, ş→s, ı→i ve büyük hâlleri), ç/ö/ü ise
  değiştirilmeden kalır -- örn. "Şükrü Öğretmen" PDF'de "Sükrü Ögretmen"
  olarak görünür. Bu sadeleştirme yalnızca PDF çıktısına özgüdür; Excel ve
  Word'de hiçbir çeviri yapılmaz, tüm karakterler birebir korunur.

### 9. Kullanışlılık eklentileri

- **Dosya değişikliği uyarısı**: oturum açıkken kaynak dosyanın boyutu ya
  da değiştirilme zamanı değişirse (`VeriOturumu.dosya_degisti_mi()`),
  durum çubuğu kalıcı olarak kırmızıya döner ve bir uyarı gösterilir --
  indekslenmiş bayt konumları artık YANLIŞ olabileceğinden, dosyayı
  kapatıp yeniden açmanız istenir.
- **Excel / Word / PDF'e doğrudan aktarma** (masaüstü): "Seçili Veriler"
  penceresinde **⬇ Excel / ⬇ Word / ⬇ PDF** düğmeleri, web sayfası açmaya
  gerek kalmadan `exporters.py`'yi doğrudan çağırıp seçtiğiniz dosyaya
  yazar (`filedialog.asksaveasfilename`) -- arka planda parça parça
  toplama, "Webde Göster" ile aynı mantık.
- **Son kullanılan dosyalar** (🕘): hem masaüstü hem web arayüzü, son
  açılan 10 dosyanın yolunu `%APPDATA%\livedata\son_dosyalar.json`'da
  paylaşır (bkz. `livedata/son_dosyalar.py`) -- bu, kaynak veriyi
  önbelleklemekten FARKLIDIR: yalnızca dosya YOLLARI tutulur, hiçbir kayıt
  verisi değil.
- **Regex (düzenli ifade) arama**: Arama sekmesindeki "Regex" kutusu
  işaretlenince aranan metin bir Python `re` deseni olarak yorumlanır
  (`re.MULTILINE` her zaman etkindir, böylece `^`/`$` her SATIRIN
  başına/sonuna göre çalışır, taranan bloğun değil). Akışlı taramada
  parça sınırını aşan eşleşmeleri yakalamak için `REGEX_TASMA_PAYI` (4096
  bayt) kadar geriye bakılır -- düz metin aramanın aksine (desen uzunluğu
  bilinir), regex'te eşleşme uzunluğu sınırsız kabul edildiğinden bu sabit
  bir güvenlik payıdır.
- **Ana tabloda kolon gizleme**: "Kolonlar…" düğmesi, geniş dosyalarda
  yalnızca ilgilendiğiniz kolonları göstermenizi sağlar. Bu yalnızca
  GÖSTERİMİ filtreler -- arama/sıralama hâlâ TÜM kolonlar üzerinde
  çalışır, Base64 çözme ve satır ayrıntısı gizli kolonlar dâhil tüm alanı
  gösterir.

## Ölçülen başarım

Dört kaynak dosya (hepsi gerçekten bu ekranla açılmış ve ölçülmüştür):

| Dosya | Boyut | Kayıt | Kolon | Kayıt bölgesi dışı |
|---|---|---|---|---|
| `eren_csv.csv` | 59,4 GiB | **205.060.846** (tarandı) | 7 | — |
| `eren_json.json` | 62,8 GiB | **238.758.543** (tarandı = bildirilen) | 6 | başlık 37 B + kuyruk 3 B |
| `eren_xml.xml` | 112,8 GiB | 293.180.461 (bildirilen) | 8 | başlık 73 B + kuyruk 8 B |
| `eren_yaml.yaml` | 84,6 GiB | 214.088.734 (bildirilen) | 9 | başlık 31 B |

| İşlem | Ölçüm |
|---|---|
| Biçim tespiti (açılış) | 5–10 ms (CSV 0,4 sn — başlık sezgisi için 1 MiB okur) |
| İlk sayfanın ekranda belirmesi | **< 0,5 sn** (tarama beklenmeden) |
| Rastgele kayda erişim | **0,41 ms** |
| 250 kayıtlık pencere okuma | **0,3 ms** |
| İndeks taraması | ~395–410 MB/sn (disk sınırlı) |
| CSV tam taraması (59,4 GiB) | **2 dk 33 sn** · 1.332.152 kayıt/sn |
| JSON tam taraması (62,8 GiB) | **2 dk 42 sn** · 396,2 MB/sn · indeks 1,8 MB |
| İndeks RAM (205M kayıt) | **1,6 MB** |
| Kayıt önbelleği tavanı | **24.000 kayıt** |
| Arama | ~780–870 MB/sn |
| Satır çözümleme (250'lik pencere) | CSV ~0,1 ms · JSON 0,36 ms · XML 2,1 ms · YAML 0,47 ms |

YAML notu: `yaml.safe_load` bu iş için çok yavaştır (154 µs/satır → 250'lik
pencere 38 ms, kaydırma takılır). Akış dizileri JSON'la aynı sözdizimine sahip
olduğundan önce `json.loads` denenir (**1,9 µs/satır, 80 kat hızlı**); JSON'un
kabul etmediği gerçek YAML sözdizimi görüldüğünde `yaml.safe_load`'a düşülür.
Sonuçlar birebir aynıdır.

## Neden eski "işlenmiş veri" yolundan çok daha hızlı?

Projedeki eski yol (`streaming_pilot/` + **Büyük Veri Aktar**) kaynağı akışla
okuyup **diske yeni bir depo yazıyordu**: JSONL kopya + her kayıt için 8
baytlık YOĞUN bir indeks + manifest. Sonra sayfalar bu depodan okunuyordu.

D:\ders_eren'de duran gerçek bir aktarım klasörü bunun maliyetini gösteriyor:

| | Eski (işlenmiş veri deposu) | Yeni (livedata) |
|---|---|---|
| Kaynağı okuma | 63,8 GB | gerektiği kadar |
| **Diske yazma** | `kayitlar.jsonl` 22,9 GiB + `kayitlar.idx` 979 MiB — ve bu aktarım **%63'te kalmış**; tamamlansa ~38 GiB | **0 bayt** |
| İndeks | kayıt başına 8 bayt, **diskte** (tam olsa 1,53 GiB) | 1000 kayıtta bir 8 bayt, **RAM'de** (1,6 MiB) |
| Görmeye başlamadan önce | tüm aktarımın bitmesi (oku + yaz) | **19 ms** |
| Disk alanı (4 dosya için) | ~150+ GiB ek | yok |

Hızın kaynağı üç karardır:

**1. Kopyalama adımı tamamen kaldırıldı.** Eski tasarımın varsayımı "kaynak
biçim rastgele erişime uygun değil, o hâlde uygun bir biçime çevirelim"di.
Oysa kaynak **zaten** rastgele erişilebilir — kayıtların nerede başladığını
bilmek yeterli. Yazma, okumadan yavaştır; 38 GiB yazmamak, 38 GiB'lık işi
tamamen yok etmek demektir.

**2. İndeks 1000 kat küçüldü.** Her kaydın konumunu tutmak 205M × 8 = 1,53
GiB eder (diske yazmak zorunda kalırsınız). Her 1000 kayıtta bir tutmak 1,6
MiB eder ve RAM'e sığar. Aradaki 999 kaydı ileri okumak yalnızca 0,3 ms
sürdüğü için bu seyreklik hissedilmez. Diske yazma zorunluluğu böylece
ortadan kalkar.

**3. İndeks artık isteğe bağlı.** Üstelik o 1,6 MiB'lık indeks bile ancak
gerekirse ve gerektiği kadar oluşturulur (yukarıya bakın).

Eski yolun bir üstünlüğü vardı: depo bir kez yazıldıktan sonra **sıralama**
yapılabiliyordu (harici sıralama geçici dosya ister). Yeni ekranda sıralama
yoktur — "diske hiçbir şey yazma" kuralının bilinçli bedeli budur ve bilinen
tek işlevsel eksiktir.

## Bilinçli sınırlar

- **Satır satır yazılmamış dosyalar açılmaz** (bkz. yukarısı). Açıkça
  reddedilir, sessizce yanlış bölünmez.
- **UTF-16/UTF-32 desteklenmez.** Satır sınırları ham bayt düzeyinde (`0x0A`)
  bulunur; bu UTF-8 ve tüm tek baytlı kodlamalarda doğrudur, UTF-16/32'de
  değildir.
- **Tam sıralı gezinme yoktur** (sayfa sıralaması, Top-K ve arama sonucu
  sıralaması vardır -- bkz. yukarısı). 200+ milyon kaydı baştan sona sıralı
  gezmek 1,53 GiB'lık bir permütasyon saklamayı gerektirir; bu ne RAM tavanına
  sığar ne de diske yazılabilir.
- **Kaynak dosya oturum sırasında değişmemelidir.** Değişirse çıpalar yanlış
  konumları gösterir. `VeriOturumu.dosya_degisti_mi()` bunu boyut +
  değişiklik zamanından tespit eder ve her iki arayüz de bunu aktif olarak
  izler: tespit edilince durum çubuğu kalıcı olarak uyarıya döner (masaüstü:
  popup + kırmızı durum satırı; web: toast + kırmızı durum metni) ve
  dosyanın kapatılıp yeniden açılması istenir -- veri sessizce yanlış
  gösterilmeye devam etmez.
- **İşletim sisteminin kendi dosya önbelleği** bu uygulamanın denetiminde
  değildir. "Diske yazılan: 0 bayt", *bu uygulamanın* hiçbir şey yazmadığı
  anlamına gelir.

## Modüller

```
livedata/
  units.py        sayı/bayt/süre biçimleme                   (bağımsız)
  rowscan.py      ham baytlarda satır sınırı primitifleri     (bağımsız)
  formats/                                                    biçime özgü HER ŞEY
    base.py         KayitBicimi sözleşmesi + sınır bulma
    csv_bicim.py    ayraç/başlık/tırnak sezgisi
    json_bicim.py   satır başına bir JSON kaydı
    xml_bicim.py    satır başına bir kayıt elementi
    yaml_bicim.py   satır başına bir dizi ögesi (JSON hızlı yolu)
    __init__.py     uzantıya göre dağıtım
  rowindex.py     seyrek indeks + tarayıcı thread             → rowscan
  blockreader.py  çıpadan rastgele kayıt penceresi okuma      → rowscan, formats
  loader.py       öncelikli istek kuyruğu + LRU önbellek      → blockreader
  finder.py       akışlı metin arama işi (düz metin + regex)  → rowscan
  sorting.py      permütasyonsuz üç sıralama kipi             → rowscan, formats
  selection.py    çoklu seçim kümesi (kayıt no + kolon)        (bağımsız)
  b64.py          Base64 ayıklama/çözme (önek/işaretçi/sonek)  (bağımsız)
  exporters.py    Excel/Word/PDF üretimi (yalnızca stdlib)     (bağımsız)
  webserver.py    seçimi localhost'ta HTML olarak yayınlar     → exporters
  son_dosyalar.py son kullanılan dosyalar listesi (%APPDATA%)  (bağımsız)
  session.py      hepsini birleştiren cephe                   → yukarıdakiler
  ui/
    renkler.py      açık/koyu tema renk tokenleri (sv-ttk)     (bağımsız)
    console.py      konsol alanı                               → renkler
    virtualtable.py sanal tablo (+ işaretleme sütunu)          → renkler, selection (çağrı sözleşmesiyle)
    b64dialog.py    Base64 çözme penceresi                     → b64, renkler
    selectionwindow.py  seçili verileri ayrı pencerede gösterir → session, virtualtable, webserver, exporters
    app.py          ana pencere (şerit/ribbon)                 → session, b64dialog, selectionwindow, son_dosyalar, renkler
    assets/icon.ico pencere ikonu (tools/ikon_uret.py üretir)
veri_goruntuleyici.py   masaüstü giriş noktası
csv_viewer.py           eski ad (aynı pencereyi açar)
gorunum/                web arayüzü (Django) -- bkz. LIVEDATA_WEB.md
webproj/                Django proje ayarları
manage.py               web giriş noktası
```

Dikkat: `rowindex`, `blockreader`, `loader`, `finder`, `session` ve `ui`
biçimden **habersizdir**; hepsi yalnızca `veri_basi`, `veri_sonu` ve
`coz_liste()` ile konuşur. Yeni bir biçim eklemek, `formats/` altına tek bir
modül eklemek demektir.

## Testler

```powershell
python -m unittest tests.test_livedata -v
```

`unittest discover -s tests` kullanmayın: depoda duran ve artık
kullanılmayan eski ekranın ~356 testini de çalıştırır, dakikalar sürer ve
bu ekranla ilgisi yoktur.

135 birim testi: satır sınırı primitifleri (tırnak paritesi, parça sınırları),
dört biçimin tespiti (BOM, UTF-16 reddi, girintili JSON'un reddi, XML kayıt
elementi bulma, YAML'ın JSON olmayan sözdizimi), indeks ve rastgele erişim
doğruluğu (kayıt içeriği kendi numarasını taşıyarak doğrulanır), başlık/kuyruk
satırlarının kayıt sayılmaması, aramanın kuyruğa taşmaması (düz metin VE
regex, MULTILINE çapaları, parça-sınırı taşma payının otomatik garanti
altına alınması), yükleyici önbellek tavanı, oturum yaşam döngüsü ve Base64
çözme (çok kolonlu birleştirme, kolon sırası, üç önek kipi, eksik dolgu,
URL-güvenli alfabe, ikili yük tespiti, otomatik önerinin çöp veriye
kanmaması, hata mesajlarının hücre içeriği sızdırmaması) ve isteğe bağlı
indeksleme (açılışta hiç tarama yapılmaması, aramanın indekssiz çalışması,
hedefli taramanın hedefte durması) ve sıralama (Top-K'nin iki yönü, sayfa
sınırlarına uyulması, okunamayan değerlerin elenmesi, XML hızlı çıkarıcının
genel yolla aynı sonucu vermesi, sonuçların indekse ipucu bırakması), çoklu
seçim (ekle/çıkar/tersine çevirme, eklenme sırasının korunması, seçim
tavanı, gösterilecek kolon listesi), Excel/Word/PDF dışa aktarımı (geçerli
zip/XML yapısı, Türkçe karakter davranışı, çok sayfalı PDF), yerel web
yayını ve son kullanılan dosyalar listesi (ekleme sırası, tekrar eklenince
öne taşınma, silinen dosyanın süzülmesi, üst sınır).

Ayrıca `python manage.py test gorunum` ile web arayüzünün kendi (Django)
testleri: dosya sistemi gezinme, sürücü listesi, olmayan yola 404.
