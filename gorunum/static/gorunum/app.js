// livedata web arayüzü — istemci tarafı.
//
// Bu dosya, Tkinter sürümündeki (`livedata/ui/app.py` + `virtualtable.py`)
// UI mantığının tarayıcı karşılığıdır. İş mantığı YOKTUR -- yalnızca
// sunucudaki API'yi çağırır ve sonucu DOM'a çizer. Üçüncü parti kütüphane
// KULLANILMAZ (proje genelindeki "harici bağımlılık yok" ilkesiyle
// tutarlı): sanal tablo da dâhil her şey el yazımı, sade JS'tir.
"use strict";

const SATIR_H = 26;          // px -- CSS'teki --satir-h ile aynı olmalı
const TAMPON_SATIR = 10;     // görünür alanın üstünde/altında önceden çekilecek satır
const DURUM_ARALIGI_MS = 400;
const ISARET_GENISLIK = 30;
const SATIRNO_GENISLIK = 90;

// ---------------------------------------------------------------------
// Durum (state)
// ---------------------------------------------------------------------
const S = {
  oid: null,
  kolonlar: [],
  kolonGenislikleri: [],
  gorunurKolonlar: null,   // null = tüm kolonlar; aksi hâlde gösterilecek indeksler
  taban: 0,
  sayfaSatir: 100000,
  toplamSatir: 0,
  kesin: false,
  gorunumVar: false,
  seciliSayi: 0,

  konsolSonId: 0,
  eslesmeSonId: 0,
  eslesmeToplam: 0,

  sonBas: 0,
  sonSatirlar: [],       // en son çizilen pencere: [[no, deger|null, secili], ...]
  bekleyenVar: false,

  pendingGit: null,      // satıra git: hedef henüz erişilebilir değilse
  aktifSatir: null,      // ayrıntı kalıbında gösterilen satır
  gozatDizin: null,
  disaAktarToken: null,
  disaAktarZamanlayici: null,
  dosyaDegistiUyarildi: false,
};

// ---------------------------------------------------------------------
// API yardımcıları
// ---------------------------------------------------------------------
async function apiGet(yol) {
  const r = await fetch(yol);
  const veri = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(veri.hata || `HTTP ${r.status}`);
  return veri;
}

async function apiPost(yol, govde) {
  const r = await fetch(yol, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(govde || {}),
  });
  const veri = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(veri.hata || `HTTP ${r.status}`);
  return veri;
}

function el(sec) { return document.querySelector(sec); }
function tumu(sec) { return Array.from(document.querySelectorAll(sec)); }

// ---------------------------------------------------------------------
// Toast bildirimleri + onay kalıbı
//
// Tarayıcının native `alert()`/`confirm()` kutuları hem arayüzü BLOKE
// eder hem de sayfanın temasından habersizdir (koyu modda bile beyaz
// kalır). Bunun yerine: hata/bilgi mesajları için kendiliğinden kaybolan
// bir toast, tek bir onay gereken yıkıcı eylemler (ör. seçimi temizleme)
// için ise sayfanın kendi modal sistemini kullanan `onayIste()`.
// ---------------------------------------------------------------------
function toast(mesaj, tur = "bilgi", sureMs = 4000) {
  const alan = el("#toast-alan");
  const div = document.createElement("div");
  div.className = "toast" + (tur === "bilgi" ? "" : " " + tur);
  div.textContent = mesaj;
  alan.appendChild(div);
  setTimeout(() => {
    div.classList.add("kapaniyor");
    setTimeout(() => div.remove(), 200);
  }, sureMs);
}

function onayIste(mesaj) {
  return new Promise((cozul) => {
    el("#onay-mesaj").textContent = mesaj;
    const modal = el("#onay-modal");
    modal.hidden = false;
    const temizle = (sonuc) => {
      modal.hidden = true;
      evet.removeEventListener("click", evetTikla);
      hayir.removeEventListener("click", hayirTikla);
      document.removeEventListener("keydown", kacTus);
      cozul(sonuc);
    };
    const evet = el("#onay-evet");
    const hayir = el("#onay-hayir");
    const evetTikla = () => temizle(true);
    const hayirTikla = () => temizle(false);
    const kacTus = (e) => { if (e.key === "Escape") temizle(false); };
    evet.addEventListener("click", evetTikla);
    hayir.addEventListener("click", hayirTikla);
    document.addEventListener("keydown", kacTus);
  });
}

function sayiFormat(n) {
  return Math.round(n).toString().replace(/\B(?=(\d{3})+(?!\d))/g, ".");
}

// ---------------------------------------------------------------------
// Şerit sekmeleri
// ---------------------------------------------------------------------
tumu(".sekme-baslik").forEach((btn) => {
  btn.addEventListener("click", () => {
    tumu(".sekme-baslik").forEach((b) => b.classList.remove("aktif"));
    tumu(".sekme-govde").forEach((g) => g.classList.remove("aktif"));
    btn.classList.add("aktif");
    el(`.sekme-govde[data-sekme-govde="${btn.dataset.sekme}"]`).classList.add("aktif");
  });
});
document.addEventListener("keydown", (e) => {
  if (!e.ctrlKey) return;
  const harita = { "1": "dosya", "2": "ana", "3": "arama", "4": "siralama", "5": "secim" };
  if (harita[e.key]) {
    e.preventDefault();
    el(`.sekme-baslik[data-sekme="${harita[e.key]}"]`).click();
  }
});
tumu(".alt-baslik").forEach((btn) => {
  btn.addEventListener("click", () => {
    tumu(".alt-baslik").forEach((b) => b.classList.remove("aktif"));
    tumu(".alt-govde").forEach((g) => g.classList.remove("aktif"));
    btn.classList.add("aktif");
    el(`.alt-govde[data-alt-govde="${btn.dataset.alt}"]`).classList.add("aktif");
  });
});
tumu(".modal-kapat").forEach((btn) => {
  btn.addEventListener("click", () => { el("#" + btn.dataset.kapat).hidden = true; });
});

// ---------------------------------------------------------------------
// Açık/koyu tema
//
// Tercih localStorage'da tutulur (sayfa `<head>`indeki satır içi betik,
// DOM çizilmeden ÖNCE bu tercihi uygular -- aksi hâlde koyu tema seçiliyken
// bir an açık tema görünüp sonra koyuya geçmesi gibi rahatsız edici bir
// "temanın titremesi" olurdu). Sistem tercihi (prefers-color-scheme),
// kullanıcı HİÇ seçim yapmadıysa devreye girer (bkz. app.css).
// ---------------------------------------------------------------------
function koyuMu() {
  const secim = document.documentElement.dataset.tema;
  if (secim === "koyu") return true;
  if (secim === "acik") return false;
  return window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches;
}
function temaDugmesiniGuncelle() {
  el("#tema-dugme").textContent = koyuMu() ? "☀ Açık Tema" : "🌙 Koyu Tema";
}
el("#tema-dugme").addEventListener("click", () => {
  const yeni = koyuMu() ? "acik" : "koyu";
  document.documentElement.dataset.tema = yeni;
  localStorage.setItem("livedata-tema", yeni);
  temaDugmesiniGuncelle();
});
temaDugmesiniGuncelle();

// ---------------------------------------------------------------------
// Konsol
// ---------------------------------------------------------------------
function konsolaYaz(metin, seviye) {
  const div = document.createElement("div");
  div.className = "konsol-" + (seviye || "bilgi");
  const simdi = new Date();
  const saat = simdi.toTimeString().slice(0, 8);
  div.textContent = `${saat} [${(seviye || "bilgi")[0]}] ${metin}`;
  const alan = el("#konsol-alan");
  const dipteydi = alan.scrollHeight - alan.scrollTop - alan.clientHeight < 30;
  alan.appendChild(div);
  if (dipteydi) alan.scrollTop = alan.scrollHeight;
}
function konsolBolum(baslik) {
  const div = document.createElement("div");
  div.className = "konsol-bolum";
  div.textContent = "──── " + baslik + " ────";
  el("#konsol-alan").appendChild(div);
}

// ---------------------------------------------------------------------
// Dosya seç (gözat) kalıbı
// ---------------------------------------------------------------------
function gozatAc() {
  el("#gozat-modal").hidden = false;
  gozatYukle(S.gozatDizin);
}
el("#dosya-sec-dugme").addEventListener("click", gozatAc);
el("#bos-durum-dugme").addEventListener("click", gozatAc);

// ---------------------------------------------------------------------
// Son kullanılan dosyalar (açılır panel)
// ---------------------------------------------------------------------
el("#son-dosyalar-dugme").addEventListener("click", async (e) => {
  e.stopPropagation();
  const panel = el("#son-dosyalar-acilir");
  if (!panel.hidden) { panel.hidden = true; return; }
  await sonDosyalariYukle();
  panel.hidden = false;
});
document.addEventListener("click", (e) => {
  const panel = el("#son-dosyalar-acilir");
  if (!panel.hidden && !panel.contains(e.target) && e.target.id !== "son-dosyalar-dugme") {
    panel.hidden = true;
  }
});

async function sonDosyalariYukle() {
  const panel = el("#son-dosyalar-acilir");
  panel.innerHTML = "";
  try {
    const veri = await apiGet("/api/son-dosyalar");
    if (!veri.dosyalar.length) {
      panel.innerHTML = '<div class="son-dosyalar-bos">Henüz dosya açılmadı.</div>';
      return;
    }
    veri.dosyalar.forEach((yol) => {
      const btn = document.createElement("button");
      btn.className = "son-dosyalar-satir";
      btn.textContent = yol;
      btn.title = yol;
      btn.addEventListener("click", () => {
        panel.hidden = true;
        el("#yol-kutu").value = yol;
        dosyayiAc();
      });
      panel.appendChild(btn);
    });
    const temizleBtn = document.createElement("button");
    temizleBtn.className = "son-dosyalar-temizle";
    temizleBtn.textContent = "Listeyi temizle";
    temizleBtn.addEventListener("click", async (e) => {
      e.stopPropagation();
      await apiPost("/api/son-dosyalar/temizle");
      panel.hidden = true;
    });
    panel.appendChild(temizleBtn);
  } catch (e) {
    panel.innerHTML = `<div class="son-dosyalar-bos">${e.message}</div>`;
  }
}

el("#gozat-yol-git").addEventListener("click", () => {
  const yol = el("#gozat-yol-kutu").value.trim();
  if (yol) gozatYukle(yol);
});
el("#gozat-yol-kutu").addEventListener("keydown", (e) => {
  if (e.key === "Enter") el("#gozat-yol-git").click();
});

async function gozatYukle(dizin) {
  try {
    const q = dizin ? `?dizin=${encodeURIComponent(dizin)}` : "";
    const veri = await apiGet("/api/gozat" + q);
    S.gozatDizin = veri.dizin;
    el("#gozat-dizin").textContent = veri.dizin;
    el("#gozat-yol-kutu").value = veri.dizin;

    // Sürücüler (C:, D:, ...): ".." ile bir kökten (C:\) başka bir
    // sürücüye asla çıkılamaz -- bu yüzden ayrı, doğrudan atlanabilir bir
    // satır olarak gösterilir.
    const surucuAlan = el("#gozat-surucu-satiri");
    surucuAlan.innerHTML = "";
    (veri.surucular || []).forEach((s) => {
      const btn = document.createElement("button");
      btn.textContent = "💽 " + s;
      if (veri.dizin.toUpperCase().startsWith(s.toUpperCase())) {
        btn.classList.add("aktif-surucu");
      }
      btn.addEventListener("click", () => gozatYukle(s));
      surucuAlan.appendChild(btn);
    });

    const liste = el("#gozat-liste");
    liste.innerHTML = "";
    if (veri.ust) {
      liste.appendChild(gozatSatirOlustur("⬆  .. (üst dizin)", "", () => gozatYukle(veri.ust)));
    }
    veri.dizinler.forEach((ad) => {
      const tamYol = veri.dizin.replace(/[\\/]+$/, "") + "\\" + ad;
      liste.appendChild(gozatSatirOlustur("📁 " + ad, "", () => gozatYukle(tamYol)));
    });
    veri.dosyalar.forEach((d) => {
      const tamYol = veri.dizin.replace(/[\\/]+$/, "") + "\\" + d.ad;
      liste.appendChild(gozatSatirOlustur("📄 " + d.ad, d.boyut_metin, () => {
        el("#yol-kutu").value = tamYol;
        el("#gozat-modal").hidden = true;
      }));
    });
  } catch (e) {
    el("#gozat-liste").innerHTML = `<div class="gozat-satir">${e.message}</div>`;
  }
}
function gozatSatirOlustur(etiket, boyut, tikla) {
  const div = document.createElement("div");
  div.className = "gozat-satir";
  div.innerHTML = `<span>${etiket}</span><span class="boyut">${boyut}</span>`;
  div.addEventListener("click", tikla);
  return div;
}

// ---------------------------------------------------------------------
// Dosya aç / kapat
// ---------------------------------------------------------------------
el("#ac-dugme").addEventListener("click", dosyayiAc);
el("#yol-kutu").addEventListener("keydown", (e) => { if (e.key === "Enter") dosyayiAc(); });
el("#kapat-dugme").addEventListener("click", dosyayiKapat);

async function dosyayiAc() {
  const yol = el("#yol-kutu").value.trim().replace(/^"|"$/g, "");
  if (!yol) { toast("Önce bir dosya yolu girin.", "uyari"); return; }
  if (S.oid) await dosyayiKapat();

  konsolBolum("Dosya açılıyor");
  const secenekMap = { "": null, "var": true, "yok": false, "duyarli": true, "duyarsiz": false };
  const govde = {
    yol,
    ayrac: el("#ayrac-secim").value || null,
    kodlama: el("#kodlama-secim").value || null,
    baslik_var: secenekMap[el("#baslik-secim").value],
    tirnak_duyarli: secenekMap[el("#tirnak-secim").value],
  };
  try {
    const veri = await apiPost("/api/ac", govde);
    S.oid = veri.oid;
    S.dosyaDegistiUyarildi = false;
    dosyaAcildiUygula(veri);
  } catch (e) {
    konsolaYaz("Açılamadı: " + e.message, "hata");
    toast("Açılamadı: " + e.message, "hata");
  }
}

function dosyaAcildiUygula(veri) {
  S.kolonlar = veri.bicim.kolonlar;
  S.gorunurKolonlar = null;
  S.taban = el("#taban-kutu").checked ? 1 : 0;
  oturumOzetiUygula(veri.oturum);
  el("#bicim-etiket").textContent = veri.bicim.ozet;
  konsolaYaz(`Kolonlar (${S.kolonlar.length}): ${S.kolonlar.slice(0, 12).join(", ")}` +
    (S.kolonlar.length > 12 ? " …" : ""), "bilgi");

  const kolonSecim = el("#sirala-kolon");
  kolonSecim.innerHTML = "";
  S.kolonlar.forEach((k) => {
    const o = document.createElement("option");
    o.value = k; o.textContent = k;
    kolonSecim.appendChild(o);
  });

  kontrolleriAyarla(true);
  el("#kapat-dugme").disabled = false;
  el("#bos-durum").hidden = true;
  baslikSatiriCiz();
  tabloyuYenile(true);
  el(".sekme-baslik[data-sekme='ana']").click();
  if (!S._pollBasladi) { S._pollBasladi = true; setInterval(durumSorgula, DURUM_ARALIGI_MS); }
  toast(`Açıldı: ${veri.bicim.ozet}`, "basari");
}

async function dosyayiKapat() {
  if (!S.oid) return;
  try { await apiPost(`/api/oturum/${S.oid}/kapat`); } catch (e) { /* göz ardı */ }
  konsolaYaz("Oturum kapatıldı.", "tamam");
  S.oid = null; S.kolonlar = []; S.toplamSatir = 0; S.gorunumVar = false;
  S.eslesmeToplam = 0; S.konsolSonId = 0; S.eslesmeSonId = 0;
  el("#bicim-etiket").textContent = "";
  el("#tablo-baslik-satiri").innerHTML = "";
  el("#tablo-govde").innerHTML = "";
  el("#tablo-aralayici").style.height = "0px";
  el("#sayfa-etiket").textContent = "Sayfa —";
  el("#secim-etiket").textContent = "Seçili: 0 kayıt";
  el("#kapat-dugme").disabled = true;
  el("#bos-durum").hidden = false;
  kontrolleriAyarla(false);
  el(".sekme-baslik[data-sekme='dosya']").click();
}

function kontrolleriAyarla(acik) {
  ["#onceki-dugme", "#sonraki-dugme", "#git-dugme", "#indeksle-dugme",
    "#kolonlar-dugme",
    "#ara-dugme", "#sirala-dugme", "#secim-sayfa-dugme", "#secim-temizle-dugme",
    "#secim-goster-dugme"].forEach((s) => { el(s).disabled = !acik; });
}

// ---------------------------------------------------------------------
// Oturum özetinin uygulanması (her satirlar/durum yanıtında gelir)
// ---------------------------------------------------------------------
function oturumOzetiUygula(ozet) {
  const eskiToplam = S.toplamSatir;
  S.toplamSatir = ozet.toplam_satir;
  S.kesin = ozet.kesin;
  S.gorunumVar = ozet.gorunum_var;
  S.sayfaSatir = ozet.sayfa_satir;
  S.seciliSayi = ozet.secili_sayi;

  el("#secim-etiket").textContent = `Seçili: ${sayiFormat(S.seciliSayi)} kayıt`;
  el("#sirala-sifirla-dugme").disabled = !S.gorunumVar;
  sayfaEtiketiGuncelle();

  // Aralayıcı yüksekliği tahmini büyüdükçe/kesinleştikçe güncellenir.
  if (Math.abs(S.toplamSatir - eskiToplam) / Math.max(1, eskiToplam || 1) > 0.001
      || eskiToplam === 0) {
    el("#tablo-aralayici").style.height = (S.toplamSatir * SATIR_H) + "px";
  }
}

function sayfaEtiketiGuncelle() {
  if (S.gorunumVar) {
    el("#sayfa-etiket").textContent = `SIRALI GÖRÜNÜM — ${sayiFormat(S.toplamSatir)} kayıt`;
    return;
  }
  const gorunurBas = ilkGorunurSatir();
  const sayfaNo = Math.floor(gorunurBas / S.sayfaSatir);
  const sayfaSayisi = Math.max(1, Math.ceil(S.toplamSatir / S.sayfaSatir));
  const isaret = S.kesin ? "" : "≈";
  el("#sayfa-etiket").textContent =
    `Sayfa ${sayfaNo + 1} / ${isaret}${sayiFormat(sayfaSayisi)}`;
}

function ilkGorunurSatir() {
  const sarmal = el("#tablo-sarmal");
  return Math.floor(sarmal.scrollTop / SATIR_H);
}

// ---------------------------------------------------------------------
// Tablo başlığı ve kolon genişlikleri
// ---------------------------------------------------------------------
function gorunenKolonIndeksleri() {
  return S.gorunurKolonlar || S.kolonlar.map((_ad, i) => i);
}

function baslikSatiriCiz() {
  S.kolonGenislikleri = S.kolonlar.map((ad) =>
    Math.max(70, Math.min(320, 20 + ad.length * 8)));

  const satir = el("#tablo-baslik-satiri");
  satir.innerHTML = "";
  satir.appendChild(hucreOlustur("☐", ISARET_GENISLIK, "isaret", () => basliktanIsaretle()));
  satir.appendChild(hucreOlustur("Satır #", SATIRNO_GENISLIK, "satir-no"));
  gorunenKolonIndeksleri().forEach((i) => {
    satir.appendChild(hucreOlustur(S.kolonlar[i], S.kolonGenislikleri[i]));
  });
}
function hucreOlustur(metin, genislik, sinif, tikla) {
  const d = document.createElement("div");
  d.className = "hucre" + (sinif ? " " + sinif : "");
  d.style.width = genislik + "px";
  d.textContent = metin;
  if (tikla) d.addEventListener("click", tikla);
  return d;
}

async function basliktanIsaretle() {
  if (!S.oid || !S.sonSatirlar.length) return;
  const hepsiSecili = S.sonSatirlar.every((s) => s[2]);
  for (const s of S.sonSatirlar) {
    if (s[1] === null) continue;
    if (s[2] === hepsiSecili) {
      try { await apiPost(`/api/oturum/${S.oid}/secim/degistir`, { kayit_no: s[0] }); }
      catch (e) { break; }
    }
  }
  tabloyuYenile(false);
}

// ---------------------------------------------------------------------
// Kolon gizleme/gösterme (ana tablo)
// ---------------------------------------------------------------------
el("#kolonlar-dugme").addEventListener("click", () => {
  const aktif = new Set(S.gorunurKolonlar || S.kolonlar.map((_ad, i) => i));
  const liste = el("#kolonlar-liste");
  liste.innerHTML = "";
  S.kolonlar.forEach((ad, i) => {
    const label = document.createElement("label");
    const kutu = document.createElement("input");
    kutu.type = "checkbox";
    kutu.checked = aktif.has(i);
    kutu.dataset.kolonIdx = i;
    label.appendChild(kutu);
    label.appendChild(document.createTextNode(ad));
    liste.appendChild(label);
  });
  el("#kolonlar-modal").hidden = false;
});
el("#kolonlar-tumu").addEventListener("click", () => {
  tumu("#kolonlar-liste input").forEach((k) => { k.checked = true; });
});
el("#kolonlar-hicbiri").addEventListener("click", () => {
  tumu("#kolonlar-liste input").forEach((k) => { k.checked = false; });
});
el("#kolonlar-uygula").addEventListener("click", () => {
  const secili = tumu("#kolonlar-liste input").filter((k) => k.checked)
    .map((k) => parseInt(k.dataset.kolonIdx, 10));
  if (!secili.length) {
    toast("En az bir kolon seçili kalmalı.", "uyari");
    return;
  }
  S.gorunurKolonlar = secili.length === S.kolonlar.length ? null : secili;
  el("#kolonlar-modal").hidden = true;
  baslikSatiriCiz();
  tabloyuYenile(true);
  const n = secili.length;
  konsolaYaz(n === S.kolonlar.length
    ? "Tüm kolonlar gösteriliyor."
    : `Kolon görünümü güncellendi: ${n}/${S.kolonlar.length} kolon gösteriliyor.`,
    "islem");
});

// ---------------------------------------------------------------------
// Sanal tablo: kaydırma + pencere çekme + çizim
// ---------------------------------------------------------------------
let kaydirmaZamanlayici = null;
el("#tablo-sarmal").addEventListener("scroll", () => {
  clearTimeout(kaydirmaZamanlayici);
  kaydirmaZamanlayici = setTimeout(() => tabloyuYenile(false), 60);
});

async function tabloyuYenile(zorla) {
  if (!S.oid) return;
  const sarmal = el("#tablo-sarmal");
  const ilkGorunur = Math.floor(sarmal.scrollTop / SATIR_H);
  const gorunurAdet = Math.ceil(sarmal.clientHeight / SATIR_H) + 1;
  const bas = Math.max(0, ilkGorunur - TAMPON_SATIR);
  const adet = gorunurAdet + 2 * TAMPON_SATIR;

  try {
    const veri = await apiGet(`/api/oturum/${S.oid}/satirlar?bas=${bas}&adet=${adet}`);
    S.sonBas = bas;
    S.sonSatirlar = veri.satirlar;
    oturumOzetiUygula(veri.oturum);
    satirlariCiz(bas, veri.satirlar);
    sayfaEtiketiGuncelle();
  } catch (e) {
    konsolaYaz("Satırlar getirilemedi: " + e.message, "hata");
  }
}

function satirlariCiz(bas, satirlar) {
  const govde = el("#tablo-govde");
  govde.innerHTML = "";
  let bekliyor = false;

  satirlar.forEach(([no, degerler, secili], i) => {
    if (degerler === null) bekliyor = true;
    const satirDiv = document.createElement("div");
    satirDiv.className = "tablo-satir" + (secili ? " secili-satir" : "")
      + (degerler === null ? " bekliyor" : "");
    satirDiv.style.top = ((bas + i) * SATIR_H) + "px";

    const isaretDiv = hucreOlustur(secili ? "☑" : "☐", ISARET_GENISLIK, "isaret");
    isaretDiv.addEventListener("click", (e) => { e.stopPropagation(); satirIsaretle(no); });
    satirDiv.appendChild(isaretDiv);

    satirDiv.appendChild(hucreOlustur(sayiFormat(no + S.taban), SATIRNO_GENISLIK, "satir-no"));

    gorunenKolonIndeksleri().forEach((k) => {
      const deger = degerler === null ? "…" : (degerler[k] !== undefined ? String(degerler[k]) : "");
      satirDiv.appendChild(hucreOlustur(deger, S.kolonGenislikleri[k]));
    });

    if (degerler !== null) {
      satirDiv.addEventListener("click", () => satirAyrintisiGoster(no, degerler));
    }
    govde.appendChild(satirDiv);
  });

  S.bekleyenVar = bekliyor;
}

async function satirIsaretle(no) {
  try {
    const sonuc = await apiPost(`/api/oturum/${S.oid}/secim/degistir`, { kayit_no: no });
    S.seciliSayi = sonuc.secili_sayi;
    el("#secim-etiket").textContent = `Seçili: ${sayiFormat(S.seciliSayi)} kayıt`;
    tabloyuYenile(false);
  } catch (e) {
    toast(e.message, "hata");
  }
}

// ---------------------------------------------------------------------
// Satır ayrıntısı + Base64 çözme
// ---------------------------------------------------------------------
function satirAyrintisiGoster(no, degerler) {
  S.aktifSatir = { no, degerler };
  const icerik = el("#satir-icerik");
  icerik.innerHTML = `<div><b>Satır numarası: ${sayiFormat(no + S.taban)}</b></div><hr>`;
  S.kolonlar.forEach((ad, i) => {
    const d = document.createElement("div");
    d.innerHTML = `<span class="alan-adi">${ad}:</span> ${
      (degerler[i] !== undefined ? String(degerler[i]) : "").replace(/</g, "&lt;")}`;
    icerik.appendChild(d);
  });
  el("#b64-sonuc").hidden = true;
  el("#satir-modal").hidden = false;
}

el("#b64-coz-dugme").addEventListener("click", async () => {
  if (!S.aktifSatir) return;
  try {
    const sonuc = await apiPost(`/api/oturum/${S.oid}/base64`, {
      hucreler: S.aktifSatir.degerler,
    });
    const alan = el("#b64-sonuc");
    alan.hidden = false;
    if (!sonuc.basarili) {
      alan.textContent = sonuc.aciklama || "Çözülemedi.";
      return;
    }
    let metin = `Ayar: ${sonuc.ayar.ozet}\nUzunluk: ${sonuc.bayt_uzunluk} bayt\n`;
    if (sonuc.tur_tahmini) metin += `Tür tahmini: ${sonuc.tur_tahmini}\n`;
    metin += "\n";
    metin += sonuc.metin !== null && sonuc.metin !== undefined
      ? `Metin (${sonuc.kodlama}):\n${sonuc.metin}`
      : `İkili veri (onaltılık döküm):\n${sonuc.onizleme || ""}`;
    alan.textContent = metin;
  } catch (e) {
    const alan = el("#b64-sonuc");
    alan.hidden = false;
    alan.textContent = "Hata: " + e.message;
  }
});

// ---------------------------------------------------------------------
// Gezinme: önceki/sonraki sayfa, satıra git, 1'den başlat, tam indeksle
// ---------------------------------------------------------------------
el("#onceki-dugme").addEventListener("click", () => sayfaKaydir(-1));
el("#sonraki-dugme").addEventListener("click", () => sayfaKaydir(1));
function sayfaKaydir(yon) {
  if (S.gorunumVar) { toast("Sıralı görünümde sayfa geçişi kullanılamaz.", "uyari"); return; }
  const sarmal = el("#tablo-sarmal");
  sarmal.scrollTop = Math.max(0, sarmal.scrollTop + yon * S.sayfaSatir * SATIR_H);
}

el("#taban-kutu").addEventListener("change", () => {
  S.taban = el("#taban-kutu").checked ? 1 : 0;
  tabloyuYenile(false);
});

el("#git-dugme").addEventListener("click", satiraGit);
el("#git-kutu").addEventListener("keydown", (e) => { if (e.key === "Enter") satiraGit(); });

async function satiraGit() {
  const ham = el("#git-kutu").value.trim().replace(/\./g, "");
  if (!ham) return;
  const istenen = parseInt(ham, 10);
  if (Number.isNaN(istenen)) { toast("Geçerli bir satır numarası girin.", "uyari"); return; }
  const hedef = istenen - S.taban;
  if (hedef < 0) { toast(`Satır numarası en az ${S.taban} olmalı.`, "uyari"); return; }
  await satiraGitDene(hedef);
}

async function satiraGitDene(hedef) {
  try {
    const sonuc = await apiPost(`/api/oturum/${S.oid}/satira-git`, { hedef });
    if (sonuc.hazir) {
      S.pendingGit = null;
      el("#git-notu").textContent = "";
      const sarmal = el("#tablo-sarmal");
      sarmal.scrollTop = Math.max(0, hedef * SATIR_H - sarmal.clientHeight / 2);
      tabloyuYenile(false);
    } else {
      S.pendingGit = hedef;
      el("#git-notu").textContent = `⏳ ${sayiFormat(hedef + S.taban)} hazırlanıyor…`;
    }
  } catch (e) {
    toast(e.message, "hata");
  }
}

el("#indeksle-dugme").addEventListener("click", async () => {
  try {
    await apiPost(`/api/oturum/${S.oid}/indeksle`);
  } catch (e) { toast(e.message, "hata"); }
});

// ---------------------------------------------------------------------
// Arama
// ---------------------------------------------------------------------
el("#ara-dugme").addEventListener("click", aramayiBaslat);
el("#arama-kutu").addEventListener("keydown", (e) => { if (e.key === "Enter") aramayiBaslat(); });
el("#arama-dur-dugme").addEventListener("click", async () => {
  try { await apiPost(`/api/oturum/${S.oid}/arama-durdur`); } catch (e) { /* yok say */ }
});

async function aramayiBaslat() {
  const metin = el("#arama-kutu").value;
  if (!metin.trim()) { toast("Aranacak metni yazın.", "uyari"); return; }
  try {
    el("#sonuc-govde").innerHTML = "";
    S.eslesmeSonId = 0; S.eslesmeToplam = 0;
    konsolBolum("Arama");
    await apiPost(`/api/oturum/${S.oid}/ara`, {
      metin, duyarli: el("#duyarli-kutu").checked,
      regex: el("#regex-kutu").checked,
    });
    el("#ara-dugme").disabled = true;
    el("#arama-dur-dugme").disabled = false;
    el(".alt-baslik[data-alt='sonuclar']").click();
  } catch (e) {
    toast(e.message, "hata");
  }
}

function eslesmeSatiriEkle(e) {
  const tr = document.createElement("tr");
  tr.dataset.satir = e.satir;
  const onizleme = (e.kirpik ? "… " : "") + e.onizleme.replace(/\t/g, " ");
  tr.innerHTML = `<td>${sayiFormat(e.satir + S.taban)}</td><td>${onizleme.replace(/</g, "&lt;")}</td>`;
  tr.addEventListener("click", () => satiraGitDene(e.satir));
  el("#sonuc-govde").appendChild(tr);
}

// ---------------------------------------------------------------------
// Sıralama
// ---------------------------------------------------------------------
el("#sirala-kapsam").addEventListener("change", siralamaKapsamiGuncelle);
function siralamaKapsamiGuncelle() {
  const tum = el("#sirala-kapsam").value === "tum";
  el("#sirala-k").disabled = !tum;
}
siralamaKapsamiGuncelle();

el("#sirala-dugme").addEventListener("click", async () => {
  const govde = {
    kolon: el("#sirala-kolon").value,
    yon: el("#sirala-yon").value,
    tur: el("#sirala-tur").value,
    kapsam: el("#sirala-kapsam").value,
    sayfa_no: Math.floor(ilkGorunurSatir() / S.sayfaSatir),
    k: parseInt((el("#sirala-k").value || "10000").replace(/\./g, ""), 10),
  };
  try {
    konsolBolum("Sıralama");
    await apiPost(`/api/oturum/${S.oid}/sirala`, govde);
    el("#sirala-dugme").disabled = true;
    el("#sirala-dur-dugme").disabled = false;
  } catch (e) {
    toast(e.message, "hata");
  }
});
el("#sirala-dur-dugme").addEventListener("click", async () => {
  try { await apiPost(`/api/oturum/${S.oid}/sirala-durdur`); } catch (e) { /* yok say */ }
});
el("#sirala-sifirla-dugme").addEventListener("click", async () => {
  try {
    const sonuc = await apiPost(`/api/oturum/${S.oid}/sirala-sifirla`);
    if (sonuc.oturum) oturumOzetiUygula(sonuc.oturum);
    konsolaYaz("Kaynak sırasına dönüldü.", "tamam");
    el("#tablo-sarmal").scrollTop = 0;
    tabloyuYenile(true);
  } catch (e) { toast(e.message, "hata"); }
});

// ---------------------------------------------------------------------
// Seçim
// ---------------------------------------------------------------------
el("#secim-sayfa-dugme").addEventListener("click", async () => {
  try {
    const sonuc = await apiPost(`/api/oturum/${S.oid}/secim/sayfa-sec`, {
      sayfa_no: Math.floor(ilkGorunurSatir() / S.sayfaSatir),
    });
    S.seciliSayi = sonuc.secili_sayi;
    el("#secim-etiket").textContent = `Seçili: ${sayiFormat(S.seciliSayi)} kayıt`;
    tabloyuYenile(false);
  } catch (e) { toast(e.message, "hata"); }
});
el("#secim-temizle-dugme").addEventListener("click", async () => {
  if (S.seciliSayi && !(await onayIste(`${sayiFormat(S.seciliSayi)} kayıt seçimden çıkarılacak. Onaylıyor musunuz?`))) return;
  try {
    await apiPost(`/api/oturum/${S.oid}/secim/temizle`);
    S.seciliSayi = 0;
    el("#secim-etiket").textContent = "Seçili: 0 kayıt";
    tabloyuYenile(false);
  } catch (e) { toast(e.message, "hata"); }
});
el("#secim-goster-dugme").addEventListener("click", secimPenceresiniAc);

async function secimPenceresiniAc() {
  if (!S.seciliSayi) { toast("Henüz hiçbir kayıt seçilmedi.", "uyari"); return; }
  el("#secim-modal").hidden = false;
  el("#disa-aktar-durum").textContent = "";
  try {
    const veri = await apiGet(`/api/oturum/${S.oid}/secim/satirlar?bas=0&adet=500`);
    el("#secim-modal-sayac").textContent = `${sayiFormat(veri.toplam)} kayıt seçili` +
      (veri.toplam > 500 ? " (ilk 500 gösteriliyor — tamamı için Excel/Word/PDF'e aktarın)" : "");
    const alan = el("#secim-liste-alan");
    alan.innerHTML = "";
    veri.satirlar.forEach(([no, degerler]) => {
      const d = document.createElement("div");
      d.className = "secim-satir";
      const metin = degerler ? degerler.join(" · ") : "…";
      d.innerHTML = `<span class="secim-no">${sayiFormat(no + S.taban)}</span><span>${metin.replace(/</g, "&lt;")}</span>`;
      alan.appendChild(d);
    });
  } catch (e) {
    el("#secim-liste-alan").textContent = e.message;
  }
}

["excel", "word", "pdf"].forEach((bicim) => {
  el(`#disa-aktar-${bicim}`).addEventListener("click", () => disaAktarBaslat(bicim));
});

async function disaAktarBaslat(bicim) {
  try {
    const sonuc = await apiPost(`/api/oturum/${S.oid}/secim/disa-aktar/${bicim}`);
    S.disaAktarToken = sonuc.token;
    el("#disa-aktar-durum").textContent = "Hazırlanıyor…";
    clearInterval(S.disaAktarZamanlayici);
    S.disaAktarZamanlayici = setInterval(() => disaAktarIlerlemeKontrol(S.disaAktarToken), 400);
  } catch (e) {
    el("#disa-aktar-durum").textContent = "Hata: " + e.message;
  }
}

async function disaAktarIlerlemeKontrol(token) {
  try {
    const veri = await apiGet(`/api/disa-aktar/${token}/ilerleme`);
    if (veri.durum === "calisiyor") {
      el("#disa-aktar-durum").textContent =
        `Toplanıyor… ${sayiFormat(veri.toplanan)}/${sayiFormat(veri.toplam)}`;
    } else if (veri.durum === "hazir") {
      clearInterval(S.disaAktarZamanlayici);
      el("#disa-aktar-durum").textContent = "İndiriliyor…";
      window.location = `/api/disa-aktar/${token}/indir`;
      setTimeout(() => { el("#disa-aktar-durum").textContent = ""; }, 2000);
    } else if (veri.durum === "hata") {
      clearInterval(S.disaAktarZamanlayici);
      el("#disa-aktar-durum").textContent = "Hata: " + veri.hata;
    }
  } catch (e) {
    clearInterval(S.disaAktarZamanlayici);
  }
}

// ---------------------------------------------------------------------
// Durum sorgulama (polling) — Tkinter'daki _kuyrugu_isle'nin web karşılığı
// ---------------------------------------------------------------------
let sonSiralamaSure = null;
let sonAramaBittiSure = null;

async function durumSorgula() {
  if (!S.oid) return;
  let veri;
  try {
    veri = await apiGet(
      `/api/oturum/${S.oid}/durum?konsol_sonrasi=${S.konsolSonId}&eslesme_sonrasi=${S.eslesmeSonId}`);
  } catch (e) {
    return; // oturum kapanmış olabilir; bir sonraki tur dener
  }

  veri.konsol.forEach((k) => konsolaYaz(k.metin, k.seviye));
  S.konsolSonId = veri.konsol_son_id;

  veri.eslesmeler.forEach(eslesmeSatiriEkle);
  S.eslesmeSonId = veri.eslesme_toplam;
  S.eslesmeToplam = veri.eslesme_toplam;
  el("#eslesme-etiket").textContent = S.eslesmeToplam
    ? `${sayiFormat(S.eslesmeToplam)} eşleşme` : "eşleşme yok";

  // İndeks çubuğu
  el("#indeks-cubuk").style.width = (veri.indeks.oran || 0) + "%";
  el("#indeks-etiket").textContent = veri.indeks.metin || "—";

  // Ortak "işlem" çubuğu: sıralama > arama önceliğiyle gösterilir
  // (Tkinter sürümünde de aynı çubuk ikisi için paylaşılır).
  if (veri.siralama.calisiyor) {
    el("#islem-baslik").textContent = "Sıralama:";
    el("#islem-cubuk").style.width = (veri.siralama.oran || 0) + "%";
    el("#islem-etiket").textContent = veri.siralama.metin || "—";
  } else if (veri.arama.calisiyor) {
    el("#islem-baslik").textContent = "Arama:";
    el("#islem-cubuk").style.width = (veri.arama.oran || 0) + "%";
    el("#islem-etiket").textContent = veri.arama.metin || "—";
  } else {
    el("#islem-baslik").textContent = "Arama:";
    el("#islem-etiket").textContent = veri.arama.metin || "—";
  }

  // Arama bitti -> düğmeleri geri al
  if (!veri.arama.calisiyor) {
    el("#ara-dugme").disabled = false;
    el("#arama-dur-dugme").disabled = true;
    if (veri.arama.bitti && veri.arama.sure !== sonAramaBittiSure) {
      sonAramaBittiSure = veri.arama.sure;
    }
  }

  // Sıralama bitti -> tabloyu yenile, düğmeleri geri al
  if (!veri.siralama.calisiyor) {
    el("#sirala-dugme").disabled = false;
    el("#sirala-dur-dugme").disabled = true;
    if (veri.siralama.bitti && veri.siralama.sure !== sonSiralamaSure) {
      sonSiralamaSure = veri.siralama.sure;
      el("#tablo-sarmal").scrollTop = 0;
      tabloyuYenile(true);
    }
  }

  oturumOzetiUygula(veri.oturum);

  // Bekleyen "satıra git" varsa yeniden dene.
  if (S.pendingGit !== null) {
    satiraGitDene(S.pendingGit);
  }

  // Görünür pencerede henüz gelmemiş satır varsa yeniden çek.
  if (S.bekleyenVar) {
    tabloyuYenile(false);
  }

  if (veri.dosya_degisti && !S.dosyaDegistiUyarildi) {
    S.dosyaDegistiUyarildi = true;
    konsolaYaz("KAYNAK DOSYA DEĞİŞTİ! Oturum açıldığından beri dosyanın "
      + "boyutu ya da değiştirilme zamanı değişti. Şu andan sonra okunan "
      + "satırlar YANLIŞ ya da BOZUK olabilir — lütfen dosyayı KAPATIP "
      + "yeniden açın.", "hata");
    toast("Kaynak dosya değişti — lütfen kapatıp yeniden açın.", "hata", 10000);
  }

  durumMetniGuncelle(veri.oturum);
}

function durumMetniGuncelle(ozet) {
  const bellek = ozet.bellek;
  const onek = S.dosyaDegistiUyarildi ? "⚠ KAYNAK DOSYA DEĞİŞTİ — YENİDEN AÇIN   |   " : "";
  const durumMetin = el("#durum-metin");
  durumMetin.textContent = onek +
    `RAM: indeks ${bayt(bellek.indeks_bayt)} (${sayiFormat(bellek.cipa)} çıpa) + ` +
    `satır önbelleği ${bellek.onbellek_pencere} pencere (${sayiFormat(bellek.onbellek_satir)} satır, ` +
    `tavan ${sayiFormat(bellek.onbellek_tavan_satir)})   |   Diske yazılan: 0 bayt`;
  durumMetin.style.color = S.dosyaDegistiUyarildi ? "var(--kirmizi)" : "";
}
function bayt(n) {
  if (n < 1024) return n + " B";
  const birimler = ["KB", "MB", "GB", "TB"];
  let i = -1;
  do { n /= 1024; i++; } while (n >= 1024 && i < birimler.length - 1);
  return n.toFixed(1).replace(".", ",") + " " + birimler[i];
}

// ---------------------------------------------------------------------
// URL parametreleriyle önceden doldurma: ?yol=<dosya>&ac=1
// (masaüstündeki `veri_goruntuleyici.py <yol>` komut satırı argümanının
// web karşılığı -- belirli bir dosyaya doğrudan bağlantı vermeyi sağlar)
// ---------------------------------------------------------------------
(function () {
  const p = new URLSearchParams(location.search);
  const yol = p.get("yol");
  if (yol) {
    el("#yol-kutu").value = yol;
    if (p.get("ac") === "1") setTimeout(dosyayiAc, 150);
  }
})();

konsolBolum("livedata (web)");
konsolaYaz("Büyük CSV / JSON / XML / YAML dosyalarını KAYNAĞINDAN, yerinde "
  + "inceleyen görüntüleyici — tarayıcı arayüzü.", "bilgi");
konsolaYaz("Diske hiçbir şey yazılmaz, dosya belleğe alınmaz, arayüz "
  + "kilitlenmez — aynı ilkeler masaüstü sürümüyle birebir.", "bilgi");
konsolaYaz("Başlamak için 'Dosya Seç…' ile bir dosya seçip 'Aç' düğmesine "
  + "basın. Sekmeler arasında Ctrl+1 … Ctrl+5 ile geçebilirsiniz.", "bilgi");
