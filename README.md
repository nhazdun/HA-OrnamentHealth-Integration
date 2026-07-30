# Ornament Health for Home Assistant

Pulls every biomarker from an [Ornament Health](https://ornament.health) profile into Home Assistant — one sensor per biomarker, each with its **full measurement history**, not just the value it had when you installed the integration.

[![hacs](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://hacs.xyz)

## What you get

- **A sensor for every biomarker** on the profile — hemoglobin, ferritin, vitamin D, TSH, cholesterol, and whatever else your lab reports contain. A typical profile yields 100–200 sensors.
- **Real history.** Lab results are dated when the blood was drawn, often years ago. Home Assistant normally records a sensor only from the moment it is created, so this integration writes every past measurement into long-term statistics. Open any biomarker and the graph shows the whole record, back to your first test.
- **Personalised reference ranges** as numeric attributes on every biomarker (`reference_min`/`reference_max`, plus the optimal range when Ornament provides one), so an automation or a chart can use them directly. Ornament calculates these bounds from the profile's age and sex, and they are converted into the same unit the sensor reports.
- **Correct units.** Ornament stores each value twice — in a canonical unit and in the unit your lab used. Sensors report the lab's unit, and older measurements are converted into that same unit so a lab switching from mg/dL to mmol/L cannot corrupt the history.
- **Qualitative results read as words.** Ornament returns urine and stool findings as 0 or 1 with the wording tucked into the unit (`Undetected|Detected`). Those sensors say `Undetected` or `Detected`, not `0.0 Undetected|Detected`, and expose which outcome is normal.
- **A problem binary sensor** that turns on when anything is flagged abnormal, plus diagnostic sensors for the biomarker count, abnormal count, last lab report date and laboratory name.
- **Grouped into lab panels.** Each Ornament category — Complete blood count, Urinalysis, Lipids, Vitamins — becomes its own device linked to the person, so 150 biomarkers browse as a couple of dozen panels instead of one flat list.
- **One device tree per person.** Add the integration once per family member; each gets its own profile device with its panels beneath it.

## Installation

### HACS (recommended)

1. HACS → three-dot menu → **Custom repositories**.
2. Repository: `https://github.com/nhazdun/HA-OrnamentHealth-Integration`, category: **Integration**.
3. Find **Ornament Health** in HACS, download it, then restart Home Assistant.

### Manual

Copy `custom_components/ornament_health` into your Home Assistant `config/custom_components/` directory and restart.

## Setup

**Settings → Devices & Services → Add Integration → Ornament Health.**

1. **Paste your API token.** The token is validated immediately against the Ornament API.
2. **Pick the person** whose data to track, from the profiles linked to that token.

To track more people, add the integration again and pick a different profile.

### Getting a token

The integration uses the public Ornament API (`api.ornament.health`). See the [Ornament API docs](https://ornament.readme.io/reference/obtaining-api-key) for how to obtain a token for your account. The token is stored in Home Assistant's config entry storage and sent only to `api.ornament.health`.

If the token expires, Home Assistant raises a reauth prompt — paste a new one and everything reconnects with its history intact.

## Options

Configure via the integration's **Configure** button:

| Option | Default | What it does |
| --- | --- | --- |
| Update interval (minutes) | 60 | How often to poll Ornament, from 15 minutes up to a week. Lab results change rarely, so a long interval is perfectly fine. |
| Import measurement history | on | Backfills past results into long-term statistics. Turn off if you only want values recorded from now on. |
| History attribute size | 20 | How many measurements to expose in the `history` attribute. Set to 0 to omit it. |
| Biomarker name language | en | Language requested from the Ornament dictionary. |

## Entities

Each biomarker sensor looks like this:

```yaml
sensor.ornament_<person>_vitamins_vitamin_d_25_hydroxy:
  state: 12.21
  unit_of_measurement: ng/mL
  attributes:
    biomarker_id: 187
    category: Vitamins
    status: normal          # or abnormal
    is_abnormal: false
    measured_at: "2026-05-14T09:00:00+00:00"
    measurement_count: 7
    first_measured_at: "2022-01-13T02:00:00+00:00"
    reference_min: 20.0     # personalised to age and sex, in the sensor's unit
    reference_max: 80.0
    optimal_min: 30.0
    optimal_max: 50.0
    previous_value: 24.8
    trend: down             # up / down / stable
    history: [{date: ..., value: ...}, ...]
```

Plus, per person: `binary_sensor.ornament_<person>_abnormal_results`, and the diagnostic sensors `biomarkers_tracked`, `abnormal_biomarkers`, `last_lab_report`, `last_laboratory`.

### Example automation

```yaml
automation:
  - alias: Notify when a new lab report arrives
    triggers:
      - trigger: state
        entity_id: sensor.ornament_nazariy_last_lab_report
    actions:
      - action: notify.mobile_app
        data:
          message: >
            New results from {{ state_attr('sensor.ornament_nazariy_last_lab_report', 'laboratory') }} —
            {{ states('sensor.ornament_nazariy_abnormal_biomarkers') }} biomarkers out of range.
```

## Syncing on demand

Two buttons sit on the person's device:

- **Sync now** — fetches from Ornament immediately instead of waiting for the next poll, and imports anything new.
- **Resync all data** — deletes the imported statistics, drops the cached biomarker dictionary, and rebuilds everything from Ornament. This is the way out if stored data ever looks wrong; Ornament is the source of truth, so nothing is lost.

The same two actions are available as the services `ornament_health.import_history` and `ornament_health.resync`, so an automation can trigger them. Both are safe to run repeatedly.

## Seeing the history

Click any biomarker sensor and the more-info dialog graphs its full record. To put several on one dashboard card, use a statistics graph — it reads the long-term store, so it shows years, not days:

```yaml
type: statistics-graph
title: Vitamin D
entities:
  - sensor.ornament_nazariy_vitamins_vitamin_d_25_hydroxy
stat_types:
  - mean
period: month
days_to_show: 2000
```

Between lab visits the line holds its last value, because that is what the sensor reads until a new result arrives.

## How history works

Home Assistant has two stores: **states** (short-lived, purged after `purge_keep_days`) and **long-term statistics** (hourly, kept forever). Only statistics accept timestamps in the past, so that is where the measurement history goes — each measurement lands in the hour it was actually taken. The sensors carry `state_class: measurement`, so Home Assistant's own graphs read those statistics and show the full record.

Gaps between lab visits appear as gaps in the graph, which is honest: no values are invented between tests.

## Icon

Home Assistant loads integration icons from [home-assistant/brands](https://github.com/home-assistant/brands), not from this repository, so the artwork is kept in [`brands/`](brands/custom_integrations/ornament_health) ready to submit: copy `custom_integrations/ornament_health/` into a fork of that repo and open a pull request. Until it is merged, Home Assistant shows the default placeholder.

## Notes and limitations

- The Ornament API exposes one token per account; all profiles linked to that account are offered in the picker.
- Biomarker names come from Ornament's dictionary (~5000 entries, cached locally and refreshed only when Ornament's digest changes). At the time of writing, the dictionary is English-only regardless of the requested language.
- This integration is read-only. It never writes to your Ornament account.
- Not affiliated with, endorsed by, or supported by Ornament Health. Medical data is shown as reported by your lab and is not medical advice.

## License

MIT — see [LICENSE](LICENSE).
