"""Ham CSV baytları üzerinde satır sınırı primitifleri.

Bu modülün tamamı BAYT üzerinde çalışır. Dosyanın tamamını asla belleğe
almaz: çağıran taraf dosyayı parça parça (chunk) okur, buradaki fonksiyonlar
da her parçayı yalnızca C hızındaki `bytes.count` / `bytes.find` /
`bytes.rfind` çağrılarıyla tarar. Satır başına Python döngüsü çalıştırmaktan
kaçınılır -- 200 milyon satırda satır başına birkaç yüz nanosaniyelik bir
Python adımı bile dakikalara mal olur.

Tırnak durumu ("parite")
------------------------
CSV'de bir kayıt, tırnak içine alınmış bir hücre satır sonu içeriyorsa
birden fazla FİZİKSEL satıra yayılabilir. Bir '\\n' baytının gerçekten kayıt
sonu olup olmadığı, o noktaya kadar görülen tırnak sayısının TEK mi ÇİFT mi
olduğuna bakılarak bulunur:

  - Tırnak sayısı çift  (parite 0) -> tırnak dışındayız -> '\\n' kayıt sonudur.
  - Tırnak sayısı tek   (parite 1) -> tırnak içindeyiz  -> '\\n' kayıt sonu DEĞİLDİR.

RFC 4180'de tırnak içindeki bir tırnak '""' ile kaçırılır; bu İKİ tırnak
pariteyi değiştirmediği için bu yaklaşım kaçış dizilerini kendiliğinden
doğru işler ve parça (chunk) sınırlarında ayrı bir özel duruma gerek
bırakmaz -- devreden tek durum bir bit'lik `parity` değeridir, hiçbir
"artık bayt" tamponu taşınmaz.

Hız
---
`parity == 0` iken bir sonraki tırnağa kadar olan bölgede tek bir
`bytes.count(NL, ...)` çağrısıyla satır sayılır; tırnak içermeyen dosyalarda
(en yaygın durum) tarama tamamen memchr hızındadır -- ölçülen: 3,7 GiB/sn,
yani pratikte her zaman diskten yavaş değil, disk sınırlayıcıdır. Tırnak
yoğun dosyalarda tırnak başına iki `find` maliyeti vardır; o durumda çağıran
taraf `quote_aware=False` ("hızlı mod") ile tırnak duyarlılığını
kapatabilir -- bu modda '\\n' koşulsuz kayıt sonu sayılır.
"""

NL = 0x0A       # '\n'
CR = 0x0D       # '\r'
QUOTE = 0x22    # '"'

# parity == 0 iken bir seferde en fazla bu kadar bayt ileri bakılır. Tırnak
# içermeyen bölgelerde tarama bu blok boyunda ilerler (blok başına 1 find +
# 1 count). Küçük tutmanın maliyeti fazla çağrı, büyük tutmanın maliyeti
# gereksiz geniş taramadır; 64 KiB ikisinin arasında iyi bir dengedir.
_QUOTE_BLOCK = 1 << 16

# nth_newline'ın kaba/ince iki aşamalı aramasında kullanılan ince blok boyu.
# Önce bu boyda bloklar `count` ile atlanır, sonra hedefi içeren blokta
# `find` ile tek tek yürünür -- böylece "n. satır sonunu bul" işlemi satır
# başına Python adımı yerine ~(blok/satır) adım maliyetine iner.
_PROBE_BLOCK = 4096


def nth_newline(buf, start, end, k):
    """buf[start:end] içindeki k. (1 tabanlı) '\\n' baytının indeksini döner.

    Bulunamazsa -1. Kaba/ince iki aşamalıdır: önce `_PROBE_BLOCK` boyunda
    bloklar `bytes.count` ile atlanır (C hızında), yalnızca hedefi içeren
    blokta `bytes.find` ile tek tek yürünür.

    Bu fonksiyon TIRNAKTAN HABERSİZDİR; yalnızca tırnak içermediği bilinen
    bölgelerde kullanılmalıdır (bkz. scan_for_anchors).
    """
    if k <= 0:
        return -1
    pos = start
    kalan = k
    while pos < end:
        blok_sonu = pos + _PROBE_BLOCK
        if blok_sonu > end:
            blok_sonu = end
        adet = buf.count(NL, pos, blok_sonu)
        if adet < kalan:
            kalan -= adet
            pos = blok_sonu
            continue
        while kalan > 0:
            idx = buf.find(NL, pos, blok_sonu)
            if idx < 0:
                return -1
            pos = idx + 1
            kalan -= 1
        return pos - 1
    return -1


def count_rows(buf, start, end, parity=0, quote_aware=True, quote=QUOTE):
    """buf[start:end] aralığındaki TAMAMLANMIŞ kayıt sayısını döner.

    Döner: (kayit_sayisi, yeni_parity). `parity`, aralığın BAŞINDAKİ tırnak
    durumudur ve bir sonraki parçaya olduğu gibi devredilir.

    Sondaki, '\\n' ile bitmeyen kısmi satır SAYILMAZ (bir sonraki parçada
    tamamlanacaktır); dosya sonundaki son satır için bkz. rowindex.
    """
    if not quote_aware:
        return buf.count(NL, start, end), 0

    satir = 0
    pos = start
    while pos < end:
        if parity:
            # Tırnak içindeyiz: kapanış tırnağına kadar hiçbir '\n' kayıt
            # sonu değildir; doğrudan bir sonraki tırnağa atla.
            q = buf.find(quote, pos, end)
            if q < 0:
                break
            parity = 0
            pos = q + 1
            continue
        blok_sonu = pos + _QUOTE_BLOCK
        if blok_sonu > end:
            blok_sonu = end
        q = buf.find(quote, pos, blok_sonu)
        if q < 0:
            satir += buf.count(NL, pos, blok_sonu)
            pos = blok_sonu
        else:
            satir += buf.count(NL, pos, q)
            parity = 1
            pos = q + 1
    return satir, parity


def scan_for_anchors(buf, start, end, base_offset, parity, rows_before,
                     stride, out_offsets, quote_aware=True, quote=QUOTE):
    """count_rows ile aynı taramayı yapar, ek olarak ÇIPA konumlarını toplar.

    `rows_before` mutlak satır sayacının aralık başındaki değeridir. Sayaç
    `stride`'ın katına her ulaştığında, O SATIRIN kaynak dosyadaki mutlak
    BAYT BAŞLANGICI `out_offsets` listesine eklenir. Çağıran taraf çıpaları
    her zaman sıralı aldığı için listeye indeksle erişebilir.

    Döner: (yeni_rows_before, yeni_parity).
    """
    satir = rows_before
    pos = start
    while pos < end:
        if parity:
            q = buf.find(quote, pos, end)
            if q < 0:
                break
            parity = 0
            pos = q + 1
            continue

        blok_sonu = pos + _QUOTE_BLOCK
        if blok_sonu > end:
            blok_sonu = end
        q = buf.find(quote, pos, blok_sonu) if quote_aware else -1
        if q < 0:
            bolge_sonu = blok_sonu
            sonraki = blok_sonu
            yeni_parity = parity
        else:
            bolge_sonu = q
            sonraki = q + 1
            yeni_parity = 1

        # [pos, bolge_sonu) tırnak İÇERMEZ -> buradaki tüm '\n'ler kayıt
        # sonudur; çıpa sınırı geçilmedikçe tek bir count yeter.
        adet = buf.count(NL, pos, bolge_sonu)
        if adet:
            p = pos
            while adet:
                gereken = stride - (satir % stride)
                if adet < gereken:
                    satir += adet
                    break
                idx = nth_newline(buf, p, bolge_sonu, gereken)
                if idx < 0:          # tutarsızlık; savunma amaçlı
                    satir += adet
                    break
                satir += gereken
                adet -= gereken
                out_offsets.append(base_offset + idx + 1)
                p = idx + 1
        pos = sonraki
        parity = yeni_parity
    return satir, parity


def first_row_end(buf, start=0, quote_aware=True, quote=QUOTE):
    """İlk KAYDI bitiren '\\n' baytının indeksini döner; yoksa -1.

    Tırnak içindeki satır sonlarını atlar. Başlık satırının nerede bittiğini
    (dolayısıyla ilk veri satırının bayt konumunu) bulmak için kullanılır.
    """
    if not quote_aware:
        return buf.find(NL, start)
    parity = 0
    pos = start
    n = len(buf)
    while pos < n:
        if parity:
            q = buf.find(quote, pos)
            if q < 0:
                return -1
            parity = 0
            pos = q + 1
            continue
        nl = buf.find(NL, pos)
        q = buf.find(quote, pos)
        if nl < 0:
            return -1
        if q < 0 or nl < q:
            return nl
        parity = 1
        pos = q + 1
    return -1


def row_start_before(buf, pos, floor=0):
    """buf[pos] baytını içeren satırın buf içindeki başlangıç indeksini döner.

    Satır başlangıcı bu parçanın içinde değilse `floor` döner (çağıran taraf
    bunu "satır bu parçadan önce başlamış" diye yorumlar).
    """
    idx = buf.rfind(NL, floor, pos)
    if idx < 0:
        return floor
    return idx + 1


def row_end_after(buf, pos, quote_aware=True, quote=QUOTE):
    """buf[pos]'tan sonraki ilk kayıt sonu '\\n' indeksini döner; yoksa len(buf).

    Yalnızca GÖSTERİM amaçlıdır (arama sonucu önizlemesini kırpmak için);
    burada tırnak duyarlılığı önizlemenin uzunluğunu etkiler, doğruluğunu
    değil.
    """
    if quote_aware:
        idx = first_row_end(buf, pos, quote_aware=True, quote=quote)
    else:
        idx = buf.find(NL, pos)
    if idx < 0:
        return len(buf)
    return idx
