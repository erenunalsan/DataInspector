"""Base64 yapılandırma diyaloğu, çözümleme sonucu penceresi ve büyük veri
(JSON/CSV) aktarım yapılandırma diyaloğu."""
import os
import tkinter as tk
from tkinter import filedialog, messagebox, ttk


def _build_json_selector(selector_mode, name_value, index_raw) -> dict:
    """`selector_mode`, kullanıcının AÇIKÇA seçtiği kayıt dizisi modudur
    ("root_array" / "name" / "index"); boş/None ise (hiçbir seçim
    yapılmamışsa) hata verir -- sessizce "root_array"a düşülmez."""
    if selector_mode == "root_array":
        return {"mode": "root_array"}
    if selector_mode == "name":
        name = (name_value or "").strip()
        if not name:
            raise ValueError("Alan adını girin.")
        return {"mode": "name", "value": name}
    if selector_mode == "index":
        raw_index = (index_raw or "").strip()
        try:
            idx = int(raw_index)
            if idx < 1:
                raise ValueError
        except ValueError:
            raise ValueError("Alan sırası 1 veya daha büyük bir tam sayı olmalı.")
        return {"mode": "index", "value": idx}
    raise ValueError(
        "Kayıt dizisi seçimi yapılmalı: kök zaten dizi / alan adıyla seç / alan sırasıyla seç."
    )


def _build_xml_selector(path_raw) -> dict:
    """XML için kayıt elementi/path seçicisini üretir. `path_raw`, kullanıcının
    tek bir metin kutusuna yazdığı, "/" ile ayrılmış BASİT bir yoldur:
      - "item" (tek parça) -> kökün doğrudan çocuğu "item" (etiketle seçim).
      - "kayitlar/item" (çok parça) -> kökün "kayitlar" çocuğunun "item"
        çocukları (iç içe/nested path seçimi).
    Wildcard, attribute koşulu ya da XPath DESTEKLENMEZ (kasıtlı olarak
    basit tutulur). Boş bırakılamaz; boş segment (ör. "a//b") reddedilir."""
    raw = (path_raw or "").strip()
    if not raw:
        raise ValueError("Kayıt elementi/path girin (ör. 'item' ya da 'kayitlar/item').")
    segments = [s.strip() for s in raw.split("/")]
    if any(not s for s in segments):
        raise ValueError("Kayıt elementi/path içinde boş bir parça olamaz (ör. 'a//b' geçersiz).")
    return {"mode": "path", "value": segments}


def _validate_preview_limits(max_records_raw, max_mib_raw):
    try:
        max_records = int((max_records_raw or "").strip())
        max_mib = float((max_mib_raw or "").strip())
        if max_records <= 0 or max_mib <= 0:
            raise ValueError
    except ValueError:
        raise ValueError("Önizleme sınırları pozitif sayı olmalı.")
    return max_records, int(max_mib * 1024 * 1024)


def build_import_config(source, out_dir, mode, selector_mode, name_value,
                         index_raw, max_records_raw, max_mib_raw) -> dict:
    """Diyalogdaki widget'lardan okunmuş HAM (zaten string/ilkel) değerlerden
    ImportJob'a verilecek yapılandırma sözlüğünü üretir. Hiçbir Tk widget'ı
    ya da diyalog penceresi bilmez; bu yüzden GUI açmadan doğrudan test
    edilebilir.

    Kaynak biçimi (JSON/CSV/XML/YAML), kaynak dosyanın UZANTISINDAN belirlenir:
      - ".csv": CSV'de "seçici" kavramı yoktur (her satır zaten bir
        kayıttır); selector_mode/name_value/index_raw TAMAMEN yoksayılır,
        selector=None döner.
      - ".json": mevcut kök-dizi/alan-adı/alan-sırası seçici doğrulaması
        AYNEN uygulanır (bkz. _build_json_selector).
      - ".xml": kayıt elementi/path seçicisi (bkz. _build_xml_selector);
        AYNI `name_value` alanı (GUI'de "Kayıt elementi / path" olarak
        relabel edilen tek metin kutusu) bu amaçla yeniden kullanılır --
        selector_mode/index_raw XML için TAMAMEN yoksayılır.
      - ".yaml"/".yml": JSON ile AYNI kök-dizi/alan-adı/alan-sırası seçici
        doğrulaması (_build_json_selector DOĞRUDAN yeniden kullanılır --
        YAML akış kaynağı JSON ile aynı seçici şeklini kabul eder).
      - başka bir uzantı: açıklayıcı bir ValueError.

    Geçersiz girdide, GUI'de messagebox olarak gösterilecek açıklayıcı bir
    ValueError fırlatır."""
    source = (source or "").strip()
    out_dir = (out_dir or "").strip()
    if not source or not out_dir:
        raise ValueError("Kaynak dosya ve çıktı klasörü seçilmelidir.")

    ext = os.path.splitext(source)[1].lower()
    if ext == ".csv":
        source_format = "csv"
        selector = None
    elif ext == ".json":
        source_format = "json"
        selector = _build_json_selector(selector_mode, name_value, index_raw)
    elif ext == ".xml":
        source_format = "xml"
        selector = _build_xml_selector(name_value)
    elif ext in (".yaml", ".yml"):
        source_format = "yaml"
        selector = _build_json_selector(selector_mode, name_value, index_raw)
    else:
        raise ValueError(
            "Büyük veri aktarımı yalnızca .json, .csv, .xml ve .yaml/.yml dosyalarını "
            f"destekler (seçilen dosya uzantısı: {ext or '(yok)'})."
        )

    max_records, max_bytes = _validate_preview_limits(max_records_raw, max_mib_raw)

    return {
        "source": source,
        "out_dir": out_dir,
        "mode": mode,
        "source_format": source_format,
        "selector": selector,
        "preview_max_records": max_records,
        "preview_max_bytes": max_bytes,
    }


def _build_base64_config(columns_raw, prefix_raw, postfix_raw, apply_to, prefix_mode) -> dict:
    """Diyalogdaki widget'lardan okunmuş HAM (zaten string) değerlerden
    Base64 çözümleme yapılandırmasını üretir. Hiçbir Tk widget'ı ya da
    diyalog penceresi bilmez; bu yüzden GUI açmadan doğrudan test
    edilebilir.

    `prefix_mode` ("starts_with"/"marker"), `apply_to` ("joined"/"parts")
    seçiminden TAMAMEN BAĞIMSIZDIR -- decoder.extract_base64_text bu ikisini
    ayrı eksenler olarak birleştirir. "marker" modunda `prefix_raw` (işaretçi
    metni) boş bırakılamaz; boşsa GUI'de messagebox olarak gösterilecek
    açıklayıcı bir ValueError fırlatır."""
    prefix = prefix_raw or ""
    if prefix_mode == "marker" and not prefix:
        raise ValueError("İşaretçi modu seçiliyken işaretçi metni boş bırakılamaz.")
    raw = (columns_raw or "").strip()
    columns = [c.strip() for c in raw.split(",") if c.strip()]
    return {
        "columns": columns,
        "prefix": prefix,
        "postfix": postfix_raw or "",
        "apply_to": apply_to,
        "prefix_mode": prefix_mode,
    }


def ask_base64_config(parent, columns: list):
    """Kullanıcıdan Base64 çözümleme için kolon sırası, prefix/işaretçi,
    postfix, bunların birleşik metne mi yoksa her parçaya mı uygulanacağını
    VE prefix'in metnin BAŞINDA mı aranacağını yoksa metin İÇİNDE bir
    İŞARETÇİ olarak mı aranacağını sorar (bu iki seçim BİRBİRİNDEN
    BAĞIMSIZDIR). Dict ({"columns": [...], "prefix": str, "postfix": str,
    "apply_to": str, "prefix_mode": str}) ya da kullanıcı iptal ederse
    None döner."""
    result = {}

    top = tk.Toplevel(parent)
    top.title("Base64 Çözümleme Ayarları")
    top.transient(parent)
    top.grab_set()

    ttk.Label(top, text="Mevcut kolonlar: " + ", ".join(columns), wraplength=420).grid(
        row=0, column=0, columnspan=2, sticky="w", padx=8, pady=(8, 4)
    )

    ttk.Label(top, text="Kolonlar (virgülle, birleştirme sırasıyla):").grid(
        row=1, column=0, sticky="w", padx=8
    )
    columns_entry = ttk.Entry(top, width=40)
    columns_entry.grid(row=1, column=1, padx=8, pady=4)

    prefix_label = ttk.Label(top, text="Prefix (opsiyonel):")
    prefix_label.grid(row=2, column=0, sticky="w", padx=8)
    prefix_entry = ttk.Entry(top, width=40)
    prefix_entry.grid(row=2, column=1, padx=8, pady=4)

    ttk.Label(top, text="Postfix (opsiyonel):").grid(row=3, column=0, sticky="w", padx=8)
    postfix_entry = ttk.Entry(top, width=40)
    postfix_entry.grid(row=3, column=1, padx=8, pady=4)

    prefix_mode_var = tk.StringVar(value="starts_with")
    ttk.Label(top, text="Prefix / işaretçi yorumlama:").grid(
        row=4, column=0, columnspan=2, sticky="w", padx=8, pady=(8, 0)
    )
    ttk.Radiobutton(
        top, text="Metnin başındaki prefix'i kaldır (mevcut)",
        variable=prefix_mode_var, value="starts_with",
    ).grid(row=5, column=0, columnspan=2, sticky="w", padx=16)
    ttk.Radiobutton(
        top, text="İşaretçiyi bul; öncesini ve işaretçiyi kaldır",
        variable=prefix_mode_var, value="marker",
    ).grid(row=6, column=0, columnspan=2, sticky="w", padx=16)

    def _update_prefix_label(*_args):
        """Yalnızca kozmetik bir geri bildirimdir -- gerçek doğrulama
        _build_base64_config'te yapılır, bu fonksiyona güvenilmez."""
        if prefix_mode_var.get() == "marker":
            prefix_label.configure(text="İşaretçi (zorunlu, metin içinde aranır):")
        else:
            prefix_label.configure(text="Prefix (opsiyonel):")

    prefix_mode_var.trace_add("write", _update_prefix_label)

    apply_to_var = tk.StringVar(value="joined")
    ttk.Label(top, text="Prefix/postfix nereye uygulansın:").grid(
        row=7, column=0, columnspan=2, sticky="w", padx=8, pady=(8, 0)
    )
    ttk.Radiobutton(
        top, text="Birleşik metne (parçalar birleştirildikten sonra)",
        variable=apply_to_var, value="joined",
    ).grid(row=8, column=0, columnspan=2, sticky="w", padx=16)
    ttk.Radiobutton(
        top, text="Her parçaya ayrı ayrı (birleştirmeden önce)",
        variable=apply_to_var, value="parts",
    ).grid(row=9, column=0, columnspan=2, sticky="w", padx=16)

    def on_ok():
        try:
            config = _build_base64_config(
                columns_entry.get(), prefix_entry.get(), postfix_entry.get(),
                apply_to_var.get(), prefix_mode_var.get(),
            )
        except ValueError as e:
            messagebox.showwarning("Uyarı", str(e), parent=top)
            return
        result.update(config)
        top.destroy()

    def on_cancel():
        result.clear()
        top.destroy()

    btn_frame = ttk.Frame(top)
    btn_frame.grid(row=10, column=0, columnspan=2, pady=8)
    ttk.Button(btn_frame, text="Tamam", command=on_ok).pack(side="left", padx=4)
    ttk.Button(btn_frame, text="İptal", command=on_cancel).pack(side="left", padx=4)

    top.protocol("WM_DELETE_WINDOW", on_cancel)
    top.wait_window()

    return result if result else None


def show_decode_result(parent, decoded_bytes: bytes, decoded_text, duration_seconds: float) -> None:
    """Çözümlenen Base64 sonucunu ayrı bir pencerede gösterir. decoded_text
    None ise (UTF-8 olarak çözülemedi) hex gösterim kullanılır."""
    top = tk.Toplevel(parent)
    top.title("Base64 Çözümleme Sonucu")

    if decoded_text is not None:
        info = f"UTF-8 metin olarak gösteriliyor ({len(decoded_bytes)} bayt, {duration_seconds * 1000:.2f} ms)"
        content = decoded_text
    else:
        info = (
            f"UTF-8 olarak çözülemedi; hex gösteriliyor "
            f"({len(decoded_bytes)} bayt, {duration_seconds * 1000:.2f} ms)"
        )
        content = decoded_bytes.hex(" ")

    ttk.Label(top, text=info, wraplength=460).pack(anchor="w", padx=8, pady=(8, 4))

    text_widget = tk.Text(top, width=60, height=15, wrap="word")
    text_widget.insert("1.0", content)
    text_widget.configure(state="disabled")
    text_widget.pack(fill="both", expand=True, padx=8, pady=(0, 8))

    ttk.Button(top, text="Kapat", command=top.destroy).pack(pady=(0, 8))


def ask_import_config(parent):
    """Kullanıcıdan büyük veri aktarımı (JSON, CSV, XML ya da YAML) için
    kaynak dosya, çıktı klasörü, mod (Önizleme/Tam Aktarım) ve -- yalnızca
    JSON/XML/YAML için -- kayıt seçicisini sorar:
      - JSON/YAML: kök zaten dizi(sequence) / kök nesnede(mapping) alan
        adı / kök nesnede alan sırası (1 tabanlı) -- AYNI seçici kontrolleri.
      - XML: kayıt elementi/path (ör. "item" ya da "kayitlar/item").
    CSV seçildiğinde (dosya uzantısına bakılır) seçici anlamsızdır (her CSV
    satırı zaten bir kayıttır); ilgili kontroller pasifleştirilir ve etiket
    bunu belirtir. Hiçbir makineye özgü yol ya da "ilk dizi" sezgisi
    sunulmaz; kullanıcı açıkça seçmelidir. Dict ya da kullanıcı iptal
    ederse None döner."""
    result = {}

    top = tk.Toplevel(parent)
    top.title("Büyük Veri Aktar (JSON/CSV/XML/YAML)")
    top.transient(parent)
    top.grab_set()

    source_var = tk.StringVar()
    out_dir_var = tk.StringVar()

    ttk.Label(top, text="Kaynak dosya (.json/.csv/.xml/.yaml/.yml):").grid(
        row=0, column=0, sticky="w", padx=8, pady=(8, 2)
    )
    ttk.Entry(top, textvariable=source_var, width=50).grid(row=0, column=1, padx=4)

    def pick_source():
        path = filedialog.askopenfilename(
            title="Kaynak JSON, CSV, XML ya da YAML dosyasını seç",
            filetypes=[
                ("JSON/CSV/XML/YAML dosyaları", "*.json *.csv *.xml *.yaml *.yml"),
                ("JSON dosyaları", "*.json"),
                ("CSV dosyaları", "*.csv"),
                ("XML dosyaları", "*.xml"),
                ("YAML dosyaları", "*.yaml *.yml"),
                ("Tüm dosyalar", "*.*"),
            ],
        )
        if path:
            source_var.set(path)

    ttk.Button(top, text="Seç...", command=pick_source).grid(row=0, column=2, padx=(0, 8))

    ttk.Label(top, text="Çıktı klasörü:").grid(row=1, column=0, sticky="w", padx=8, pady=2)
    ttk.Entry(top, textvariable=out_dir_var, width=50).grid(row=1, column=1, padx=4)

    def pick_out_dir():
        path = filedialog.askdirectory(title="Çıktı klasörünü seç")
        if path:
            out_dir_var.set(path)

    ttk.Button(top, text="Seç...", command=pick_out_dir).grid(row=1, column=2, padx=(0, 8))

    ttk.Separator(top, orient="horizontal").grid(row=2, column=0, columnspan=3, sticky="ew", pady=8)

    mode_var = tk.StringVar(value="preview")
    ttk.Label(top, text="Aktarım türü:").grid(row=3, column=0, sticky="w", padx=8)
    ttk.Radiobutton(
        top, text="Önizleme (aşağıdaki sınırlarla, kısmi -- asla \"tamamlandı\" sayılmaz)",
        variable=mode_var, value="preview",
    ).grid(row=4, column=0, columnspan=3, sticky="w", padx=16)
    ttk.Radiobutton(
        top, text="Tam Aktarım (seçilen dizinin TAMAMI; kayıt/bayt sınırı yoktur)",
        variable=mode_var, value="full",
    ).grid(row=5, column=0, columnspan=3, sticky="w", padx=16)

    ttk.Separator(top, orient="horizontal").grid(row=6, column=0, columnspan=3, sticky="ew", pady=8)

    selector_label = ttk.Label(top, text="Kayıt dizisi (JSON/YAML için):")
    selector_label.grid(row=7, column=0, sticky="w", padx=8)
    # NOT: Kasıtlı olarak bir varsayılan YOKTUR -- kullanıcı üç seçenekten
    # birini açıkça işaretlemeden "Aktarımı Başlat" hata verir. Önceki
    # sürümde varsayılan "root_array" idi; kullanıcı yalnızca aşağıdaki
    # alan-sırası kutusuna değer yazıp radyo düğmesine tıklamayı unutursa
    # seçici sessizce (ve yanlış biçimde) "root_array" olarak gönderiliyordu.
    # Bunu önlemek için hem varsayılan kaldırıldı hem de alan adı/sırası
    # kutularından birine yazı yazmak ilgili radyo düğmesini otomatik
    # işaretler (aşağıdaki bind'lar).
    selector_var = tk.StringVar(value="")
    root_array_radio = ttk.Radiobutton(
        top, text="Kök zaten bir dizi (ör. [ {...}, {...} ])",
        variable=selector_var, value="root_array",
    )
    root_array_radio.grid(row=8, column=0, columnspan=3, sticky="w", padx=16)
    name_radio = ttk.Radiobutton(
        top, text="Kök bir nesne; alan ADIYLA seç:",
        variable=selector_var, value="name",
    )
    name_radio.grid(row=9, column=0, sticky="w", padx=16)
    name_entry = ttk.Entry(top, width=20)
    name_entry.grid(row=9, column=1, sticky="w")
    name_entry.bind("<KeyRelease>", lambda e: selector_var.set("name"))
    index_radio = ttk.Radiobutton(
        top, text="Kök bir nesne; alan SIRASIYLA seç (1 tabanlı: ilk alan = 1):",
        variable=selector_var, value="index",
    )
    index_radio.grid(row=10, column=0, columnspan=2, sticky="w", padx=16)
    index_entry = ttk.Entry(top, width=10)
    index_entry.grid(row=10, column=2, sticky="w")
    index_entry.bind("<KeyRelease>", lambda e: selector_var.set("index"))

    _selector_widgets = (root_array_radio, name_radio, name_entry, index_radio, index_entry)

    def _update_format_ui(*_args):
        """Kaynak dosyanın uzantısına göre seçici bölümünü etkinleştirir/
        pasifleştirir/relabel eder. Yalnızca kozmetik bir geri bildirimdir
        -- gerçek doğrulama build_import_config'te (uzantıya bakarak)
        YİNE DE yapılır, bu fonksiyona güvenilmez.
          - CSV: seçici tamamen pasif (her satır zaten bir kayıttır).
          - XML: yalnızca "alan adı" kutusu aktif kalır, "Kayıt elementi /
            path" olarak relabel edilir (ör. "item" ya da "kayitlar/item");
            kök-dizi/alan-sırası JSON'a özgü olduğu için pasifleştirilir.
          - JSON/YAML (ya da tanınmayan/boş uzantı): mevcut üç seçenek de
            aktif -- YAML, JSON ile AYNI seçici mantığını kullanır.
        """
        ext = os.path.splitext(source_var.get())[1].lower()
        is_csv = (ext == ".csv")
        is_xml = (ext == ".xml")

        root_array_radio.configure(state="disabled" if (is_csv or is_xml) else "normal")
        index_radio.configure(state="disabled" if (is_csv or is_xml) else "normal")
        index_entry.configure(state="disabled" if (is_csv or is_xml) else "normal")
        name_radio.configure(state="disabled" if is_csv else "normal")
        name_entry.configure(state="disabled" if is_csv else "normal")

        if is_csv:
            selector_label.configure(text="Kayıt dizisi (CSV'de gerekmez; her satır zaten bir kayıttır):")
            name_radio.configure(text="Kök bir nesne; alan ADIYLA seç:")
        elif is_xml:
            selector_label.configure(text="Kayıt elementi / path (XML için zorunlu):")
            name_radio.configure(text="Kayıt elementi / path (ör. 'item' ya da 'kayitlar/item'):")
            selector_var.set("name")  # tek aktif secenek oldugu icin gorsel olarak isaretle
        else:
            selector_label.configure(text="Kayıt dizisi (yalnızca JSON için):")
            name_radio.configure(text="Kök bir nesne; alan ADIYLA seç:")

    source_var.trace_add("write", _update_format_ui)

    ttk.Separator(top, orient="horizontal").grid(row=11, column=0, columnspan=3, sticky="ew", pady=8)

    ttk.Label(top, text="Önizleme sınırları (yalnızca Önizleme modunda kullanılır):").grid(
        row=12, column=0, columnspan=3, sticky="w", padx=8
    )
    ttk.Label(top, text="En fazla kayıt:").grid(row=13, column=0, sticky="w", padx=16)
    max_records_entry = ttk.Entry(top, width=10)
    max_records_entry.insert(0, "1000")
    max_records_entry.grid(row=13, column=1, sticky="w")
    ttk.Label(top, text="En fazla MiB:").grid(row=14, column=0, sticky="w", padx=16)
    max_mib_entry = ttk.Entry(top, width=10)
    max_mib_entry.insert(0, "32")
    max_mib_entry.grid(row=14, column=1, sticky="w")

    def on_ok():
        try:
            config = build_import_config(
                source_var.get(), out_dir_var.get(), mode_var.get(),
                selector_var.get(), name_entry.get(), index_entry.get(),
                max_records_entry.get(), max_mib_entry.get(),
            )
        except ValueError as e:
            messagebox.showwarning("Uyarı", str(e), parent=top)
            return

        result.update(config)
        top.destroy()

    def on_cancel():
        result.clear()
        top.destroy()

    btn_frame = ttk.Frame(top)
    btn_frame.grid(row=15, column=0, columnspan=3, pady=10)
    ttk.Button(btn_frame, text="Aktarımı Başlat", command=on_ok).pack(side="left", padx=4)
    ttk.Button(btn_frame, text="İptal", command=on_cancel).pack(side="left", padx=4)

    top.protocol("WM_DELETE_WINDOW", on_cancel)
    top.wait_window()

    return result if result else None
