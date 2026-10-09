"""Ekrandaki konsol alanı: zaman damgalı, seviyeli bilgilendirme akışı.

Kullanıcı büyük bir dosyayla çalışırken "şu an ne oluyor?" sorusunun cevabını
sürekli görebilmelidir. Konsol; açılan dosyayı, tespit edilen biçimi, indeks
taramasının ilerleyişini, her sayfa/pencere yüklemesinin süresini, arama
sonuçlarını ve hataları tek bir yerde toplar.

Satır sayısı sınırlıdır (varsayılan 3000): uzun bir oturumda konsolun kendisi
belleği doldurmasın diye en eski satırlar atılır.
"""
import time
import tkinter as tk
from tkinter import ttk

from . import renkler

EN_FAZLA_SATIR = 3000


class KonsolAlani(ttk.Frame):
    def __init__(self, parent, **kw):
        super().__init__(parent, **kw)

        ust = ttk.Frame(self)
        ust.grid(row=0, column=0, sticky="ew")
        ttk.Label(ust, text="Konsol", font=("Segoe UI", 9, "bold")).pack(side="left")
        self._otomatik = tk.BooleanVar(value=True)
        ttk.Checkbutton(ust, text="Otomatik kaydır",
                        variable=self._otomatik).pack(side="right", padx=4)
        ttk.Button(ust, text="Kopyala", width=9,
                   command=self.panoya_kopyala).pack(side="right", padx=2)
        ttk.Button(ust, text="Temizle", width=9,
                   command=self.temizle).pack(side="right", padx=2)

        self.metin = tk.Text(self, height=5, wrap="none", state="disabled",
                             font=("Consolas", 9),
                             relief="solid", borderwidth=1)
        kaydir = ttk.Scrollbar(self, orient="vertical", command=self.metin.yview)
        self.metin.configure(yscrollcommand=kaydir.set)
        self.metin.grid(row=1, column=0, sticky="nsew")
        kaydir.grid(row=1, column=1, sticky="ns")

        self.rowconfigure(1, weight=1)
        self.columnconfigure(0, weight=1)

        self.metin.tag_configure("kalin", font=("Consolas", 9, "bold"))
        self.tema_yenile()

        self._satir_sayisi = 0

    # ------------------------------------------------------------------
    def tema_yenile(self):
        """Açık/koyu tema değiştiğinde metin zemini ve satır renklerini
        tazeler (bkz. `renkler.py` -- bu renkler sabit değil, o anki temaya
        göre hesaplanır)."""
        self.metin.configure(background=renkler.konsol_zemin(),
                             foreground=renkler.konsol_metin(),
                             insertbackground=renkler.konsol_metin())
        self.metin.tag_configure("zaman", foreground=renkler.ikincil())
        for ad, (_, renk) in renkler.konsol_seviyeleri().items():
            self.metin.tag_configure(ad, foreground=renk)

    # ------------------------------------------------------------------
    def yaz(self, mesaj, seviye="bilgi", kalin=False):
        """Konsola bir satır ekler. YALNIZCA Tk ana thread'inden çağrılmalıdır."""
        isaret, _ = renkler.konsol_seviyeleri().get(seviye, renkler.konsol_seviyeleri()["bilgi"])
        damga = time.strftime("%H:%M:%S")
        self.metin.configure(state="normal")
        self.metin.insert("end", f"{damga} ", ("zaman",))
        etiketler = [seviye] + (["kalin"] if kalin else [])
        self.metin.insert("end", f"[{isaret}] {mesaj}\n", tuple(etiketler))
        self._satir_sayisi += 1
        if self._satir_sayisi > EN_FAZLA_SATIR:
            fazla = self._satir_sayisi - EN_FAZLA_SATIR
            self.metin.delete("1.0", f"{fazla + 1}.0")
            self._satir_sayisi = EN_FAZLA_SATIR
        self.metin.configure(state="disabled")
        if self._otomatik.get():
            self.metin.see("end")

    def bolum(self, baslik):
        """Görsel ayraçlı bir başlık satırı."""
        self.yaz("─" * 8 + " " + baslik + " " + "─" * 8, "islem", kalin=True)

    def temizle(self):
        self.metin.configure(state="normal")
        self.metin.delete("1.0", "end")
        self.metin.configure(state="disabled")
        self._satir_sayisi = 0

    def panoya_kopyala(self):
        icerik = self.metin.get("1.0", "end-1c")
        self.clipboard_clear()
        self.clipboard_append(icerik)
        self.yaz(f"Konsol içeriği panoya kopyalandı ({len(icerik)} karakter).",
                 "tamam")
