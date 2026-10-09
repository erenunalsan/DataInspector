"""Base64 decode: prefix/postfix ayıklama + çok kolonlu birleştirme + çözümleme.

Belirli kolon adlarına veya sabit bir parça sırasına bağımlı değildir.
Kullanıcı çalışma zamanında hangi kolonların hangi sırayla kullanılacağını
ve prefix/postfix'in birleşik metne mi yoksa her parçaya mı uygulanacağını
belirler; bu proje bunu tahmin etmez.

Prefix/postfix ayıklaması tam eşleşme kontrolüyle yapılır; str.strip()/
lstrip()/rstrip() kullanılmaz (bunlar literal alt-dize değil, karakter
kümesi siler). Base64 çözümlemesinin sonucu bytes'tır; metne çevirme ayrı,
isteğe bağlı bir adımdır. Bu, kriptografik şifre çözme değildir.
"""
import base64
import binascii


class DecodeError(Exception):
    """Base64 çözümleme sırasında oluşan anlaşılır hata."""


def _strip_exact(text: str, prefix: str, postfix: str, label: str) -> str:
    if prefix:
        if not text.startswith(prefix):
            raise DecodeError(f"{label}: metin beklenen prefix ile başlamıyor: {prefix!r}")
        text = text[len(prefix):]
    if postfix:
        if not text.endswith(postfix):
            raise DecodeError(f"{label}: metin beklenen postfix ile bitmiyor: {postfix!r}")
        text = text[: len(text) - len(postfix)]
    return text


def _find_marker_and_strip(text: str, marker: str, postfix: str, label: str) -> str:
    """`marker`'ı `text` içinde REGEX OLARAK DEĞİL, birebir Unicode alt-dize
    olarak arar (`str.find`); ilk geçtiği yere kadarki kısmı VE marker'ın
    kendisini kaldırır. Birden fazla geçiyorsa `str.find` zaten İLK
    eşleşmeyi döner. Marker bulunamazsa GERÇEK metin içeriğini hata
    mesajına yazmadan açıklayıcı bir DecodeError fırlatır (yalnızca
    kullanıcının kendi girdiği marker metni -- ki bu bir yapılandırma
    değeridir, hücre verisi değildir -- mesajda yer alır)."""
    idx = text.find(marker)
    if idx == -1:
        raise DecodeError(f"{label}: belirtilen işaretçi metinde bulunamadı: {marker!r}")
    text = text[idx + len(marker):]
    if postfix:
        if not text.endswith(postfix):
            raise DecodeError(f"{label}: metin beklenen postfix ile bitmiyor: {postfix!r}")
        text = text[: len(text) - len(postfix)]
    return text


def extract_base64_text(parts: list, prefix: str = "", postfix: str = "", apply_to: str = "joined",
                         prefix_mode: str = "starts_with") -> str:
    """parts: kullanıcının seçtiği kolonların, belirlediği sırada ham metin
    değerleri. apply_to="joined" ise prefix/postfix birleşik metne,
    "parts" ise her parçaya ayrı ayrı uygulanır.

    prefix_mode (GERİYE UYUMLU, varsayılan "starts_with"):
      - "starts_with": MEVCUT davranış -- metin TAM OLARAK `prefix` ile
        başlamalıdır (bkz. _strip_exact); başlamıyorsa açıklayıcı hata.
      - "marker": `prefix`, metin içinde (regex DEĞİL, birebir Unicode
        alt-dize olarak) aranan bir İŞARETÇİDİR; ilk geçtiği yere kadarki
        kısım ve işaretçinin kendisi kaldırılır (bkz.
        _find_marker_and_strip). Kolon numarasına göre değişen dinamik
        önekleri olan hücrelerde (ör. "118380417_3_½_<veri>") tek bir sabit
        prefix yerine ortak bir işaretçi ("½_") kullanmayı sağlar. Bu modda
        `prefix` (işaretçi metni) BOŞ bırakılamaz.
    """
    if not parts:
        raise DecodeError("Base64 çözümleme için en az bir kolon seçilmelidir")

    for i, part in enumerate(parts):
        if not isinstance(part, str):
            raise DecodeError(
                f"Seçilen {i + 1}. kolonun değeri metin değil (tür: {type(part).__name__}); "
                "bu hücre Base64 çözümlemesi için uygun değil"
            )

    if prefix_mode not in ("starts_with", "marker"):
        raise DecodeError(f"Geçersiz prefix modu: {prefix_mode!r}")
    if prefix_mode == "marker" and not prefix:
        raise DecodeError("İşaretçi modu seçiliyken işaretçi metni boş bırakılamaz")

    def strip_one(text: str, label: str) -> str:
        if prefix_mode == "marker":
            return _find_marker_and_strip(text, prefix, postfix, label)
        return _strip_exact(text, prefix, postfix, label)

    if apply_to == "parts":
        stripped = [strip_one(part, f"{i + 1}. parça") for i, part in enumerate(parts)]
        return "".join(stripped)

    joined = "".join(parts)
    return strip_one(joined, "Birleşik metin")


def decode_base64(text: str) -> bytes:
    """Base64 metnini bytes'a çözer; biçim geçersizse DecodeError fırlatır."""
    try:
        return base64.b64decode(text, validate=True)
    except (binascii.Error, ValueError) as e:
        raise DecodeError(f"Geçersiz Base64 verisi: {e}") from e


def try_decode_text(data: bytes, encoding: str = "utf-8"):
    """Bayt dizisini metne çevirmeyi dener; başarısızsa None döner (çağıran
    taraf bu durumda hex gösterime düşebilir). Başarılı bir Base64 çözümü,
    sonucun geçerli bir metin olacağını garanti etmez."""
    try:
        return data.decode(encoding)
    except UnicodeDecodeError:
        return None
