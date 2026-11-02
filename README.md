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

## Add-ons (apps): internet usage vs. local container traffic
On Home Assistant OS / Supervised, the Supervisor reports cumulative network RX/TX bytes for each
add-on container. These counters cover everything crossing the container's virtual interface on the
internal `hassio` bridge (`172.30.32.0/23`), **not** only internet traffic, so they are never used as
internet (WAN) usage directly. The integration samples them every minute, classifies each add-on
(slug first, then `/addons/{slug}/info`: `ingress`, `ingress_only`, `host_network`, exposed ports) and
splits every delta into real WAN bytes and internal bridge bytes:

| Profile | WAN usage | Internal bridge |
|---|---|---|
| Local only (File editor, InfluxDB, Mosquitto, Grafana, SSH, VS Code, Zigbee2MQTT?) | 0 B | all RX/TX |
| Backup (Google Drive Backup?) | TX + ~4 % of TX as RX (ACKs) | the rest of RX (snapshot pulled from the Supervisor) |
| Tunnel / proxy (Cloudflared, Tailscale, WireGuard, Nginx proxy) | 50 % of RX/TX | other 50 % (hop to Home Assistant Core) |
| Internet capable (everything else) | all RX/TX | ? |

Slug lists and factors are in `const.py`. Home Assistant Core runs on the host network and has no
container counters, so it is listed as its own consumer: what your router measured for the HA host
(choose it in the settings) minus the add-ons' WAN usage, i.e. cloud integrations, HACS, streams,
voice and Supervisor/OS updates. Add-on WAN is capped at the router total.

The dashboard shows `[ Internet (WAN) | Local Container Traffic | All ]` (default: Internet), and the
`Top add-on ?` sensors carry both metrics in their attributes.
* Add-ons with `host_network: true` report whole-host counters, so they are listed as "not ranked"
  instead of being attributed wrongly.
* Add-on totals recorded by earlier versions (raw RX+TX counted as internet) are discarded on upgrade.
* Not available on Container/Core installs (no Supervisor); the section is simply hidden.

## Service estimates – what is real and what is not
Home Assistant has no per-integration byte counters. Each integration is labelled:

| Label | Meaning |
|---|---|
| Measured | Its host is a device you track → real router counters (split evenly if several integrations share it) |
| Estimated | Internet-facing (`cloud_*` iot_class): polls per day (from the coordinator interval when found) × typical payload |
| Local network | `local_*` integrations: measured if tracked, otherwise a polling estimate, or no estimate for local push. Hidden by default, tick the checkbox to show |
| Hidden | Zigbee, Z-Wave, Bluetooth, Thread, helpers, calculated: no IP traffic |
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
