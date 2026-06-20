



**Amazon Order Status Integration for Home Assistant**

The Amazon Order Status integration allows Home Assistant to track your Amazon order emails and provide up-to-date information about delivery status. By connecting directly to your email via IMAP, the integration automatically detects when orders are received, shipped, and delivered, and provides quick links to the order tracking pages.

We obtain this information via email as Amazon does not publish any public API that could be used for order tracking. 

**Features**

* Automatically track Amazon order delivery status.
* Parse English and German Amazon order status emails through language profiles.
* Match related emails by Amazon order ID first, then by item title when Amazon omits the order ID from shipped or out-for-delivery emails.
* Preserve item titles separately from the raw email subject.
* Track compact status history per order.
* Configurable polling interval to check for new order updates.
* Configurable initial scan window for first setup and rebuilds.
* Optional automatic marking of processed emails as read.
* Configurable retention for delivered orders.
* Scan diagnostics on the last-updated sensor.
* Sender-domain validation to ignore non-Amazon messages with matching subjects.
* Privacy options to hide order IDs, item titles, and tracking URLs from sensor attributes.
* Reconfigure flow for changing IMAP connection settings without deleting the integration.
* Service for manual rescans without deleting Home Assistant storage files.
* Fully customizable options via Home Assistant's UI.

**Installation**

*Custom HACS Repository*

Click here: 

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=ichwars&repository=ha-amazon-order-status&category=integration)

OR

   * Open HACS (Home Assistant Community Store) in Home Assistant
   * Click the three dots menu (top right) and select Custom repositories
   * Put ichwars/ha-amazon-order-status for Repository, and Integration for Category, then click "Add".
   * Click "Explore and Download Repositories" in the lower right.  Search for "Amazon Order Status" and install
   * Restart Home Assistant




*Manual*

Download the Integration: https://github.com/ichwars/ha-amazon-order-status

Place the amazon_order_status folder in your Home Assistant custom_components directory:
* Home Assistant Directory/custom_components/amazon_order_status/

*Make sure it contains:*
```
* translations/en.json
* __init\__.py
* config_flow.py
* coordinator.py
* const.py
* options_flow.py
* manifest.json
* sensor.py
* services.yaml
```

****Restart Home Assistant to detect the new integration.****

**After the install, you must add the Integration:**

* Go to Settings → Devices & Services → Add Integration.

* Search for Amazon Order Status.

* Enter your IMAP server details, username, and password.

**Configuration Options**

* *All options can be changed through the Integration Options dialog after adding the integration.*

Option - Description

* ```delivered_retention_days```: 	How long Home Assistant should keep a record of delivered items. Default: 30 days.
* ```update_interval```: 	How often Home Assistant should check your Amazon emails for order updates, in minutes. Default: 5 minutes.
* ```initial_scan_days```: How many days of email should be scanned when the integration has no previous scan timestamp. Default: 14 days.
* ```mark_as_read```: 	If enabled, emails containing Amazon delivery updates will be automatically marked as read after processing. Default: True.
* ```require_amazon_sender```: If enabled, only messages with sender headers from Amazon domains are processed. Default: True.
* ```expose_order_id```: If enabled, order IDs are exposed as sensor attributes. Default: True.
* ```expose_item_title```: If enabled, parsed item titles are exposed as sensor attributes. Default: True.
* ```expose_tracking_url```: If enabled, Amazon HTTPS tracking/order links are exposed as sensor attributes. Default: True.
* ```expose_delivery_details```: If enabled, body-derived delivery estimate, delivery window, delivered-at text, and item count are exposed as sensor attributes. Default: False.
* ```expose_carrier```: If enabled, detected shipping carrier names are exposed as sensor attributes. Default: False.
* ```expose_item_image```: If enabled, trusted Amazon product image URLs parsed from the email body are exposed as sensor attributes. Default: False.
* ```expose_parser_debug```: If enabled, sanitized parser diagnostics are exposed. Raw emails, addresses, order IDs, and full links are not exposed. Default: False.
* ```imap_folder```: Optional - Specify a folder to search for emails rather than the default INBOX.  If left blank, defaults to searching INBOX.  If a folder is specified (Either "Folder Name" or "INBOX/Folder Name" depending on provider) email searches will be limited to that folder. 

Upon initial installation, this integration scans the previous ```initial_scan_days``` worth of emails for Amazon order emails. Depending on the volume of email in the inbox, this initial scan could take anywhere from a few seconds to a few minutes. Once the initial data load is complete, the integration keeps track of its last-scanned date/time and performs only rapid scans of the messages received since the last check.

**Upgrade and Migration**

Version ```1.4.8``` keeps existing tracked orders and can read the legacy global storage key automatically. After updating through HACS or manually replacing the integration files, restart Home Assistant.

Version ```1.4.7``` changed entity unique IDs to include the config entry ID so multiple Amazon Order Status entries can coexist. Existing single-entry installations may see newly created entities after updating from older releases; remove old disabled/orphaned entities from the entity registry if Home Assistant keeps them around.

If you want to rebuild the tracked order list after upgrading, call ```amazon_order_status.rescan``` instead of deleting files from ```/config/.storage```. Use ```clear_existing: true``` for a clean rebuild from the selected lookback window.

If you enabled body-derived attributes such as ```item_image_url``` after orders were already tracked, call ```amazon_order_status.rescan``` once. A rescan can now enrich existing orders with missing details from older order emails without moving the order status backwards.

The project is licensed under the MIT License. See ```LICENSE``` and ```CHANGELOG.md``` for release details.

**Notes**

***Security Warning - Your IMAP password is stored in the .storage/core_config_entries along with, likely, many other secret values.  This is a cleartext file.  HA, by necessity, must store all secret data in such a way that, if your server is breached at the filesystem level, your secrets could be exposed.  You should be confident in the security of your HA installation (not exposed to the internet, no unencrypted backups of the .storage directory) before using this or any integration that asks for secret values.***

*Note that some email providers (Google, most notably) require the use of a passcode (Google calls it an "App Password") for some third party applications to access your inbox, rather than your gmail/google workspace credentials.  See here for more information on how to create an app password in Google: https://support.google.com/accounts/answer/185833?hl=en*

* Adjust ```update_interval``` depending on how frequently you want to poll your inbox. Setting this too low may result in unnecessary server load.

* Option ```delivered_retention_days``` helps prevent the history from growing too large over time.

Once configured, this integration creates 6 new sensors:

* ```sensor.amazon_orders_delivered``` 
* ```sensor.amazon_orders_delivery_attempted```
* ```sensor.amazon_orders_out_for_delivery```
* ```sensor.amazon_orders_ordered```
* ```sensor.amazon_orders_shipped```
* ```sensor.amazon_orders_last_updated```

The ```sensor.amazon_orders_last_updated``` sensor contains a datestamp indicating the last email check. Its attributes also expose diagnostics for the most recent scan:

* ```started``` and ```since```
* ```imap_folder```
* ```email_count```, ```fetched_count```, ```recognized_count```, ```updated_count```, and ```enriched_count```
* ```matched_by_subject_count```
* skip counters such as ```skipped_no_order_id```, ```skipped_no_status```, and ```skipped_status_regression```
* ```error``` if the scan failed before email processing

The remaining sensors contain the following attributes :
* ```order_id``` (Amazon Order ID)
* ```item_title``` (best available item title parsed from Amazon status emails)
* ```status``` (current normalized status)
* ```subject``` (display subject; preserves the item title when later emails only contain a generic delivery subject; only exposed when raw order IDs and item titles are enabled)
* ```last_subject``` (raw subject from the most recent email that updated the order; only exposed when raw order IDs and item titles are enabled)
* ```updated``` (send date of the email - indicates the date/time of the most recent order update.  This will be an iso date stamp, which can be reformatted via templates in any way you choose. Some examples are below.)
* ```tracking_url``` (provides the link back to the amazon order tracking page for that order)
* ```delivery_estimate``` (body-derived delivery date or phrase, such as ```24. Juni - 25. Juni``` or ```verzögert```)
* ```delivery_window``` (body-derived time window, such as ```15h - 19h```)
* ```delivered_at``` (body-derived delivered or attempted delivery phrase, such as ```heute um 11:04```)
* ```carrier``` (detected carrier, when found)
* ```item_count``` (detected item count)
* ```item_image_url``` (trusted Amazon product image URL parsed from the email body)
* ```parser_debug``` (sanitized parser diagnostics; no raw email text, addresses, order IDs, or full links)
* ```history``` (compact list of status changes seen for the order)

The ```order_id```, ```item_title```, ```tracking_url```, body-derived delivery fields, carrier, item image URL, and parser debug attributes can be hidden through the integration options. To avoid indirect leaks, raw subjects in current orders and history events are only exposed when both order IDs and item titles are enabled; tracking URLs are also removed from history when tracking URL exposure is disabled. Tracking URLs are only kept when they point to HTTPS Amazon domains. Item image URLs are only kept when they point to trusted Amazon image CDN hosts.

This integration tracks the current status for each order. A single order will appear in one status sensor at a time: Ordered → Shipped → Out for delivery → Delivery attempted → Delivered. Status updates are monotonic, so a late "ordered" email will not move an already-shipped order backwards.

German Amazon.de subjects such as these are supported:

* ```Bestellt: "Item name"```
* ```Versendet: "Item name"```
* ```In Zustellung: "Item name"```
* ```Zustellversuch: "Item name"```
* ```Zugestellt: 1 Artikel | Bestellung # 123-4567890-1234567```
* ```Aktualisierung der voraussichtlichen Lieferung ... Bestellung ...```

**Dashboard Example**

Each status card is conditional, so the dashboard shows nothing when there are no orders in that status.

```yaml
type: vertical-stack
cards:
  - type: conditional
    conditions:
      - entity: sensor.amazon_orders_ordered
        state_not: "0"
    card:
      type: markdown
      title: Amazon Orders - Ordered
      content: >
        {% for o in state_attr('sensor.amazon_orders_ordered', 'orders') or [] %}
        {% set title = o.get('item_title') or o.get('subject') or o.get('order_id') or 'Amazon order' %}
        {% set img = o.get('item_image_url') %}
        {% if img %}![Item]({{ img }}){% endif %}

        **{{ title }}**

        {% if o.get('delivery_estimate') %}Delivery: {{ o.get('delivery_estimate') }}{% endif %}

        {% if o.get('updated') %}Updated: {{ o.get('updated') | as_timestamp | timestamp_custom('%d.%m.%Y %H:%M') }}{% endif %}

        {% if o.get('order_id') %}Order ID: {{ o.get('order_id') }}{% endif %}

        {% if o.get('tracking_url') %}[Open order]({{ o.get('tracking_url') }}){% endif %}
        {% endfor %}
  - type: conditional
    conditions:
      - entity: sensor.amazon_orders_shipped
        state_not: "0"
    card:
      type: markdown
      title: Amazon Orders - Shipped
      content: >
        {% for o in state_attr('sensor.amazon_orders_shipped', 'orders') or [] %}
        {% set title = o.get('item_title') or o.get('subject') or o.get('order_id') or 'Amazon order' %}
        {% set img = o.get('item_image_url') %}
        {% if img %}![Item]({{ img }}){% endif %}

        **{{ title }}**

        {% if o.get('delivery_estimate') %}Delivery: {{ o.get('delivery_estimate') }}{% endif %}

        {% if o.get('delivery_window') %}Window: {{ o.get('delivery_window') }}{% endif %}

        {% if o.get('updated') %}Updated: {{ o.get('updated') | as_timestamp | timestamp_custom('%d.%m.%Y %H:%M') }}{% endif %}

        {% if o.get('order_id') %}Order ID: {{ o.get('order_id') }}{% endif %}

        {% if o.get('tracking_url') %}[Track package]({{ o.get('tracking_url') }}){% endif %}
        {% endfor %}
  - type: conditional
    conditions:
      - entity: sensor.amazon_orders_out_for_delivery
        state_not: "0"
    card:
      type: markdown
      title: Amazon Orders - Out for Delivery
      content: >
        {% for o in state_attr('sensor.amazon_orders_out_for_delivery', 'orders') or [] %}
        {% set title = o.get('item_title') or o.get('subject') or o.get('order_id') or 'Amazon order' %}
        {% set img = o.get('item_image_url') %}
        {% if img %}![Item]({{ img }}){% endif %}

        **{{ title }}**

        {% if o.get('delivery_estimate') %}Delivery: {{ o.get('delivery_estimate') }}{% endif %}

        {% if o.get('delivery_window') %}Window: {{ o.get('delivery_window') }}{% endif %}

        {% if o.get('carrier') %}Carrier: {{ o.get('carrier') }}{% endif %}

        {% if o.get('updated') %}Updated: {{ o.get('updated') | as_timestamp | timestamp_custom('%d.%m.%Y %H:%M') }}{% endif %}

        {% if o.get('tracking_url') %}[Track package]({{ o.get('tracking_url') }}){% endif %}
        {% endfor %}
  - type: conditional
    conditions:
      - entity: sensor.amazon_orders_delivery_attempted
        state_not: "0"
    card:
      type: markdown
      title: Amazon Orders - Delivery Attempted
      content: >
        {% for o in state_attr('sensor.amazon_orders_delivery_attempted', 'orders') or [] %}
        {% set title = o.get('item_title') or o.get('subject') or o.get('order_id') or 'Amazon order' %}
        {% set img = o.get('item_image_url') %}
        {% if img %}![Item]({{ img }}){% endif %}

        **{{ title }}**

        {% if o.get('delivered_at') %}Attempted: {{ o.get('delivered_at') }}{% endif %}

        {% if o.get('carrier') %}Carrier: {{ o.get('carrier') }}{% endif %}

        {% if o.get('updated') %}Updated: {{ o.get('updated') | as_timestamp | timestamp_custom('%d.%m.%Y %H:%M') }}{% endif %}

        {% if o.get('tracking_url') %}[Track package]({{ o.get('tracking_url') }}){% endif %}
        {% endfor %}
  - type: conditional
    conditions:
      - entity: sensor.amazon_orders_delivered
        state_not: "0"
    card:
      type: markdown
      title: Amazon Orders - Delivered
      content: >
        {% for o in state_attr('sensor.amazon_orders_delivered', 'orders') or [] %}
        {% set title = o.get('item_title') or o.get('subject') or o.get('order_id') or 'Amazon order' %}
        {% set img = o.get('item_image_url') %}
        {% if img %}![Item]({{ img }}){% endif %}

        **{{ title }}**

        {% if o.get('delivered_at') %}Delivered: {{ o.get('delivered_at') }}{% endif %}

        {% if o.get('item_count') %}Items: {{ o.get('item_count') }}{% endif %}

        {% if o.get('updated') %}Updated: {{ o.get('updated') | as_timestamp | timestamp_custom('%d.%m.%Y %H:%M') }}{% endif %}

        {% if o.get('tracking_url') %}[Open order]({{ o.get('tracking_url') }}){% endif %}
        {% endfor %}
```

**Services**

```amazon_order_status.purge_order```

Remove a specific order from tracking by order ID.

```yaml
service: amazon_order_status.purge_order
data:
  order_id: "123-4567890-1234567"
  # config_entry_id: "optional-home-assistant-config-entry-id"
```

```amazon_order_status.rescan```

Rescan Amazon order emails over a configurable lookback period. This replaces the old manual workflow of deleting ```/config/.storage/amazon_order_status``` when you want to rebuild the tracked order state.

```yaml
service: amazon_order_status.rescan
data:
  days: 30
  clear_existing: true
  # config_entry_id: "optional-home-assistant-config-entry-id"
```

Use ```clear_existing: true``` when you want to rebuild the order list from the selected email lookback window. Use ```clear_existing: false``` to keep existing orders and only merge any status emails found in the lookback window.

Use ```clear_existing: false``` after enabling optional attributes such as item images when you only want to enrich existing tracked orders from recent emails.

Occasionally Amazon ships packages through 3d party couriers and a "Delivered" email is never sent (or drastically delayed).  To account for this, you can manually delete orders from the database.  You can pass the order id to ```amazon_order_status.purge_order``` through dev tools, although it's easier to create a helper and script, and pass values to the script via a button card.

Create a Helper: 
* Go to Settings > Devices & Services > Helpers
* Click Create Helper
* Select "Text"
* Name: amazon_order_purge_id
* Click Create

Then create a script:
* Go to Settings > Automations & scenes > Scripts
* Click Create script
* Click Create new script
* Click the 3 dots in the upper right > Edit in YAML
* Paste the following:
```
sequence:
  - data_template:
      order_id: "{{ states('input_text.amazon_order_purge_id') }}"
    action: amazon_order_status.purge_order
alias: Purge Amazon Order
description: ""
```
* Click Save.

You can then leverage the helper and script in a dashboard to purge orders by order ID.  Here's a sample set of buttons:
```
  - type: horizontal-stack
    cards:
      - type: entities
        entities:
          - entity: input_text.amazon_order_purge_id
            name: Order ID to purge
            secondary_info: none
      - show_name: true
        show_icon: true
        type: button
        name: Purge order
        icon: mdi:delete
        tap_action:
          action: call-service
          service: script.turn_on
          target:
            entity_id: script.purge_amazon_order
        hold_action:
          action: none
        show_state: false
        icon_height: 20px
```

The purge helper/button stack can be placed below the conditional order stack from the dashboard example above.
