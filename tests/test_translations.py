"""Regression tests for translation coverage."""

from __future__ import annotations

import json
from pathlib import Path
import unittest


INTEGRATION_DIR = (
    Path(__file__).resolve().parents[1]
    / "custom_components"
    / "amazon_order_status"
)

CONFIG_FIELDS = {
    "email",
    "imap_server",
    "username",
    "password",
    "imap_port",
    "imap_folder",
    "poll_interval",
    "initial_scan_days",
    "mark_as_read",
    "require_amazon_sender",
    "expose_order_id",
    "expose_item_title",
    "expose_tracking_url",
    "expose_delivery_details",
    "expose_carrier",
    "expose_item_image",
    "expose_parser_debug",
}

OPTION_FIELDS = {
    "delivered_retention_days",
    "update_interval",
    "initial_scan_days",
    "imap_folder",
    "mark_as_read",
    "require_amazon_sender",
    "expose_order_id",
    "expose_item_title",
    "expose_tracking_url",
    "expose_delivery_details",
    "expose_carrier",
    "expose_item_image",
    "expose_parser_debug",
}


def _load_translation(language: str) -> dict:
    return json.loads((INTEGRATION_DIR / "translations" / f"{language}.json").read_text())


class TranslationCoverageTest(unittest.TestCase):
    """Ensure forms do not fall back to raw option keys."""

    def test_config_fields_have_labels_and_descriptions(self):
        for language in ("en", "de"):
            with self.subTest(language=language):
                strings = _load_translation(language)
                user_step = strings["config"]["step"]["user"]
                reconfigure_step = strings["config"]["step"]["reconfigure"]

                self.assertLessEqual(CONFIG_FIELDS, set(user_step["data"]))
                self.assertLessEqual(CONFIG_FIELDS, set(user_step["data_description"]))
                self.assertLessEqual(
                    {"email", "imap_server", "username", "password", "imap_port"},
                    set(reconfigure_step["data"]),
                )
                self.assertLessEqual(
                    {"email", "imap_server", "username", "password", "imap_port"},
                    set(reconfigure_step["data_description"]),
                )

    def test_options_are_grouped_and_fully_described(self):
        for language in ("en", "de"):
            with self.subTest(language=language):
                strings = _load_translation(language)
                init_step = strings["options"]["step"]["init"]
                sections = init_step["sections"]

                self.assertEqual(
                    {"scan", "processing", "attributes"},
                    set(sections),
                )

                labels = {}
                descriptions = {}
                for section in sections.values():
                    labels.update(section["data"])
                    descriptions.update(section["data_description"])

                self.assertLessEqual(OPTION_FIELDS, set(labels))
                self.assertLessEqual(OPTION_FIELDS, set(descriptions))


if __name__ == "__main__":
    unittest.main()
