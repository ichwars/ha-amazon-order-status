# Changelog

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
