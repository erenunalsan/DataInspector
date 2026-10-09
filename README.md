# DataInspector · livedata

![Python](https://img.shields.io/badge/python-3.13-blue)
![Platform](https://img.shields.io/badge/platform-Windows-0078D6)
![UI](https://img.shields.io/badge/UI-Tkinter%20%7C%20Django-green)
![Tests](https://img.shields.io/badge/tests-135%20passing-brightgreen)

**[English](#english)** · **[Türkçe](#türkçe)**

---

## English

**A big-data viewer that inspects CSV, JSON, XML and YAML files with hundreds
of millions of records in place, straight from the source.** The file is
never loaded into memory and no intermediate file is written to disk; the
first page of a 112 GB file appears in under half a second.

It has two equivalent interfaces, both built on the same core (`livedata/`):

- **Desktop** — Tkinter, Office-style ribbon menu, Windows 11 (Fluent)
  light/dark theme.
- **Web** — Django; used from a browser on the same machine or from another
  computer/phone on the local network.

### Highlights

- **Four formats, one engine** — CSV/TSV, JSON/JSONL/NDJSON, XML and YAML
  open in the same window at the same speed.
- **Instant open** — format detection ~10 ms, first page < 0.5 s; no waiting
  for a full index scan, which runs only when and as far as needed.
- **Random access** — jump to any row in 0.4 ms; the sparse index (one
  offset per 1,000 records) takes only **1.6 MB of RAM** for 205 million
  records.
- **Search** — plain text or regex, case-sensitive or not; ~800 MB/s
  streaming scan without an index, with navigation between matches.
- **Sorting** — without writing to disk: in-page sort, top-N (Top-K) and
  sorting of search results.
- **Multi-selection** — mark records, view them in a separate window, copy
  to the clipboard or export to **Excel / Word / PDF** (standard library
  only).
- **Base64 decoding** — joins and decodes Base64 fields split across
  several columns, with prefixes/suffixes; detects text vs. binary payloads.
- **Safety nets** — warns if the source file changes during a session;
  explicitly rejects files that are not written one record per line instead
  of silently showing wrong results.
- **Conveniences** — column hiding, recent files, row detail window,
  drag-and-drop to open, single-file `.exe` packaging.

### Three rules

1. **Nothing is written to disk.** No temporary files, converted copies,
   index files or caches; the source is opened read-only. The status bar
   shows it at all times: *"Written to disk: 0 bytes"*. (Exceptions: the
   Excel/Word/PDF outputs the user explicitly asks for, and the list of
   recent file paths.)
2. **The file is not loaded into memory.** RAM usage has a ceiling
   independent of file size — a 112 GB file uses the same memory as a
   600 MB one.
3. **The UI never freezes.** Index scanning, record reading, search and
   sorting run on background threads.

### Installation

```bash
git clone https://github.com/erenunalsan/DataInspector.git
cd DataInspector
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

| Package | Used for |
|---|---|
| `PyYAML` | Fallback parser for YAML syntax that is not JSON-compatible |
| `sv-ttk` | Desktop light/dark theme |
| `django`, `waitress` | Web interface |
| `pillow` | Generating the app icon (`tools/ikon_uret.py`) |
| `pyinstaller` | Only for building the `.exe` (optional) |

### Usage

#### Desktop

Double-click `veri_goruntuleyici.bat` (drop a data file onto it to load that
file on startup), or:

```bash
python veri_goruntuleyici.py
```

```bash
python veri_goruntuleyici.py "D:\data\file.csv"
```

| Tab | Contents | Shortcut |
|---|---|---|
| **Dosya** (File) | CSV options: delimiter, encoding, header row, quoting | `Ctrl+1` |
| **Ana Sayfa** (Home) | Paging, go to row, Base64 decode, full index, columns | `Ctrl+2` |
| **Arama** (Search) | Text/regex search, case sensitivity, match navigation | `Ctrl+3` |
| **Sıralama** (Sort) | Column, direction, type, scope, top-N | `Ctrl+4` |
| **Seçim** (Selection) | Select page, clear selection, show/export selected | `Ctrl+5` |

> The user interface is in Turkish.

#### Web

The **🌐 Web Arayüzü** button on the desktop app starts the server in the
background and opens the browser. To start it manually, use
`webde_goruntule.bat` or:

```bash
python manage.py runserver 127.0.0.1:8000 --noreload
```

Then open `http://127.0.0.1:8000`. Sessions are kept in-process, so the
server must run as a **single process** (`--noreload` is required). Details
and API endpoints: [LIVEDATA_WEB.md](LIVEDATA_WEB.md).

> ⚠️ The web interface is designed for the local machine / a trusted local
> network: there is no authentication or CSRF protection and `DEBUG = True`.
> Do not run it as-is on an internet-facing server.

#### Distributing to a machine without Python

`tools/exe_paketle.bat` packages the desktop app into a single
`dist/LiveDataGoruntuleyici.exe` (~12 MB); no Python installation is needed
on the target machine.

### Supported files

Extensions: `.csv` `.tsv` `.txt` `.json` `.jsonl` `.ndjson` `.xml` `.yaml`
`.yml` — UTF-8 and single-byte encodings (UTF-16/32 are not supported).

The speed comes from a single assumption: **one record = one line.** Truly
large data files are almost always written this way, so finding the Nth
record reduces to finding the Nth `\n` byte, and all four formats share the
same index/search code.

| Format | Expected layout |
|---|---|
| CSV | Optional header row + one record per line (quoted fields supported) |
| JSON | `{"rows":[` header, one object per line, `]}` trailer — or JSON Lines |
| XML | `<?xml…?>` + wrapper, one record element per line, closing tag |
| YAML | `rows:` header, one `- {…}` flow item per line |

Pretty-printed JSON or XML with records spread across multiple lines will
not open; a descriptive error is shown instead of wrong row numbers.

### Measured performance

Measured with real files through this application:

| File | Size | Records |
|---|---|---|
| CSV | 59.4 GiB | 205,060,846 |
| JSON | 62.8 GiB | 238,758,543 |
| XML | 112.8 GiB | 293,180,461 |
| YAML | 84.6 GiB | 214,088,734 |

| Operation | Measurement |
|---|---|
| First page on screen | **< 0.5 s** |
| Random record access | **0.41 ms** |
| Reading a 250-record window | 0.3 ms |
| Full index scan | ~400 MB/s (disk-bound) — 59.4 GiB CSV: 2 min 33 s |
| Search | ~780–870 MB/s |
| Index RAM (205M records) | **1.6 MB** |

The project's previous version first copied the source into a new on-disk
store (JSONL + dense index): ~150 GiB of extra disk for the same four files,
plus waiting for the import to finish. livedata removes that copy step
entirely — see the comparison in [LIVEDATA.md](LIVEDATA.md).

### Architecture

```
livedata/
  rowscan.py      line-boundary primitives on raw bytes
  formats/        everything format-specific (csv / json / xml / yaml)
  rowindex.py     sparse index + scanner thread
  blockreader.py  random record-window reads from an anchor
  loader.py       priority request queue + LRU cache
  finder.py       streaming text / regex search
  sorting.py      three permutation-free sort modes
  selection.py    multi-selection set
  b64.py          Base64 extraction / decoding
  exporters.py    Excel / Word / PDF generation (stdlib only)
  session.py      facade tying everything together
  ui/             Tkinter desktop interface
gorunum/          Django web interface (thin adapter + virtual table JS)
webproj/          Django project settings
veri_goruntuleyici.py   desktop entry point
manage.py               web entry point
tools/            icon generation and .exe packaging
```

The core is format-agnostic: adding a new format means adding a single
module under `formats/`. The `livedata/` package does not depend on Tkinter;
the web interface uses it unchanged.

### Tests

```bash
python -m unittest tests.test_livedata
```

```bash
python manage.py test gorunum
```

The first runs the 135 unit tests of the livedata core (line boundaries,
format detection, index correctness, search, sorting, selection, Base64,
export…); the second runs the web interface tests.

> Do not use `unittest discover -s tests`: `tests/` also contains ~356 tests
> for the legacy code below; they take minutes and are unrelated to
> livedata.

### Documentation

The detailed documents are in Turkish:

- [LIVEDATA.md](LIVEDATA.md) — architecture, UI, all features,
  measurements, deliberate limits.
- [LIVEDATA_WEB.md](LIVEDATA_WEB.md) — web interface architecture, API and
  differences from the desktop app.
- [ARCHITECTURE.md](ARCHITECTURE.md) — architecture of the legacy
  DataInspector version (historical).

### Legacy code

`main.py`, `models.py`, `gui/`, `parsers/`, `algorithms/`, `decoder/`,
`streaming_pilot/`, `utils/` and `ARCHITECTURE.md` belong to the project's
first, now abandoned version (DataInspector). livedata is a completely
independent infrastructure written from scratch and uses none of them. The
legacy code is kept in the repository for historical reference only and is
not maintained. The small sample files under `samples/` are also for that
legacy version's tests.

---

## Türkçe

**Yüz milyonlarca kayıtlık CSV, JSON, XML ve YAML dosyalarını kaynağından,
yerinde inceleyen büyük veri görüntüleyici.** Dosya belleğe alınmaz, diske
hiçbir ara dosya yazılmaz; 112 GB'lık bir dosyanın ilk sayfası yarım
saniyenin altında ekrana gelir.

İki eşdeğer arayüzü vardır, ikisi de aynı çekirdeği (`livedata/`) kullanır:

- **Masaüstü** — Tkinter, Office tarzı şerit (ribbon) menü, Windows 11
  (Fluent) açık/koyu tema.
- **Web** — Django; aynı makineden ya da yerel ağdaki başka bir
  bilgisayar/telefondan tarayıcıyla kullanılır.

### Öne çıkanlar

- **Dört biçim, tek motor** — CSV/TSV, JSON/JSONL/NDJSON, XML ve YAML aynı
  pencerede, aynı hızda açılır.
- **Anında açılış** — biçim tespiti ~10 ms, ilk sayfa < 0,5 sn; tam indeks
  taraması beklenmez, yalnızca gerektiğinde ve gerektiği kadar yapılır.
- **Rastgele erişim** — herhangi bir satıra 0,4 ms'de gitme; seyrek indeks
  (1000 kayıtta bir konum) 205 milyon kayıt için yalnızca **1,6 MB RAM**.
- **Arama** — düz metin ya da regex, harfe duyarlı/duyarsız; indeks
  gerektirmeden ~800 MB/sn akışlı tarama, eşleşmeler arası gezinme.
- **Sıralama** — diske yazmadan: sayfa içi sıralama, en iyi N (Top-K) ve
  arama sonuçlarının sıralanması.
- **Çoklu seçim** — kayıtları işaretle, ayrı pencerede gör, panoya kopyala
  ya da **Excel / Word / PDF**'e aktar (yalnızca standart kütüphane ile).
- **Base64 çözme** — birden çok kolona bölünmüş, önekli/sonekli Base64
  alanlarını birleştirip çözer; metin/ikili yük tespiti.
- **Güvenlik ağları** — kaynak dosya oturum sırasında değişirse uyarır;
  satır satır yazılmamış dosyaları sessizce yanlış göstermek yerine açıkça
  reddeder.
- **Kolaylıklar** — kolon gizleme, son kullanılan dosyalar, satır ayrıntı
  penceresi, sürükle-bırak ile açma, tek dosyalık `.exe` paketleme.

### Üç kural

1. **Diske hiçbir şey yazılmaz.** Ara dosya, dönüştürülmüş kopya, indeks
   dosyası ya da önbellek oluşturulmaz; kaynak salt okunur açılır. Durum
   satırı bunu sürekli gösterir: *"Diske yazılan: 0 bayt"*. (İstisna:
   kullanıcının açıkça istediği Excel/Word/PDF çıktıları ve son kullanılan
   dosyaların yol listesi.)
2. **Dosya belleğe alınmaz.** RAM kullanımı dosya boyutundan bağımsız bir
   tavanla sınırlıdır — 112 GB'lık dosya da 600 MB'lık dosya da aynı belleği
   kullanır.
3. **Arayüz kilitlenmez.** İndeks taraması, kayıt okuma, arama ve sıralama
   arka plan thread'lerinde çalışır.

### Kurulum

```bash
git clone https://github.com/erenunalsan/DataInspector.git
cd DataInspector
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

| Paket | Ne için |
|---|---|
| `PyYAML` | YAML'ın JSON'la uyumsuz sözdizimi için yedek çözücü |
| `sv-ttk` | Masaüstü açık/koyu tema |
| `django`, `waitress` | Web arayüzü |
| `pillow` | Uygulama ikonunun üretimi (`tools/ikon_uret.py`) |
| `pyinstaller` | Yalnızca `.exe` paketlemek için (isteğe bağlı) |

### Kullanım

#### Masaüstü

`veri_goruntuleyici.bat`'a çift tıklayın (bir veri dosyasını üzerine
sürükleyip bırakırsanız açılışta yüklenir) ya da:

```bash
python veri_goruntuleyici.py
```

```bash
python veri_goruntuleyici.py "D:\veri\dosya.csv"
```

| Sekme | İçerik | Kısayol |
|---|---|---|
| **Dosya** | CSV seçenekleri: ayraç, kodlama, başlık satırı, tırnak | `Ctrl+1` |
| **Ana Sayfa** | Sayfa geçişi, satıra git, Base64 çöz, tam indeksle, kolonlar | `Ctrl+2` |
| **Arama** | Metin/regex arama, harf duyarlılığı, eşleşmeler arası gezinme | `Ctrl+3` |
| **Sıralama** | Kolon, yön, tür, kapsam, en iyi N | `Ctrl+4` |
| **Seçim** | Sayfayı seç, seçimi temizle, seçilenleri göster/aktar | `Ctrl+5` |

#### Web

Masaüstündeki **🌐 Web Arayüzü** düğmesi sunucuyu arka planda başlatıp
tarayıcıyı açar. Elle başlatmak için `webde_goruntule.bat` ya da:

```bash
python manage.py runserver 127.0.0.1:8000 --noreload
```

Ardından `http://127.0.0.1:8000` adresini açın. Oturumlar process içinde
tutulduğundan sunucu **tek process** ile çalışmalıdır (`--noreload` şart).
Ayrıntılar ve API uç noktaları: [LIVEDATA_WEB.md](LIVEDATA_WEB.md).

> ⚠️ Web arayüzü yerel makine / güvenilir yerel ağ için tasarlanmıştır:
> kimlik doğrulama ve CSRF koruması yoktur, `DEBUG = True`'dur. İnternete
> açık bir sunucuda bu hâliyle çalıştırmayın.

#### Python olmayan bir bilgisayara dağıtmak

`tools/exe_paketle.bat` masaüstü ekranını tek dosyalık
`dist/LiveDataGoruntuleyici.exe`'ye (~12 MB) paketler; hedef makinede Python
kurulumu gerekmez.

### Desteklenen dosyalar

Uzantılar: `.csv` `.tsv` `.txt` `.json` `.jsonl` `.ndjson` `.xml` `.yaml`
`.yml` — UTF-8 ve tek baytlı kodlamalar (UTF-16/32 desteklenmez).

Hızın kaynağı tek bir varsayımdır: **bir kayıt = bir satır.** Gerçekten büyük
veri dosyaları neredeyse her zaman böyle yazılır; bu sayede N. kaydı bulmak
N. `\n` baytını bulmaya indirgenir ve dört biçim de aynı indeks/arama kodunu
kullanır.

| Biçim | Beklenen yapı |
|---|---|
| CSV | İsteğe bağlı başlık satırı + satır başına bir kayıt (tırnaklı alanlar desteklenir) |
| JSON | `{"rows":[` başlığı, satır başına bir nesne, `]}` kuyruğu — ya da JSON Lines |
| XML | `<?xml…?>` + sarmalayıcı, satır başına bir kayıt elementi, kapanış etiketi |
| YAML | `rows:` başlığı, satır başına bir `- {…}` akış ögesi |

Girintili ("pretty-print") JSON ya da kayıtları birden çok satıra yayılmış
XML açılmaz; yanlış satır numarası göstermek yerine açıklayıcı bir hata
verilir.

### Ölçülen başarım

Gerçek dosyalarla, bu uygulama üzerinden ölçülmüştür:

| Dosya | Boyut | Kayıt |
|---|---|---|
| CSV | 59,4 GiB | 205.060.846 |
| JSON | 62,8 GiB | 238.758.543 |
| XML | 112,8 GiB | 293.180.461 |
| YAML | 84,6 GiB | 214.088.734 |

| İşlem | Ölçüm |
|---|---|
| İlk sayfanın ekranda belirmesi | **< 0,5 sn** |
| Rastgele kayda erişim | **0,41 ms** |
| 250 kayıtlık pencere okuma | 0,3 ms |
| Tam indeks taraması | ~400 MB/sn (disk sınırlı) — 59,4 GiB CSV: 2 dk 33 sn |
| Arama | ~780–870 MB/sn |
| İndeks RAM (205M kayıt) | **1,6 MB** |

Projenin önceki sürümü kaynağı önce diske yeni bir depoya (JSONL + yoğun
indeks) aktarıyordu: aynı dört dosya için ~150 GiB ek disk ve aktarım
bitene kadar bekleme. livedata bu kopyalama adımını tamamen kaldırır —
karşılaştırma için [LIVEDATA.md](LIVEDATA.md) ("Neden eski işlenmiş veri
yolundan çok daha hızlı?").

### Mimari

```
livedata/
  rowscan.py      ham baytlarda satır sınırı primitifleri
  formats/        biçime özgü her şey (csv / json / xml / yaml)
  rowindex.py     seyrek indeks + tarayıcı thread
  blockreader.py  çıpadan rastgele kayıt penceresi okuma
  loader.py       öncelikli istek kuyruğu + LRU önbellek
  finder.py       akışlı metin / regex arama
  sorting.py      permütasyonsuz üç sıralama kipi
  selection.py    çoklu seçim kümesi
  b64.py          Base64 ayıklama / çözme
  exporters.py    Excel / Word / PDF üretimi (yalnızca stdlib)
  session.py      hepsini birleştiren cephe
  ui/             Tkinter masaüstü arayüzü
gorunum/          Django web arayüzü (ince adaptör + sanal tablo JS)
webproj/          Django proje ayarları
veri_goruntuleyici.py   masaüstü giriş noktası
manage.py               web giriş noktası
tools/            ikon üretimi ve .exe paketleme
```

Çekirdek biçimden habersizdir: yeni bir biçim eklemek `formats/` altına tek
bir modül eklemek demektir. `livedata/` paketi Tkinter'a bağımlı değildir;
web arayüzü onu hiç değiştirmeden kullanır.

### Testler

```bash
python -m unittest tests.test_livedata
```

```bash
python manage.py test gorunum
```

İlki livedata çekirdeğinin 135 birim testini (satır sınırları, biçim
tespiti, indeks doğruluğu, arama, sıralama, seçim, Base64, dışa aktarım…),
ikincisi web arayüzünün testlerini çalıştırır.

> `unittest discover -s tests` kullanmayın: `tests/` altında aşağıdaki eski
> koda ait ~356 test daha vardır; dakikalar sürer ve livedata ile ilgisi
> yoktur.

### Belgeler

- [LIVEDATA.md](LIVEDATA.md) — mimari, ekran, tüm özellikler, ölçümler,
  bilinçli sınırlar.
- [LIVEDATA_WEB.md](LIVEDATA_WEB.md) — web arayüzünün mimarisi, API'si ve
  masaüstünden farkları.
- [ARCHITECTURE.md](ARCHITECTURE.md) — eski DataInspector sürümünün mimarisi
  (tarihsel).

### Eski kod

`main.py`, `models.py`, `gui/`, `parsers/`, `algorithms/`, `decoder/`,
`streaming_pilot/`, `utils/` ve `ARCHITECTURE.md` projenin ilk, artık terk
edilmiş sürümüne (DataInspector) aittir. livedata bunlardan tamamen
bağımsız, sıfırdan yazılmış yeni bir altyapıdır ve hiçbirini kullanmaz. Eski
kod yalnızca tarihsel referans için depoda tutulur ve bakımı yapılmaz.
`samples/` altındaki küçük örnek dosyalar da bu eski sürümün testleri
içindir.
