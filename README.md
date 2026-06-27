# Amazon Order Status for Home Assistant

Amazon Order Status watches Amazon order emails over IMAP and turns them into Home Assistant sensors. Amazon does not provide a public order-tracking API, so this integration reads the order updates already sent to your inbox.

## Features

- Tracks Amazon order progress from email updates.
- Supports English and German Amazon mail subjects and body details.
- Uses a 2.0 shipment-first model with nested `shipments` per order.
- Exposes rolled-up order sensors, including `sensor.amazon_orders_partially_delivered`.
- Adds manual workflow services for corrections and cleanup.
- Keeps privacy-sensitive fields optional through integration settings.
- Includes `amazon_order_status.rescan` for rebuilds without deleting Home Assistant storage files.

## Installation

### HACS

Add `ichwars/ha-amazon-order-status` as a custom integration repository in HACS, install it, and restart Home Assistant.

[![Open your Home Assistant instance and open a repository inside HACS.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=ichwars&repository=ha-amazon-order-status&category=integration)

### Manual

Download this repository from [GitHub](https://github.com/ichwars/ha-amazon-order-status), copy `custom_components/amazon_order_status` into your Home Assistant `custom_components` directory, then restart Home Assistant.

After restarting, add the integration in `Settings -> Devices & Services -> Add Integration`.

## Configuration Notes

All runtime options can be changed later from the integration options dialog.

- `update_interval`: mailbox polling interval in minutes.
- `initial_scan_days`: lookback window for first setup and rebuilds.
- `delivered_retention_days`: retention period for delivered orders.
- `mark_as_read`: optionally mark processed Amazon mail as read.
- `require_amazon_sender`: accept only Amazon sender domains.
- `expose_order_id`, `expose_item_title`, `expose_tracking_url`: control sensitive attributes.
- `expose_delivery_details`, `expose_carrier`, `expose_item_image`, `expose_parser_debug`: opt in to additional detail fields.
- `imap_folder`: optional folder override instead of `INBOX`.

## Upgrade to 2.0.0

Version `2.0.0` is a breaking release.

- 1.x tracked state is not migrated into the new 2.0 sensor payloads.
- Orders now store nested `shipments`, and order status is rolled up from shipment status.
- Manual workflow services now include `amazon_order_status.set_status`, `amazon_order_status.mark_delivered`, `amazon_order_status.ignore_order`, and `amazon_order_status.restore_order`.

### Migration

1. Update through HACS or replace the custom component manually.
2. Restart Home Assistant.
3. Rebuild the order cache with a rescan.

```yaml
service: amazon_order_status.rescan
data:
  days: 30
  clear_existing: true
```

Use `clear_existing: true` for the 2.0 migration rebuild. That clears legacy tracked state and repopulates the integration from the selected email lookback window.

If you only want to enrich current 2.0 orders from recent mail, keep existing entries and use:

```yaml
service: amazon_order_status.rescan
data:
  days: 30
  clear_existing: false
```

## Sensors and Data Model

Each status sensor exposes an `orders` attribute. In 2.0, every order can contain nested `shipments`, so dashboards should read both levels defensively with `.get(...)`.

Common status sensors include:

- `sensor.amazon_orders_ordered`
- `sensor.amazon_orders_shipped`
- `sensor.amazon_orders_out_for_delivery`
- `sensor.amazon_orders_delivery_attempted`
- `sensor.amazon_orders_partially_delivered`
- `sensor.amazon_orders_delivered`
- `sensor.amazon_orders_last_updated`

Depending on order history, the integration can also surface delayed, pickup ready, delivery problem, undeliverable, canceled, return started, refunded, and ignored states.

At the order level, attributes can include:

- `status`, `updated`, `shipment_count`, `shipments`, `history`, `manual`, `ignored`
- optional `order_id`, `item_title`, `tracking_url`
- optional rolled-up delivery details such as `delivery_estimate`, `delivery_window`, `delivered_at`, `item_count`

At the shipment level, attributes can include:

- `status`, `updated`, `history`, `manual`, `ignored`
- optional `shipment_id`, `item_title`, `tracking_url`
- optional shipment detail fields such as `delivery_date_start`, `delivery_date_end`, `delivery_window_start`, `delivery_window_end`, `delivery_is_delayed`, `carrier`, `item_image_url`

## Dashboard

This example is German-first and uses only safe `o.get(...)` and `s.get(...)` access. It renders each order and then its nested `shipments`.

```yaml
type: vertical-stack
cards:
  - type: conditional
    conditions:
      - entity: sensor.amazon_orders_shipped
        state_not: "0"
    card:
      type: markdown
      title: Amazon Bestellungen - Versandt
      content: >
        {% for o in state_attr('sensor.amazon_orders_shipped', 'orders') or [] %}
        {% set titel = o.get('item_title') or o.get('subject') or o.get('order_id') or 'Amazon Bestellung' %}
        **{{ titel }}**

        {% if o.get('delivery_estimate') %}Lieferung: {{ o.get('delivery_estimate') }}{% endif %}
        {% if o.get('updated') %}Aktualisiert: {{ o.get('updated') | as_timestamp | timestamp_custom('%d.%m.%Y %H:%M') }}{% endif %}
        {% if o.get('order_id') %}Bestellung: {{ o.get('order_id') }}{% endif %}

        {% for s in o.get('shipments') or [] %}
        - Sendung: {{ s.get('item_title') or s.get('shipment_id') or 'Amazon Sendung' }}
          {% if s.get('status') %}({{ s.get('status') }}){% endif %}
          {% if s.get('delivery_window') %}- Zeitfenster: {{ s.get('delivery_window') }}{% endif %}
          {% if s.get('tracking_url') %}- [Tracking]({{ s.get('tracking_url') }}){% endif %}
        {% endfor %}

        {% endfor %}
  - type: conditional
    conditions:
      - entity: sensor.amazon_orders_partially_delivered
        state_not: "0"
    card:
      type: markdown
      title: Amazon Bestellungen - Teilweise zugestellt
      content: >
        {% for o in state_attr('sensor.amazon_orders_partially_delivered', 'orders') or [] %}
        {% set titel = o.get('item_title') or o.get('subject') or o.get('order_id') or 'Amazon Bestellung' %}
        **{{ titel }}**

        {% for s in o.get('shipments') or [] %}
        - {{ s.get('item_title') or s.get('shipment_id') or 'Sendung' }}
          {% if s.get('status') %}: {{ s.get('status') }}{% endif %}
          {% if s.get('delivered_at') %}- Zugestellt: {{ s.get('delivered_at') }}{% endif %}
          {% if s.get('tracking_url') %}- [Details]({{ s.get('tracking_url') }}){% endif %}
        {% endfor %}

        {% endfor %}
```

## Services

### `amazon_order_status.rescan`

Re-scan Amazon order mail over a configurable lookback window.

```yaml
service: amazon_order_status.rescan
data:
  days: 30
  clear_existing: true
  # config_entry_id: "optional-home-assistant-config-entry-id"
```

### `amazon_order_status.set_status`

Manually set an order or shipment status.

```yaml
service: amazon_order_status.set_status
data:
  order_id: "123-4567890-1234567"
  status: "Delivered"
  # shipment_id: "optional-shipment-id"
  # config_entry_id: "optional-home-assistant-config-entry-id"
```

### `amazon_order_status.mark_delivered`

Manually mark an order or shipment as delivered.

```yaml
service: amazon_order_status.mark_delivered
data:
  order_id: "123-4567890-1234567"
  delivered_at: "2026-06-27T12:34:56+02:00"
  # shipment_id: "optional-shipment-id"
  # config_entry_id: "optional-home-assistant-config-entry-id"
```

### `amazon_order_status.ignore_order`

Hide an order or shipment from active workflow without deleting it.

```yaml
service: amazon_order_status.ignore_order
data:
  order_id: "123-4567890-1234567"
  # shipment_id: "optional-shipment-id"
  # config_entry_id: "optional-home-assistant-config-entry-id"
```

### `amazon_order_status.restore_order`

Restore an ignored order or shipment back into the normal workflow.

```yaml
service: amazon_order_status.restore_order
data:
  order_id: "123-4567890-1234567"
  # shipment_id: "optional-shipment-id"
  # config_entry_id: "optional-home-assistant-config-entry-id"
```

### `amazon_order_status.purge_order`

Remove a tracked order entirely by order ID.

```yaml
service: amazon_order_status.purge_order
data:
  order_id: "123-4567890-1234567"
  # config_entry_id: "optional-home-assistant-config-entry-id"
```

## Privacy and Security

- IMAP credentials are stored by Home Assistant in `.storage/core_config_entries`.
- Raw email bodies are not stored by this integration.
- Order IDs, item titles, tracking URLs, delivery details, carrier names, item images, and parser diagnostics can be hidden through options.
- Tracking URLs are filtered to trusted HTTPS Amazon domains before exposure.

If your mail provider requires an app password, use that instead of your main account password.

## License

Released under the MIT License. See `LICENSE` and `CHANGELOG.md`.
