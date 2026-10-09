"""livedata -- CSV/JSON/XML/YAML dosyalarını YERİNDE inceleyen görüntüleyici.

Bu paket, DataInspector'ın eski (parsers/ + streaming_pilot/) yollarından
BAĞIMSIZ, yeni ve kendi kendine yeten bir altyapıdır. Tek bir kuralı vardır:

    Kaynak dosya dışında HİÇBİR VERİ DİSKE YAZILMAZ ve dosyanın tamamı
    HİÇBİR ZAMAN belleğe alınmaz.

Dört biçim de tek bir varsayımla aynı motoru paylaşır: **bir kayıt = bir
fiziksel satır**. Biçime özgü olan tek şey, kayıtların dosyanın neresinde
başlayıp bittiği ve bir satırın nasıl hücrelere çevrildiğidir; ikisi de
`formats/` altında kalır (bkz. formats/base.py).

400 milyon satırlık (onlarca GB) bir dosya, yalnızca şu üç yapıyla gezilir:

  1. `rowindex.RowIndex`  -- her `stride` satırda bir BAYT KONUMU tutan
     seyrek indeks (400M satır / 1000 = 400.000 çıpa x 8 bayt = ~3 MB).
  2. `loader.WindowLoader` -- ekranda görünen satır penceresini kaynaktan
     okuyan arka plan thread'i + sınırlı (LRU) pencere önbelleği.
  3. `finder.SearchJob`   -- kaynağı bayt akışı olarak tarayan arama işi.

Modüller (bağımlılık yönü yukarıdan aşağı):

    units.py       -- sayı/bayt/süre biçimleme (hiçbir şeye bağımlı değil)
    rowscan.py     -- ham baytlar üzerinde satır sınırı primitifleri
    formats/       -- biçime özgü her şey (CSV/JSON/XML/YAML)
    rowindex.py    -- seyrek indeks + tarayıcı thread (rowscan)
    blockreader.py -- çıpalardan rastgele kayıt penceresi okuma (rowscan, formats)
    loader.py      -- öncelikli istek kuyruğu + LRU önbellek (blockreader)
    finder.py      -- akışlı metin arama işi (rowscan)
    session.py     -- yukarıdakileri tek bir oturumda birleştiren cephe
    ui/            -- Tkinter arayüzü (yalnızca session'a bağımlı)
"""
