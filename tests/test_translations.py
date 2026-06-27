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
SERVICES_PATH = INTEGRATION_DIR / "services.yaml"

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

REQUIRED_SERVICE_KEYS = {
    "purge_order",
    "rescan",
    "set_status",
    "mark_delivered",
    "ignore_order",
    "restore_order",
}

SERVICE_FIELD_REQUIREMENTS = {
    "purge_order": {
        "order_id": True,
        "config_entry_id": False,
    },
    "rescan": {
        "days": False,
        "clear_existing": False,
        "config_entry_id": False,
    },
    "set_status": {
        "order_id": True,
        "status": True,
        "shipment_id": False,
        "config_entry_id": False,
    },
    "mark_delivered": {
        "order_id": True,
        "shipment_id": False,
        "delivered_at": False,
        "config_entry_id": False,
    },
    "ignore_order": {
        "order_id": True,
        "shipment_id": False,
        "config_entry_id": False,
    },
    "restore_order": {
        "order_id": True,
        "shipment_id": False,
        "config_entry_id": False,
    },
}


def _load_translation(language: str) -> dict:
    return json.loads((INTEGRATION_DIR / "translations" / f"{language}.json").read_text())


def _load_services() -> dict:
    services: dict[str, dict[str, dict[str, dict[str, bool]]]] = {}
    current_service: str | None = None
    current_field: str | None = None
    in_fields = False

    for raw_line in SERVICES_PATH.read_text().splitlines():
        line = raw_line.rstrip()
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue

        indent = len(line) - len(line.lstrip(" "))
        if indent == 0 and stripped.endswith(":"):
            current_service = stripped[:-1]
            services[current_service] = {"fields": {}}
            current_field = None
            in_fields = False
            continue

        if current_service is None:
            continue

        if indent == 2 and stripped == "fields:":
            in_fields = True
            current_field = None
            continue

        if indent == 4 and in_fields and stripped.endswith(":"):
            current_field = stripped[:-1]
            services[current_service]["fields"][current_field] = {}
            continue

        if indent == 6 and current_field and stripped.startswith("required:"):
            value = stripped.split(":", 1)[1].strip().lower()
            services[current_service]["fields"][current_field]["required"] = value == "true"

    return services


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

    def test_services_yaml_covers_manual_workflow_services(self):
        services = _load_services()

        self.assertEqual(REQUIRED_SERVICE_KEYS, set(services))

        for service_name, expected_fields in SERVICE_FIELD_REQUIREMENTS.items():
            with self.subTest(service=service_name):
                fields = services[service_name]["fields"]
                self.assertLessEqual(set(expected_fields), set(fields))
                for field_name, required in expected_fields.items():
                    with self.subTest(service=service_name, field=field_name):
                        self.assertEqual(required, fields[field_name]["required"])

    def test_service_translations_cover_manual_workflow_services(self):
        for language in ("en", "de"):
            with self.subTest(language=language):
                services = _load_translation(language)["services"]

                self.assertEqual(REQUIRED_SERVICE_KEYS, set(services))

                for service_name, expected_fields in SERVICE_FIELD_REQUIREMENTS.items():
                    with self.subTest(language=language, service=service_name):
                        service = services[service_name]
                        self.assertIn("name", service)
                        self.assertIn("description", service)

                        translated_fields = service["fields"]
                        self.assertLessEqual(set(expected_fields), set(translated_fields))
                        for field_name in expected_fields:
                            with self.subTest(
                                language=language,
                                service=service_name,
                                field=field_name,
                            ):
                                self.assertIn("name", translated_fields[field_name])
                                self.assertIn("description", translated_fields[field_name])

    def test_mark_delivered_describes_iso_datetime_input(self):
        services_yaml = _load_services()
        delivered_yaml = services_yaml["mark_delivered"]["fields"]["delivered_at"]
        yaml_text = SERVICES_PATH.read_text()

        self.assertIn("ISO", yaml_text)
        self.assertIn("2026-06-27", yaml_text)
        self.assertTrue(delivered_yaml["required"] is False)

        en_description = _load_translation("en")["services"]["mark_delivered"]["fields"][
            "delivered_at"
        ]["description"]
        de_description = _load_translation("de")["services"]["mark_delivered"]["fields"][
            "delivered_at"
        ]["description"]

        self.assertIn("ISO", en_description)
        self.assertIn("date", en_description.lower())
        self.assertIn("ISO", de_description)
        self.assertIn("datum", de_description.lower())


if __name__ == "__main__":
    unittest.main()
