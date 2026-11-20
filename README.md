# Fluvius outages

[![HACS Custom](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://hacs.xyz)
[![Validate](https://github.com/Coollision/ha-fluvius-outages/actions/workflows/validate.yml/badge.svg)](https://github.com/Coollision/ha-fluvius-outages/actions/workflows/validate.yml)
[![License: Apache-2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)

Know when the power is (or will be) out at your address in Flanders: **planned works and unplanned outages** reported by Fluvius, as Home Assistant entities you can automate on.

> **Unofficial.** Not affiliated with or endorsed by Fluvius, Home Assistant, Nabu Casa or the Open Home Foundation. See [NOTICE](NOTICE).

## Why

Fluvius shows outages on an [outage map](https://www.fluvius.be/nl/storingen-en-werken/stroomonderbrekingen) but offers nothing a smart home can read. This integration reads the same data the map uses and tells Home Assistant whether an outage touches **your postcode and street**, so you can get a heads-up the day before planned works, switch things off gracefully, or know it is not just your fuse.

## Requirements

| | |
|---|---|
| Home Assistant | 2026.10 or newer |
| Account | None. No login, no API key to request |

## Installation

1. Add this repository to HACS as a **custom repository** of type **Integration** (`https://github.com/Coollision/ha-fluvius-outages`), download it and restart Home Assistant.
2. **Settings → Devices & services → Add integration → Fluvius outages**.

## Setup

| Field | |
|---|---|
| **Postcode** | Required. Four digits. |
| **Streets** | Optional, one or more. Only outages touching these streets are reported. Spelling does not need to be exact (`Molenbekstraat` finds `MOLENBEEKSTRAAT`) and a house number is ignored. Leave empty to watch the whole postcode, which is noisy in a big municipality. |
| **Work codes** | Optional. Fluvius gives every job a *werfcode*, printed on the notice in your letterbox. Outages with a listed code are always reported, wherever they are. |

You can add the integration more than once, for example for your home and your parents' house. Streets, work codes and the update interval can be changed later under **Configure**.

## Entities

Each watched location is one service device with:

| Entity | |
|---|---|
| `binary_sensor` **Power outage** | On while a planned or unplanned outage covers the location. Attributes: `type` (`planned` / `unplanned`), `start`, `end`, `werfcode`, `customers_affected`, `customers_restored`, `streets`. |
| `binary_sensor` **Planned outage upcoming** | On from the moment planned works are announced for the location until they start. How early depends on the *Days ahead* setting. Same attributes as the next planned outage. |
| `sensor` **Next planned outage** | Start time of the next planned outage that has not begun, with the same attributes. |
| `sensor` **Power expected back** | End of the outage under way. Unknown for an unplanned outage: Fluvius has no end time until the power is restored. |
| `calendar` **Outages** | Every announced outage as a calendar event. |

**On a UPS?** *Power outage* reports what Fluvius says about your street, independent of your own mains. If your cluster runs on a UPS it tells you why the lights are about to go out, and `customers_affected`, `customers_restored`, `start` and `end` describe the outage while it lasts (Fluvius gives no end time for an unplanned one until it is fixed).

The binary sensors and the sensors switch at the exact start and end time of an outage, without waiting for the next poll.

### Example: warn me as soon as works are announced

```yaml
automation:
  - alias: Planned power outage announced
    triggers:
      - trigger: state
        entity_id: binary_sensor.planned_outage_upcoming # your entity id
        to: "on"
    actions:
      - action: notify.notify
        data:
          title: Planned power outage
          message: >-
            {{ state_attr(trigger.entity_id, 'start') }} to
            {{ state_attr(trigger.entity_id, 'end') }},
            {{ state_attr(trigger.entity_id, 'customers_affected') }} customers
```

### Example: warn the evening before

```yaml
automation:
  - alias: Planned power outage tomorrow
    triggers:
      - trigger: calendar
        event: start
        entity_id: calendar.outages # your entity id
        offset: "-12:00:00"
    actions:
      - action: notify.notify
        data:
          title: Power outage tomorrow
          message: "{{ trigger.calendar_event.description }}"
```

## How it works

- Every 10 minutes (configurable, 5 minutes at the very least) the integration asks Fluvius for all ongoing and announced outages and keeps the ones that match your location. Matching happens inside Home Assistant: **your postcode and street are never sent to Fluvius**.
- Fluvius's website hands every visitor the same public key for this data. The integration reads it from the outage page itself and fetches a new one if it is refused, so there is no key to configure.
- An outage counts as *under way* between its start and end time. An unplanned outage with no end stays under way until Fluvius reports it as restored.

## Limitations

- **Unofficial interface.** This is the endpoint behind Fluvius's own website, not a documented API. Fluvius can change or block it. If the integration stops working, check the logs and open an issue.
- **15-day horizon.** Fluvius only answers for dates up to 15 days ahead, so planned works announced earlier appear once they come within 14 days.
- **Flanders only.** Fluvius covers Flemish distribution; Wallonia and Brussels are served by other operators.
- Outages are reported per street, not per house. Being in the street does not guarantee your house is affected.

## Diagnostics

Download diagnostics from the integration page. Your postcode, streets and work codes are redacted.
