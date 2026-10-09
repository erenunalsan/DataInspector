"""Kullanıcının işaretlediği kayıtları tutan, arayüzden bağımsız küme.

Bu modül Tkinter'ı hiç bilmez: yalnızca "hangi kayıt numaraları seçili"
sorusunun cevabını tutar. Seçili kayıtların GERÇEK DEĞERLERİ burada
saklanmaz -- yalnızca kayıt numaraları. Değerler gösterilecekleri anda
`VeriOturumu.kayitlar()` ile (arka plandaki pencere yükleyiciden, dağınık
erişimle) getirilir; bu, "dosya belleğe alınmaz" kuralıyla tutarlıdır ve
200.000 kayıt seçilse bile bellek kullanımı kayıt numaralarıyla (kayıt
başına 28 bayt'lık bir Python `int`) sınırlı kalır.

Neden bir tavan var?
--------------------
Seçim kullanıcının bilinçli eylemiyle büyür (tek tek tıklama ya da "Sayfayı
Seç"); teknik olarak sınırsız büyüyebilir. `EN_FAZLA_SECIM`, sıralamadaki
Top-K tavanıyla aynı büyüklük mertebesindedir (200.000) ve aynı gerekçeye
dayanır: sınırsız büyüyen bir küme, "RAM tavanı dosya boyutundan bağımsız
olmalı" ilkesini kullanıcının kendi eylemiyle çiğneyebilir.

Gelecek: yerel web yayını
--------------------------
Bu sınıf bilinçli olarak sade tutulmuştur (salt Python listesi + küme):
ileride bir kayıt numarası listesini yerel bir HTTP sunucusuna aktarmak
(`serialize`/`dict` dönüşümü) tek satırlık bir iş olsun diye. Web sunucusu
bu turda YAZILMAMIŞTIR; yalnızca veri modeli buna hazır tutulmuştur.
"""

# Sıralamadaki KIP_TUM_DOSYA tavanıyla aynı büyüklük mertebesi (bkz. sorting.py).
EN_FAZLA_SECIM = 200_000


class SecimKumesi:
    """Seçili kayıt numaraları (eklenme sırasıyla) + gösterilecek kolonlar.

    Kayıt numaraları eklenme sırasını korur (kullanıcı "önce şunu, sonra
    bunu" seçtiğinde, ayrı bir pencerede o sırayla görmeyi bekler); `sirali`
    metodu ayrıca kaynak sırasına göre de bir görünüm sağlar.
    """

    def __init__(self):
        self._liste = []          # eklenme sırasıyla kayıt numaraları
        self._kume = set()
        # None = tüm kolonlar gösterilir; değilse gösterilecek kolon
        # indekslerinin listesi (sırası önemlidir -- kullanıcı kolonları
        # yeniden sıralayabilir).
        self.kolonlar = None

    def __len__(self):
        return len(self._liste)

    def __contains__(self, kayit_no):
        return kayit_no in self._kume

    def __iter__(self):
        return iter(self._liste)

    def __bool__(self):
        return bool(self._liste)

    # -- değişiklik ------------------------------------------------------
    def ekle(self, kayit_no):
        """Kaydı seçime ekler. Zaten seçiliyse ya da tavan dolmuşsa False döner."""
        if kayit_no in self._kume:
            return False
        if len(self._liste) >= EN_FAZLA_SECIM:
            return False
        self._kume.add(kayit_no)
        self._liste.append(kayit_no)
        return True

    def cikar(self, kayit_no):
        """Kaydı seçimden çıkarır. Seçili değilse False döner."""
        if kayit_no not in self._kume:
            return False
        self._kume.discard(kayit_no)
        self._liste.remove(kayit_no)
        return True

    def degistir(self, kayit_no):
        """Kaydın seçim durumunu tersine çevirir.

        Döner: True (şimdi seçili), False (şimdi seçili değil), ya da
        None (seçmeye çalışıldı ama tavan doluydu -- durum değişmedi).
        """
        if kayit_no in self._kume:
            self.cikar(kayit_no)
            return False
        return True if self.ekle(kayit_no) else None

    def coklu_ekle(self, kayit_nolari):
        """Birden çok kaydı sırayla ekler; (eklenen, tavana_takilan) döner."""
        eklenen = 0
        tavana_takildi = False
        for no in kayit_nolari:
            if no in self._kume:
                continue
            if self.ekle(no):
                eklenen += 1
            else:
                tavana_takildi = True
                break
        return eklenen, tavana_takildi

    def temizle(self):
        self._liste.clear()
        self._kume.clear()

    # -- okuma -------------------------------------------------------
    def liste(self):
        """Eklenme sırasıyla kayıt numaraları (kopya)."""
        return list(self._liste)

    def sirali(self):
        """Kaynak dosyadaki sırayla (artan kayıt numarası) kopya."""
        return sorted(self._liste)

    def dolu_mu(self):
        return len(self._liste) >= EN_FAZLA_SECIM

    def kolonlari_ayarla(self, indeksler):
        """Gösterilecek kolonları (sırayla) belirler; boş liste = hiçbiri."""
        self.kolonlar = list(indeksler)

    def gosterilecek_kolonlar(self, toplam_kolon_sayisi):
        """`kolonlar` None ise tüm kolon indekslerini, değilse ayarlanan
        listeyi döner."""
        if self.kolonlar is None:
            return list(range(toplam_kolon_sayisi))
        return list(self.kolonlar)
