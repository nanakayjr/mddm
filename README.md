# Mikrotik Data Usage (HACS)

Per-device **RX/TX data usage** (daily, monthly, yearly) built from the traffic sensors your
MikroTik integration (MikroTik Extended / Mikrotik Router) already exposes, plus an
**estimate of the data demand of each Home Assistant integration**, and a ready-made
**sidebar dashboard**.

## Install
1. HACS → ⋮ → *Custom repositories* → add this repo as **Integration**.
2. Install, restart Home Assistant.
3. Settings → Devices & services → *Add integration* → **Mikrotik Data Usage**.
4. Pick the devices to track, the periods (day / month / year) and, optionally, which tracked
   device is your Home Assistant host. A **Data Usage** item appears in the sidebar.

## Prerequisite
In MikroTik Extended, enable the per-client traffic sensors (client traffic / accounting).
Onboarding lists every `…TX` / `…RX` sensor pair it finds (MikroTik ones first). If none are
found the setup tells you so.

## A device isn't listed?
1. Disabled sensors don't show up: Settings → Devices & services → Entities → filter *Disabled*,
   search `tx`/`rx`, enable them (setup tells you how many disabled MikroTik TX/RX sensors exist).
2. Add it manually in the setup dialog: pick its RX and TX sensor (e.g. the kb/s ones) and a name.
3. Diagnose with Developer tools → Template:
   `{{ states.sensor | selectattr('attributes.unit_of_measurement','in',['kbps','kb/s','kbit/s','Mbps','kB/s','B/s','bps']) | map(attribute='entity_id') | list }}`

## How numbers are computed
* **Rate sensors** (bps, Mbps, B/s…) are integrated over time (trapezoid, sampled every 30 s
  and on every state change; gaps over 10 min are not interpolated).
* If a device has both kinds, the cumulative counter is used (exact) unless you tick *Prefer throughput*.
  Rate-based totals are only as precise as the sensor's update interval (MikroTik Extended: scan interval).
* **Counter sensors** (B, MB, GB…) are accumulated as deltas; a decrease is treated as a
  counter reset (e.g. a counter that zeroes every midnight).
* Day / month / year totals roll over at local midnight and persist across restarts.
* If download shows up as TX, enable *Swap RX/TX* (router vs. client perspective).

## Entities
Per tracked device: `<Today|This month|This year> RX / TX / total` (MB, `total` state class,
`last_reset` set, so they work in the Energy-style statistics and long-term graphs).
Plus *Network …* totals, *Top consumer …* rankings and *Home Assistant services estimate*.

## Add-ons (apps): measured, not estimated
On Home Assistant OS / Supervised, the Supervisor reports cumulative network RX/TX bytes for each
add-on container. The integration samples them every minute and builds daily/monthly/yearly totals
(restarts and updates, which reset the counters, are handled). You get a ranking in the dashboard
and `Top add-on today/this month/this year` sensors (full ranking in the attributes).
* Counters include LAN and internet traffic of the container (also its chatter with Home Assistant).
* Add-ons with `host_network: true` report whole-host counters, so they are listed as "not ranked"
  instead of being attributed wrongly.
* Not available on Container/Core installs (no Supervisor); the section is simply hidden.

## Service estimates – what is real and what is not
Home Assistant has no per-integration byte counters. Each integration is labelled:

| Label | Meaning |
|---|---|
| Measured | Its host is a device you track → real router counters (split evenly if several integrations share it) |
| Estimated | Cloud/polling: polls per day (from the coordinator interval when found) × typical payload |
| LAN estimate | Local host that you don't track; same estimate |
| Not estimable | Streaming/media/camera/voice – depends on use |

Choose your HA host in the settings to see *estimate vs. measured vs. everything else*
(updates, add-ons, backups, media). Payload sizes live in `estimator.py` (`PROFILES`) – tune them.

## Known limitations
* Written against the HA APIs without a live HA available to the author: expect to fix small
  issues on first run (please open an issue with the log).
* Client sensors must exist; a lease with no traffic sensor cannot be measured.
* A counter that resets and, within one sample, climbs past its previous value loses a little.
* Dashboard shows the last 30 days; history is kept for 400 days.

## Develop
`python -m pytest tests` runs the accounting-engine tests.
