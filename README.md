# DataInspector · livedata

**Yüz milyonlarca kayıtlık CSV, JSON, XML ve YAML dosyalarını kaynağından,
yerinde inceleyen büyük veri görüntüleyici.** Dosya belleğe alınmaz, diske
hiçbir ara dosya yazılmaz; 112 GB'lık bir dosyanın ilk sayfası yarım
saniyenin altında ekrana gelir.

![Python](https://img.shields.io/badge/python-3.13-blue)
![Platform](https://img.shields.io/badge/platform-Windows-0078D6)
![Arayüz](https://img.shields.io/badge/aray%C3%BCz-Tkinter%20%7C%20Django-green)
![Testler](https://img.shields.io/badge/testler-135%20ge%C3%A7iyor-brightgreen)

İki eşdeğer arayüzü vardır, ikisi de aynı çekirdeği (`livedata/`) kullanır:

- **Masaüstü** — Tkinter, Office tarzı şerit (ribbon) menü, Windows 11
  (Fluent) açık/koyu tema.
- **Web** — Django; aynı makineden ya da yerel ağdaki başka bir
  bilgisayar/telefondan tarayıcıyla kullanılır.

---

## Öne çıkanlar

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

## Üç kural

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

## Kurulum

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

## Kullanım

### Masaüstü

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

### Web

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

### Python olmayan bir bilgisayara dağıtmak

`tools/exe_paketle.bat` masaüstü ekranını tek dosyalık
`dist/LiveDataGoruntuleyici.exe`'ye (~12 MB) paketler; hedef makinede Python
kurulumu gerekmez.

## Desteklenen dosyalar

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

## Ölçülen başarım

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
karşılaştırma için [LIVEDATA.md](LIVEDATA.md) ("Neden eski işlenmiş veri yolundan çok daha hızlı?").

## Mimari

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

## Testler

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

## Belgeler

- [LIVEDATA.md](LIVEDATA.md) — mimari, ekran, tüm özellikler, ölçümler,
  bilinçli sınırlar.
- [LIVEDATA_WEB.md](LIVEDATA_WEB.md) — web arayüzünün mimarisi, API'si ve
  masaüstünden farkları.
- [ARCHITECTURE.md](ARCHITECTURE.md) — eski DataInspector sürümünün mimarisi
  (tarihsel).

## Eski kod

`main.py`, `models.py`, `gui/`, `parsers/`, `algorithms/`, `decoder/`,
`streaming_pilot/`, `utils/` ve `ARCHITECTURE.md` projenin ilk, artık terk
edilmiş sürümüne (DataInspector) aittir. livedata bunlardan tamamen
bağımsız, sıfırdan yazılmış yeni bir altyapıdır ve hiçbirini kullanmaz. Eski
kod yalnızca tarihsel referans için depoda tutulur ve bakımı yapılmaz.
`samples/` altındaki küçük örnek dosyalar da bu eski sürümün testleri
içindir.
