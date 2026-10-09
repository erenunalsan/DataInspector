"""gorunum (web arayüzü) için birim testleri.

Veritabanı kullanılmadığından (`DATABASES = {}`, bkz. webproj/settings.py)
`SimpleTestCase` kullanılır -- `TestCase` bir veritabanı transaction'ı
gerektirir ve burada yoktur.
"""
import os

from django.test import Client, SimpleTestCase


class TestGozat(SimpleTestCase):
    """Dosya sistemi gezinme uç noktasını (`/api/gozat`) sınar.

    Asıl hata: ".." ile YALNIZCA bir dizinin üst dizinine çıkılabiliyordu;
    bir kökten (`C:\\`) başka bir sürücüye (`D:\\`) hiçbir şekilde
    geçilemiyordu (`os.path.dirname("C:\\")` kendisini döner). Düzeltme,
    bağlı sürücüleri ayrı bir liste olarak sunar ve doğrudan herhangi bir
    yola atlanmasına izin verir.
    """
    client_class = Client

    def test_surucu_listesi_en_az_c_icerir(self):
        r = self.client.get("/api/gozat")
        self.assertEqual(r.status_code, 200)
        veri = r.json()
        self.assertIn("surucular", veri)
        if os.name == "nt":
            self.assertIn("C:\\", veri["surucular"])
            # Birden fazla sürücü varsa hepsi "X:\" biçiminde olmalı.
            for s in veri["surucular"]:
                self.assertRegex(s, r"^[A-Z]:\\$")

    def test_baska_bir_koke_dogrudan_atlanabilir(self):
        """Sürücü listesindeki HERHANGİ bir sürücüye `dizin` parametresiyle
        doğrudan gidilebildiğini doğrular (".." zincirlemeye gerek yok)."""
        ilk = self.client.get("/api/gozat").json()
        for surucu in ilk["surucular"]:
            r = self.client.get(f"/api/gozat?dizin={surucu}")
            self.assertEqual(r.status_code, 200, f"{surucu} açılamadı")
            veri = r.json()
            self.assertEqual(os.path.normcase(veri["dizin"]),
                             os.path.normcase(surucu))
            # Bir sürücü kökünde ".." anlamsızdır -- yukarı çıkılamaz.
            self.assertIsNone(veri["ust"])

    def test_olmayan_dizin_404_doner(self):
        r = self.client.get("/api/gozat?dizin=Z:\\kesinlikle-olmayan-bir-yol-xyz")
        self.assertEqual(r.status_code, 404)
