import unittest

from backend.app.anpr import normalize_plate, _score_candidate_norm


class TestPlateNormalization(unittest.TestCase):
    def test_palestine_format_single_tail_digit(self):
        self.assertEqual(normalize_plate("1.2345-6 P"), "123456")
        self.assertEqual(normalize_plate("1.2345-6P"), "123456")

    def test_palestine_format_double_tail_digits(self):
        self.assertEqual(normalize_plate("1.2345-67 P"), "1234567")
        self.assertEqual(normalize_plate("1.2345-67P"), "1234567")

    def test_israel_with_prefix(self):
        self.assertEqual(normalize_plate("IL 12-345-67"), "1234567")
        self.assertEqual(normalize_plate("IL12-345-6"), "123456")

    def test_israel_without_prefix(self):
        self.assertEqual(normalize_plate("12-345-67"), "1234567")
        self.assertEqual(normalize_plate("12-345-6"), "123456")

    def test_strip_country_marker_suffix(self):
        self.assertEqual(normalize_plate("2148HP"), "2148H")

    def test_general_plate_keeps_letters(self):
        self.assertEqual(normalize_plate("abc-123"), "ABC123")

    def test_trim_trailing_letter_noise(self):
        self.assertEqual(normalize_plate("52148HB"), "52148HB")


class TestVariants(unittest.TestCase):
    def test_generate_variants_trims_noise(self):
        from backend.app.anpr import _generate_variants
        variants = _generate_variants("52148HB")
        self.assertIn("52148H", variants)


class TestPlateScoring(unittest.TestCase):
    def test_numeric_plates_not_penalized(self):
        score_6 = _score_candidate_norm("123456", 0.8)
        score_7 = _score_candidate_norm("1234567", 0.8)
        self.assertGreater(score_6, 0)
        self.assertGreater(score_7, 0)


if __name__ == "__main__":
    unittest.main()
