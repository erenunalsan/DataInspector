"""livedata (CSV/JSON/XML/YAML'ı yerinde inceleyen görüntüleyici) birim testleri.

Testler yalnızca küçük geçici dosyalar kullanır; arayüz (Tkinter) gerektirmez.
Her test, gerçek dosya sisteminde gerçek bayt okuması yapar -- indeksin ve
okuyucunun doğruluğu ancak böyle sınanabilir.
"""
import os
import queue
import shutil
import tempfile
import unittest

import io
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
import zipfile

from livedata import (b64, blockreader, exporters, finder, loader, rowindex,
                      rowscan, selection, son_dosyalar, sorting, units,
                      webserver)
from livedata import formats as csvformat
from livedata.session import VeriOturumu


def tara(bicim, stride=4, blok=64):
    """Bir dosyayı baştan sona indeksler ve hazır RowIndex döner."""
    idx = rowindex.RowIndex(bicim.veri_basi, stride=stride)
    tarayici = rowindex.IndexScanner(bicim, idx, queue.Queue(), blok=blok)
    tarayici.start()
    tarayici.join(timeout=30)
    return idx


class GeciciDosyaKarisimi:
    """Test sınıflarına geçici dizin + dosya yazma kolaylığı ekler."""

    def setUp(self):
        self.dizin = tempfile.mkdtemp(prefix="livedata-test-")
        self.addCleanup(shutil.rmtree, self.dizin, ignore_errors=True)

    def yaz(self, icerik, ad="t.csv"):
        yol = os.path.join(self.dizin, ad)
        with open(yol, "wb") as f:
            f.write(icerik)
        return yol


# ======================================================================
class TestRowscan(unittest.TestCase):
    """Ham bayt üzerindeki satır sınırı primitifleri."""

    def test_tirnaksiz_satir_sayimi(self):
        veri = b"a,b\nc,d\ne,f\n"
        self.assertEqual(rowscan.count_rows(veri, 0, len(veri)), (3, 0))

    def test_sondaki_kismi_satir_sayilmaz(self):
        veri = b"a,b\nc,d"
        self.assertEqual(rowscan.count_rows(veri, 0, len(veri))[0], 1)

    def test_tirnak_icindeki_satir_sonu_kayit_sonu_degil(self):
        veri = b'a,"birinci\nikinci"\nc,d\n'
        self.assertEqual(rowscan.count_rows(veri, 0, len(veri))[0], 2)

    def test_kacisli_tirnak_pariteyi_bozmaz(self):
        # "" kaçışı iki tırnaktır; parite değişmez, satır sonu kayıt sonudur.
        veri = b'a,"x""y"\nc,d\n'
        self.assertEqual(rowscan.count_rows(veri, 0, len(veri)), (2, 0))

    def test_parite_parcalar_arasinda_tasinir(self):
        veri = b'a,"acik\nhala acik\nkapandi"\nson,satir\n'
        kesme = 12
        s1, p1 = rowscan.count_rows(veri, 0, kesme)
        s2, p2 = rowscan.count_rows(veri, kesme, len(veri), p1)
        self.assertEqual(s1 + s2, 2)
        self.assertEqual(p2, 0)

    def test_tirnak_duyarsiz_mod_her_satir_sonunu_sayar(self):
        veri = b'a,"birinci\nikinci"\nc,d\n'
        self.assertEqual(
            rowscan.count_rows(veri, 0, len(veri), quote_aware=False)[0], 3)

    def test_nth_newline(self):
        veri = b"0\n1\n2\n3\n4\n"
        self.assertEqual(rowscan.nth_newline(veri, 0, len(veri), 1), 1)
        self.assertEqual(rowscan.nth_newline(veri, 0, len(veri), 3), 5)
        self.assertEqual(rowscan.nth_newline(veri, 0, len(veri), 99), -1)

    def test_scan_for_anchors_konumlari(self):
        veri = b"".join(b"%d\n" % i for i in range(10))   # her satır 2 bayt
        cipalar = []
        satir, _ = rowscan.scan_for_anchors(veri, 0, len(veri), 0, 0, 0, 3, cipalar)
        self.assertEqual(satir, 10)
        # 3, 6 ve 9 numaralı satırların başlangıçları
        self.assertEqual(cipalar, [6, 12, 18])

    def test_first_row_end_tirnagi_atlar(self):
        veri = b'a,"ic\nsatir"\nsonraki\n'
        self.assertEqual(rowscan.first_row_end(veri), 12)


# ======================================================================
class TestBicimTespit(GeciciDosyaKarisimi, unittest.TestCase):
    """Ayraç / kodlama / başlık sezgisi."""

    def test_virgul_ve_baslik(self):
        b = csvformat.bicim_tespit(self.yaz(b"ad,yas\nAli,30\nVeli,41\nAyse,25\n"))
        self.assertEqual(b.ayrac, ",")
        self.assertTrue(b.baslik_var)
        self.assertEqual(b.kolonlar, ["ad", "yas"])
        self.assertEqual(b.veri_basi, 7)

    def test_noktali_virgul_basliksiz(self):
        icerik = b"".join(b"%d_0_aa;%d_1_bb;%d_2_cc\n" % (i, i, i) for i in range(20))
        b = csvformat.bicim_tespit(self.yaz(icerik))
        self.assertEqual(b.ayrac, ";")
        self.assertFalse(b.baslik_var)
        self.assertEqual(b.kolonlar, ["Kolon 1", "Kolon 2", "Kolon 3"])
        self.assertEqual(b.veri_basi, 0)

    def test_kullanici_secimi_sezgiyi_ezer(self):
        icerik = b"".join(b"%d_0_aa;%d_1_bb\n" % (i, i) for i in range(20))
        b = csvformat.bicim_tespit(self.yaz(icerik), baslik_var=True)
        self.assertTrue(b.baslik_var)
        self.assertEqual(b.kolonlar, ["0_0_aa", "0_1_bb"])

    def test_utf8_bom(self):
        b = csvformat.bicim_tespit(self.yaz(b"\xef\xbb\xbfad,yas\nAli,30\nVeli,41\n"))
        self.assertEqual(b.kodlama, "utf-8-sig")
        self.assertEqual(b.veri_basi, 3 + 7)

    def test_utf16_reddedilir(self):
        with self.assertRaises(csvformat.BicimHatasi) as ctx:
            csvformat.bicim_tespit(self.yaz(b"\xff\xfea\x00,\x00b\x00\n\x00"))
        self.assertIn("UTF-16", str(ctx.exception))

    def test_bos_dosya_reddedilir(self):
        with self.assertRaises(csvformat.BicimHatasi):
            csvformat.bicim_tespit(self.yaz(b""))

    def test_tirnak_yoksa_duyarlilik_kapali(self):
        b = csvformat.bicim_tespit(self.yaz(b"a;b\n1;2\n3;4\n"))
        self.assertFalse(b.tirnak_duyarli)

    def test_tirnak_varsa_duyarlilik_acik(self):
        b = csvformat.bicim_tespit(self.yaz(b'a;b\n1;"x;y"\n3;4\n'))
        self.assertTrue(b.tirnak_duyarli)


# ======================================================================
class TestIndeksVeOkuyucu(GeciciDosyaKarisimi, unittest.TestCase):
    """RowIndex + BlockReader: kesin satır sayısı ve rastgele erişim."""

    def test_satir_sayisi_ve_rastgele_erisim(self):
        icerik = b"".join(b"%d_0_x;%d_1_y\n" % (i, i) for i in range(500))
        b = csvformat.bicim_tespit(self.yaz(icerik))
        idx = tara(b, stride=7)
        self.assertTrue(idx.tamam)
        self.assertEqual(idx.toplam_satir, 500)

        with blockreader.BlockReader(b, idx) as r:
            for hedef in (0, 1, 6, 7, 8, 13, 250, 499):
                with self.subTest(satir=hedef):
                    self.assertEqual(r.satir_oku(hedef, 1)[0][0], f"{hedef}_0_x")

    def test_pencere_okuma_ardisik(self):
        icerik = b"".join(b"%d;v\n" % i for i in range(200))
        b = csvformat.bicim_tespit(self.yaz(icerik))
        idx = tara(b, stride=10)
        with blockreader.BlockReader(b, idx) as r:
            pencere = r.satir_oku(57, 25)
        self.assertEqual(len(pencere), 25)
        self.assertEqual([s[0] for s in pencere], [str(i) for i in range(57, 82)])

    def test_dosya_sonunda_kisa_pencere(self):
        icerik = b"".join(b"%d;v\n" % i for i in range(30))
        b = csvformat.bicim_tespit(self.yaz(icerik))
        idx = tara(b, stride=5)
        with blockreader.BlockReader(b, idx) as r:
            self.assertEqual(len(r.satir_oku(25, 50)), 5)

    def test_sondaki_newlinesiz_satir_sayilir(self):
        b = csvformat.bicim_tespit(self.yaz(b"a;b\n1;2\n3;4"), baslik_var=True)
        idx = tara(b, stride=2)
        self.assertEqual(idx.toplam_satir, 2)
        with blockreader.BlockReader(b, idx) as r:
            self.assertEqual(r.satir_oku(1, 1)[0], ["3", "4"])

    def test_cok_satirli_tirnakli_kayit_tek_kayittir(self):
        icerik = (b'ad;not\n'
                  b'Ali;"birinci\nikinci"\n'
                  b'Veli;"a""b"\n'
                  b'Ayse;duz\n')
        b = csvformat.bicim_tespit(self.yaz(icerik), baslik_var=True)
        self.assertTrue(b.tirnak_duyarli)
        idx = tara(b, stride=2)
        self.assertEqual(idx.toplam_satir, 3)
        with blockreader.BlockReader(b, idx) as r:
            self.assertEqual(r.satir_oku(0, 1)[0], ["Ali", "birinci\nikinci"])
            self.assertEqual(r.satir_oku(1, 1)[0], ["Veli", 'a"b'])
            self.assertEqual(r.satir_oku(2, 1)[0], ["Ayse", "duz"])

    def test_crlf_satir_sonlari(self):
        """Windows satır sonu (\\r\\n): '\\r' hücre değerine sızmamalı."""
        b = csvformat.bicim_tespit(
            self.yaz(b"0;a;b\r\n1;c;d\r\n2;e;f\r\n"), baslik_var=False)
        idx = tara(b, stride=2)
        self.assertEqual(idx.toplam_satir, 3)
        with blockreader.BlockReader(b, idx) as r:
            self.assertEqual(r.satir_oku(0, 1)[0], ["0", "a", "b"])
            self.assertEqual(r.satir_oku(2, 1)[0], ["2", "e", "f"])

    def test_crlf_baslikli(self):
        b = csvformat.bicim_tespit(self.yaz(b"ad;yas\r\nAli;30\r\nVeli;41\r\nAyse;25\r\n"))
        self.assertTrue(b.baslik_var)
        self.assertEqual(b.kolonlar, ["ad", "yas"])
        idx = tara(b, stride=2)
        self.assertEqual(idx.toplam_satir, 3)
        with blockreader.BlockReader(b, idx) as r:
            self.assertEqual(r.satir_oku(0, 1)[0], ["Ali", "30"])

    def test_crlf_tirnak_icinde_satir_sonu_korunur(self):
        b = csvformat.bicim_tespit(
            self.yaz(b'ad;not\r\nAli;"bir\r\niki"\r\nVeli;duz\r\n'), baslik_var=True)
        idx = tara(b, stride=2)
        self.assertEqual(idx.toplam_satir, 2)
        with blockreader.BlockReader(b, idx) as r:
            self.assertEqual(r.satir_oku(0, 1)[0], ["Ali", "bir\r\niki"])
            self.assertEqual(r.satir_oku(1, 1)[0], ["Veli", "duz"])

    def test_cipa_sayisi_ve_bellek(self):
        icerik = b"".join(b"%d;v\n" % i for i in range(1000))
        b = csvformat.bicim_tespit(self.yaz(icerik))
        idx = tara(b, stride=100)
        # 0. çıpa veri başı + her 100 satırda bir
        self.assertEqual(idx.cipa_sayisi(), 11)
        self.assertLess(idx.bellek_bayt(), 1024)

    def test_erisilebilir_taramadan_bagimsiz(self):
        """İlk çıpa aralığı, tarayıcı hiç çalışmasa bile okunabilir olmalı."""
        icerik = b"".join(b"%d;v\n" % i for i in range(5000))
        b = csvformat.bicim_tespit(self.yaz(icerik))
        idx = rowindex.RowIndex(b.veri_basi, stride=1000)   # tarayıcı ÇALIŞMADI
        self.assertTrue(idx.erisilebilir(0))
        self.assertTrue(idx.erisilebilir(999))
        self.assertFalse(idx.erisilebilir(4000))
        with blockreader.BlockReader(b, idx) as r:
            self.assertEqual(r.satir_oku(500, 1)[0][0], "500")

    def test_arama_ipucu_erisim_acar(self):
        icerik = b"".join(b"%d;v\n" % i for i in range(5000))
        b = csvformat.bicim_tespit(self.yaz(icerik))
        idx = rowindex.RowIndex(b.veri_basi, stride=1000)
        hedef = 4321
        ofset = sum(len(b"%d;v\n" % i) for i in range(hedef))
        self.assertFalse(idx.erisilebilir(hedef))
        idx.ipucu_ekle(hedef, b.veri_basi + ofset)
        self.assertTrue(idx.erisilebilir(hedef))
        with blockreader.BlockReader(b, idx) as r:
            self.assertEqual(r.satir_oku(hedef, 1)[0][0], str(hedef))

    def test_ilk_erisilebilir(self):
        idx = rowindex.RowIndex(0, stride=100)
        self.assertEqual(idx.ilk_erisilebilir(0, 50), 0)
        self.assertIsNone(idx.ilk_erisilebilir(9000, 9250))
        idx.ipucu_ekle(9100, 12345)
        self.assertEqual(idx.ilk_erisilebilir(9000, 9250), 9100)


# ======================================================================
class TestArama(GeciciDosyaKarisimi, unittest.TestCase):
    """Akışlı arama: sınır aşımı, harf duyarlılığı, satır numarası."""

    def _ara(self, bicim, idx, metin, duyarli=True, blok=64, geri=16):
        desen = finder.Desen(metin, duyarli, bicim.kodlama)
        kuy = queue.Queue()
        is_ = finder.SearchJob(bicim, idx, desen, kuy, blok=blok, geri_bak=geri)
        is_.start()
        is_.join(timeout=30)
        eslesmeler = []
        while not kuy.empty():
            olay = kuy.get()
            if olay["tur"] == finder.OLAY_ESLESME:
                eslesmeler.extend(olay["eslesmeler"])
        return eslesmeler

    def setUp(self):
        super().setUp()
        satirlar = []
        self.beklenen = [3, 77, 199]
        for i in range(200):
            isaret = "ARANAN" if i in self.beklenen else "normal"
            satirlar.append(f"{i};{isaret};son{i}")
        self.yol = self.yaz(("\n".join(satirlar) + "\n").encode())
        self.bicim = csvformat.bicim_tespit(self.yol, baslik_var=False)
        self.idx = tara(self.bicim, stride=10, blok=256)

    def test_parca_boyundan_bagimsiz_ayni_sonuc(self):
        for blok in (7, 32, 101, 4096):
            with self.subTest(blok=blok):
                bulunan = self._ara(self.bicim, self.idx, "ARANAN", blok=blok,
                                    geri=min(16, blok))
                self.assertEqual(sorted(e.satir for e in bulunan), self.beklenen)

    def test_satir_basi_ve_onizleme(self):
        e = self._ara(self.bicim, self.idx, "ARANAN", blok=4096)[0]
        self.assertEqual(e.satir, 3)
        self.assertTrue(e.onizleme.startswith("3;ARANAN"))
        with open(self.yol, "rb") as f:
            f.seek(e.satir_basi)
            self.assertTrue(f.read(10).startswith(b"3;ARANAN"))

    def test_arama_indekse_ipucu_birakir(self):
        idx = rowindex.RowIndex(self.bicim.veri_basi, stride=10)
        self._ara(self.bicim, idx, "ARANAN", blok=4096)
        self.assertTrue(idx.erisilebilir(199))

    def test_harf_duyarliligi(self):
        yol = self.yaz(b"0;Merhaba\n1;MERHABA\n2;merhaba\n3;yok\n", "h.csv")
        b = csvformat.bicim_tespit(yol, baslik_var=False)
        idx = tara(b, stride=2, blok=128)
        self.assertEqual([e.satir for e in self._ara(b, idx, "merhaba", True)], [2])
        self.assertEqual(sorted(e.satir for e in self._ara(b, idx, "merhaba", False)),
                         [0, 1, 2])
        self.assertEqual(sorted(e.satir for e in self._ara(b, idx, "MeRhAbA", False)),
                         [0, 1, 2])

    def test_turkce_buyuk_kucuk(self):
        yol = self.yaz("0;Şirket\n1;ŞİRKET\n2;şirket\n3;yok\n".encode(), "tr.csv")
        b = csvformat.bicim_tespit(yol, baslik_var=False)
        idx = tara(b, stride=2, blok=128)
        bulunan = sorted(e.satir for e in self._ara(b, idx, "şirket", False))
        self.assertEqual(bulunan, [0, 1, 2])

    def test_tr_harf_donusumleri(self):
        self.assertEqual(finder.tr_buyuk("işi"), "İŞİ")
        self.assertEqual(finder.tr_kucuk("IŞIK"), "ışık")

    def test_bos_desen_reddedilir(self):
        with self.assertRaises(ValueError):
            finder.Desen("", False)

    def test_desendeki_satir_sonu_bosluga_cevrilir(self):
        self.assertNotIn("\n", finder.Desen("a\nb", True).desenler[0].decode())

    # -- regex (düzenli ifade) arama --------------------------------------
    def _ara_regex(self, bicim, idx, desen_metni, duyarli=False, blok=4096):
        desen = finder.Desen(desen_metni, duyarli, bicim.kodlama, regex=True)
        kuy = queue.Queue()
        # geri_bak KASITLI OLARAK verilmiyor: SearchJob artık kendisi
        # desen.uzunluk'a göre yeterli bir alt sınır uygular (bkz.
        # finder.py'deki `gereken_en_az`) -- çağıranın bunu elle doğru
        # ayarlamasına gerek yoktur/olmamalıdır.
        is_ = finder.SearchJob(bicim, idx, desen, kuy, blok=blok)
        is_.start()
        is_.join(timeout=30)
        eslesmeler = []
        while not kuy.empty():
            olay = kuy.get()
            if olay["tur"] == finder.OLAY_ESLESME:
                eslesmeler.extend(olay["eslesmeler"])
        return eslesmeler

    def test_regex_arama_dogru_satirlari_bulur(self):
        yol = self.yaz(b"0;abc123\n1;abc999\n2;xyz555\n3;abc42\n", "rx2.csv")
        b = csvformat.bicim_tespit(yol, baslik_var=False)
        idx = tara(b, stride=2, blok=128)
        bulunan = sorted(e.satir for e in self._ara_regex(b, idx, r"abc\d+"))
        self.assertEqual(bulunan, [0, 1, 3])

    def test_regex_karakter_sinifi(self):
        yol = self.yaz(b"0;kedi\n1;kopek\n2;kus\n3;balik\n", "rx3.csv")
        b = csvformat.bicim_tespit(yol, baslik_var=False)
        idx = tara(b, stride=2, blok=128)
        bulunan = sorted(e.satir for e in self._ara_regex(b, idx, r"^\d;k[eo]"))
        self.assertEqual(bulunan, [0, 1])

    def test_regex_harf_duyarliligi(self):
        yol = self.yaz(b"0;Merhaba\n1;merhaba\n2;yok\n", "rx4.csv")
        b = csvformat.bicim_tespit(yol, baslik_var=False)
        idx = tara(b, stride=2, blok=128)
        duyarli = sorted(e.satir for e in
                         self._ara_regex(b, idx, "merhaba", duyarli=True))
        duyarsiz = sorted(e.satir for e in
                          self._ara_regex(b, idx, "merhaba", duyarli=False))
        self.assertEqual(duyarli, [1])
        self.assertEqual(duyarsiz, [0, 1])

    def test_gecersiz_regex_reddedilir(self):
        with self.assertRaises(ValueError):
            finder.Desen("(", False, regex=True)

    def test_regex_parca_boyundan_bagimsiz_ayni_sonuc(self):
        # NOT: blok değerleri REGEX_TASMA_PAYI'dan (4096) KÜÇÜK OLAMAZ --
        # regex'te eşleşme uzunluğu sınırsız kabul edildiğinden taşma payı
        # sabittir; bir blok bu paydan küçükse üst üste taşan pencereler
        # aynı eşleşmeyi birden çok kez bulur (düz metin aramada nlen çok
        # küçük olduğundan bu sorun yaşanmaz). Gerçek kullanımda blok her
        # zaman VARSAYILAN_BLOK (8 MiB) olduğundan bu yalnızca teorik bir
        # alt sınırdır.
        yol = self.yaz(
            ("\n".join(f"{i};deger{i:03d}" for i in range(200)) + "\n").encode(),
            "rx5.csv")
        b = csvformat.bicim_tespit(yol, baslik_var=False)
        idx = tara(b, stride=10, blok=256)
        beklenen = None
        for blok in (4096, 8192, 20000):
            bulunan = sorted(e.satir for e in
                             self._ara_regex(b, idx, r"deger0[0-4]\d", blok=blok))
            if beklenen is None:
                beklenen = bulunan
            self.assertEqual(bulunan, beklenen, f"blok={blok}")
        self.assertEqual(beklenen, list(range(50)))


# ======================================================================
class TestYukleyici(GeciciDosyaKarisimi, unittest.TestCase):
    """WindowLoader: önbellek, LRU tavanı, öncelik."""

    def setUp(self):
        super().setUp()
        icerik = b"".join(b"%d;v\n" % i for i in range(2000))
        self.bicim = csvformat.bicim_tespit(self.yaz(icerik))
        self.idx = tara(self.bicim, stride=50, blok=512)

    def test_pencere_yuklenir_ve_onbelleklenir(self):
        kuy = queue.Queue()
        yk = loader.WindowLoader(self.bicim, self.idx, kuy, pencere=100, onbellek=4)
        yk.start()
        self.addCleanup(yk.dur)
        self.assertIsNone(yk.onbellekten(3))
        yk.iste(3, loader.ONCELIK_GORUNUR)
        olay = kuy.get(timeout=10)
        self.assertEqual(olay["tur"], loader.OLAY_PENCERE)
        veri = yk.onbellekten(3)
        self.assertIsNotNone(veri)
        self.assertEqual(veri[0][0], "300")
        self.assertEqual(len(veri), 100)

    def test_lru_tavani_asilmaz(self):
        kuy = queue.Queue()
        yk = loader.WindowLoader(self.bicim, self.idx, kuy, pencere=100, onbellek=3)
        yk.start()
        self.addCleanup(yk.dur)
        for pid in range(8):
            yk.iste(pid, loader.ONCELIK_GORUNUR)
        for _ in range(8):
            kuy.get(timeout=10)
        self.assertLessEqual(len(yk._onbellek), 3)
        self.assertLessEqual(yk.onbellek_satir_sayisi(), 300)

    def test_indekslenmemis_pencere_okunmaz(self):
        idx = rowindex.RowIndex(self.bicim.veri_basi, stride=50)  # tarama yok
        kuy = queue.Queue()
        yk = loader.WindowLoader(self.bicim, idx, kuy, pencere=100, onbellek=4)
        yk.start()
        self.addCleanup(yk.dur)
        yk.iste(15, loader.ONCELIK_GORUNUR)     # satır 1500 -- çıpasız
        with self.assertRaises(queue.Empty):
            kuy.get(timeout=1.0)
        self.assertIsNone(yk.onbellekten(15))


# ======================================================================
class TestOturum(GeciciDosyaKarisimi, unittest.TestCase):
    """VeriOturumu: arayüzün gördüğü cephe."""

    def setUp(self):
        super().setUp()
        icerik = b"".join(b"%d_0_x;%d_1_y\n" % (i, i) for i in range(3000))
        self.yol = self.yaz(icerik)

    def test_satirlar_beklemez_ve_sonra_dolar(self):
        oturum = VeriOturumu(self.yol, queue.Queue(), sayfa_satir=1000)
        self.addCleanup(oturum.kapat)
        oturum.baslat()

        ilk = oturum.satirlar(0, 20)
        self.assertEqual(len(ilk), 20)
        self.assertEqual([s for s, _ in ilk], list(range(20)))

        son = __import__("time").time() + 10
        while __import__("time").time() < son:
            dolu = oturum.satirlar(0, 20)
            if all(d is not None for _, d in dolu):
                break
        self.assertTrue(all(d is not None for _, d in dolu))
        self.assertEqual(dolu[0][1][0], "0_0_x")
        self.assertEqual(dolu[19][1][0], "19_0_x")

    def test_sayfa_hesabi(self):
        oturum = VeriOturumu(self.yol, queue.Queue(), sayfa_satir=1000)
        self.addCleanup(oturum.kapat)
        oturum.baslat()
        # İndeks İSTEK ÜZERİNE oluşur; kesin sayı için tam indeksleme gerekir.
        oturum.indeksi_tamamla()
        oturum.tarayici.join(timeout=20)
        self.assertTrue(oturum.kesin_mi())
        self.assertEqual(oturum.toplam_satir(), 3000)
        self.assertEqual(oturum.sayfa_sayisi(), 3)
        self.assertEqual(oturum.sayfa_no(2500), 2)

    def test_kapat_thread_birakmaz(self):
        oturum = VeriOturumu(self.yol, queue.Queue())
        oturum.baslat()
        oturum.kapat()
        self.assertFalse(oturum.tarayici.is_alive())
        self.assertFalse(oturum.yukleyici.is_alive())

    def test_dosya_degisikligi_farkedilir(self):
        oturum = VeriOturumu(self.yol, queue.Queue())
        self.addCleanup(oturum.kapat)
        self.assertFalse(oturum.dosya_degisti_mi())
        with open(self.yol, "ab") as f:
            f.write(b"9999_0_x;9999_1_y\n")
        self.assertTrue(oturum.dosya_degisti_mi())


# ======================================================================
class TestCokBicim(GeciciDosyaKarisimi, unittest.TestCase):
    """JSON / XML / YAML: aynı motor, biçime özgü kayıt çözümlemesi.

    Her testte kayıt içeriği kendi satır numarasını taşır (`<no>_<kolon>_x`),
    böylece indeksin ve rastgele erişimin doğruluğu içerikten doğrulanabilir.
    """

    # -- kaynak dosya üreticileri --------------------------------------
    def json_dosyasi(self, adet=400, sarmalayici=True):
        satirlar = []
        if sarmalayici:
            satirlar.append(b'{"count":%d,"cols":3,"rows":[' % adet)
        for i in range(adet):
            virgul = b"," if (i < adet - 1 or not sarmalayici) else b""
            satirlar.append(b'["%d_0_a","%d_1_b","%d_2_c"]%s' % (i, i, i, virgul))
        if sarmalayici:
            satirlar.append(b"]}")
        return self.yaz(b"\n".join(satirlar) + b"\n", "v.json")

    def xml_dosyasi(self, adet=400):
        satirlar = [b'<?xml version="1.0" encoding="UTF-8"?>',
                    b'<rows count="%d" cols="3">' % adet]
        for i in range(adet):
            satirlar.append(b"<r><c>%d_0_a</c><c>%d_1_b</c><c>%d_2_c</c></r>"
                            % (i, i, i))
        satirlar.append(b"</rows>")
        return self.yaz(b"\n".join(satirlar) + b"\n", "v.xml")

    def yaml_dosyasi(self, adet=400):
        satirlar = [b"count: %d" % adet, b"cols: 3", b"rows:"]
        for i in range(adet):
            satirlar.append(b'  - ["%d_0_a","%d_1_b","%d_2_c"]' % (i, i, i))
        return self.yaz(b"\n".join(satirlar) + b"\n", "v.yaml")

    # -- ortak doğrulama ------------------------------------------------
    def _dogrula(self, yol, adet, kolon_sayisi=3, kuyruk_var=True):
        bicim = csvformat.bicim_tespit(yol)
        self.assertEqual(len(bicim.kolonlar), kolon_sayisi)
        self.assertEqual(bicim.beyan_edilen_kayit, adet)
        if kuyruk_var:
            self.assertLess(bicim.veri_sonu, bicim.boyut,
                            "kuyruk satırı kayıt bölgesinin dışında kalmalı")
        idx = tara(bicim, stride=7, blok=256)
        self.assertTrue(idx.tamam)
        self.assertEqual(idx.toplam_satir, adet,
                         "kuyruk/başlık satırları kayıt sayılmamalı")
        with blockreader.BlockReader(bicim, idx) as r:
            for hedef in (0, 1, 6, 7, 199, adet - 1):
                with self.subTest(kayit=hedef):
                    kayit = r.satir_oku(hedef, 1)[0]
                    self.assertEqual(len(kayit), kolon_sayisi)
                    self.assertEqual(kayit[0], f"{hedef}_0_a")
                    self.assertEqual(kayit[2], f"{hedef}_2_c")
            pencere = r.satir_oku(50, 25)
            self.assertEqual([k[0] for k in pencere],
                             [f"{i}_0_a" for i in range(50, 75)])
        return bicim, idx

    # -- JSON -----------------------------------------------------------
    def test_json_sarmalayicili(self):
        bicim, _ = self._dogrula(self.json_dosyasi(), 400)
        self.assertEqual(bicim.tur, "json")

    def test_json_lines_sarmalayicisiz(self):
        """Saf JSON Lines: başlık/kuyruk yok, her satır bağımsız bir kayıt."""
        yol = self.yaz(b"\n".join(
            b'["%d_0_a","%d_1_b","%d_2_c"]' % (i, i, i) for i in range(120)) + b"\n",
            "s.jsonl")
        bicim = csvformat.bicim_tespit(yol)
        self.assertEqual(bicim.veri_basi, 0)
        idx = tara(bicim, stride=5, blok=256)
        self.assertEqual(idx.toplam_satir, 120)
        with blockreader.BlockReader(bicim, idx) as r:
            self.assertEqual(r.satir_oku(119, 1)[0][0], "119_0_a")

    def test_json_nesne_kayitlari_kolon_adlari(self):
        yol = self.yaz(b"\n".join(
            b'{"ad":"a%d","yas":%d,"sehir":"x"}' % (i, i) for i in range(40)) + b"\n",
            "n.jsonl")
        bicim = csvformat.bicim_tespit(yol)
        self.assertEqual(bicim.kolonlar, ["ad", "yas", "sehir"])
        idx = tara(bicim, stride=5, blok=256)
        with blockreader.BlockReader(bicim, idx) as r:
            self.assertEqual(r.satir_oku(7, 1)[0], ["a7", "7", "x"])

    # -- XML ------------------------------------------------------------
    def test_xml(self):
        bicim, _ = self._dogrula(self.xml_dosyasi(), 400)
        self.assertEqual(bicim.tur, "xml")
        self.assertEqual(bicim.kayit_etiketi, "r")

    def test_xml_farkli_etiketler_kolon_adi_olur(self):
        satirlar = [b"<kok>"]
        for i in range(30):
            satirlar.append(b"<kayit><ad>a%d</ad><yas>%d</yas></kayit>" % (i, i))
        satirlar.append(b"</kok>")
        yol = self.yaz(b"\n".join(satirlar) + b"\n", "e.xml")
        bicim = csvformat.bicim_tespit(yol)
        self.assertEqual(bicim.kayit_etiketi, "kayit")
        self.assertEqual(bicim.kolonlar, ["ad", "yas"])
        idx = tara(bicim, stride=5, blok=256)
        self.assertEqual(idx.toplam_satir, 30)
        with blockreader.BlockReader(bicim, idx) as r:
            self.assertEqual(r.satir_oku(9, 1)[0], ["a9", "9"])

    # -- YAML -----------------------------------------------------------
    def test_yaml(self):
        bicim, _ = self._dogrula(self.yaml_dosyasi(), 400, kuyruk_var=False)
        self.assertEqual(bicim.tur, "yaml")

    def test_yaml_json_olmayan_sozdizimi(self):
        """Tırnaksız skalerler JSON hızlı yoluyla çözülemez; YAML'a düşmeli."""
        satirlar = [b"rows:"]
        for i in range(30):
            satirlar.append(b"  - [a%d, %d, true, null]" % (i, i))
        yol = self.yaz(b"\n".join(satirlar) + b"\n", "g.yaml")
        bicim = csvformat.bicim_tespit(yol)
        idx = tara(bicim, stride=5, blok=256)
        self.assertEqual(idx.toplam_satir, 30)
        with blockreader.BlockReader(bicim, idx) as r:
            self.assertEqual(r.satir_oku(3, 1)[0], ["a3", "3", "true", ""])

    # -- biçimden bağımsız davranışlar ----------------------------------
    def test_arama_her_bicimde_satir_numarasini_bulur(self):
        for ad, uretici in (("json", self.json_dosyasi), ("xml", self.xml_dosyasi),
                            ("yaml", self.yaml_dosyasi)):
            with self.subTest(bicim=ad):
                yol = uretici(300)
                bicim = csvformat.bicim_tespit(yol)
                idx = tara(bicim, stride=10, blok=512)
                desen = finder.Desen("137_1_b", True, bicim.kodlama)
                kuy = queue.Queue()
                job = finder.SearchJob(bicim, idx, desen, kuy, blok=128, geri_bak=32)
                job.start()
                job.join(timeout=30)
                bulunan = []
                while not kuy.empty():
                    olay = kuy.get()
                    if olay["tur"] == finder.OLAY_ESLESME:
                        bulunan += [e.satir for e in olay["eslesmeler"]]
                self.assertEqual(bulunan, [137])

    def test_kuyruk_satirlari_aranmaz(self):
        """Arama kayıt bölgesiyle sınırlıdır; kuyruktaki metin eşleşmemeli."""
        yol = self.xml_dosyasi(50)
        bicim = csvformat.bicim_tespit(yol)
        idx = tara(bicim, stride=10, blok=512)
        desen = finder.Desen("</rows>", True, bicim.kodlama)
        kuy = queue.Queue()
        job = finder.SearchJob(bicim, idx, desen, kuy, blok=128, geri_bak=32)
        job.start()
        job.join(timeout=30)
        bulunan = []
        while not kuy.empty():
            olay = kuy.get()
            if olay["tur"] == finder.OLAY_ESLESME:
                bulunan += olay["eslesmeler"]
        self.assertEqual(bulunan, [])

    def test_satir_basina_bir_kayit_olmayan_dosya_reddedilir(self):
        """Girintili ('pretty') JSON sessizce yanlış bölünmez, açıkça reddedilir."""
        icerik = b'{\n  "rows": [\n    {\n      "ad": "Ali",\n      "yas": 30\n    },\n'
        icerik += b'    {\n      "ad": "Veli",\n      "yas": 41\n    }\n  ]\n}\n'
        with self.assertRaises(csvformat.BicimHatasi) as ctx:
            csvformat.bicim_tespit(self.yaz(icerik, "pretty.json"))
        self.assertIn("satır", str(ctx.exception).lower())

    def test_desteklenmeyen_uzanti(self):
        with self.assertRaises(csvformat.BicimHatasi):
            csvformat.bicim_tespit(self.yaz(b"veri\n", "dosya.parquet"))

    def test_oturum_her_bicimde_calisir(self):
        for ad, uretici in (("json", self.json_dosyasi), ("xml", self.xml_dosyasi),
                            ("yaml", self.yaml_dosyasi)):
            with self.subTest(bicim=ad):
                yol = uretici(250)
                oturum = VeriOturumu(yol, queue.Queue(), sayfa_satir=100)
                self.addCleanup(oturum.kapat)
                oturum.baslat()
                oturum.indeksi_tamamla()
                oturum.tarayici.join(timeout=20)
                self.assertEqual(oturum.toplam_satir(), 250)
                self.assertEqual(oturum.sayfa_sayisi(), 3)


class TestIstegeBagliIndeks(GeciciDosyaKarisimi, unittest.TestCase):
    """İndeks açılışta oluşturulmaz; yalnızca gerekince ve GEREKTİĞİ KADAR."""

    def kur(self, adet=20_000, sayfa=1000, blok=4096):
        icerik = b"".join(b"%d_0_x;%d_1_y\n" % (i, i) for i in range(adet))
        yol = self.yaz(icerik)
        # Küçük tarama bloğu: hedefli taramanın hedefte DURDUĞUNU
        # ölçebilmek için. Gerçek dosyalarda blok 8 MiB'dır ve aşım
        # ihmal edilebilir; burada aşımı görünür kılmamak gerekiyor.
        oturum = VeriOturumu(yol, queue.Queue(), sayfa_satir=sayfa,
                             tarama_blok=blok)
        self.addCleanup(oturum.kapat)
        oturum.baslat()
        return oturum

    def _bekle(self, kosul, sure=15):
        son = __import__("time").time() + sure
        while __import__("time").time() < son:
            if kosul():
                return True
            __import__("time").sleep(0.02)
        return False

    def test_acilista_hic_tarama_yapilmaz(self):
        oturum = self.kur()
        __import__("time").sleep(0.4)
        self.assertEqual(oturum.index.taranan_bayt, 0,
                         "açılışta hiçbir bayt taranmamalı")
        self.assertFalse(oturum.index.tamam)
        self.assertTrue(oturum.tarayici.duraklatildi)

    def test_ilk_kayitlar_indekssiz_okunur(self):
        oturum = self.kur()
        self.assertTrue(self._bekle(
            lambda: all(d is not None for _, d in oturum.satirlar(0, 40))))
        veri = oturum.satirlar(0, 40)
        self.assertEqual(veri[0][1][0], "0_0_x")
        self.assertEqual(veri[39][1][0], "39_0_x")
        self.assertEqual(oturum.index.taranan_bayt, 0,
                         "ilk kayıtlar için tarama gerekmemeli")

    def test_indeks_yalnizca_hedefe_kadar_ilerler(self):
        """Uzak bir kayıt istendiğinde dosyanın TAMAMI değil, o kayda kadarki
        bölüm taranmalı."""
        oturum = self.kur(adet=20_000)
        hedef = 5_000
        self.assertTrue(oturum.indeksi_ilerlet(hedef))
        self.assertTrue(self._bekle(lambda: oturum.index.erisilebilir(hedef)))
        self.assertTrue(self._bekle(lambda: oturum.tarayici.duraklatildi))
        self.assertFalse(oturum.index.tamam, "tam tarama yapılmamalı")
        self.assertGreaterEqual(oturum.index.taranan_satir, hedef)
        self.assertLess(oturum.index.taranan_satir, 20_000,
                        "hedefin çok ötesine geçilmemeli")
        # Okunan bayt da dosyanın tamamından belirgin biçimde az olmalı.
        self.assertLess(oturum.index.taranan_bayt,
                        oturum.bicim.veri_bayt * 0.75,
                        "dosyanın tamamına yakını okunmamalı")
        # Hedeften sonrası hâlâ erişilemez olmalı
        self.assertFalse(oturum.index.erisilebilir(19_000))

    def test_hedefe_varinca_kayit_dogru_okunur(self):
        oturum = self.kur(adet=20_000)
        hedef = 7_777
        oturum.indeksi_ilerlet(hedef + 300)
        self.assertTrue(self._bekle(lambda: oturum.index.erisilebilir(hedef)))
        self.assertTrue(self._bekle(
            lambda: oturum.satirlar(hedef, 1)[0][1] is not None))
        self.assertEqual(oturum.satirlar(hedef, 1)[0][1][0], f"{hedef}_0_x")

    def test_sayfa_icinde_kaydirma_indeksi_tetikler(self):
        """Sayfa içinde ileri kaydırmak da yeni bir bölgeye bakmaktır.

        Bu tetikleme olmadan, ilk çıpa aralığının ötesine kaydıran kullanıcı
        kalıcı olarak '…' yer tutucusu görürdü.
        """
        oturum = self.kur(adet=20_000)
        hedef = 6_500
        # NOT: "ilk çağrıda satırlar henüz boştur" DİYE BİR KURAL YOKTUR.
        # Küçük bir dosyada tarama+okuma bir milisaniyeden kısa sürebilir ve
        # veri daha ilk çağrıda hazır olabilir. Bunu iddia eden bir doğrulama
        # kararsız (flaky) olur; önemli olan, verinin SONUNDA gelmesidir.
        oturum.satirlar(hedef, 40)                 # yalnızca BAKIYORUZ
        self.assertTrue(self._bekle(
            lambda: all(d is not None for _, d in oturum.satirlar(hedef, 40))),
            "kaydırma indeksi tetiklemeli ve satırlar dolmalı")
        dolu = oturum.satirlar(hedef, 40)
        self.assertEqual(dolu[0][1][0], f"{hedef}_0_x")
        self.assertEqual(dolu[39][1][0], f"{hedef + 39}_0_x")
        self.assertFalse(oturum.index.tamam, "tam tarama yapılmamalı")

    def test_tam_indeksleme_istenince_calisir(self):
        oturum = self.kur(adet=20_000)
        self.assertTrue(oturum.indeksi_tamamla())
        oturum.tarayici.join(timeout=20)
        self.assertTrue(oturum.index.tamam)
        self.assertEqual(oturum.index.toplam_satir, 20_000)

    def test_arama_indekssiz_calisir(self):
        """Aramanın indekse hiç ihtiyacı yoktur; kayıt numaralarını kendi sayar."""
        oturum = self.kur(adet=5_000)
        oturum.ara("4321_0_x", duyarli=True)
        eslesmeler = []
        son = __import__("time").time() + 20
        while __import__("time").time() < son:
            try:
                olay = oturum.kuyruk.get(timeout=0.2)
            except queue.Empty:
                continue
            if olay["tur"] == finder.OLAY_ESLESME:
                eslesmeler += [e.satir for e in olay["eslesmeler"]]
            elif olay["tur"] == finder.OLAY_BITTI:
                break
        self.assertEqual(eslesmeler, [4321])
        self.assertEqual(oturum.index.taranan_bayt, 0,
                         "arama için indeks taraması yapılmamalı")

    def test_arama_bitince_istenmeyen_tarama_surdurulmez(self):
        oturum = self.kur(adet=5_000)
        oturum.ara("yok_bu_metin", duyarli=True)
        oturum.arama.join(timeout=20)
        oturum.arama_bitti()
        __import__("time").sleep(0.3)
        self.assertTrue(oturum.tarayici.duraklatildi)
        self.assertEqual(oturum.index.taranan_bayt, 0)


class TestSiralama(GeciciDosyaKarisimi, unittest.TestCase):
    """Top-K, sayfa sıralaması ve liste sıralaması.

    Üçü de bir permütasyon (kayıt başına 8 bayt) gerektirmediği için "diske
    hiçbir şey yazma" kuralı bozulmadan çalışırlar.
    """

    DEGERLER = [507, 12, 990, 3, 771, 44, 615, 128, 899, 256,
                60, 333, 702, 18, 455, 81, 967, 240, 530, 7]

    def kur(self, degerler=None, ad="s.csv"):
        degerler = self.DEGERLER if degerler is None else degerler
        icerik = b"".join(
            ("%d_0_x;%03d;g%d\n" % (i, d, i % 3)).encode()
            for i, d in enumerate(degerler))
        yol = self.yaz(icerik, ad)
        bicim = csvformat.bicim_tespit(yol, baslik_var=False)
        idx = tara(bicim, stride=4, blok=256)
        return bicim, idx, degerler

    def _kos(self, bicim, idx, **kw):
        kuy = queue.Queue()
        kw.setdefault("blok", 256)
        job = sorting.SiralamaJob(bicim, idx, kuy, **kw)
        job.start()
        job.join(timeout=30)
        while not kuy.empty():
            olay = kuy.get()
            if olay["tur"] == sorting.OLAY_HATA:
                raise olay["hata"]
            if olay["tur"] == sorting.OLAY_BITTI:
                return olay
        raise AssertionError("bitti olayı gelmedi")

    # -- Top-K ----------------------------------------------------------
    def test_topk_en_buyuk(self):
        bicim, idx, degerler = self.kur()
        olay = self._kos(bicim, idx, kolon=1, k=5, yon=sorting.AZALAN,
                         tur=sorting.TUR_SAYI, kip=sorting.KIP_TUM_DOSYA)
        beklenen = [i for i, _ in sorted(enumerate(degerler),
                                         key=lambda p: -p[1])[:5]]
        self.assertEqual(olay["kayitlar"], beklenen)
        self.assertEqual(olay["incelenen"], len(degerler))

    def test_topk_en_kucuk(self):
        bicim, idx, degerler = self.kur()
        olay = self._kos(bicim, idx, kolon=1, k=5, yon=sorting.ARTAN,
                         tur=sorting.TUR_SAYI, kip=sorting.KIP_TUM_DOSYA)
        beklenen = [i for i, _ in sorted(enumerate(degerler),
                                         key=lambda p: p[1])[:5]]
        self.assertEqual(olay["kayitlar"], beklenen)

    def test_topk_k_kayit_sayisindan_buyukse_hepsi_gelir(self):
        bicim, idx, degerler = self.kur()
        olay = self._kos(bicim, idx, kolon=1, k=1000, yon=sorting.AZALAN,
                         tur=sorting.TUR_SAYI, kip=sorting.KIP_TUM_DOSYA)
        self.assertEqual(len(olay["kayitlar"]), len(degerler))

    def test_topk_metin_siralamasi(self):
        """Sıfır dolgulu metin, sayısal sırayla aynı sonucu vermelidir."""
        bicim, idx, degerler = self.kur()
        metin = self._kos(bicim, idx, kolon=1, k=5, yon=sorting.AZALAN,
                          tur=sorting.TUR_METIN, kip=sorting.KIP_TUM_DOSYA)
        sayi = self._kos(bicim, idx, kolon=1, k=5, yon=sorting.AZALAN,
                         tur=sorting.TUR_SAYI, kip=sorting.KIP_TUM_DOSYA)
        self.assertEqual(metin["kayitlar"], sayi["kayitlar"])

    def test_topk_sonuclar_indekse_ipucu_birakir(self):
        """Sonuçlar dosyaya dağılmıştır; konumları bilinmezse gösterilemezler."""
        bicim, _idx, _d = self.kur()
        bos = rowindex.RowIndex(bicim.veri_basi, stride=4)   # tarama YOK
        olay = self._kos(bicim, bos, kolon=1, k=5, yon=sorting.AZALAN,
                         tur=sorting.TUR_SAYI, kip=sorting.KIP_TUM_DOSYA)
        self.assertEqual(bos.taranan_bayt, 0, "Top-K indeks taraması istemez")
        for no in olay["kayitlar"]:
            self.assertTrue(bos.erisilebilir(no),
                            f"kayıt {no} ipucusuz gösterilemez")
        with blockreader.BlockReader(bicim, bos) as r:
            ilk = olay["kayitlar"][0]
            self.assertEqual(r.satir_oku(ilk, 1)[0][0], f"{ilk}_0_x")

    # -- Aralık (sayfa) -------------------------------------------------
    def test_aralik_sayfa_sinirlarina_uyar(self):
        bicim, idx, degerler = self.kur()
        olay = self._kos(bicim, idx, kolon=1, yon=sorting.ARTAN,
                         tur=sorting.TUR_SAYI, kip=sorting.KIP_ARALIK,
                         kayit_bas=5, kayit_son=15)
        beklenen = sorted(range(5, 15), key=lambda i: degerler[i])
        self.assertEqual(olay["kayitlar"], beklenen)
        self.assertTrue(all(5 <= x < 15 for x in olay["kayitlar"]))

    def test_aralik_cipadan_baslasa_da_sayfa_disi_alinmaz(self):
        """Tarama sayfadan ÖNCEKİ çıpadan başlar; öncesi elenmelidir."""
        bicim, idx, degerler = self.kur()
        cipa_satir, cipa_ofset = idx.cipa_bul(9)
        self.assertLess(cipa_satir, 9, "test anlamlı olsun diye çıpa önce olmalı")
        olay = self._kos(bicim, idx, kolon=1, yon=sorting.ARTAN,
                         tur=sorting.TUR_SAYI, kip=sorting.KIP_ARALIK,
                         bas_ofset=cipa_ofset, bas_satir=cipa_satir,
                         kayit_bas=9, kayit_son=14)
        self.assertEqual(olay["kayitlar"],
                         sorted(range(9, 14), key=lambda i: degerler[i]))

    # -- Liste ----------------------------------------------------------
    def test_liste_secili_kayitlari_siralar(self):
        bicim, idx, degerler = self.kur()
        secili = [3, 11, 0, 17, 8]
        olay = self._kos(bicim, idx, kolon=1, yon=sorting.AZALAN,
                         tur=sorting.TUR_SAYI, kip=sorting.KIP_LISTE,
                         satir_nolari=secili)
        self.assertEqual(olay["kayitlar"],
                         sorted(secili, key=lambda i: -degerler[i]))

    # -- Okunamayan değerler --------------------------------------------
    def test_okunamayan_degerler_sonuca_alinmaz_ve_sayilir(self):
        yol = self.yaz(b"0_0_x;5;a\n1_0_x;;a\n2_0_x;3;a\n3_0_x;abc;a\n4_0_x;9;a\n",
                       "bos.csv")
        bicim = csvformat.bicim_tespit(yol, baslik_var=False)
        idx = tara(bicim, stride=2, blok=64)
        olay = self._kos(bicim, idx, kolon=1, yon=sorting.AZALAN,
                         tur=sorting.TUR_SAYI, kip=sorting.KIP_ARALIK)
        self.assertEqual(olay["kayitlar"], [4, 0, 2])
        self.assertEqual(olay["bos_anahtar"], 2)

    def test_sayisal_turkce_yazim(self):
        self.assertEqual(sorting.anahtar_degeri("1.234,56", sorting.TUR_SAYI),
                         1234.56)
        self.assertEqual(sorting.anahtar_degeri("1234.56", sorting.TUR_SAYI),
                         1234.56)
        self.assertIsNone(sorting.anahtar_degeri("abc", sorting.TUR_SAYI))
        self.assertIsNone(sorting.anahtar_degeri(None, sorting.TUR_METIN))

    # -- XML hızlı anahtar çıkarıcı --------------------------------------
    def test_xml_hizli_cikarici_genel_yolla_ayni_sonucu_verir(self):
        """Bayt düzeyindeki hızlı yol 17 kat hızlıdır; sonucu aynı olmalı."""
        satirlar = [b'<?xml version="1.0"?>', b"<rows>"]
        for i in range(40):
            satirlar.append(
                ("<r><c>%d_0_a</c><c>deger%d</c><c>%d_2_c</c></r>" % (i, i * 7, i))
                .encode())
        satirlar.append(b"</rows>")
        yol = self.yaz(b"\n".join(satirlar) + b"\n", "h.xml")
        bicim = csvformat.bicim_tespit(yol)
        hizli = sorting.cikarici_olustur(bicim, 1)
        self.assertIsInstance(hizli, sorting.XmlAnahtarCikarici)
        genel = sorting.AnahtarCikarici(bicim, 1)
        for i in range(40):
            ham = ("<r><c>%d_0_a</c><c>deger%d</c><c>%d_2_c</c></r>"
                   % (i, i * 7, i)).encode()
            self.assertEqual(hizli.ham(ham), genel.ham(ham))
            self.assertEqual(hizli.ham(ham), f"deger{i * 7}")

    def test_xml_hizli_cikarici_beklenmedik_yapida_genel_yola_duser(self):
        yol = self.yaz(
            b'<rows>\n<r><c>a</c><c>b</c></r>\n<r><c>c</c><c>d</c></r>\n</rows>\n',
            "d.xml")
        bicim = csvformat.bicim_tespit(yol)
        cikarici = sorting.cikarici_olustur(bicim, 1)
        # Beklenen etiketi içermeyen bir satır: hata vermeden None dönmeli
        self.assertIsNone(cikarici.ham(b"<r><baska>x</baska></r>"))

    def test_xml_farkli_etiketlerde_hizli_yol_kullanilmaz(self):
        satirlar = [b"<kok>"]
        for i in range(30):
            satirlar.append(("<kayit><ad>a%d</ad><yas>%d</yas></kayit>" % (i, i))
                            .encode())
        satirlar.append(b"</kok>")
        yol = self.yaz(b"\n".join(satirlar) + b"\n", "f.xml")
        bicim = csvformat.bicim_tespit(yol)
        cikarici = sorting.cikarici_olustur(bicim, 1)
        self.assertNotIsInstance(cikarici, sorting.XmlAnahtarCikarici)
        self.assertEqual(cikarici.ham(b"<kayit><ad>a7</ad><yas>7</yas></kayit>"),
                         "7")

    # -- Diğer biçimler --------------------------------------------------
    def test_json_ve_yaml_siralanabilir(self):
        for ad, satirlar in (
            ("v.jsonl", [('["%d_0_a","%03d"]' % (i, d)).encode()
                         for i, d in enumerate(self.DEGERLER)]),
            ("v.yaml", [b"rows:"] + [('  - ["%d_0_a","%03d"]' % (i, d)).encode()
                                     for i, d in enumerate(self.DEGERLER)]),
        ):
            with self.subTest(dosya=ad):
                yol = self.yaz(b"\n".join(satirlar) + b"\n", ad)
                bicim = csvformat.bicim_tespit(yol)
                idx = tara(bicim, stride=4, blok=256)
                olay = self._kos(bicim, idx, kolon=1, k=4, yon=sorting.AZALAN,
                                 tur=sorting.TUR_SAYI,
                                 kip=sorting.KIP_TUM_DOSYA)
                beklenen = [i for i, _ in sorted(enumerate(self.DEGERLER),
                                                 key=lambda p: -p[1])[:4]]
                self.assertEqual(olay["kayitlar"], beklenen)

    # -- Oturum cephesi --------------------------------------------------
    def test_oturum_gorunumu(self):
        bicim, _idx, degerler = self.kur(ad="o.csv")
        oturum = VeriOturumu(bicim.yol, queue.Queue(), sayfa_satir=10,
                             tarama_blok=256)
        self.addCleanup(oturum.kapat)
        oturum.baslat()
        self.assertFalse(oturum.gorunum_var())
        oturum.gorunum_ayarla([4, 1, 9])
        self.assertTrue(oturum.gorunum_var())
        self.assertEqual(oturum.gorunum_uzunlugu(), 3)
        veri = oturum.kayitlar([4, 1, 9])
        self.assertEqual([no for no, _ in veri], [4, 1, 9])
        oturum.gorunum_temizle()
        self.assertFalse(oturum.gorunum_var())

    def test_oturum_secimi(self):
        """VeriOturumu her zaman kendi SecimKumesi'ni taşır; değerleri
        kayitlar() ile dağınık olarak okunabilir."""
        bicim, _idx, degerler = self.kur(ad="sec.csv")
        oturum = VeriOturumu(bicim.yol, queue.Queue(), sayfa_satir=10,
                             tarama_blok=256)
        self.addCleanup(oturum.kapat)
        oturum.baslat()
        self.assertEqual(len(oturum.secim), 0)
        oturum.secim.ekle(4)
        oturum.secim.ekle(1)
        oturum.secim.ekle(9)
        self.assertEqual(oturum.secim.liste(), [4, 1, 9])
        son = __import__("time").time() + 15
        while __import__("time").time() < son:
            veri = oturum.kayitlar(oturum.secim.liste())
            if all(d is not None for _, d in veri):
                break
            __import__("time").sleep(0.02)
        self.assertEqual([no for no, _ in veri], [4, 1, 9])
        okunan = {no: int(d[1]) for no, d in veri}
        self.assertEqual(okunan, {4: degerler[4], 1: degerler[1], 9: degerler[9]})
        oturum.secim.cikar(1)
        self.assertEqual(oturum.secim.liste(), [4, 9])


class TestSecim(unittest.TestCase):
    """SecimKumesi: işaretlenen kayıt numaralarının kümesi (Tk'siz)."""

    def test_ekle_cikar_kapsama(self):
        k = selection.SecimKumesi()
        self.assertEqual(len(k), 0)
        self.assertTrue(k.ekle(5))
        self.assertIn(5, k)
        self.assertEqual(len(k), 1)
        self.assertFalse(k.ekle(5), "zaten seçiliyken tekrar eklemek False dönmeli")
        self.assertTrue(k.cikar(5))
        self.assertNotIn(5, k)
        self.assertFalse(k.cikar(5), "seçili değilken çıkarmak False dönmeli")

    def test_degistir_tersine_cevirir(self):
        k = selection.SecimKumesi()
        self.assertTrue(k.degistir(1))     # yok -> ekle -> True
        self.assertIn(1, k)
        self.assertFalse(k.degistir(1))    # var -> çıkar -> False
        self.assertNotIn(1, k)

    def test_eklenme_sirasi_korunur(self):
        k = selection.SecimKumesi()
        for no in (7, 2, 9, 4):
            k.ekle(no)
        self.assertEqual(k.liste(), [7, 2, 9, 4])
        self.assertEqual(k.sirali(), [2, 4, 7, 9])

    def test_temizle(self):
        k = selection.SecimKumesi()
        k.ekle(1); k.ekle(2); k.ekle(3)
        k.temizle()
        self.assertEqual(len(k), 0)
        self.assertEqual(k.liste(), [])
        self.assertNotIn(1, k)

    def test_coklu_ekle(self):
        k = selection.SecimKumesi()
        eklenen, doldu = k.coklu_ekle([1, 2, 3, 2, 1])   # tekrarlar yok sayılır
        self.assertEqual(eklenen, 3)
        self.assertFalse(doldu)
        self.assertEqual(k.sirali(), [1, 2, 3])

    def test_tavan_asilmaz(self):
        k = selection.SecimKumesi()
        eski_tavan = selection.EN_FAZLA_SECIM
        selection.EN_FAZLA_SECIM = 3
        try:
            eklenen, doldu = k.coklu_ekle(range(10))
            self.assertEqual(eklenen, 3)
            self.assertTrue(doldu)
            self.assertEqual(len(k), 3)
            self.assertFalse(k.ekle(999), "tavan dolduğunda yeni ekleme reddedilmeli")
            self.assertIsNone(k.degistir(999),
                              "tavan dolduğunda degistir() None dönmeli")
        finally:
            selection.EN_FAZLA_SECIM = eski_tavan

    def test_gosterilecek_kolonlar_varsayilan_hepsi(self):
        k = selection.SecimKumesi()
        self.assertEqual(k.gosterilecek_kolonlar(5), [0, 1, 2, 3, 4])
        k.kolonlari_ayarla([2, 0])
        self.assertEqual(k.gosterilecek_kolonlar(5), [2, 0])

    def test_bool_ve_iter(self):
        k = selection.SecimKumesi()
        self.assertFalse(bool(k))
        k.ekle(1); k.ekle(2)
        self.assertTrue(bool(k))
        self.assertEqual(list(k), [1, 2])


class TestBase64(unittest.TestCase):
    """Seçili kaydın alanlarından Base64 çözme."""

    # Kaynak dosyadaki gerçek gizli kayıt (CSV satır 16.481.845) ile aynı düzen:
    # her hücre "<satır>_<kolon>_½_<yük>" biçiminde ve yük 7 kolona bölünmüş.
    GERCEK = [
        "16481845_0_½_RXJlbiwgem9ybHVrbGFyxLF",
        "16481845_1_½_uIHNlbmkgeW9yZHXEn3UgYW",
        "16481845_2_½_4sIGFzbMSxbmRhIHphZmVyZ",
        "16481845_3_½_SBlbiDDp29rIHlha2xhxZ90",
        "16481845_4_½_xLHEn8SxbiBhbmTEsXI7IGn",
        "16481845_5_½_Dp2luZGVraSBnw7xjZSBzYX",
        "16481845_6_½_LEsWwgdmUgaWxlcmxlLg==",
    ]
    BEKLENEN = ("Eren, zorlukların seni yorduğu an, aslında zafere en çok "
                "yaklaştığın andır; içindeki güce sarıl ve ilerle.")

    def test_isaretci_kipi_cok_kolonlu(self):
        ayar = b64.Ayar(range(7), onek="½_", onek_kipi=b64.KIP_ISARETCI,
                        uygula=b64.UYGULA_PARCA)
        sonuc = b64.coz(self.GERCEK, ayar)
        self.assertEqual(sonuc.metin, self.BEKLENEN)
        self.assertEqual(sonuc.kodlama, "utf-8")

    def test_otomatik_ayar_gercek_kaydi_cozer(self):
        ayar, sonuc, aciklama = b64.otomatik_ayar(self.GERCEK)
        self.assertIsNotNone(ayar, aciklama)
        self.assertEqual(sonuc.metin, self.BEKLENEN)
        # İşaretçi tek karakter değil, parçaların ORTAK önek soneki olmalı.
        self.assertEqual(ayar.onek, "_½_")
        self.assertEqual(ayar.kolonlar, list(range(7)))

    def test_otomatik_ayar_normal_kayitta_oneri_vermez(self):
        """Rastgele onaltılık metin de geçerli Base64'tür; öneri sunulmamalı."""
        normal = [f"{i}_0_ecac9873c12b109f81ce7a5f924e5ece" for i in range(7)]
        ayar, sonuc, aciklama = b64.otomatik_ayar(normal)
        self.assertIsNone(ayar)
        self.assertIn("bulunamadı", aciklama)

    def test_otomatik_ayar_tek_baytli_kodlamaya_kanmaz(self):
        """cp1254/latin-1 her baytı 'okunabilir' gösterir; öneri ölçütü UTF-8'dir.

        'aaaa…' yükü 0x69 0xA6 0x9A baytlarına çözülür: cp1254'te okunabilir
        bir metin, UTF-8'de ise geçersiz. Öneri verilmemelidir.
        """
        cop = [f"{i}_0_" + "a" * 32 for i in range(7)]
        ayar, sonuc, aciklama = b64.otomatik_ayar(cop)
        self.assertIsNone(ayar, f"çöp veriye öneri verildi: {aciklama}")
        # Aynı veri ELLE çözüldüğünde yine de gösterilebilir olmalı.
        elle = b64.coz(cop, b64.Ayar([0], onek="_0_", onek_kipi=b64.KIP_ISARETCI))
        self.assertEqual(len(elle.veri), 24)

    def test_kolon_sirasi_onemli(self):
        ters = b64.Ayar([1, 0], onek="½_", onek_kipi=b64.KIP_ISARETCI)
        duz = b64.Ayar([0, 1], onek="½_", onek_kipi=b64.KIP_ISARETCI)
        hucreler = ["x_½_SGVsbG8s", "y_½_IER1bnlhIQ=="]
        self.assertEqual(b64.coz(hucreler, duz).metin, "Hello, Dunya!")
        self.assertNotEqual(b64.coz(hucreler, ters).veri,
                            b64.coz(hucreler, duz).veri)

    def test_baslangic_kipi(self):
        ayar = b64.Ayar([0], onek="ON:", onek_kipi=b64.KIP_BASLANGIC)
        self.assertEqual(b64.coz(["ON:SGVsbG8="], ayar).metin, "Hello")
        with self.assertRaises(b64.CozmeHatasi) as ctx:
            b64.coz(["BASKA:SGVsbG8="], ayar)
        self.assertIn("önekle başlamıyor", str(ctx.exception))

    def test_sonek_atilir(self):
        ayar = b64.Ayar([0], sonek="|SON")
        self.assertEqual(b64.coz(["SGVsbG8=|SON"], ayar).metin, "Hello")
        with self.assertRaises(b64.CozmeHatasi):
            b64.coz(["SGVsbG8="], b64.Ayar([0], sonek="|SON"))

    def test_birlesik_uygulama(self):
        ayar = b64.Ayar([0, 1], onek="X", onek_kipi=b64.KIP_BASLANGIC,
                        uygula=b64.UYGULA_BIRLESIK)
        self.assertEqual(b64.coz(["XSGVs", "bG8="], ayar).metin, "Hello")

    def test_isaretci_ilk_ve_son_gecis_farkli(self):
        hucreler = ["a-b-SGVsbG8="]
        ilk = b64.Ayar([0], onek="-", onek_kipi=b64.KIP_ISARETCI,
                       isaretci_son=False)
        son = b64.Ayar([0], onek="-", onek_kipi=b64.KIP_ISARETCI,
                       isaretci_son=True)
        self.assertEqual(b64.coz(hucreler, son).metin, "Hello")
        with self.assertRaises(b64.CozmeHatasi):
            b64.coz(hucreler, ilk)          # "b-SGVsbG8=" -> '-' geçersiz

    def test_eksik_dolgu_tamamlanir(self):
        self.assertEqual(b64.coz(["SGVsbG8"], b64.Ayar([0])).metin, "Hello")

    def test_gecersiz_uzunluk_aciklanir(self):
        with self.assertRaises(b64.CozmeHatasi) as ctx:
            b64.coz(["SGVsbG8Q1"], b64.Ayar([0]))
        self.assertIn("4'e bölümünden", str(ctx.exception))

    def test_alfabe_disi_karakter_aciklanir(self):
        with self.assertRaises(b64.CozmeHatasi) as ctx:
            b64.coz(["SGVs bG8=½½"], b64.Ayar([0], bosluk_at=True))
        self.assertIn("Base64 alfabesine ait olmayan", str(ctx.exception))

    def test_url_guvenli_alfabe(self):
        import base64 as std
        veri = bytes(range(250, 256))
        metin = std.urlsafe_b64encode(veri).decode()
        self.assertIn("_", metin + "_")     # URL alfabesi '-'/'_' kullanır
        sonuc = b64.coz([metin], b64.Ayar([0], url_alfabe=True))
        self.assertEqual(sonuc.veri, veri)

    def test_ikili_veri_metne_cevrilmez(self):
        import base64 as std
        png = b"\x89PNG\r\n\x1a\n" + bytes(range(60))
        metin = std.b64encode(png).decode()
        sonuc = b64.coz([metin], b64.Ayar([0]))
        self.assertEqual(sonuc.veri, png)
        self.assertFalse(sonuc.metin_mi)
        self.assertEqual(b64.tur_tahmini(sonuc.veri), "PNG görüntü")

    def test_bos_kolon_secimi_reddedilir(self):
        with self.assertRaises(b64.CozmeHatasi):
            b64.coz(["SGVsbG8="], b64.Ayar([]))

    def test_olmayan_kolon_aciklanir(self):
        with self.assertRaises(b64.CozmeHatasi) as ctx:
            b64.coz(["SGVsbG8="], b64.Ayar([5]))
        self.assertIn("bu kayıtta yok", str(ctx.exception))

    def test_bosluklar_atilir(self):
        ayar = b64.Ayar([0], bosluk_at=True)
        self.assertEqual(b64.coz(["SGVs bG8=\n"], ayar).metin, "Hello")

    def test_onizleme_metni(self):
        dokum = b64.onizleme_metni(b"AB\x00\xff")
        self.assertIn("41 42 00 ff", dokum)
        self.assertIn("AB..", dokum)

    def test_hata_mesajinda_hucre_icerigi_yok(self):
        """Hata mesajları kaynak veriyi sızdırmamalı."""
        gizli = "COK_GIZLI_DEGER_12345"
        with self.assertRaises(b64.CozmeHatasi) as ctx:
            b64.coz([gizli + "½"], b64.Ayar([0], onek="YOK:",
                                            onek_kipi=b64.KIP_BASLANGIC))
        self.assertNotIn(gizli, str(ctx.exception))


class TestSonDosyalar(unittest.TestCase):
    """Son kullanılan dosyalar listesini sınar (bkz. livedata/son_dosyalar.py).

    Gerçek %APPDATA%'ya dokunmamak için `_dosya_yolu()` geçici bir dosyaya
    yamalanır (monkeypatch).
    """

    def setUp(self):
        self._gecici_dizin = tempfile.mkdtemp()
        self._kayit_yolu = os.path.join(self._gecici_dizin, "son_dosyalar.json")
        self._orijinal = son_dosyalar._dosya_yolu
        son_dosyalar._dosya_yolu = lambda: self._kayit_yolu

        self.p1 = os.path.join(self._gecici_dizin, "a.csv")
        self.p2 = os.path.join(self._gecici_dizin, "b.csv")
        for p in (self.p1, self.p2):
            open(p, "w").close()

    def tearDown(self):
        son_dosyalar._dosya_yolu = self._orijinal
        shutil.rmtree(self._gecici_dizin, ignore_errors=True)

    def test_bos_baslar(self):
        self.assertEqual(son_dosyalar.oku(), [])

    def test_ekleme_sirasi_en_yeni_basta(self):
        son_dosyalar.ekle(self.p1)
        son_dosyalar.ekle(self.p2)
        self.assertEqual(son_dosyalar.oku(), [self.p2, self.p1])

    def test_tekrar_eklenen_one_tasinir(self):
        son_dosyalar.ekle(self.p1)
        son_dosyalar.ekle(self.p2)
        son_dosyalar.ekle(self.p1)
        self.assertEqual(son_dosyalar.oku(), [self.p1, self.p2])

    def test_silinen_dosya_listeden_suzulur(self):
        son_dosyalar.ekle(self.p1)
        son_dosyalar.ekle(self.p2)
        os.remove(self.p2)
        self.assertEqual(son_dosyalar.oku(), [self.p1])

    def test_en_fazla_sinirini_asmaz(self):
        yollar = []
        for i in range(son_dosyalar.EN_FAZLA + 5):
            p = os.path.join(self._gecici_dizin, f"f{i}.csv")
            open(p, "w").close()
            yollar.append(p)
            son_dosyalar.ekle(p)
        self.assertEqual(len(son_dosyalar.oku()), son_dosyalar.EN_FAZLA)
        # En son eklenenler korunmalı (en yeniden en eskiye).
        self.assertEqual(son_dosyalar.oku()[0], yollar[-1])

    def test_temizle(self):
        son_dosyalar.ekle(self.p1)
        son_dosyalar.temizle()
        self.assertEqual(son_dosyalar.oku(), [])


class TestBirimler(unittest.TestCase):
    def test_sayi(self):
        self.assertEqual(units.sayi(1234567), "1.234.567")

    def test_bayt(self):
        self.assertEqual(units.bayt(512), "512 B")
        self.assertEqual(units.bayt(1536), "1,5 KB")

    def test_sure(self):
        self.assertEqual(units.sure(0.0431), "43,1 ms")
        self.assertEqual(units.sure(91.4), "1 dk 31 sn")

    def test_yuzde_sinirlari(self):
        self.assertEqual(units.yuzde(5, 0), 0.0)
        self.assertEqual(units.yuzde(10, 10), 100.0)


class TestWebYayini(unittest.TestCase):
    """Seçili verilerin localhost'ta yayınlanmasını sınar (bkz. webserver.py)."""

    def test_sayfa_uret_hucreleri_kacar_ve_eksik_kayidi_atlar(self):
        govde = webserver.sayfa_uret(
            "Başlık", ["ad", "not"], [1, 2, 3],
            {1: ["<script>", "a&b"], 3: ["x", "y"]})
        html_metni = govde.decode("utf-8")
        self.assertIn("&lt;script&gt;", html_metni)
        self.assertIn("a&amp;b", html_metni)
        # Kayıt 2 toplanmamış (veri sözlüğünde yok) -- satır atlanmalı.
        # (Başlık satırı da bir <tr> içerdiğinden gövdedeki <td class="no">
        #  sayısı üzerinden -- yani veri satırı sayısı üzerinden -- sayıyoruz.)
        self.assertEqual(html_metni.count('<td class="no">'), 2)

    def test_baslat_bellekten_sunar_ve_diske_yazmaz(self):
        govde = webserver.sayfa_uret("T", ["a"], [1], {1: ["deger"]})
        yayin = webserver.WebYayini()
        try:
            self.assertFalse(yayin.calisiyor_mu())
            yayin.baslat(govde)
            self.assertTrue(yayin.calisiyor_mu())
            adres = yayin.adres()
            self.assertTrue(adres.startswith("http://127.0.0.1:"))
            with urllib.request.urlopen(adres, timeout=3) as yanit:
                self.assertEqual(yanit.read(), govde)
        finally:
            yayin.durdur()
        self.assertFalse(yayin.calisiyor_mu())

    def test_durdur_sonrasi_erisilemez(self):
        govde = webserver.sayfa_uret("T", ["a"], [1], {1: ["x"]})
        yayin = webserver.WebYayini()
        yayin.baslat(govde)
        adres = yayin.adres()
        yayin.durdur()
        with self.assertRaises(OSError):
            urllib.request.urlopen(adres, timeout=1)

    def test_yeniden_baslatma_oncekini_durdurur(self):
        yayin = webserver.WebYayini()
        try:
            yayin.baslat(webserver.sayfa_uret("A", ["a"], [1], {1: ["x"]}))
            ilk_adres = yayin.adres()
            yayin.baslat(webserver.sayfa_uret("B", ["a"], [1], {1: ["y"]}))
            ikinci_adres = yayin.adres()
            with urllib.request.urlopen(ikinci_adres, timeout=3) as yanit:
                self.assertIn(b"y", yanit.read())
            if ilk_adres != ikinci_adres:
                with self.assertRaises(OSError):
                    urllib.request.urlopen(ilk_adres, timeout=1)
        finally:
            yayin.durdur()

    def test_sayfa_disa_aktarim_dugmelerini_icerir(self):
        govde = webserver.sayfa_uret("T", ["a"], [1], {1: ["x"]})
        html_metni = govde.decode("utf-8")
        self.assertIn("/disa-aktar/excel", html_metni)
        self.assertIn("/disa-aktar/word", html_metni)
        self.assertIn("/disa-aktar/pdf", html_metni)

    def test_disa_aktarim_yoksa_dugmeler_gizli(self):
        govde = webserver.sayfa_uret("T", ["a"], [1], {1: ["x"]},
                                     disa_aktarim_var=False)
        self.assertNotIn(b"/disa-aktar/", govde)

    def test_disa_aktar_rotalari_dosya_indirtir(self):
        kolon_adlari = ["ad", "sehir"]
        nolar = [0, 1]
        veri = {0: ["Ayşe", "İstanbul"], 1: ["Ali", "Muğla"]}
        govde = webserver.sayfa_uret("Başlık", kolon_adlari, nolar, veri)
        baglam = {"baslik": "Başlık", "kolon_adlari": kolon_adlari,
                  "nolar": nolar, "veri": veri}
        yayin = webserver.WebYayini()
        try:
            yayin.baslat(govde, baglam)
            taban = yayin.adres()

            with urllib.request.urlopen(taban + "disa-aktar/excel", timeout=3) as r:
                self.assertEqual(
                    r.headers["Content-Type"],
                    "application/vnd.openxmlformats-officedocument."
                    "spreadsheetml.sheet")
                self.assertIn("attachment", r.headers["Content-Disposition"])
                icerik = r.read()
            with zipfile.ZipFile(io.BytesIO(icerik)) as z:
                self.assertIsNone(z.testzip())

            with urllib.request.urlopen(taban + "disa-aktar/word", timeout=3) as r:
                self.assertIn("wordprocessingml", r.headers["Content-Type"])
                icerik = r.read()
            with zipfile.ZipFile(io.BytesIO(icerik)) as z:
                self.assertIsNone(z.testzip())

            with urllib.request.urlopen(taban + "disa-aktar/pdf", timeout=3) as r:
                self.assertEqual(r.headers["Content-Type"], "application/pdf")
                icerik = r.read()
            self.assertTrue(icerik.startswith(b"%PDF-1.4"))
        finally:
            yayin.durdur()

    def test_baglam_yokken_disa_aktar_yolu_404_doner(self):
        govde = webserver.sayfa_uret("T", ["a"], [1], {1: ["x"]})
        yayin = webserver.WebYayini()
        try:
            yayin.baslat(govde)  # disa_aktar_baglami verilmedi
            taban = yayin.adres()
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.urlopen(taban + "disa-aktar/excel", timeout=3)
            self.assertEqual(ctx.exception.code, 404)
        finally:
            yayin.durdur()


class TestDisaAktar(unittest.TestCase):
    """Excel/Word/PDF üretimini doğrudan sınar (bkz. exporters.py)."""

    KOLONLAR = ["ad", "yaş", "not"]
    NOLAR = [0, 1, 2, 3]
    VERI = {
        0: ["Çağla", "30", "<script>&\"tırnak\""],
        1: ["Şükrü İşık", "45", "normal"],
        # 2 kasıtlı eksik -- toplanmamış kayıt, çıktıda atlanmalı.
        3: ["Öznur Muğla", "22", ""],
    }

    def test_xlsx_gecerli_zip_ve_xml_uretir(self):
        veri = exporters.xlsx_uret("Başlık Ğüzel", self.KOLONLAR, self.NOLAR, self.VERI)
        with zipfile.ZipFile(io.BytesIO(veri)) as z:
            self.assertIsNone(z.testzip())
            gerekli = {"[Content_Types].xml", "_rels/.rels", "xl/workbook.xml",
                      "xl/_rels/workbook.xml.rels", "xl/styles.xml",
                      "xl/worksheets/sheet1.xml"}
            self.assertTrue(gerekli.issubset(set(z.namelist())))
            for ad in gerekli:
                ET.fromstring(z.read(ad))  # XML olarak ayrıştırılabilmeli
            sayfa = z.read("xl/worksheets/sheet1.xml").decode("utf-8")
        self.assertIn("Çağla", sayfa)
        self.assertIn("&lt;script&gt;", sayfa)
        # Kayıt 2 toplanmamış -- 4 veri satırı değil 3 olmalı (+1 başlık).
        self.assertEqual(sayfa.count("<row "), 4)

    def test_docx_gecerli_zip_ve_xml_uretir(self):
        veri = exporters.docx_uret("Başlık", self.KOLONLAR, self.NOLAR, self.VERI)
        with zipfile.ZipFile(io.BytesIO(veri)) as z:
            self.assertIsNone(z.testzip())
            gerekli = {"[Content_Types].xml", "_rels/.rels", "word/document.xml"}
            self.assertTrue(gerekli.issubset(set(z.namelist())))
            for ad in gerekli:
                ET.fromstring(z.read(ad))
            belge = z.read("word/document.xml").decode("utf-8")
        self.assertIn("Çağla", belge)
        self.assertIn("&lt;script&gt;", belge)
        self.assertEqual(belge.count("<w:tr>"), 4)

    def test_pdf_gecerli_yapida_coklu_sayfa_uretir(self):
        # 300 kayıt -- tek sayfaya sığmayacağından sayfalama sınanır.
        kolonlar = ["ad", "not"]
        nolar = list(range(300))
        veri = {i: [f"Kişi{i}", "değer " * 6] for i in nolar}
        pdf = exporters.pdf_uret("Çok Sayfalı", kolonlar, nolar, veri)
        self.assertTrue(pdf.startswith(b"%PDF-1.4"))
        self.assertTrue(pdf.rstrip().endswith(b"%%EOF"))
        # xref tablosunun işaret ettiği ofset gerçekten "xref" ile başlamalı.
        konum = pdf.rfind(b"startxref")
        ofset = int(pdf[konum + len(b"startxref"):].split()[0])
        self.assertEqual(pdf[ofset:ofset + 4], b"xref")
        # Birden fazla /Type /Page nesnesi olmalı (sayfalama gerçekleşmiş).
        self.assertGreater(pdf.count(b"/Type /Page "), 1)

    def test_pdf_turkce_harfleri_cp1252ye_sigdirir(self):
        pdf = exporters.pdf_uret("Çiçek", ["ad"], [0],
                                 {0: ["Iğdır Şükrü Öğretmen"]})
        # ğ/ş/ı gibi WinAnsiEncoding dışı harfler ASCII'ye çevrilmiş olmalı
        # (ü/ö gibi cp1252'de VAR olan harfler ise aynen -- bayt olarak --
        # korunur, bkz. exporters._TR_PDF_CEVIRI).
        self.assertIn("Igdir S\xfckr\xfc \xd6gretmen".encode("cp1252"), pdf)
        self.assertNotIn("ğ".encode("utf-8"), pdf)
        self.assertNotIn("ş".encode("utf-8"), pdf)

    def test_pdf_bos_secim_hata_vermez(self):
        pdf = exporters.pdf_uret("Boş", ["a"], [], {})
        self.assertTrue(pdf.startswith(b"%PDF-1.4"))


if __name__ == "__main__":
    unittest.main()
