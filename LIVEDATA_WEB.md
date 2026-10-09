# livedata — web arayüzü (Django)

Masaüstündeki Tkinter ekranının (bkz. `LIVEDATA.md`) tarayıcıdan
kullanılabilen karşılığı. **Aynı çekirdek** (`livedata/` paketi: `session.py`,
`loader.py`, `rowindex.py`, `finder.py`, `sorting.py`, `selection.py`,
`exporters.py`) hiç değiştirilmeden kullanılır — bu paket hiçbir yerde
Tkinter'a bağımlı değildir (`grep -r tkinter livedata/*.py` boş döner).
Django yalnızca ince bir web katmanıdır: `gorunum/` uygulaması.

Aynı üç kural burada da geçerlidir:
1. **Diske hiçbir şey yazılmaz.** Veritabanı bile yoktur (`DATABASES = {}`)
   — hiçbir migrasyon, hiçbir `db.sqlite3` oluşmaz. Excel/Word/PDF dışa
   aktarımları tamamen bellekte üretilip HTTP yanıtı olarak akıtılır.
2. **Kaynak dosya belleğe alınmaz.** Sanal tablo yalnızca o an görünen
   satırları ister; aynı pencere yükleyici/önbellek tavanı geçerlidir.
3. **Arayüz kilitlenmez.** Arka plan iş parçacıkları (indeks tarama, arama,
   sıralama, dışa aktarım toplama) hiçbir HTTP isteğini bloke etmez;
   tarayıcı ilerlemeyi **polling** ile izler (bkz. aşağıda).

## Çalıştırma

En kolay yol: **masaüstü uygulamasındaki (`veri_goruntuleyici.bat`) hızlı
erişim çubuğundaki "🌐 Web Arayüzü" düğmesi.** Sunucu çalışmıyorsa arka
planda kendisi başlatır (Tk ana döngüsünü bloklamadan, bir arka plan
thread'i sunucunun hazır olmasını bekler), sonra varsayılan tarayıcıyı
açar. O an açık bir dosya varsa, tarayıcı DOĞRUDAN aynı dosyayla açılır.
Masaüstü uygulamasını kapatmak, arka planda başlattığı sunucuyu da durdurur.

Elle çalıştırmak isterseniz:

```
pip install -r requirements.txt
python manage.py runserver 127.0.0.1:8000 --noreload
```

ya da çift tıklanabilir **`webde_goruntule.bat`**. Tarayıcıda
`http://127.0.0.1:8000` açılır. Belirli bir dosyayı doğrudan açan bağlantı:

```
http://127.0.0.1:8000/?yol=D:\ders_eren\eren_csv.csv&ac=1
```

**Yerel ağdan** erişmek için (aynı Wi-Fi/LAN'daki başka bir bilgisayar/
telefon) bu makinenin IP'sini kullanın: `http://192.168.x.x:8000`.

### ÖNEMLİ KISIT: tek process

`gorunum/kayit.py`'deki oturum kaydı (`VeriOturumu` nesneleri, arka plan
thread'leri) **process-içi bir Python sözlüğünde** tutulur. Bu yüzden
uygulama **TEK worker/process** ile çalıştırılmalıdır:

- `python manage.py runserver --noreload` (`--noreload` şart: aksi hâlde
  Django'nun otomatik yeniden yükleyicisi ikinci bir process açar ve
  oturumlar ikisi arasında bölünür).
- ya da `waitress-serve --host=0.0.0.0 --port=8000 --threads=8
  webproj.wsgi:application` (çoklu THREAD serbesttir, çoklu PROCESS
  değildir — `waitress` varsayılan olarak tek process çalışır).

Bu kısıt, projenin kullanım senaryosuyla (yerel makine / yerel ağ, tek
kullanıcı ya da birkaç güvenilir yerel kullanıcı) zaten uyumludur; gerçek
çok kullanıcılı bir sunucu için ayrı bir mimari (paylaşılan durum, kimlik
doğrulama) gerekir.

## Mimari

```
Tarayıcı
  │  fetch() + 400ms'de bir polling
  ▼
Django (webproj/ + gorunum/) — TEK process
  │
  ├─ gorunum/kayit.py     — {oid: VeriOturumu} process-içi sözlük
  ├─ gorunum/olaylar.py   — kuyruğu tüketen arka plan thread'i, JSON durum
  ├─ gorunum/disa_aktar.py— Excel/Word/PDF'i arka planda toplayıp üretir
  └─ gorunum/views.py     — ince adaptör: JSON <-> livedata çağrıları
  │
  ▼
livedata/ (DEĞİŞMEDEN) — session.py, loader.py, rowindex.py, finder.py,
                         sorting.py, selection.py, exporters.py
  │
  ▼
Kaynak dosya (60-120 GB, yerinde okunur)
```

### Neden polling, WebSocket değil

Django Channels + ASGI + (çoklu worker'da) Redis, tek kullanıcılı yerel bir
araç için gereksiz bir operasyonel ağırlıktır. Basit bir `GET .../durum`
uç noktası, Tkinter'daki `queue.Queue` + `after(30ms)` döngüsünün doğrudan
web karşılığıdır: `DurumTakipcisi` (bkz. `gorunum/olaylar.py`) kuyruğu TEK
bir arka plan thread'iyle tüketip JSON'a uygun bir anlık görüntüye yazar;
tarayıcı bunu 400ms'de bir okur. Yerel ağda bu gecikme fark edilmez.

### Sanal tablo (JS, üçüncü parti kütüphane yok)

`gorunum/static/gorunum/app.js`, Tkinter'daki `SanalTablo`nun ("yalnızca
görünen satırları gerçekle") tarayıcı karşılığıdır: sabit yükseklikli bir
"aralayıcı" (`spacer`) div toplam satır sayısı kadar yükseklik alır,
kaydırma pozisyonuna göre yalnızca görünen ~40-60 satır `GET .../satirlar
?bas=&adet=` ile çekilip mutlak konumlandırılmış div'ler olarak çizilir.
Masaüstündeki paged (100.000 satırlık "sayfa") yaklaşımının aksine, web
sürümü dosyanın TAMAMINDA **sürekli** kaydırma sağlar — "sayfa" kavramı
yalnızca sıralama kapsamı ve "Sayfayı Seç" için bir yığın (chunk) sınırı
olarak kalır.

## API uç noktaları

| Uç nokta | Karşılığı (app.py) |
|---|---|
| `POST /api/ac` | `_ac()` |
| `POST /api/oturum/<id>/kapat` | `_kapat()` |
| `GET /api/oturum/<id>/satirlar?bas=&adet=` | `_satir_saglayici()` |
| `GET /api/oturum/<id>/durum?konsol_sonrasi=&eslesme_sonrasi=` | `_kuyrugu_isle()` |
| `POST /api/oturum/<id>/satira-git` | `_satira_git()` |
| `POST /api/oturum/<id>/indeksle` | `_indeksi_tamamla()` |
| `POST /api/oturum/<id>/ara`, `/arama-durdur` | `_ara()`, `_arama_durdur()` |
| `POST /api/oturum/<id>/sirala`, `/sirala-durdur`, `/sirala-sifirla` | sıralama metotları |
| `POST /api/oturum/<id>/secim/degistir`, `/sayfa-sec`, `/temizle` | seçim metotları |
| `GET /api/oturum/<id>/secim/satirlar` | `SeciliVerilerPenceresi._satir_saglayici` |
| `POST /api/oturum/<id>/secim/disa-aktar/<excel\|word\|pdf>` | (arka planda başlatır, `token` döner) |
| `GET /api/disa-aktar/<token>/ilerleme`, `/indir` | ilerleme + dosya indirme |
| `POST /api/oturum/<id>/base64` | `_base64_coz()` |
| `GET /api/gozat?dizin=` | `filedialog.askopenfilename` karşılığı (basit dizin listesi + bağlı sürücüler) |
| `GET /api/son-dosyalar`, `POST /api/son-dosyalar/temizle` | `livedata/son_dosyalar.py` (masaüstüyle PAYLAŞILAN kayıt) |

`konsol_sonrasi`/`eslesme_sonrasi` birer **imleç**tir (cursor): tarayıcı her
`durum` isteğinde yalnızca YENİ konsol satırlarını/eşleşmeleri alır, tüm
geçmişi tekrar çekmez.

## Görünüm

Hızlı erişim çubuğundaki **🌙 Koyu Tema / ☀ Açık Tema** düğmesi tüm sayfayı
(tablo, konsol, kalıplar dâhil) CSS özel özellikleriyle (custom properties)
temalar; tercih `localStorage`'da kalır ve sonraki ziyaretlerde korunur.
Kullanıcı hiç seçim yapmadıysa sistem tercihi (`prefers-color-scheme`)
devreye girer. Belirli bir temayla açılan bağlantı paylaşmak için:
`http://127.0.0.1:8000/?tema=koyu` (ya da `acik`).

Dosya açılmadan önce tablo alanında karşılayıcı bir **boş durum ekranı**
gösterilir. `alert()`/`confirm()` gibi tarayıcının bloklayan, tema-duyarsız
kutuları yerine kendiliğinden kaybolan **toast bildirimleri** (`toast()`)
ve sayfanın kendi **onay kalıbı** (`onayIste()`) kullanılır -- ikisi de
`app.js`'de, üçüncü parti kütüphane olmadan.

## Sonradan eklenenler

- **🕘 Son dosyalar**: `/api/son-dosyalar` (masaüstüyle PAYLAŞILAN
  `livedata/son_dosyalar.py`'den okur) -- "Dosya Seç…" düğmesinin yanındaki
  açılır panel.
- **Dosya değişikliği uyarısı**: her `/durum` yanıtı `dosya_degisti` alanı
  taşır (yalnızca 400ms'lik polling'de kontrol edilir, `/satirlar` gibi çok
  sık çağrılan uç noktalarda DEĞİL); `true` olduğunda durum çubuğu kalıcı
  kırmızıya döner ve bir toast gösterilir.
- **Regex arama**: Arama sekmesindeki "Regex" kutusu, `/api/oturum/<id>/ara`
  isteğine `regex: true` ekler (bkz. `finder.Desen(..., regex=True)`).
- **Ana tabloda kolon gizleme**: "Kolonlar…" düğmesi -- yalnızca istemci
  tarafında render'ı filtreler, `/satirlar` her zaman TÜM kolonları döner
  (satır ayrıntısı/Base64 gizli kolonlar dâhil çalışmaya devam eder).

## Bilinçli sadeleştirmeler (masaüstüne göre)

- **Sayfalama yerine sürekli kaydırma** (yukarıda açıklandı) — Önceki/
  Sonraki sayfa düğmeleri artık `SAYFA_SATIR` kadar atlayan bir kısayoldur.
- **Eşleşme ◀/▶ gezinme düğmeleri yok** — "Arama sonuçları" sekmesindeki
  bir satıra tıklamak zaten o kayda gider; ayrı ok düğmeleri MVP kapsamı
  dışında bırakıldı.
- **"Seçilenleri Göster" penceresi ilk 500 kaydı gösterir** (kolon
  filtresi yoktur); tam liste için Excel/Word/PDF'e aktarım kullanılır
  (bunlar seçimin TAMAMINI, arka planda toplayıp içerir).
- **CSRF ara katmanı devre dışı** — API'ler düz JSON kabul eder, Django
  form/çerez akışı kullanmaz. Yalnızca yerel/güvenilir ağ kullanımı için
  uygundur; internete açık bir dağıtımda önce kimlik doğrulama eklenmelidir.

## Dosyalar

```
manage.py, webproj/            — Django proje iskeleti (ayarlar, URL kökü)
gorunum/
  views.py                     — API uç noktaları (ince adaptör)
  kayit.py                     — {oid: VeriOturumu} process-içi kayıt defteri
  olaylar.py                   — kuyruk -> JSON durum adaptörü (DurumTakipcisi)
  disa_aktar.py                — Excel/Word/PDF arka plan toplama işi
  templates/gorunum/ana.html   — tek sayfa iskelet (şerit + tablo + konsol)
  static/gorunum/app.js        — sanal tablo, polling, tüm istemci mantığı
  static/gorunum/app.css       — masaüstü şerit tasarımıyla tutarlı görünüm
webde_goruntule.bat             — çift tıkla, sunucuyu başlat, tarayıcıyı aç
```
