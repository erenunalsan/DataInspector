"""Kaynaktan, indeks çıpalarını kullanarak rastgele KAYIT penceresi okur.

Dört biçim (CSV/JSON/XML/YAML) için de aynıdır: kayıtlar satır satır
okunur ve her satır `bicim.coz_liste()` ile hücrelere çevrilir. Biçime
özgü tek istisna, tırnak duyarlı CSV'dir -- orada bir kayıt birden fazla
fiziksel satıra yayılabildiği için csv modülü kullanılır.

Bir satır penceresi okumanın maliyeti üç adımdır:

    1. `index.cipa_bul(satir)` -> en yakın önceki çıpa (bellekten, O(log n))
    2. `f.seek(cipa_ofset)`     -> tek bir disk konumlandırma
    3. en fazla `stride - 1` kayıt atla, sonra istenen kadar kayıt oku

Okunan bayt miktarı, istenen pencere + en fazla bir çıpa aralığıdır (~300
KB); dosya ne kadar büyük olursa olsun bu değişmez. Hiçbir aşamada dosyanın
tamamı, hatta bir sayfanın tamamı bile belleğe alınmaz.

Her thread KENDİ BlockReader'ını (dolayısıyla kendi dosya tanıtıcısını)
kullanmalıdır: dosya konumu (seek) paylaşılan bir durumdur, iki thread aynı
tanıtıcıyı kullanırsa birbirinin konumunu bozar.
"""
import csv

from . import rowscan

VARSAYILAN_TAMPON = 512 * 1024
# Tek bir fiziksel satırın kabul edilen üst sınırı. Bozuk/ikili bir dosyada
# '\n' hiç bulunmazsa tampon sınırsız büyüyeceği için gereklidir.
EN_FAZLA_SATIR_BAYT = 64 << 20


class SatirOkumaHatasi(Exception):
    pass


class _Tampon:
    """Belirli bir bayt konumundan başlayan, ileri yönlü tamponlu okuyucu."""

    def __init__(self, f, bas_ofset, blok=VARSAYILAN_TAMPON, sinir=None):
        self._f = f
        self._blok = blok
        self._f.seek(bas_ofset)
        self.buf = b""
        self.pos = 0
        self.bas = bas_ofset      # buf[0]'ın dosyadaki mutlak konumu
        self.eof = False
        # Kayıtların bittiği mutlak konum. JSON/XML'de dosyanın sonunda
        # kayıt OLMAYAN kuyruk satırları vardır (']}', '</rows>'); bu sınır
        # onların kayıt sanılmasını önler.
        self.sinir = sinir
        self._okunan = bas_ofset

    @property
    def mutlak(self):
        return self.bas + self.pos

    def _daha(self):
        """Tampona bir blok daha okur. Yeni veri geldiyse True."""
        if self.eof:
            return False
        if self.pos:
            self.buf = self.buf[self.pos:]
            self.bas += self.pos
            self.pos = 0
        if len(self.buf) > EN_FAZLA_SATIR_BAYT:
            raise SatirOkumaHatasi(
                f"Tek bir satır {EN_FAZLA_SATIR_BAYT // (1 << 20)} MB'ı aştı; "
                "dosya CSV olmayabilir ya da ayraç/satır sonu yanlış seçilmiş "
                "olabilir.")
        istenen = self._blok
        if self.sinir is not None:
            kalan = self.sinir - self._okunan
            if kalan <= 0:
                self.eof = True
                return False
            istenen = min(istenen, kalan)
        yeni = self._f.read(istenen)
        if not yeni:
            self.eof = True
            return False
        self._okunan += len(yeni)
        self.buf += yeni
        return True

    def satir(self):
        """Sonraki fiziksel satırı ('\\n' hariç) döner; veri bittiyse None."""
        while True:
            nl = self.buf.find(rowscan.NL, self.pos)
            if nl >= 0:
                s = self.buf[self.pos:nl]
                self.pos = nl + 1
                return s
            if not self._daha():
                if self.pos < len(self.buf):
                    s = self.buf[self.pos:]
                    self.pos = len(self.buf)
                    return s
                return None

    def satir_atla(self, adet):
        """`adet` fiziksel satır atlar. Atlanamayan (dosya bitti) sayıyı döner.

        Satır satır Python döngüsü kurmaz: tampondaki '\\n' sayısını tek bir
        `count` ile öğrenip hedefe `nth_newline` ile atlar.
        """
        while adet > 0:
            var = self.buf.count(rowscan.NL, self.pos)
            if var >= adet:
                idx = rowscan.nth_newline(self.buf, self.pos, len(self.buf), adet)
                self.pos = idx + 1
                return 0
            adet -= var
            self.pos = len(self.buf)
            if not self._daha():
                return adet
        return 0


class BlockReader:
    """Kaynak dosyadan satır penceresi okur. Thread başına bir örnek kullanın."""

    def __init__(self, bicim, index, tampon=VARSAYILAN_TAMPON):
        self.bicim = bicim
        self.index = index
        self._tampon_boyu = tampon
        self._f = open(bicim.yol, "rb")

    def kapat(self):
        try:
            self._f.close()
        except OSError:
            pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.kapat()
        return False

    # ------------------------------------------------------------------
    def satir_oku(self, bas_satir, adet):
        """[bas_satir, bas_satir+adet) kayıtlarını döner: list[list[str]].

        Dosya erken biterse daha az kayıt dönebilir. Çağıran taraf, bu
        aralığın indekste KESİN olarak konumlandırılabilir olduğunu
        (`index.erisilebilir`) önceden doğrulamalıdır; aksi hâlde dönen
        satırlar doğru numaraya karşılık gelmeyebilir.
        """
        if adet <= 0:
            return []
        cipa_satir, cipa_ofset = self.index.cipa_bul(bas_satir)
        atlanacak = bas_satir - cipa_satir
        t = _Tampon(self._f, cipa_ofset, self._tampon_boyu,
                    sinir=getattr(self.bicim, "veri_sonu", None))

        if self.bicim.tirnak_duyarli:
            return self._oku_tirnak_duyarli(t, atlanacak, adet)
        return self._oku_hizli(t, atlanacak, adet)

    def _oku_hizli(self, t, atlanacak, adet):
        """Kayıt == fiziksel satır olan yol (tırnaksız CSV, JSON, XML, YAML).

        Her satır, biçimin kendi `coz_liste()` çağrısıyla hücrelere çevrilir;
        bu katman kayıt dilbilgisini bilmez. Çözümlenemeyen bir satır okumayı
        DURDURMAZ: ham metni tek hücre olarak döner, böylece kullanıcı sorunu
        tabloda görür (kolon sayısı tutmadığı için satır kırmızı işaretlenir)
        ve gezinme kesintiye uğramaz.
        """
        if atlanacak and t.satir_atla(atlanacak):
            return []
        bicim = self.bicim
        cikti = []
        for _ in range(adet):
            s = t.satir()
            if s is None:
                break
            if s.endswith(b"\r"):
                s = s[:-1]
            try:
                cikti.append(bicim.coz_liste(s))
            except Exception:                        # noqa: BLE001
                cikti.append([s.decode(bicim.kodlama, "replace")])
        return cikti

    def _oku_tirnak_duyarli(self, t, atlanacak, adet):
        """Tırnaklı dosya yolu: kayıtlar csv modülüyle çözümlenir.

        Fiziksel satırlar satır sonlarıyla BİRLİKTE csv.reader'a verilir;
        böylece tırnak içindeki satır sonları kayıt değerinde olduğu gibi
        korunur (kayıt çok satırlı olabilir).
        """
        kodlama = self.bicim.kodlama

        def satir_uret():
            while True:
                s = t.satir()
                if s is None:
                    return
                yield s.decode(kodlama, "replace") + "\n"

        okuyucu = csv.reader(satir_uret(), delimiter=self.bicim.ayrac,
                             quotechar=self.bicim.tirnak)
        try:
            for _ in range(atlanacak):
                if next(okuyucu, None) is None:
                    return []
            cikti = []
            for kayit in okuyucu:
                cikti.append(kayit)
                if len(cikti) >= adet:
                    break
            return cikti
        except csv.Error as e:
            raise SatirOkumaHatasi(f"CSV çözümleme hatası: {e}") from e

    # ------------------------------------------------------------------
    def ham_blok_oku(self, ofset, adet_bayt):
        """Verilen konumdan ham bayt okur (arama önizlemesi için)."""
        self._f.seek(ofset)
        return self._f.read(adet_bayt)
