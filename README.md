# TrueNAS for Home Assistant

[![GitHub release](https://img.shields.io/github/v/release/anto294/homeassistant-truenas?style=plastic)](https://github.com/anto294/homeassistant-truenas/releases)
[![HACS Custom](https://img.shields.io/badge/HACS-Custom-41BDF5.svg?style=plastic)](https://hacs.xyz/docs/faq/custom_repositories/)
[![CI](https://img.shields.io/github/actions/workflow/status/anto294/homeassistant-truenas/ci.yml?style=plastic)](https://github.com/anto294/homeassistant-truenas/actions)
![Downloads](https://img.shields.io/github/downloads/anto294/homeassistant-truenas/total?style=plastic)

Monitor and control a TrueNAS SCALE system from Home Assistant: pools, datasets, disks, services, apps, virtual machines, containers, cloud sync, replication and snapshot tasks, and system updates.

> [!NOTE]
> **This is a fork** of [tomaae/homeassistant-truenas](https://github.com/tomaae/homeassistant-truenas) by Tomaae. It is distributed separately as a HACS custom repository and targets the versioned JSON-RPC API of **TrueNAS 25.04 and later**, including 25.10 and 27.0. Please report problems with this fork [here](https://github.com/anto294/homeassistant-truenas/issues), not upstream.

## Contents

- [Differences from upstream](#differences-from-upstream)
- [Requirements](#requirements)
- [Installation](#installation)
- [Configuration](#configuration)
- [Entities](#entities)
- [Actions](#actions)
- [Supported TrueNAS versions](#supported-truenas-versions)
- [Troubleshooting](#troubleshooting)
- [Translations](#translations)
- [Credits and license](#credits-and-license)

## Differences from upstream

- Reads the TrueNAS version on every update and calls the API methods of that release, so it keeps working after an in-place TrueNAS upgrade without reconfiguration.
- Supports TrueNAS 25.10 (`vm.*`, `update.status`, `update.run`, `pool.snapshot.create`) and 27.0 (`container.*`).
- Adds container entities and the `container_start` / `container_stop` actions on TrueNAS 27.0.
- Keeps the last known VM, container and memory values when a single query fails or returns no samples, instead of making entities unavailable.
- Handles `null` values that newer TrueNAS releases return for reporting data and app versions.

## Requirements

| Component | Minimum version |
|---|---|
| TrueNAS SCALE | 25.04 |
| Home Assistant | 2024.11.0 |

TrueNAS CORE and SCALE releases before 25.04 are not supported, because they do not provide the versioned websocket API this integration uses.

## Installation

### HACS (recommended)

[![Open your Home Assistant instance and open this repository inside HACS.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=anto294&repository=homeassistant-truenas&category=integration)

Or add the repository manually:

1. In Home Assistant, open **HACS**, then the three-dot menu → **Custom repositories**.
2. Add `https://github.com/anto294/homeassistant-truenas` with type **Integration**.
3. Search for **TrueNAS**, download it and restart Home Assistant.

### Manual

Download `truenas.zip` from the [latest release](https://github.com/anto294/homeassistant-truenas/releases/latest), extract it into `config/custom_components/truenas/` and restart Home Assistant.

### Switching from the upstream integration

This fork uses the same `truenas` domain as upstream, so only one of the two can be installed at a time.

1. In HACS, remove the upstream **TrueNAS** integration. This deletes only its files.
2. Add this repository and download it as described above.
3. Restart Home Assistant.

Your config entries, entities and their history are kept, because the domain and entity unique IDs are the same.

## Configuration

1. In the TrueNAS web UI, create an API key for Home Assistant (user menu → **API Keys** → **Add**).
2. In Home Assistant, go to **Settings → Devices & services → Add integration → TrueNAS** and fill in:

   | Field | Description |
   |---|---|
   | Name | Friendly name for this TrueNAS system |
   | Host | Hostname or IP address |
   | API key | The key created in step 1 |
   | Verify SSL | Turn off if TrueNAS uses a self-signed certificate |

You can add the integration once per TrueNAS system. To change the host or API key later, use **Reconfigure** from the integration's menu.

If TrueNAS does not appear in the list, clear your browser cache.

## Entities

Data is polled every 60 seconds; available updates are checked every 12 hours.

| Device | Entity | Type | Notes |
|---|---|---|---|
| System | Uptime | sensor | Target for the reboot and shutdown actions |
| System | CPU usage, CPU temperature, load (1/5/15 min) | sensor | |
| System | Memory usage, ARC size | sensor | |
| System | Network RX / TX | sensor | One pair per interface |
| System | TrueNAS update | update | Install system updates from Home Assistant |
| Pools | Healthy | binary sensor | One per pool, including `boot-pool` |
| Pools | Free space | sensor | |
| Datasets | Used space | sensor | One per dataset; target for the snapshot action |
| Disks | Temperature | sensor | One per disk |
| Services | Running | binary sensor | One per TrueNAS service |
| Apps | Running | binary sensor | One per app |
| Apps | App update | update | |
| VMs | Running | binary sensor | One per virtual machine |
| Containers | Running | binary sensor | TrueNAS 27.0 and later |
| Cloud sync | Status | sensor | One per cloud sync task |
| Replication | Status | sensor | One per replication task |
| Snapshot tasks | Status | sensor | One per periodic snapshot task |

Most entities expose extra details as attributes (for example pool scrub state, disk model and serial, dataset compression and quota, VM memory and vCPUs).

## Actions

All actions target an entity of this integration.

| Action | Target entity | Description |
|---|---|---|
| `truenas.system_reboot` | Uptime sensor | Reboot TrueNAS |
| `truenas.system_shutdown` | Uptime sensor | Shut down TrueNAS |
| `truenas.dataset_snapshot` | Dataset sensor | Create a snapshot named `custom-<ISO timestamp>` |
| `truenas.service_start` / `_stop` / `_restart` / `_reload` | Service binary sensor | Control a TrueNAS service |
| `truenas.app_start` / `app_stop` | App binary sensor | Start or stop an app |
| `truenas.vm_start` / `vm_stop` | VM binary sensor | Start or stop a VM. `vm_start` accepts `overcommit: true` to start even without enough free memory |
| `truenas.container_start` / `container_stop` | Container binary sensor | Start or stop a container (27.0 and later) |
| `truenas.cloudsync_run` / `cloudsync_abort` | Cloud sync sensor | Run or abort a cloud sync task |

Example:

```yaml
action: truenas.dataset_snapshot
target:
  entity_id: sensor.truenas_tank_media
```

## Supported TrueNAS versions

The API methods used depend on the running release:

| Feature | 25.04 | 25.10 | 27.0 |
|---|---|---|---|
| System update check | `update.check_available` | `update.status` | `update.status` |
| System update install | `update.update` | `update.run` | `update.run` |
| Virtual machines | `virt.instance.*` | `vm.*` | `vm.*` |
| Containers | listed with VMs (`virt.instance.*`) | not available | `container.*` |
| Dataset snapshot | `zfs.snapshot.create` | `pool.snapshot.create` | `pool.snapshot.create` |

API references: [all versions](https://api.truenas.com/), [25.10](https://api.truenas.com/v25.10/), [27.0](https://api.truenas.com/v27.0/).

TrueNAS nightly and development builds can change the API at any time; some features may stop working on them.

## Troubleshooting

Enable debug logging to see every API query and response:

```yaml
logger:
  default: info
  logs:
    custom_components.truenas: debug
```

You can also download diagnostics from the integration's page (sensitive data is redacted) and attach them to an [issue](https://github.com/anto294/homeassistant-truenas/issues).

## Translations

Available in English, Italian, Portuguese (Brazil), Russian, Slovak and Spanish.

English strings live in `custom_components/truenas/strings.json` and `custom_components/truenas/translations/en.json`. To add or improve a language, open a pull request that adds or updates the matching file in [`custom_components/truenas/translations/`](custom_components/truenas/translations/).

## Credits and license

This project is a fork of [tomaae/homeassistant-truenas](https://github.com/tomaae/homeassistant-truenas), created by Tomaae and its contributors. Thanks to them for the original integration.

Distributed under the [Apache License 2.0](LICENSE).
