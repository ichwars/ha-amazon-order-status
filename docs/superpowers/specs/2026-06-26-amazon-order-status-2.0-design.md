# Amazon Order Status 2.0 Design

## Goal

Version 2.0 rebuilds the integration around a shipment-first Amazon order model. It intentionally breaks the 1.x storage shape and sensor contract so the integration can represent partial shipments, non-happy-path delivery states, structured delivery windows, and manual user corrections without trying to preserve ambiguous legacy data. Users rebuild tracked state with the existing `amazon_order_status.rescan` service after upgrading.

## Scope

This release implements the eight requested product gaps as one coherent 2.0 change:

1. Expanded non-happy-path order statuses.
2. Shipment-aware data model for partial deliveries.
3. Structured delivery date and time attributes.
4. Broader parser language/status profiles with tests.
5. Better carrier/tracking boundaries and documented limitations.
6. Manual user workflows for status correction, ignore, restore, and archive-style removal.
7. A complete Home Assistant dashboard example for the new contract.
8. Release and migration communication for the breaking 2.0 upgrade.

Out of scope: live carrier tracking, package-number scraping that stores unvalidated third-party tracking identifiers, payment/refund amount parsing, and any raw email storage.

## Breaking-Change Strategy

2.0 uses a clean storage rebuild. The coordinator no longer attempts to migrate the 1.x `orders` map into the new schema because one 1.x order entry may represent an order, a shipment, or one item depending on which Amazon email was seen last. On first 2.0 load, legacy stored 1.x data is ignored for active sensor data and remains only as stale storage until Home Assistant overwrites the integration store on the next successful save.

The README and changelog must tell users to run:

```yaml
service: amazon_order_status.rescan
data:
  days: 30
  clear_existing: true
```

Users who need older history can increase `days` up to the existing 365-day service limit.

## Data Model

The coordinator stores `orders` as a dictionary keyed by Amazon order ID. Each order has a stable top-level summary and a list of shipment records.

```python
{
    "order_id": "123-4567890-1234567",
    "status": "Partially delivered",
    "subject": "Original display subject",
    "last_subject": "Most recent matched subject",
    "updated": "2026-06-26T17:30:00+00:00",
    "item_count": 2,
    "items": [
        {
            "item_key": "normalized-title",
            "item_title": "Example item",
            "item_image_url": "https://m.media-amazon.com/images/I/example.jpg",
            "quantity": 1,
        }
    ],
    "shipments": [
        {
            "shipment_id": "123-4567890-1234567:normalized-title",
            "status": "Out for delivery",
            "item_title": "Example item",
            "item_image_url": "https://m.media-amazon.com/images/I/example.jpg",
            "tracking_url": "https://www.amazon.de/gp/your-account/ship-track/example",
            "carrier": "DHL",
            "delivery_estimate": "24. Juni - 25. Juni",
            "delivery_date_start": "2026-06-24",
            "delivery_date_end": "2026-06-25",
            "delivery_window": "15h - 19h",
            "delivery_window_start": "15:00",
            "delivery_window_end": "19:00",
            "delivered_at": None,
            "delivery_is_delayed": False,
            "updated": "2026-06-26T17:30:00+00:00",
            "history": [
                {
                    "status": "Shipped",
                    "subject": "Versendet: Example item",
                    "updated": "2026-06-25T10:00:00+00:00",
                    "tracking_url": "https://www.amazon.de/gp/your-account/ship-track/example",
                }
            ],
            "manual": False,
            "ignored": False,
        }
    ],
    "history": [
        {
            "status": "Partially delivered",
            "updated": "2026-06-26T17:30:00+00:00",
            "reason": "shipment_rollup",
        }
    ],
    "manual": False,
    "ignored": False,
}
```

The exposed sensor attributes keep privacy filtering. Existing optional privacy toggles still control order IDs, item titles, tracking URLs, delivery details, carriers, item images, and parser debug. When an optional group is enabled, missing optional values are exposed as `null`.

## Status Model

Shipment statuses are the canonical state machine:

- `Ordered`
- `Shipped`
- `Out for delivery`
- `Delivery attempted`
- `Pickup ready`
- `Delayed`
- `Delivery problem`
- `Undeliverable`
- `Delivered`
- `Canceled`
- `Return started`
- `Refunded`
- `Ignored`

Order status is a rollup over non-ignored shipments:

- all canceled -> `Canceled`
- all refunded -> `Refunded`
- any return started -> `Return started`
- any undeliverable -> `Undeliverable`
- any delivery problem -> `Delivery problem`
- any delayed -> `Delayed`
- any pickup ready -> `Pickup ready`
- all delivered -> `Delivered`
- at least one delivered and at least one not delivered -> `Partially delivered`
- otherwise highest-progress active shipment status by rank

Manual service changes set `manual: true` and must not be overwritten by older emails. Newer Amazon emails may update details, but a manual status remains authoritative until `restore_order` clears the manual marker.

## Sensors

2.0 creates one status-count sensor per order rollup status:

- `sensor.amazon_orders_ordered`
- `sensor.amazon_orders_shipped`
- `sensor.amazon_orders_out_for_delivery`
- `sensor.amazon_orders_delivery_attempted`
- `sensor.amazon_orders_pickup_ready`
- `sensor.amazon_orders_delayed`
- `sensor.amazon_orders_delivery_problem`
- `sensor.amazon_orders_undeliverable`
- `sensor.amazon_orders_partially_delivered`
- `sensor.amazon_orders_delivered`
- `sensor.amazon_orders_canceled`
- `sensor.amazon_orders_return_started`
- `sensor.amazon_orders_refunded`
- `sensor.amazon_orders_ignored`
- `sensor.amazon_orders_last_updated`

Each status sensor exposes:

```python
{
    "order_count": 1,
    "shipment_count": 2,
    "orders": [
        {
            "order_id": "123-4567890-1234567",
            "status": "Partially delivered",
            "shipments": [],
        }
    ],
}
```

Each exposed order includes `shipments` after privacy filtering. Dashboard examples should render shipment rows inside each order.

## Parser Behavior

The parser recognizes German and English subjects/body text for:

- ordered
- shipped
- out for delivery
- delivery attempted
- pickup ready / locker pickup
- delayed / running late
- delivery problem / action required
- undeliverable
- delivered
- canceled / cancelled
- return started
- refunded

Language profiles remain regex-based and tested through anonymized subject/body snippets. Parsing must continue to reject non-Amazon sender domains when `require_amazon_sender` is enabled.

## Structured Delivery Dates

The body parser keeps the current human-readable fields and adds structured fields when the text is parseable:

- `delivery_date_start`: ISO `YYYY-MM-DD`
- `delivery_date_end`: ISO `YYYY-MM-DD`
- `delivery_window_start`: local `HH:MM`
- `delivery_window_end`: local `HH:MM`
- `delivery_is_delayed`: boolean

Relative German/English terms use the email received date as the anchor:

- `heute` / `today` -> received date
- `morgen` / `tomorrow` -> received date + 1 day
- explicit day-month ranges use the received year unless the date has already passed by more than 180 days, then the next year is used

Ambiguous date text remains only in `delivery_estimate`; structured fields stay `null`.

## Services

Existing services remain but change meaning where needed:

- `amazon_order_status.rescan`: rebuilds the 2.0 order/shipment store. `clear_existing: true` is the recommended 2.0 migration path.
- `amazon_order_status.purge_order`: removes an entire order and all shipments.

New services:

- `amazon_order_status.set_status`
  - required: `order_id`, `status`
  - optional: `shipment_id`, `config_entry_id`
  - sets a manual status on the order or shipment.
- `amazon_order_status.mark_delivered`
  - required: `order_id`
  - optional: `shipment_id`, `delivered_at`, `config_entry_id`
  - convenience wrapper for `set_status` to `Delivered`.
- `amazon_order_status.ignore_order`
  - required: `order_id`
  - optional: `shipment_id`, `config_entry_id`
  - marks an order or shipment ignored without deleting stored history.
- `amazon_order_status.restore_order`
  - required: `order_id`
  - optional: `shipment_id`, `config_entry_id`
  - clears `ignored` and `manual` flags so future emails can update the entity normally.

All service calls persist state and refresh sensors immediately.

## Carrier And Tracking Boundary

The integration may expose carrier names found in Amazon email content when `expose_carrier` is enabled. It does not call carrier APIs and does not promise live carrier tracking. Tracking URLs remain limited to validated HTTPS Amazon domains.

## Dashboard Contract

The README must include a complete dashboard example that:

- has conditional cards for all 2.0 statuses,
- shows orders with nested shipments,
- uses only `dict.get(...)` access,
- shows structured delivery dates and time windows when present,
- hides optional details when privacy settings do not expose them,
- includes German labels because the maintainer/user context is primarily German, with English entity names still documented.

## Versioning And Release Communication

The release version is `2.0.0`. The changelog must include:

- breaking storage change,
- rescan migration command,
- new status sensors,
- new services,
- structured delivery fields,
- parser coverage expansion,
- carrier/tracking limitation.

The README upgrade section must explicitly say 1.x dashboards that assumed one order row per status may need to be updated because orders now contain nested `shipments`.

## Testing Strategy

Tests must cover:

- status detection for German and English examples across all canonical statuses,
- shipment rollup status behavior,
- partial delivery with one delivered shipment and one active shipment,
- structured date parsing for today/tomorrow and explicit German date ranges,
- privacy filtering for nested shipments,
- manual service helpers at coordinator level,
- ignoring and restoring orders/shipments,
- 2.0 clean-storage behavior that does not present legacy 1.x entries as current data,
- service schemas/translations for the new service fields,
- full existing test suite regression.

No production behavior may be added without a failing test first.

## Implementation Notes

The current `coordinator.py` is doing too much. The implementation should split new focused helpers where practical:

- `models.py`: constants, status ranks, rollup helpers, schema builders.
- `parser.py`: text cleanup, language profiles, body/detail extraction.
- `coordinator.py`: IMAP fetch, state persistence, service-facing mutations.
- `sensor.py`: Home Assistant entity exposure and privacy filtering.

The split should be done only where it directly supports the 2.0 feature work; avoid cosmetic refactors outside the paths touched by this design.
