# TrueNAS Link for Home Assistant

[![GitHub release](https://img.shields.io/github/v/release/anto294/homeassistant-truenas?style=plastic)](https://github.com/anto294/homeassistant-truenas/releases)
[![Marketplace catalog](https://img.shields.io/badge/Marketplace-hacs%2Fdefault-41BDF5.svg?style=plastic)](https://github.com/hacs/default)
[![CI](https://img.shields.io/github/actions/workflow/status/anto294/homeassistant-truenas/ci.yml?style=plastic)](https://github.com/anto294/homeassistant-truenas/actions)
![Downloads](https://img.shields.io/github/downloads/anto294/homeassistant-truenas/total?style=plastic)

[TrueNAS](https://www.truenas.com/) is an operating system for network-attached storage, built on OpenZFS. This integration lets you monitor and control a TrueNAS SCALE system from Home Assistant: pools, datasets, disks, services, apps, virtual machines, containers, cloud sync, replication and snapshot tasks, and system updates.

Targets the versioned JSON-RPC API of **TrueNAS 25.04 and later**, including 25.10 and 27.0. It keeps working after an in-place TrueNAS upgrade without reconfiguration.

> [!NOTE]
> TrueNAS Link started as a fork of [tomaae/homeassistant-truenas](https://github.com/tomaae/homeassistant-truenas). It is a separate integration with its own `truenas_link` domain, so please report problems [here](https://github.com/anto294/homeassistant-truenas/issues), not upstream. See [Differences from upstream](#differences-from-upstream).

## Contents

- [What you can do with it](#what-you-can-do-with-it)
- [Requirements](#requirements)
- [Installation](#installation)
- [Configuration](#configuration)
- [Entities](#entities)
- [How data is updated](#how-data-is-updated)
- [Actions](#actions)
- [Automation examples](#automation-examples)
- [Security](#security)
- [Supported TrueNAS versions](#supported-truenas-versions)
- [Known limitations](#known-limitations)
- [Troubleshooting](#troubleshooting)
- [Removal](#removal)
- [Translations](#translations)
- [Migrating from version 1.x or from the upstream integration](#migrating-from-version-1x-or-from-the-upstream-integration)
- [Differences from upstream](#differences-from-upstream)
- [Credits and license](#credits-and-license)

## What you can do with it

- **Hear about problems early:** get a notification when a pool is no longer healthy, a disk runs hot, or TrueNAS raises a critical alert.
- **See your storage in one place:** put free space, dataset size and scrub state on a dashboard, and keep their history.
- **Tie TrueNAS into your home:** shut it down cleanly when the UPS runs low, or stop a VM at night.
- **Protect data around changes:** take a dataset snapshot from an automation before a risky job, or run a replication when you want.
- **Stay up to date:** see when TrueNAS or an app has an update, and install it from Home Assistant if you allow that.

## Requirements

| Component | Minimum version |
|---|---|
| TrueNAS SCALE | 25.04 |
| Home Assistant | 2026.11.0 |

TrueNAS CORE and SCALE releases before 25.04 are not supported, because they do not provide the versioned websocket API this integration uses. Any hardware or virtual machine running a supported release works. What a system does not report, such as the temperature of a virtual disk, shows as unknown.

## Installation

### Marketplace (recommended)

Since Home Assistant 2026.11, HACS is built into Home Assistant as the Marketplace, and can no longer be installed separately. The Marketplace reads the same catalog, [hacs/default](https://github.com/hacs/default), where TrueNAS Link is listed.

[![Open your Home Assistant instance and open a repository in the Marketplace.](https://my.home-assistant.io/badges/marketplace_repository.svg)](https://my.home-assistant.io/redirect/marketplace_repository/?owner=anto294&repository=homeassistant-truenas&category=integration)

Or go to **Settings → Marketplace**, search for **TrueNAS Link**, open it and select **Install**, then confirm. Restart Home Assistant if a repair asks you to.

#### Pre-releases

The Marketplace offers stable releases only, unless you ask for pre-releases:

1. Go to **Settings → Devices & services → Marketplace** and open the **TrueNAS Link** device.
2. Enable the **Pre-release** entity, which is disabled by default.
3. Turn on its switch.

You are then offered a pre-release if it is newer than the latest stable release. Back up Home Assistant first: going back to an older version needs that backup, or adding the entry again.

### Manual

Download `truenas_link.zip` from the [latest release](https://github.com/anto294/homeassistant-truenas/releases/latest), extract it into `config/custom_components/truenas_link/` and restart Home Assistant.

### Updating

The Marketplace offers a new version as an update under **Settings → Updates**. After you install it, restart Home Assistant to apply it: a repair under **Settings → System → Repairs** reminds you and can restart it for you. After a manual installation, replace the contents of the folder and restart.

Check the [changelog](CHANGELOG.md) first, as it says what to look at before you upgrade.

## Configuration

1. In the TrueNAS web UI, create an API key for Home Assistant (user menu → **API Keys** → **Add**).
2. In Home Assistant, go to **Settings → Devices & services → Add integration → TrueNAS Link** and fill in:

   | Field | Description |
   |---|---|
   | Host | Hostname or IP address |
   | API key | The key created in step 1 |
   | Access level | **Read-only** (default) or **Administrator** (see [Access level](#access-level)) |
   | Verify SSL | On by default. Turn off if TrueNAS uses a self-signed certificate |

You can add the integration once per TrueNAS system. To change the host or API key later, use **Reconfigure** from the integration's menu. It does not show the stored API key: leave the field empty to keep it. To change the access level, use **Configure**.

Entity IDs are built from the entry's name, which is set once. The first entry is named `TrueNAS`, so its entities look like `sensor.truenas_system_uptime`. Later entries take the hostname of their TrueNAS system. Renaming an entry in Home Assistant only changes the title shown, not its entity IDs.

If TrueNAS Link does not appear in the list, clear your browser cache.

### Discovery

Home Assistant discovers a TrueNAS system on your network if its hostname starts with `truenas`, and offers it in **Settings → Devices & services** with the address filled in. You still enter an API key and confirm, and nothing is sent to the system before that. To stop being offered one, choose **Ignore**.

A system with another hostname, on another network, or with mDNS turned off is not discovered: add it by hand. A discovered address never replaces the address of an existing entry, because an announcement on the network proves nothing and the entry's key would be sent there. If the address changes, use **Reconfigure**.

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

If TrueNAS reports no value for a sensor, its state is unknown, not 0. A value of 0 that TrueNAS does report stays 0. On a virtual TrueNAS, which has no such reading, CPU temperature stays unknown.

| Device | Entity | Type | Notes |
|---|---|---|---|
| System | Uptime | sensor | Target for the reboot and shutdown actions |
| System | CPU usage, CPU temperature, load (1 min) | sensor | |
| System | Load (5 and 15 min) | sensor | Disabled by default |
| System | Memory usage | sensor | |
| System | ARC size | sensor | Disabled by default |
| System | Network RX / TX | sensor | One pair per interface |
| System | TrueNAS update | update | Install system updates from Home Assistant. **Installing one reboots the NAS** |
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

## How data is updated

- Home Assistant asks TrueNAS for all data every 60 seconds, over one connection that stays open. TrueNAS does not push changes, so a change can take up to a minute to show.
- Available updates are checked every 12 hours.
- The connection logs in again every 15 minutes, so a revoked API key is noticed.
- New items, such as a new dataset or VM, get their entities on the next poll, without a reload.
- An item that is gone becomes unavailable at once, and its entity is removed after about an hour of successful polls without it. A failed query or an empty list never counts, because a pool that is still importing or Docker restarting looks the same.
- If TrueNAS cannot be reached, entities become unavailable, the log says so once, and they recover on their own.

## Actions

All actions target an entity of this integration, given as `target`, and need the Administrator access level. On a read-only entity, or on an entity the action is not meant for, they give an error and send nothing to TrueNAS. If the entity's entry is not loaded, for example because TrueNAS is unreachable at startup, the action does nothing and Home Assistant logs that the entity is not available.

An action also gives an error if TrueNAS refuses it, cannot be reached, or if it does not apply, such as starting a running VM. In an automation, use `continue_on_error: true` on a step that may fail without stopping the rest. Actions that start a job only report failures in starting it.

`vm_start`'s `overcommit` is the only parameter. The other actions take none.

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
  entity_id: sensor.truenas_datasets_tank_media
```

## Automation examples

Entity IDs below are for an entry named `TrueNAS` with a pool named `tank`. Find yours in **Settings → Devices & services → TrueNAS Link**.

Get a notification when a pool is no longer healthy:

```yaml
alias: TrueNAS pool problem
triggers:
  - trigger: state
    entity_id: binary_sensor.truenas_system_tank_healthy
    to: "off"
actions:
  - action: notify.notify
    data:
      message: The TrueNAS pool tank is no longer healthy
```

Take a snapshot every night (needs the Administrator access level):

```yaml
alias: Nightly TrueNAS snapshot
triggers:
  - trigger: time
    at: "02:00:00"
actions:
  - action: truenas_link.dataset_snapshot
    target:
      entity_id: sensor.truenas_datasets_tank_media
```

Shut down TrueNAS when the UPS battery runs low (needs the Administrator access level, and your own UPS sensor):

```yaml
alias: Shut down TrueNAS on low battery
triggers:
  - trigger: numeric_state
    entity_id: sensor.ups_battery
    below: 20
actions:
  - action: truenas_link.system_shutdown
    target:
      entity_id: sensor.truenas_system_uptime
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
- Installing a TrueNAS update reboots the NAS when it is done, with no further question. If Home Assistant runs on this NAS, it restarts too. This also applies to an automation that installs updates.
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

## Known limitations

- **Discovery** only finds a system whose hostname starts with `truenas`, on the same network, and it never updates the address of an entry. See [Discovery](#discovery).
- **The entry's name cannot change**, because entity IDs are built from it.
- **Last scrub** only knows a pool's latest scan, because that is all TrueNAS reports. After a resilver, and a restart of Home Assistant, it stays unknown until the next scrub finishes.
- **Temperatures** are unknown where TrueNAS has none, such as virtual disks and virtual CPUs.
- **Renaming TrueNAS** leaves an empty **System** device. See [Troubleshooting](#troubleshooting).
- **Deleting the last item of a section**, such as the only VM, does not remove its entity automatically, because an empty list can also be Docker restarting. Delete its device by hand.
- **Cloud sync and replication** show the state of their last job, and TrueNAS may forget it after a reboot, so they can be unknown until the next run.

## Troubleshooting

**Certificate verification failed:** TrueNAS uses a self-signed certificate. Install a trusted one, or turn off **Verify SSL** with **Reconfigure**.

**API key rejected:** the key was revoked, expired or typed wrong. Home Assistant shows **Reconfigure** on the entry: create a new key in TrueNAS and paste it there.

**Connection refused, no route or unknown hostname:** check the host, and add the port if it is not 443, such as `192.168.1.10:8443`. TrueNAS must serve its API over HTTPS.

**Entities are unavailable:** TrueNAS cannot be reached, or that one item is gone from TrueNAS. A single one coming back on its own means it was temporary.

**An action gives an error:** Read-only entries refuse actions, and each action only works on its own type of entity. See [Actions](#actions).

**Sensors stay unknown:** TrueNAS reports no value for them. See [Known limitations](#known-limitations).

**Two entries on one system:** Home Assistant raises a repair issue. Remove the entry you do not need.

Enable debug logging to see every API query and response:

```yaml
logger:
  default: info
  logs:
    custom_components.truenas_link: debug
```

After you revoke an API key, TrueNAS keeps an open connection going, so Home Assistant notices at its next login, within 15 minutes, and then asks for a new key.

When TrueNAS cannot be reached, the log says so once, and once more when it is back. The cause is only in the debug log.

After you rename TrueNAS, an empty **System** device stays next to the new one, because a device's identifier holds the hostname. To remove it, open it in **Settings → Devices & services**, then three-dot menu → **Delete**.

You can also download diagnostics from the integration's page (sensitive data is redacted) and attach them to an [issue](https://github.com/anto294/homeassistant-truenas/issues).

## Removal

1. In **Settings → Devices & services → TrueNAS Link**, open the entry's three-dot menu and select **Delete**. Repeat for each entry. This also removes its devices and entities.
2. In **Settings → Marketplace**, open **TrueNAS Link**, then three-dot menu → **Uninstall**, and confirm. After a manual installation, delete `config/custom_components/truenas_link/` instead.
3. Restart Home Assistant if a repair asks you to. After a manual installation, always restart it.
4. In the TrueNAS web UI, revoke the API key you created for Home Assistant (user menu → **API Keys**). Home Assistant no longer uses it, but it stays valid until you delete it.

You can also skip step 1: if an entry is still configured, the Marketplace offers **Delete and uninstall** in step 2, which removes the entries, their devices and their entities in one step.

Remove automations, scripts and dashboards that use these entities or actions yourself. Long-term statistics stay until you delete them in **Developer tools → Statistics**.

## Translations

Available in English, Italian, Portuguese (Brazil), Russian, Slovak and Spanish.

English strings live in `custom_components/truenas_link/strings.json` and `custom_components/truenas_link/translations/en.json`. To add or improve a language, open a pull request that adds or updates the matching file in [`custom_components/truenas_link/translations/`](custom_components/truenas_link/translations/).

## Migrating from version 1.x or from the upstream integration

Version 2.0 renamed the domain from `truenas` to `truenas_link`. Home Assistant cannot move config entries between domains, so each TrueNAS system has to be added again. If you remove the old entry first and it was named `TrueNAS`, the default, the new one gets the same entity IDs as before, so their history, statistics, dashboards and automation triggers keep working. **Since 2.1 a new entry can no longer be given a name, so an old entry with another name gets new entity IDs:** update what uses them, or rename the entities in Home Assistant.

1. Note the name of each TrueNAS entry in **Settings → Devices & services → TrueNAS**. It is the entry's title, `TrueNAS` unless you changed it.
2. Delete those entries (three-dot menu → **Delete**).
3. Install the new version:
   - **From 1.x of this integration, on Home Assistant 2026.11 or later:** your HACS content moved to the Marketplace when Home Assistant updated. In **Settings → Marketplace**, open **TrueNAS Link** → three-dot menu → **Uninstall**, then install it again. Do not use **Update**, because the domain has changed. If `config/custom_components/truenas/` is still there, delete it.
   - **From 1.x of this integration, on an older Home Assistant that still has HACS:** in HACS, open **TrueNAS Link** → three-dot menu → **Remove** (this also deletes `config/custom_components/truenas/`). Do not use **Update**: HACS keeps the old domain, and the download (and the repository refresh) fails with "No manifest.json file found custom_components/truenas/manifest.json". Then either update Home Assistant to 2026.11 or later and install from the Marketplace, or download version 2.0.1 from HACS, the last release for your version of Home Assistant.
   - **From the upstream integration, on Home Assistant 2026.11 or later:** install TrueNAS Link as described above, then uninstall the upstream **TrueNAS** integration in the Marketplace. If `config/custom_components/truenas/` is still there and no other integration uses it, delete it.
   - **From the upstream integration, on an older Home Assistant that still has HACS:** remove the upstream **TrueNAS** integration in HACS, and delete the same folder if it is still there. Then either update Home Assistant to 2026.11 or later and install from the Marketplace, or download version 2.0.1 from HACS, the last release for your version of Home Assistant.
4. Restart Home Assistant.
5. Add **TrueNAS Link** with the same host and API key as before (see [Configuration](#configuration)).
6. In automations and scripts, replace `truenas.` actions with `truenas_link.` (for example `truenas.vm_start` becomes `truenas_link.vm_start`).

If you prefer, you can instead keep the upstream integration and run both side by side. The entity IDs of the first TrueNAS Link entry then collide with the upstream ones, so Home Assistant adds a `_2` suffix to the new ones.

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
