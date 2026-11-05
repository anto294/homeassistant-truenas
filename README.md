# TrueNAS Link for Home Assistant

[![GitHub release](https://img.shields.io/github/v/release/anto294/homeassistant-truenas?style=plastic)](https://github.com/anto294/homeassistant-truenas/releases)
[![HACS Default](https://img.shields.io/badge/HACS-Default-41BDF5.svg?style=plastic)](https://github.com/hacs/integration)
[![CI](https://img.shields.io/github/actions/workflow/status/anto294/homeassistant-truenas/ci.yml?style=plastic)](https://github.com/anto294/homeassistant-truenas/actions)
![Downloads](https://img.shields.io/github/downloads/anto294/homeassistant-truenas/total?style=plastic)

Monitor and control a TrueNAS SCALE system from Home Assistant: pools, datasets, disks, services, apps, virtual machines, containers, cloud sync, replication and snapshot tasks, and system updates.

Targets the versioned JSON-RPC API of **TrueNAS 25.04 and later**, including 25.10 and 27.0. It keeps working after an in-place TrueNAS upgrade without reconfiguration.

> [!NOTE]
> TrueNAS Link started as a fork of [tomaae/homeassistant-truenas](https://github.com/tomaae/homeassistant-truenas). It is a separate integration with its own `truenas_link` domain, so please report problems [here](https://github.com/anto294/homeassistant-truenas/issues), not upstream. See [Differences from upstream](#differences-from-upstream).

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

## Requirements

| Component | Minimum version |
|---|---|
| TrueNAS SCALE | 25.04 |
| Home Assistant | 2024.11.0 |

TrueNAS CORE and SCALE releases before 25.04 are not supported, because they do not provide the versioned websocket API this integration uses.

## Installation

### HACS (recommended)

[![Open your Home Assistant instance and open this repository inside HACS.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=anto294&repository=homeassistant-truenas&category=integration)

Or, in Home Assistant, open **HACS**, search for **TrueNAS Link**, download it and restart Home Assistant.

### Manual

Download `truenas_link.zip` from the [latest release](https://github.com/anto294/homeassistant-truenas/releases/latest), extract it into `config/custom_components/truenas_link/` and restart Home Assistant.

## Configuration

1. In the TrueNAS web UI, create an API key for Home Assistant (user menu → **API Keys** → **Add**).
2. In Home Assistant, go to **Settings → Devices & services → Add integration → TrueNAS Link** and fill in:

   | Field | Description |
   |---|---|
   | Name | Friendly name for this TrueNAS system |
   | Host | Hostname or IP address |
   | API key | The key created in step 1 |
   | Access level | **Read-only** (default) or **Administrator** (see [Access level](#access-level)) |
   | Verify SSL | Turn off if TrueNAS uses a self-signed certificate |

You can add the integration once per TrueNAS system. To change the host, API key or access level later, use **Reconfigure** from the integration's menu.

If TrueNAS Link does not appear in the list, clear your browser cache.

### Access level

| Level | Entities | Actions | Installing updates | API key |
|---|---|---|---|---|
| Read-only (default) | All | No | No | A key whose user has the `READONLY_ADMIN` role |
| Administrator | All | Yes | Yes | A key with full access |

New entries start as Read-only, so actions are always a deliberate choice. Entries created before this option stay on Administrator.

Read-only does not hide any entity, because every sensor only reads data. Update entities still show that an update is available, but without an install button. The actions are removed from Home Assistant, unless another TrueNAS entry has Administrator access. In that case, calling one on a read-only entity gives an error.

The level is what the integration does with the key, not what the key is allowed to do. To have TrueNAS enforce read-only access as well, use a key with the `READONLY_ADMIN` role. If you select Administrator with such a key, the actions and install buttons appear but TrueNAS refuses them, and the error is written to the Home Assistant log.

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
| `truenas_link.system_reboot` | Uptime sensor | Reboot TrueNAS |
| `truenas_link.system_shutdown` | Uptime sensor | Shut down TrueNAS |
| `truenas_link.dataset_snapshot` | Dataset sensor | Create a snapshot named `custom-<ISO timestamp>` |
| `truenas_link.service_start` / `_stop` / `_restart` / `_reload` | Service binary sensor | Control a TrueNAS service |
| `truenas_link.app_start` / `app_stop` | App binary sensor | Start or stop an app |
| `truenas_link.vm_start` / `vm_stop` | VM binary sensor | Start or stop a VM. `vm_start` accepts `overcommit: true` to start even without enough free memory |
| `truenas_link.container_start` / `container_stop` | Container binary sensor | Start or stop a container (27.0 and later) |
| `truenas_link.cloudsync_run` / `cloudsync_abort` | Cloud sync sensor | Run or abort a cloud sync task |

Example:

```yaml
action: truenas_link.dataset_snapshot
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
    custom_components.truenas_link: debug
```

You can also download diagnostics from the integration's page (sensitive data is redacted) and attach them to an [issue](https://github.com/anto294/homeassistant-truenas/issues).

## Translations

Available in English, Italian, Portuguese (Brazil), Russian, Slovak and Spanish.

English strings live in `custom_components/truenas_link/strings.json` and `custom_components/truenas_link/translations/en.json`. To add or improve a language, open a pull request that adds or updates the matching file in [`custom_components/truenas_link/translations/`](custom_components/truenas_link/translations/).

## Migrating from version 1.x or from the upstream integration

Version 2.0 renamed the domain from `truenas` to `truenas_link`. Home Assistant cannot move config entries between domains, so each TrueNAS system has to be added again. If you remove the old entry first and give the new one the **same name**, the entities get the same entity IDs as before, so their history, statistics, dashboards and automation triggers keep working.

1. Note the name of each TrueNAS entry in **Settings → Devices & services → TrueNAS**. It is the entry's title, `TrueNAS` unless you changed it.
2. Delete those entries (three-dot menu → **Delete**).
3. Install the new version:
   - **From 1.x of this integration:** in HACS, open **TrueNAS Link** → three-dot menu → **Remove** (this also deletes `config/custom_components/truenas/`), then download it again from HACS. Do not use **Update**: HACS keeps the old domain, and the download (and the repository refresh) fails with "No manifest.json file found custom_components/truenas/manifest.json".
   - **From the upstream integration:** download TrueNAS Link as described above, then remove the upstream **TrueNAS** integration in HACS. If the `config/custom_components/truenas/` folder still exists and no other integration uses it, delete it.
4. Restart Home Assistant.
5. Add **TrueNAS Link** with the same name, host and API key as before (see [Configuration](#configuration)).
6. In automations and scripts, replace `truenas.` actions with `truenas_link.` (for example `truenas.vm_start` becomes `truenas_link.vm_start`).

If you prefer, you can instead keep the upstream integration and run both side by side. Then give the TrueNAS Link entry a different name, so the entity IDs do not collide (otherwise Home Assistant adds a `_2` suffix to the new ones).

## Differences from upstream

- Has its own `truenas_link` domain, so it can be installed next to the upstream `truenas` integration.
- Reads the TrueNAS version on every update and calls the API methods of that release, so it keeps working after an in-place TrueNAS upgrade without reconfiguration.
- Supports TrueNAS 25.10 (`vm.*`, `update.status`, `update.run`, `pool.snapshot.create`) and 27.0 (`container.*`).
- Adds container entities and the `container_start` / `container_stop` actions on TrueNAS 27.0.
- Keeps the last known VM, container and memory values when a single query fails or returns no samples, instead of making entities unavailable.
- Handles `null` values that newer TrueNAS releases return for reporting data and app versions.

## Credits and license

This project is a fork of [tomaae/homeassistant-truenas](https://github.com/tomaae/homeassistant-truenas), created by Tomaae and its contributors. Thanks to them for the original integration.

Distributed under the [Apache License 2.0](LICENSE).
