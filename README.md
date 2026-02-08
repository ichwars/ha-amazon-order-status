**Amazon Order Status Integration for Home Assistant**

The Amazon Order Status integration allows Home Assistant to track your Amazon order emails and provide up-to-date information about delivery status. By connecting directly to your email via IMAP, the integration automatically detects when orders are received, shipped, and delivered, and provides quick links to the order tracking pages.

We obtain this information via email as Amazon does not publish any public API that could be used for order tracking. 

**Features**

* Automatically track Amazon order delivery status.
* Configurable polling interval to check for new order updates.
* Optional automatic marking of processed emails as read.
* Configurable retention for delivered orders.
* Fully customizable options via Home Assistant's UI.

**Installation**

Download the Integration: https://github.com/koconnorgit/ha-amazon-order-status/releases/latest

Place the amazon_order_status folder in your Home Assistant custom_components directory:
config/custom_components/amazon_order_status/

*Make sure it contains:*

* translations/en.json
* __init\__.py
* config_flow.py
* coordinator.py
* const.py
* options_flow.py
* manifest.json
* sensor.py

****Restart Home Assistant to detect the new integration.****

**Add the Integration:**

* Go to Settings → Devices & Services → Add Integration.

* Search for Amazon Order Status.

* Enter your IMAP server details, username, and password.

Configuration Options

* *All options can be changed through the Integration Options dialog after adding the integration.*

Option - Description

* delivered_retention_days: 	How long Home Assistant should keep a record of delivered items. Default: 30 days.
* update_interval: 	How often Home Assistant should check your Amazon emails for order updates, in minutes. Default: 5 minutes.
* mark_as_read: 	If enabled, emails containing Amazon delivery updates will be automatically marked as read after processing. Default: True.

Upon intial installation, this integration will scan the previous 14 days worth of emails for Amazon order emails.  Depending on the volume of email in the inbox, this initial scan could take anywhere from a few seconds to a few minutes.  During this time, the integration dialog will display a spinning icon.  You can check the progress of the initial data load by looking at the console of your home assistant instance for debug log messages.  Once the initial data load is complete, the integration will keep track of its last-scanned date/time and perform only rapid scans of the messages recieved since the last check.

**Notes**

***Security Warning - Your IMAP password is stored in the .storage/core_config_entries along with, likely, many other secret values.  This is a cleartext file.  HA, by necessity, must store all secret data in such a way that, if your server is breached at the filesystem level, your secrets could be exposed.  You should be confident in the security of your HA installation (not exposed to the internet, no unencrypted backups of the .storage directory) before using this or any integration that asks for secret values.***

*Note that some email providers (Google, most notably) require the use of a passcode (Google calls it an "App Password") for some third party applications to access your inbox, rather than your gmail/google workspace credentials.  See here for more information on how to create an app password in Google: https://support.google.com/accounts/answer/185833?hl=en*

Adjust update_interval depending on how frequently you want to poll your inbox. Setting this too low may result in unnecessary server load.

* delivered_retention_days helps prevent the history from growing too large over time.

Once configured, this integration creates 5 new sensors:

* sensor.amazon_orders_delivered 
* sensor.amazon_orders_out_for_delivery
* sensor.amazon_orders_ordered
* sensor.amazon_orders_shipped
* sensor.amazon_orders_last_updated

The sensor.amazon_orders_last_updated sensor contains a datestamp indicating the last email check.

The remaining sensors contain the following attributes :
* subject (contains a truncated order name taken from the subject line of the email)
* updated (send date of the email - indicates the date of the most recent order update)
* tracking_url (provides the link back to the amazon order tracking page for that order.

...these can be parsed though markdown or other methods to display the Order dates, tracking links, etc. on the dashboard.    Here is an example markdown card to display order information from the sensor.amazon_orders_ordered sensor:



```
Amazon Orders – Ordered
{% set orders = state_attr('sensor.amazon_orders_ordered', 'orders') or [] %}
{% for data in orders %}
- **Item:** {{ data.subject }}
  - Updated: {{ data.updated | as_timestamp | timestamp_custom('%b %d at %I:%M %p') }}
  - [Track Package]({{ data.tracking_url }})
{% else %}
_No orders in this state._
{% endfor %}
```

For Mushroom Card users, here is a more attractive set of widgets:
```
type: vertical-stack
cards:
  - type: markdown
    title: 🟡 Ordered
    content: >
      {% for o in state_attr('sensor.amazon_orders_ordered', 'orders') or [] %}
      • **{{ o.subject }}**  Updated: {{o.updated | as_timestamp |
      timestamp_custom('%b %d at %I:%M %p') }} [Open]({{ o.tracking_url }}) {{
      '\n' }} {% else %} _None_ {% endfor %}
  - type: markdown
    title: 🚚 Shipped
    content: >
      {% for o in state_attr('sensor.amazon_orders_shipped', 'orders') or [] %}
      • **{{ o.subject }}**   Updated: {{o.updated | as_timestamp |
      timestamp_custom('%b %d at %I:%M %p') }}[Track]({{ o.tracking_url }}) {{
      '\n' }} {% else %} _None_ {% endfor %}
  - type: markdown
    title: 🚚 Out for Delivery
    content: >
      {% for o in state_attr('sensor.amazon_orders_out_for_delivery', 'orders') or [] %}
      • **{{ o.subject }}**   Updated: {{o.updated | as_timestamp |
      timestamp_custom('%b %d at %I:%M %p') }}[Track]({{ o.tracking_url }}) {{
      '\n' }} {% else %} _None_ {% endfor %}
  - type: markdown
    title: 📬 Delivered
    content: |2

        {% for o in state_attr('sensor.amazon_orders_delivered', 'orders') or [] %}
        • **{{ o.subject }}** Updated: {{o.updated | as_timestamp | timestamp_custom('%b %d at %I:%M %p') }} [Open]({{ o.tracking_url }}) {{ '\n' }}
        {% else %}
        _None_
        {% endfor %}


```
