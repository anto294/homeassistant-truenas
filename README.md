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

- [Requirements](#requirements)
- [Installation](#installation)
- [Configuration](#configuration)
- [Entities](#entities)
- [Actions](#actions)
- [Security](#security)
- [Supported TrueNAS versions](#supported-truenas-versions)
- [Troubleshooting](#troubleshooting)
- [Translations](#translations)
- [Migrating from version 1.x or from the upstream integration](#migrating-from-version-1x-or-from-the-upstream-integration)
- [Differences from upstream](#differences-from-upstream)
- [Credits and license](#credits-and-license)

## Requirements

| Component | Minimum version |
|---|---|
| TrueNAS SCALE | 25.04 |
| Home Assistant | 2026.11.0 |

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
   | Verify SSL | On by default. Turn off if TrueNAS uses a self-signed certificate |

You can add the integration once per TrueNAS system. To change the host, API key or access level later, use **Reconfigure** from the integration's menu. Reconfigure does not show the stored API key: leave the field empty to keep it.

If TrueNAS Link does not appear in the list, clear your browser cache.

### Access level

| Level | Sensors | Actions | Installing updates | Cron job switches | API key |
|---|---|---|---|---|---|
| Read-only (default) | All | No | No | No | A key whose user has the `READONLY_ADMIN` role |
| Administrator | All | Yes | Yes | Yes | A key with full access |

New entries start as Read-only, so actions are always a deliberate choice. Entries created before this option stay on Administrator.

With Read-only, whatever cannot work is refused or gone:

- Cron job switches are not created, and switching an entry to Read-only removes them and the **Cron jobs** device.
- Actions stay listed in Home Assistant, because they belong to the integration and not to an entry, but calling one on a read-only entity gives an error and sends nothing to TrueNAS.
- Update entities stay, because they still show that an update is available, but they have no install button.

All sensors and binary sensors stay, because they only read data.

See [Security](#security) for what the level does and does not protect against.

## Entities

Data is polled every 60 seconds; available updates are checked every 12 hours.

| Device | Entity | Type | Notes |
|---|---|---|---|
| System | Uptime | sensor | Target for the reboot and shutdown actions |
| System | CPU usage, CPU temperature, load (1/5/15 min) | sensor | |
| System | Memory usage, ARC size | sensor | |
| System | Network RX / TX | sensor | One pair per interface |
| System | TrueNAS update | update | Install system updates from Home Assistant |
| System | Alerts | sensor | Active TrueNAS alerts; the messages are an attribute |
| System | Critical alerts | binary sensor | On for an alert of level CRITICAL or above |
| System | Reboot required | binary sensor | The reasons are an attribute |
| Pools | Healthy | binary sensor | One per pool, including `boot-pool` |
| Pools | Free space | sensor | |
| Pools | Scan | sensor | `idle`, `scrubbing`, `paused` or `resilvering`; target for the scrub actions |
| Pools | Last scrub | sensor | When the last scrub finished. Unknown after a Home Assistant restart until a finished scrub is the pool's latest scan again |
| Pools | Errors | sensor | ZFS read, write and checksum errors of the pool's disks |
| Datasets | Used space | sensor | One per dataset; target for the snapshot action |
| Disks | Temperature | sensor | One per disk |
| Services | Running | binary sensor | One per TrueNAS service |
| Apps | Running | binary sensor | One per app |
| Apps | App update | update | |
| VMs | Running | binary sensor | One per virtual machine |
| Containers | Running | binary sensor | TrueNAS 27.0 and later |
| Cloud sync | Status | sensor | One per cloud sync task |
| Replication | Status | sensor | One per replication task; target for the run action |
| Snapshot tasks | Status | sensor | One per periodic snapshot task |
| Cron jobs | Enabled | switch | One per cron job. Disabled by default, Administrator only |

Most entities expose extra details as attributes (for example pool scrub state, disk model and serial, dataset compression and quota, VM memory and vCPUs).

## Actions

All actions target an entity of this integration and need the Administrator access level.

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
| `truenas_link.replication_run` | Replication sensor | Run a replication task |
| `truenas_link.pool_scrub_start` / `pool_scrub_pause` / `pool_scrub_stop` | Pool scan sensor | Start or resume, pause, or stop a scrub. Not available for the boot pool |

Example:

```yaml
action: truenas_link.dataset_snapshot
target:
  entity_id: sensor.truenas_tank_media
```

## Security

An API key is powerful, and Home Assistant is one more place that can use it. This integration is designed so that a mistake in a dashboard or an automation stays small.

**How it limits the risk**

- **Read-only by default.** New entries cannot change anything on TrueNAS until you choose Administrator.
- **Actions instead of switches.** Shutting down the NAS or stopping a VM is an action you have to call on purpose. Voice assistants and commands such as "turn off the living room" cannot reach it.
- **Cron job switches are limited.** They are disabled by default, and as config entities they are not exposed to voice assistants or switched by area and device targets. They can only enable or disable a job.
- **No free-form input.** No action accepts a command, a user or an API method. There is no action to run a cron job, and the integration never reads the command or user of a cron job.
- **Clean stops first.** VMs and containers get time to shut down. On TrueNAS 25.10 and later, they are forced off only after their shutdown timeout. On 25.04, a VM that does not shut down within 60 seconds keeps running.
- **A resilver cannot be interrupted.** Scrub actions are refused while a pool is resilvering.

**What it does not protect against**

- **The access level is a limit in this integration, not on the key.** Only a key with the `READONLY_ADMIN` role makes TrueNAS itself refuse changes, so use one if you do not need actions. Anyone who can read your Home Assistant configuration can read the key.
- **Narrow roles do not make a key harmless.** `POOL_WRITE`, needed for scrubs, is also the role of `pool.export`. `SYSTEM_CRON_WRITE`, needed for cron job switches, also allows changing and running cron jobs, which can run commands on the NAS. `system.shutdown` needs `FULL_ADMIN`. Treat any key that can do more than read as an administrator's key.
- **Turning off Verify SSL exposes the key.** It is on by default, but TrueNAS often uses a self-signed certificate, which needs it off. Without it, someone on your network could intercept the connection and the key. Prefer a certificate Home Assistant trusts, especially with an Administrator key. Existing entries keep their setting: check it with **Reconfigure**.

**Before you automate power actions**

- If Home Assistant runs in a VM or app on this NAS, shutting down the NAS or stopping that VM also stops Home Assistant, and it cannot bring them back. The integration cannot detect this.
- Nothing here can turn on a NAS that is off, because its API is not running. Use the [Wake on LAN](https://www.home-assistant.io/integrations/wake_on_lan/) integration, if your hardware supports it.
- Disabling a cron job is silent. If it runs your backups, nothing tells you they stopped.

## Supported TrueNAS versions

The API methods used depend on the running release:

| Feature | 25.04 | 25.10 | 27.0 |
|---|---|---|---|
| System update check | `update.check_available` | `update.status` | `update.status` |
| System update install | `update.update` | `update.run` | `update.run` |
| Virtual machines | `virt.instance.*` | `vm.*` | `vm.*` |
| Containers | listed with VMs (`virt.instance.*`) | not available | `container.*` |
| Dataset snapshot | `zfs.snapshot.create` | `pool.snapshot.create` | `pool.snapshot.create` |
| Scrub actions | `pool.scrub.scrub` | `pool.scrub.scrub` | `zpool.scrub.run` |

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
- Adds entities for new datasets, VMs, apps and other items without a reload. An item that TrueNAS stops listing becomes unavailable, and its entities are removed after about an hour (60 successful updates). A failed query or an empty list never counts: Docker restarting or a pool that is not imported yet removes nothing. To remove what an empty list leaves behind, delete the device from its page in Home Assistant.
- Handles `null` values that newer TrueNAS releases return for reporting data and app versions.

## Credits and license

This project started as a fork of [tomaae/homeassistant-truenas](https://github.com/tomaae/homeassistant-truenas), created by Tomaae and its contributors. Thanks to them for the original integration.

Distributed under the [Apache License 2.0](LICENSE).
