import base64
import unittest

from decoder.base64_decoder import (
    DecodeError,
    decode_base64,
    extract_base64_text,
    try_decode_text,
)
from gui.dialogs import _build_base64_config


class TestExtractBase64Text(unittest.TestCase):
    def test_no_columns_raises(self):
        with self.assertRaises(DecodeError):
            extract_base64_text([])

    def test_non_string_part_raises(self):
        with self.assertRaises(DecodeError):
            extract_base64_text([123])

    def test_joined_prefix_postfix_stripped(self):
        result = extract_base64_text(
            ["DATA:", "SGVsbG8=", ";END"], prefix="DATA:", postfix=";END", apply_to="joined"
        )
        self.assertEqual(result, "SGVsbG8=")

    def test_joined_missing_prefix_raises(self):
        with self.assertRaises(DecodeError):
            extract_base64_text(["SGVsbG8=;END"], prefix="DATA:", postfix=";END", apply_to="joined")

    def test_joined_missing_postfix_raises(self):
        with self.assertRaises(DecodeError):
            extract_base64_text(["DATA:SGVsbG8="], prefix="DATA:", postfix=";END", apply_to="joined")

    def test_parts_prefix_postfix_applied_per_part(self):
        result = extract_base64_text(
            ["DATA:abc;END", "DATA:def;END"], prefix="DATA:", postfix=";END", apply_to="parts"
        )
        self.assertEqual(result, "abcdef")

    def test_no_prefix_postfix_just_joins(self):
        result = extract_base64_text(["abc", "def"])
        self.assertEqual(result, "abcdef")

    def test_strip_is_exact_not_charset_based(self):
        # postfix "AB" tam eslesmeli; "XAB" sonu "AB" ile bitiyor, kaldirilmali.
        result = extract_base64_text(["XAB"], postfix="AB", apply_to="joined")
        self.assertEqual(result, "X")


class TestDecodeBase64(unittest.TestCase):
    def test_valid_base64_decodes(self):
        encoded = base64.b64encode("Merhaba".encode("utf-8")).decode("ascii")
        data = decode_base64(encoded)
        self.assertEqual(data, b"Merhaba")

    def test_invalid_base64_raises(self):
        with self.assertRaises(DecodeError):
            decode_base64("bu gecerli bir base64 degil!!!")

    def test_bad_padding_raises(self):
        with self.assertRaises(DecodeError):
            decode_base64("SGVsbG8")


class TestTryDecodeText(unittest.TestCase):
    def test_valid_utf8_decodes(self):
        data = "İstanbul".encode("utf-8")
        self.assertEqual(try_decode_text(data), "İstanbul")

    def test_invalid_utf8_returns_none(self):
        data = b"\xff\xfe\x00\x01"
        self.assertIsNone(try_decode_text(data))


class TestEndToEndSplitAcrossColumns(unittest.TestCase):
    def test_split_base64_reassembled_in_order(self):
        original = "DataInspector test mesaji"
        encoded = base64.b64encode(original.encode("utf-8")).decode("ascii")
        mid = len(encoded) // 2
        part1, part2 = encoded[:mid], encoded[mid:]

        text = extract_base64_text(
            [f"P:{part1}:S", f"P:{part2}:S"], prefix="P:", postfix=":S", apply_to="parts"
        )
        data = decode_base64(text)
        self.assertEqual(try_decode_text(data), original)


class TestPrefixModeStartsWithUnchanged(unittest.TestCase):
    """Regresyon 1: mevcut başlangıç-prefix davranışı, prefix_mode
    parametresi hiç verilmese de, açıkça "starts_with" verilse de AYNI
    şekilde çalışmaya devam eder (geriye uyumlu varsayılan)."""

    def test_default_prefix_mode_matches_explicit_starts_with(self):
        args = (["DATA:", "SGVsbG8=", ";END"],)
        kwargs = dict(prefix="DATA:", postfix=";END", apply_to="joined")
        result_default = extract_base64_text(*args, **kwargs)
        result_explicit = extract_base64_text(*args, prefix_mode="starts_with", **kwargs)
        self.assertEqual(result_default, "SGVsbG8=")
        self.assertEqual(result_explicit, "SGVsbG8=")

    def test_starts_with_missing_prefix_still_raises(self):
        with self.assertRaises(DecodeError):
            extract_base64_text(
                ["SGVsbG8=;END"], prefix="DATA:", postfix=";END",
                apply_to="joined", prefix_mode="starts_with",
            )


class TestPrefixModeMarker(unittest.TestCase):
    """Regresyon 2-4, 6-7: metin içi işaretçi modu."""

    def test_marker_in_middle_of_text_found_and_prefix_stripped(self):
        # Gorevdeki tam ornek: "118380417_3_½_RGVuZW1l" + isaretci "½_"
        # -> "RGVuZW1l".
        result = extract_base64_text(
            ["118380417_3_½_RGVuZW1l"], prefix="½_", apply_to="joined", prefix_mode="marker",
        )
        self.assertEqual(result, "RGVuZW1l")

    def test_marker_not_found_raises_without_leaking_cell_content(self):
        secret_looking_text = "GIZLI_HUCRE_ICERIGI_ABCDEF123"
        try:
            extract_base64_text(
                [secret_looking_text], prefix="½_", apply_to="joined", prefix_mode="marker",
            )
            self.fail("DecodeError beklendi")
        except DecodeError as e:
            message = str(e)
            # Hata mesaji, kullanicinin kendi girdigi isaretci metnini
            # (yapilandirma degeri) icerebilir, ama GERCEK HUCRE ICERIGINI
            # ASLA icermemeli.
            self.assertNotIn(secret_looking_text, message)
            self.assertNotIn("GIZLI_HUCRE_ICERIGI", message)

    def test_multiple_marker_occurrences_uses_first_match(self):
        # Isaretci ("::") birden fazla kez geciyor; ILK esleseneden
        # SONRAKI kisim alinmali (ikinci "::"den sonraki kisim degil).
        result = extract_base64_text(
            ["once::SGVsbG8=::sonra"], prefix="::", apply_to="joined", prefix_mode="marker",
        )
        self.assertEqual(result, "SGVsbG8=::sonra")

    def test_marker_mode_with_empty_marker_raises(self):
        with self.assertRaises(DecodeError):
            extract_base64_text(["veri"], prefix="", apply_to="joined", prefix_mode="marker")

    def test_marker_mode_combined_with_postfix(self):
        # Regresyon 7: marker + postfix birlikte, ayni parcada calismali.
        result = extract_base64_text(
            ["118380417_0_½_SGVsbG8=:END"], prefix="½_", postfix=":END",
            apply_to="joined", prefix_mode="marker",
        )
        self.assertEqual(result, "SGVsbG8=")

    def test_marker_mode_per_part_with_postfix_applied_to_each_part(self):
        # "Her parcaya ayri ayri" + marker + postfix: her parca KENDI
        # icinde marker/postfix'ten temizlenip SONRA birlestirilmeli.
        result = extract_base64_text(
            ["118380417_0_½_abc:END", "118380417_1_½_def:END"],
            prefix="½_", postfix=":END", apply_to="parts", prefix_mode="marker",
        )
        self.assertEqual(result, "abcdef")


class TestMarkerModeRealScenarioTurkishRoundTrip(unittest.TestCase):
    """Regresyon 5-6: gercek senaryoyu (6 kolon, dinamik on-ekli parcalar,
    "her parcaya ayri ayri" + "metin ici isaretci") bilinen bir Turkce
    metinle uctan uca dogrular. Parcalar KASITLI OLARAK Base64'un 4'lu
    sinirina hizalanmadan bolunur -- boylece once temizleyip birlestirme,
    SONRA tek seferde decode etme sirasinin dogru oldugu kanitlanir (tek
    tek parcalar bagimsiz gecerli Base64 olmak ZORUNDA degildir)."""

    def test_six_dynamic_prefixed_parts_reassemble_original_turkish_text(self):
        original = "Bu bir Türkçe test mesajıdır: şğüçöı ĞÜÇÖİ"
        encoded = base64.b64encode(original.encode("utf-8")).decode("ascii")
        self.assertGreater(len(encoded), 12)

        n = 6
        base_len = len(encoded) // n
        # Kasitli olarak duzensiz (4'un kati OLMAYAN) sinirlarla bol.
        cut_points = [0]
        for i in range(1, n):
            cut_points.append(min(len(encoded), base_len * i + (i % 3)))
        cut_points.append(len(encoded))
        pieces = [encoded[cut_points[i]:cut_points[i + 1]] for i in range(n)]
        self.assertEqual("".join(pieces), encoded)
        # En az bir parcanin uzunlugu 4'un kati DEGIL (gercekci senaryo).
        self.assertTrue(any(len(p) % 4 != 0 for p in pieces if p))

        wrapped = [f"118380417_{i}_½_{piece}" for i, piece in enumerate(pieces)]

        text = extract_base64_text(
            wrapped, prefix="½_", postfix="", apply_to="parts", prefix_mode="marker",
        )
        self.assertEqual(text, encoded)  # once temizlenip birlestirildi
        data = decode_base64(text)  # sonra TEK SEFERDE decode edildi
        self.assertEqual(try_decode_text(data), original)


class TestBuildBase64Config(unittest.TestCase):
    """gui.dialogs._build_base64_config: widget'lardan okunan HAM
    degerlerden Base64 yapilandirmasi uretme mantigi -- gercek Tk diyalogu
    ACILMADAN dogrudan test edilir (bkz. gui/dialogs.py'deki
    build_import_config ile ayni desen)."""

    def test_starts_with_default_prefix_mode(self):
        config = _build_base64_config("Kolon 1, Kolon 2", "P:", ":S", "joined", "starts_with")
        self.assertEqual(config["columns"], ["Kolon 1", "Kolon 2"])
        self.assertEqual(config["prefix"], "P:")
        self.assertEqual(config["postfix"], ":S")
        self.assertEqual(config["apply_to"], "joined")
        self.assertEqual(config["prefix_mode"], "starts_with")

    def test_marker_mode_with_nonempty_marker_ok(self):
        config = _build_base64_config("Kolon 1", "½_", "", "parts", "marker")
        self.assertEqual(config["prefix"], "½_")
        self.assertEqual(config["prefix_mode"], "marker")

    def test_marker_mode_with_empty_marker_raises(self):
        with self.assertRaises(ValueError):
            _build_base64_config("Kolon 1", "", "", "parts", "marker")

    def test_starts_with_mode_allows_empty_prefix(self):
        # "starts_with" modunda bos prefix zaten opsiyoneldir (mevcut
        # davranis); yalnizca "marker" modunda zorunludur.
        config = _build_base64_config("Kolon 1", "", "", "joined", "starts_with")
        self.assertEqual(config["prefix"], "")


if __name__ == "__main__":
    unittest.main()
