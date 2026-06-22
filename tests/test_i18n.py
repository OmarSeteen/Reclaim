"""Tests for the translation layer. No GUI, no I/O."""

import unittest

from Reclaim import i18n


class TestI18n(unittest.TestCase):
    def tearDown(self):
        i18n.set_language("en")            # never leak language into other tests

    def test_english_passes_through(self):
        i18n.set_language("en")
        self.assertEqual(i18n.t("Analyze"), "Analyze")
        self.assertFalse(i18n.is_rtl())

    def test_arabic_translates_known_and_falls_back(self):
        i18n.set_language("ar")
        self.assertTrue(i18n.is_rtl())
        self.assertNotEqual(i18n.t("Analyze"), "Analyze")          # translated
        self.assertEqual(i18n.t("a string with no translation yet"),
                         "a string with no translation yet")        # graceful fallback

    def test_unknown_language_falls_back_to_english(self):
        i18n.set_language("zz")
        self.assertEqual(i18n.get_language(), "en")
        self.assertEqual(i18n.t("Analyze"), "Analyze")

    def test_templates_keep_placeholders(self):
        # A translated template must still contain {v} so .format works after.
        i18n.set_language("ar")
        template = i18n.t("Total reclaimable: {v}")
        self.assertIn("{v}", template)
        self.assertIn("9 GB", template.format(v="9 GB"))


if __name__ == "__main__":
    unittest.main()
