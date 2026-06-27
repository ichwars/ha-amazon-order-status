# Changelog

## 2.0.0

### Breaking Changes

- This release moves the runtime and sensor payloads to a shipment-first 2.0 model with nested `shipments` on each order.
- Legacy 1.x stored order state is not migrated into the new 2.0 sensor data.
- Users should rebuild tracked state with `amazon_order_status.rescan` instead of relying on old persisted order payloads.

### Migration

After updating and restarting Home Assistant, rebuild the tracked order list with:

```yaml
service: amazon_order_status.rescan
data:
  days: 30
  clear_existing: true
```

Use `clear_existing: true` for the initial 2.0 migration rebuild. Use `clear_existing: false` only when you want to enrich existing 2.0 orders from recent email without wiping them first.

### Added

- Shipment-first order storage with nested `shipments` in sensor attributes.
- Rolled-up order status sensors for the expanded state model, including `sensor.amazon_orders_partially_delivered`.
- Manual workflow services: `amazon_order_status.set_status`, `amazon_order_status.mark_delivered`, `amazon_order_status.ignore_order`, and `amazon_order_status.restore_order`.
- German-first dashboard documentation that iterates nested shipments safely with `o.get(...)` and `s.get(...)`.

### Changed

- Release metadata now identifies this integration as version `2.0.0`.
- Upgrade guidance now documents the required rescan-based rebuild workflow for breaking changes.

### Privacy

- Raw email bodies are still not stored.
- Sensitive attributes such as order IDs, titles, tracking URLs, delivery details, carrier data, item images, and parser diagnostics remain opt-in or hideable through integration options.
- Tracking URLs continue to be filtered to trusted HTTPS Amazon domains before exposure.

## 1.4.11

### Fixed

- Optional exposed attributes such as `delivery_window`, `carrier`, and `item_image_url` now remain present with `null` values when Amazon did not provide them, preventing strict Home Assistant templates from failing on missing dict keys.

## 1.4.10

### Fixed

- Successful scans that find new emails but no Amazon order status emails now log at debug level instead of warning level, avoiding noisy Home Assistant log entries during normal inbox activity.

## 1.4.9

### Changed

- Options flow is grouped into Scan, Processing, and Visible sensor attributes sections with full English and German labels/descriptions.
- Manual rescans can enrich existing orders with missing body-derived details from older emails, such as item images, without moving the order status backwards.

### Fixed

- Dashboard examples now use safe `dict.get(...)` access for optional attributes.

## 1.4.8

### Added

- Body parser for targeted delivery details from Amazon status emails.
- `Delivery attempted` status for failed delivery attempt emails.
- Optional sensor attributes for delivery estimate, delivery window, delivered-at text, item count, carrier, item image URL, and sanitized parser debug.
- Amazon product image extraction from trusted Amazon image CDN URLs.
- Regression tests for body detail extraction, delivery update subjects, delivery attempts, image URL validation, and sensor privacy filtering.
- HACS brand icon at `custom_components/amazon_order_status/brand/icon.png`.

### Changed

- Item titles can now be improved from Amazon email body HTML image alt text.
- Delivery update emails without a direct status can enrich existing tracked orders without changing their current status.
- Subject/item matching can use the full item title parsed from the email body.

### Privacy

- Raw email content is not stored.
- New body-derived attributes are hidden by default and require explicit opt-in through integration options.
- Parser debug is sanitized and only stores field names/counts, not order IDs, addresses, raw links, or message bodies.

## 1.4.7

### Added

- Reconfigure flow for IMAP connection settings.
- Sender-domain validation for Amazon status emails.
- Privacy options to hide order IDs, item titles, and tracking URLs from sensor attributes.
- Privacy filtering for raw subject and history details when order IDs or item titles are hidden.
- German translations.
- Optional `config_entry_id` service field for multi-entry setups.
- CI workflow for syntax, JSON, and regression tests.

### Changed

- Sensors now use Home Assistant `SensorEntity` with `native_value`, device info, and diagnostic category for the last-updated sensor.
- Config and options flows now use Home Assistant selectors with bounded numeric inputs.
- Options changes reload the config entry through a Home Assistant update listener.
- Subject-based matching now refuses ambiguous item-title matches instead of updating multiple orders.
- Tracking URLs are only exposed when they point to HTTPS Amazon domains.

### Fixed

- IMAP scan failures no longer advance `last_check`, preventing missed order emails after transient search/login failures.
- Manual rescans with `clear_existing` no longer persist an empty order list when the rescan fails.
- Custom IMAP ports are now used by the real scan path, not only by config validation.
- IMAP connections now log out through `finally` cleanup.
- Invalid stored timestamps no longer crash retention cleanup.

## 1.4.6

### Added

- German Amazon.de order email support through localized language profiles.
- Item title extraction via the `item_title` sensor attribute.
- Compact per-order status history via the `history` sensor attribute.
- `last_subject` and `status` attributes for easier dashboard rendering and debugging.
- `amazon_order_status.rescan` service for manual rescans without deleting Home Assistant storage files.
- Configurable initial scan window via the integration options.
- Scan diagnostics on the last-updated sensor, including processed email counts and skip reasons.
- Regression tests for German status parsing, item-title matching, status progression, and history de-duplication.
- MIT license file for this fork.

### Changed

- Related Amazon status emails are matched by Amazon order ID first, then by item title when Amazon omits the order ID from shipped or out-for-delivery emails.
- Order status updates are monotonic: an order can move from `Ordered` to `Shipped` to `Out for delivery` to `Delivered`, but late or duplicate older-status emails do not move it backwards.
- Storage is now scoped per config entry, with fallback loading from the legacy global storage key.
- README installation links, documentation, and issue tracker references now point to `ichwars/ha-amazon-order-status`.

### Migration Notes

- Existing tracked orders from the legacy storage key are read automatically.
- After updating, use the `amazon_order_status.rescan` service if you want to rebuild tracked state from recent emails:

```yaml
service: amazon_order_status.rescan
data:
  days: 30
  clear_existing: true
```

### Validation

- `python -m unittest tests.test_parser_helpers`
- `python -m py_compile` for integration modules
- JSON validation for `manifest.json` and `translations/en.json`
- `git diff --check`
