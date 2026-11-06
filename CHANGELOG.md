# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Fixed

- The title of the reauthentication flow no longer shows a translation error, and no
  longer writes an error to the Home Assistant log.
- An entry added from a discovered system while TrueNAS did not give its id no longer
  fails **Reconfigure** and reauthentication with "unique ID mismatch". Such an entry
  made with 2.1.1b1 is repaired when it next loads.
- **Uptime** no longer moves by an hour when clocks change, if TrueNAS booted before the
  change.
- A discovered system no longer stays on offer after you add its address by hand. If you
  add it under a name, choose **Ignore**: a name cannot be matched with an address.
- Removing one of several duplicate entries of a TrueNAS system no longer clears the
  repair issue of another duplicate. It goes away when the entry holding the id does.

## [2.1.1b1] - 2026-11-06

### Documentation

- The README now covers what you can do with the integration, how data is updated,
  automation examples, known limitations and more troubleshooting.

### Added

- TrueNAS systems with a name starting with `truenas` are now discovered on the local
  network. Home Assistant offers them with the address filled in, and you still enter
  an API key and confirm.

### Changed

- Two entries on the same TrueNAS system now raise a repair issue in **Settings →
  System → Repairs**, instead of a warning in the log. It goes away when you remove one.
- VMs, containers, services and apps now show **Running** or **Not running**, and Reboot
  required shows **Problem** or **OK**. Their on and off states are the same, so
  automations keep working.
- Reboot required, pool scan, last scrub and errors, and network RX and TX are now
  diagnostic entities, so new dashboards made by Home Assistant leave them out.
- On new installations, load (5 and 15 min) and ARC size start disabled, because they
  change often and few people use them. Existing entities stay as they are.

### Fixed

- A disk without a serial, such as a virtual one, got a second entity
  (`sensor.truenas_disks_vdb_2`) when TrueNAS partitioned it and changed its
  identifier, and its first entity stayed unavailable. The entity now follows the
  disk and keeps its ID, name and history. A disk with another serial or size is
  still a new disk.
- Revoking an API key went unnoticed for as long as the connection stayed open, because
  TrueNAS keeps it going. The integration now logs in again every 15 minutes, so the
  revoked key is noticed by then and Home Assistant asks for a new one.

## [2.1.0] - 2026-11-05

The first stable release since 2.0.1. It collects 2.1.0b1, 2.1.0b2 and 2.1.0b3, and
their sections below have every detail.

### Before you upgrade

- **TrueNAS Link now requires Home Assistant 2026.11 or later.** On an older version,
  stay on 2.0.1 until you can update Home Assistant. 2.0.1's Reconfigure stops working
  on Home Assistant 2026.12, so update to this release before or together with that.
- **There is nothing to set up again.** Existing entries are migrated at startup, and
  keep their name, access level and entity IDs. **Back up Home Assistant first:** after
  the migration, an older version refuses to load the entry, so going back needs that
  backup or adding the entry again.
- **Check your automations for these changes:**
  - A failed action is now an error, so an automation can stop where it used to carry
    on. Add `continue_on_error: true` to a step that may fail.
  - An action now runs only on entities it is meant for, and gives an error on others.
  - Sensors without a value are now unknown instead of 0, and automations that compare
    them with a number do not trigger on unknown.
  - The entities of items deleted from TrueNAS are removed after about an hour, which
    loses their customizations.
  - The `icon` attribute is gone from these entities' state.

### Added

- An access level for each entry, Administrator or Read-only, in the **Configure**
  menu. New entries start as Read-only, and existing ones stay on Administrator.
- Reauthentication when TrueNAS rejects the API key.
- Alerts, reboot required, and pool scan, last scrub and errors sensors.
- `pool_scrub_start`, `pool_scrub_pause`, `pool_scrub_stop` and `replication_run`
  actions, and a switch per cron job, disabled by default.
- New items on TrueNAS get their entities without a reload.
- Translated entity names in five languages, plus complete forms and errors. Entity IDs
  do not change.

### Changed

- The setup form no longer asks for a name, and the same TrueNAS system can no longer
  be added twice.
- Verify SSL is on by default for new entries. Existing entries keep their setting.
- A lost connection now logs one message, and one when it is back.
- The connection to TrueNAS is now asynchronous, and `websockets` is pinned to 17.4.
- The README now covers installing, updating, testing pre-releases and removing through
  the Marketplace, which replaced HACS in Home Assistant 2026.11. It also warns that
  installing a TrueNAS update reboots the NAS.

### Security

- Credentials of cloud sync and replication tasks no longer reach Home Assistant.
- The debug log and diagnostics hide more: secrets, and free-text fields that can hold
  them. The API key forms mask the key, and Reconfigure no longer sends it to the browser.
- Actions no longer run on the wrong entity. `pool_scrub_stop` on the uptime sensor,
  for one, used to shut TrueNAS down.

### Fixed

- A TrueNAS that stopped answering blocked the integration: requests now give up after
  150 seconds, and entities become unavailable instead of showing old data.
- Reconfigure no longer breaks on Home Assistant 2026.12, keeps what was entered after
  an error, and no longer reloads the entry twice.
- The forms give the right error for a refused connection, an unreachable host, an
  unknown name and a server that is not a websocket.
- Connections are no longer left open after a failed login, setup or reload.
- The uptime sensor no longer changes state on every update.
- An empty **System** device left by renaming TrueNAS can now be deleted.
- On TrueNAS 25.04, stopping a VM no longer cuts its power immediately.

## [2.1.0b3] - 2026-11-05

### Changed

- **Sensors without a value now show as unknown instead of 0.** This applies to CPU
  temperature, CPU usage, load, memory, ARC size, network traffic, uptime, and the
  temperature of a disk that TrueNAS reports none for. So a virtual TrueNAS shows an
  unknown CPU temperature, not 0 °C. **Automations that compare these sensors with a
  number do not trigger on unknown, so check any that relied on 0.** A 0 that TrueNAS
  really reports stays 0, and if a query fails the last values stay, as before.
- **A lost connection now logs one message, and one when it is back.** It used to log up
  to three, from different places. The cause of the failure is now in the debug log, and
  the forms no longer log an error that they already show.
- `websockets` is now pinned to 17.4, instead of any version from 15.0.1 on.
- The README now explains installing, testing pre-releases and removing through the
  Marketplace, which replaced HACS in Home Assistant 2026.11, and warns that installing a
  TrueNAS update reboots the NAS.

### Fixed

- The errors of a rejected API key and of a failed update are now translated, which
  also fixes the "TrueNas" typo in the log.
- The uptime sensor no longer changes state on every update. Its time went back and
  forth by a second, without any reboot, which also filled the history. A real reboot
  still updates it.
- An empty **System** device that stays behind after renaming TrueNAS can now be deleted.
- The setup and Reconfigure forms now give the right error. A refused connection gave a
  generic message, and with a port such as 8404 even "API not found", because the
  errors were recognized by text that never appeared in them or that held the address.
  A name that does not resolve, a host that cannot be reached and a server that is not
  a websocket now each get their own message.

## [2.1.0b2] - 2026-11-05

### Security

- The debug log showed text fields in full, because it hid values by field name
  only. An app's notes, for one, can list its default credentials. It now hides
  app notes, descriptions and comments, environment variables, command-line
  arguments, job output and alert text. Diagnostics hide them too. Text in a
  field the integration does not know about can still reach the debug log, so
  check a log before sharing it.
- Diagnostics also hide the names of cron job switches, which repeat the job's
  description.
- The setup, Reconfigure and reauthentication forms now mask the API key.
  Reconfigure no longer sends the stored key to the browser: leave the field
  empty to keep it.
- **An action now runs only on entities it is meant for.** Actions used to run a
  method of the same name on whatever entity they targeted, so
  `truenas_link.cloudsync_abort` or `pool_scrub_stop` on the uptime sensor shut
  TrueNAS down, and `vm_stop` on a service stopped that service. These calls now give
  an error and send nothing to TrueNAS. An automation that relied on one needs the
  right action.

### Added

- New datasets, VMs, containers, apps, disks, tasks and cron jobs get their entities
  without a reload.

### Changed

- **TrueNAS Link now requires Home Assistant 2026.11 or later.** On an older
  version, stay on 2.0.1 until you can update Home Assistant. Note that 2.0.1's
  Reconfigure stops working on Home Assistant 2026.12.
- **Actions now always stay available, and are refused on read-only entries.**
  They used to disappear from Home Assistant when no entry had Administrator
  access. They are now registered once for the integration, so automations using
  them still validate when TrueNAS is unreachable. Calling one on a read-only entity
  gives an error and sends nothing to TrueNAS. If the target's entry is not loaded,
  Home Assistant does nothing, and logs that the entity is not available.
- **Entity names are now translated**, into Italian, Portuguese (Brazil), Russian,
  Slovak and Spanish, so they may look different in your language. Forms and errors
  are now complete in these languages. Entity IDs do not change, in any language.
  Names you gave to entities yourself stay. Icons moved to `icons.json`, so the
  `icon` attribute is gone from these entities' state: templates that read it need
  another source.
- **Entities of items deleted from TrueNAS are now removed, which loses their
  customizations.** An item that TrueNAS stops listing becomes unavailable at once,
  and its entities are removed after about an hour (60 successful updates). If it
  comes back, it gets the same entity ID. A failed query or an empty list never
  counts, so Docker restarting or a pool that is not imported yet removes nothing,
  and neither do the datasets of a pool that is gone. What an empty list leaves
  behind, such as the last VM, can be removed by deleting its device.
- **The access level has moved from Reconfigure to Configure**, in the integration's
  menu. The name and the access level are now options of the entry, because only the
  host, the API key and Verify SSL are needed to connect. Existing entries are
  migrated at startup, and keep their name, access level and entity IDs.
  **After this, going back to an older version needs the entry to be added again:**
  an older version refuses to load the migrated entry, so a read-only entry can never
  turn into an Administrator one by accident.
- **The setup form no longer asks for a name.** The first entry is named `TrueNAS`,
  later ones take the hostname of their system. Existing entries keep their name and
  entity IDs. This changes what happens if you remove an entry with a name of your
  own and add it again: its entities get new IDs, so update what uses them. Renaming
  an entry in Home Assistant now survives Reconfigure, and never changes entity IDs.
- **The same TrueNAS system can no longer be added twice**, whatever its name or
  address. Reconfigure and reauthentication refuse an address or key that leads
  to another system, and still accept a new address for the same one. Existing
  entries get their system's id at startup. If you already have two entries for
  one system, both keep working and the log says so: remove one if you do not need
  it.

### Fixed

- A query that TrueNAS left without an answer logged a warning on every update. It is
  now logged once, and again when the query works.
- Polling and actions no longer use a thread of Home Assistant's pool: the
  connection to TrueNAS is now asynchronous. Behavior stays the same, and cancelling
  an action, such as an automation restarting, closes the connection, so its late
  answer cannot be taken for the answer to the next request.
- Every entity went unavailable if reading the boot pool failed once.
- Datasets no longer vanish from the data when their query fails, which made their
  entities fail on the next update.
- The link to TrueNAS on the System device now uses HTTPS, the only protocol the
  integration uses to reach it.
- A method that TrueNAS refuses no longer writes an error to the log on every
  update. It is logged once, again if the reason changes, and a message says when
  the method works again.

## [2.1.0b1] - 2026-11-05

Pre-release for testing ahead of 2.1.0. It has not been tested on a real TrueNAS
system yet.

### Before you upgrade

Existing entries keep working with their current settings, including their
access level and Verify SSL. There is nothing to do first, but two things now
behave differently:

- **Actions can now fail with a visible error, so an automation can stop where
  it used to carry on.** Until now, a failed action only wrote to the log or did
  nothing. It is now an error when TrueNAS refuses the action, cannot be reached
  or reports that the operation failed, and when the action does not apply, such
  as starting a running VM or a scrub during a resilver. If a step of an
  automation or script may fail without stopping the rest, add
  `continue_on_error: true` to it. A reboot or shutdown does not count as failed
  if the NAS stops answering or closes the connection while going down. Actions
  that start a job, such as a cloud sync or an app start, only report failures in
  starting it: a job that fails later is not reported as a failed action.
- **Verify SSL is now on by default, for new entries only.** Existing entries
  keep their setting. If TrueNAS uses a self-signed certificate, turn it off when
  adding the entry: the error message now says so.

### Added

- **Access level** option on the setup and Reconfigure forms: Administrator
  or Read-only. With Read-only, all entities keep working, update entities
  have no install button, actions are no longer offered, and cron job
  switches are removed. New entries start as Read-only; existing entries
  stay on Administrator.
- Reauthentication: when TrueNAS rejects the API key, Home Assistant asks for
  a new one instead of retrying forever. The new key is tested before it is
  saved.
- **Alerts** sensor and **Critical alerts** binary sensor, with the messages
  as an attribute.
- **Reboot required** binary sensor, with the reasons as an attribute.
- For each pool: **scan** sensor (idle, scrubbing, paused or resilvering),
  **last scrub** sensor and **errors** sensor (ZFS read, write and checksum
  errors).
- `pool_scrub_start`, `pool_scrub_pause` and `pool_scrub_stop` actions.
- `replication_run` action.
- A switch per cron job to enable or disable it. It is disabled by default
  and needs Administrator access.
- **Security** section in the README.

### Changed

- TrueNAS Link is now in the HACS default repositories: search for it in
  HACS, without adding a custom repository. The README is updated to match.

### Security

- Cloud sync and replication tasks are now read with only the fields the
  integration uses, so their credentials, encryption password and encryption
  key do not reach Home Assistant, not even its debug log.
- The debug log now hides secrets in everything TrueNAS sends or receives.
- Diagnostics now also hide the hostname, the network interfaces' MAC
  addresses, and those secrets.

### Fixed

- On TrueNAS 25.04, stopping a VM cut its power immediately. It now gets 60
  seconds to shut down cleanly. If it does not, it keeps running.
- A TrueNAS that kept the connection up but stopped answering blocked the
  integration indefinitely: entities stayed available with old data, and
  actions waited without an end. Requests now give up after 150 seconds.
- Entities could also stay available with old data when the connection dropped
  during an update. In both cases the update now fails, entities become
  unavailable, and the next update reconnects.
- Reconfigure would have failed from Home Assistant 2026.12, which no longer
  accepts an update listener together with a config flow that reloads. The
  integration has no options flow, so the listener is gone, and an entry can no
  longer reload twice after Reconfigure.
- Connections to TrueNAS were left open, each with its own threads, after a
  rejected login, the connection test of the setup and Reconfigure forms, a
  failed setup, and an unload or reload.
- `cloudsync_run` and `cloudsync_abort` crashed with a `TypeError` when the
  task could not be read, or had never run.
- A failed update install no longer leaves an empty job id behind.
- The setup and Reconfigure forms showed an empty error when TrueNAS accepted
  the connection but did not answer, or for any failure the integration did
  not recognize. A timeout now gets its own message, and everything else a
  general "could not connect" one.
- Reconfigure forgot what was entered when the connection test failed, and
  showed the stored values again.
- The 2.0.0 upgrade steps (README and changelog) told 1.x users to update
  the integration in HACS. That fails, because HACS keeps the old domain:
  the download and the repository refresh stop with "No manifest.json file
  found custom_components/truenas/manifest.json". The steps now say to
  remove TrueNAS Link in HACS (three-dot menu → **Remove**, which also
  deletes `config/custom_components/truenas/`) and download it again.

### Development

- Fixed the open CodeQL code scanning alerts: the platforms pass their
  entity descriptions and services to the shared entity setup explicitly
  instead of through module imports it looked up at runtime, an unused
  import is gone, and third-party GitHub Actions are pinned to commit SHAs.
- Tests work with `DeviceInfo` as a dataclass (Home Assistant 2026.11).

## [2.0.1] - 2026-11-04

### Fixed

- Connecting and logging in to TrueNAS no longer runs on the Home
  Assistant event loop. While TrueNAS was slow or unreachable, the whole
  Home Assistant instance could stall until the connection timed out.
- The target picker of every action now lists TrueNAS Link entities. Since
  2.0.0 it offered the upstream integration's entities, or nothing.
- With **Verify SSL** on, connections no longer always fail with
  `certificate_verify_failed`. The integration now uses Home Assistant's
  SSL contexts, which load the trusted CA certificates.

## [2.0.0] - 2026-11-04

The integration is now called **TrueNAS Link** and uses its own domain,
`truenas_link`, instead of `truenas`, which belongs to the upstream
integration. It can now be installed next to upstream, and it can be
submitted to the HACS default repositories.

### Before you upgrade

**This release does not update an existing setup in place.** Home
Assistant cannot move config entries from one domain to another, so every
TrueNAS system has to be added again. Follow these steps in order, so the
entities come back with the same entity IDs and keep their history,
statistics, dashboards and automation triggers:

1. Note the name of each entry in **Settings → Devices & services →
   TrueNAS** (`TrueNAS` unless you changed it).
2. Delete those entries **before** updating.
3. In HACS, open **TrueNAS Link** → three-dot menu → **Remove** (this
   also deletes `config/custom_components/truenas/`), then download it
   again from HACS. Do not use **Update**: HACS keeps the old domain, and
   the download fails with "No manifest.json file found
   custom_components/truenas/manifest.json".
4. Restart Home Assistant.
5. Add **TrueNAS Link** with the same name, host and API key.
6. Rename the actions in automations and scripts from `truenas.*` to
   `truenas_link.*`, for example `truenas.vm_start` to
   `truenas_link.vm_start`.

The README has the same steps, and also covers switching from the upstream
integration or running both side by side.

### Changed

- **Domain renamed from `truenas` to `truenas_link`.** The integration
  files are installed in `custom_components/truenas_link/`, all actions
  are called `truenas_link.<action>`, and the debug logger is
  `custom_components.truenas_link`. Entity IDs are unchanged when the entry
  is added again with the same name (see Before you upgrade).
- **Display name is "TrueNAS Link"** in Home Assistant and HACS. Devices
  are still named after the entry ("TrueNAS" by default).
- **Release asset renamed to `truenas_link.zip`.** For manual
  installation, extract it into `config/custom_components/truenas_link/`.

## [1.5.3] - 2026-11-04

### Fixed

- Home Assistant logged that the integration "calls
  `device_registry.async_get_or_create` with a deprecated `via_device`
  parameter" (stops working in Home Assistant 2027.8). Devices are now linked
  to the TrueNAS System device by its device id on Home Assistant 2026.8 and
  later, and as before on older releases.
- The System device is now registered before any other TrueNAS device, so
  Disks, VMs, Apps and the other devices are always shown under it, whatever
  order Home Assistant sets the platforms up in.

### Development

- Tests check device info against the installed Home Assistant's own
  device info keys and deprecations, on both CI Home Assistant versions.

## [1.5.2] - 2026-11-04

### Removed

- CPU usage sensor attributes `system`, `user`, `nice`, `idle`, `iowait`
  and `softirq`, and memory usage sensor attributes `cached` and
  `buffered`. TrueNAS does not report these values, so they were always 0.

### Fixed

- The "ARC size" sensor always reported 0. The integration now reads the
  `size` entry of the ARC size reporting graph, the name TrueNAS uses on
  25.04, 25.10 and 27.0.
- The memory usage sensor's `used` attribute was always 0. It now shows
  total minus available memory.
- Home Assistant warned that the integration "sets an invalid entity ID:
  'update.truenas_system_'" (an error from Home Assistant 2027.2). The
  system update entity keeps its existing id, `update.truenas_system`.
- Devices no longer use the `default_name`, `default_model` and
  `default_manufacturer` device info keys, which Home Assistant removes
  in 2027.9.
- System statistics: the reporting time window was inverted, and the
  fallback for a graph that TrueNAS cannot serve never worked. Now one
  failing graph (for example CPU temperature on some hardware, or one
  network interface) is skipped and the other statistics still update,
  instead of all of them being lost.

### Development

- Tests now cover system statistics with realistic
  `reporting.netdata_get_data` payloads for every graph the integration
  reads (ARC size, CPU, CPU temperature, load, memory and interfaces),
  the per-graph fallback, entity ids and device info.

## [1.5.1] - 2026-11-04

### Removed

- Leftover `jail_start`, `jail_stop` and `jail_restart` action definitions.
  Jails were a TrueNAS CORE feature; the integration never registered these
  actions, so they could not be called.

### Fixed

- On TrueNAS 25.10 and later the integration never finished setting up and
  stayed in "setup retry" ("TrueNas Disconnected"), logging
  `unable to fetch data "update.status" (argument of type 'NoneType' is not
  a container or iterable)`. JSON-RPC errors are now read from the
  top-level `error` member of the response, as the protocol defines,
  instead of from inside the method result, where `update.status` always
  returns `"error": null`. A failed API call is logged with TrueNAS' reason
  and no longer drops the connection.

### Development

- Added a pytest suite, run in CI against both the oldest supported and the
  latest Home Assistant release. It covers JSON-RPC response handling and
  the TrueNAS 25.10+ update check.

## [1.5.0] - 2026-11-04

First release of this fork, [anto294/homeassistant-truenas](https://github.com/anto294/homeassistant-truenas),
distributed as a HACS custom repository. It builds on
[tomaae/homeassistant-truenas](https://github.com/tomaae/homeassistant-truenas)
and includes all upstream changes since its last stable release, 1.3.1
(the unreleased 1.4 work and the 1.4 betas), listed under
[Included from upstream](#included-from-upstream).

The integration now detects the TrueNAS version on every update and uses the
API methods of that release, so it works on TrueNAS 25.04, 25.10 and 27.0 and
keeps working after an in-place TrueNAS upgrade without reconfiguration.

### Before you upgrade

- **TrueNAS 25.04 or later is required.** The integration only uses the
  versioned JSON-RPC 2.0 websocket API (`wss://<host>/api/current`), which
  TrueNAS introduced in 25.04. TrueNAS CORE and SCALE releases before 25.04
  are no longer supported.
- **Home Assistant 2024.11.0 or later is required.** HACS will not offer the
  update on older Home Assistant releases.
- **Switching from the upstream integration:** both use the `truenas`
  domain, so only one can be installed. Remove the upstream integration from
  HACS (this only deletes its files), add this repository as a custom
  repository, download it and restart Home Assistant. Config entries,
  entities and their IDs are kept. See the README for step-by-step
  instructions.
- **Pool usage values change.** The pool usage percentage was reporting
  free space instead of used space; it now reports used space (see Fixed).
  Review automations or alerts that use it.
- **Stopping a VM is now a graceful shutdown.** `vm_stop` asks the guest to
  shut down and only forces it off after the VM's configured shutdown
  timeout, instead of powering it off immediately.

### Added

- **Containers on TrueNAS 27.0.** TrueNAS 27.0 manages LXC containers
  through a new `container.*` API. Each container gets a binary sensor in a
  new "Containers" device, on while it is running, with description,
  autostart, CPU set, memory limit and status attributes.
- **`container_start` and `container_stop` actions.** Both check the live
  container state first. `container_stop` requests a clean shutdown and only
  forces it after the container's shutdown timeout.
- **Support for TrueNAS 25.10 and 27.0** for system update checks, system
  update installation, virtual machines and dataset snapshots, which had
  stopped working on those releases (see Fixed).
- **Italian translation** of the configuration and reconfiguration flows and
  of all connection error messages.
- **Brand icon and logo shipped with the integration**
  (`custom_components/truenas/brand/`), so Home Assistant shows the TrueNAS
  icon without relying on the central brands repository.
- **Integration category** "Computers & network > NAS & servers" and
  network connectivity in the manifest, used by Home Assistant to classify
  the integration.

### Changed

- **TrueNAS version detection.** The version is parsed from any release
  string (for example `25.10.1`, `25.10-RC.1`, `27.0.0-BETA.1` or
  `TrueNAS-SCALE-24.10.2`) and re-checked on every update, so the right API
  methods are used immediately after a TrueNAS upgrade. Pre-release version
  strings previously broke the system information update entirely.
- **`vm_start` honours the `overcommit` option.** It was accepted by the
  action but ignored on TrueNAS 25.04.
- **`vm_stop` is a graceful shutdown** with a forced power-off after the
  VM's shutdown timeout (see Before you upgrade).
- **Repository links.** The integration's documentation and "Report issue"
  links in Home Assistant and HACS now point to this repository.
- **README rewritten** for this fork: installation through HACS (including
  a My Home Assistant button), switching from upstream, tables of all
  entities and actions with their parameters, supported TrueNAS versions and
  the API methods used on each, Apps, the Verify SSL option, reconfiguration
  and diagnostics. Claims about jails and TrueNAS CORE, which are not
  supported, were removed.

### Fixed

- **System update check on TrueNAS 25.10+.** `update.check_available` was
  removed in 25.10, so the update entity never reported a new TrueNAS
  version. The integration now uses `update.status` on 25.10 and later.
- **Installing a TrueNAS update from Home Assistant on 25.10+.**
  `update.update` no longer starts an upgrade on 25.10, so installing did
  nothing. The integration now uses `update.run`, and installation progress
  is still reported.
- **Virtual machines on TrueNAS 25.10+.** 25.10 removed the
  `virt.instance.*` API used by 25.04, so VM sensors disappeared and
  `vm_start`/`vm_stop` failed. VMs are now read and controlled through
  `vm.*` on 25.10 and later. Entity IDs are unchanged for users coming from
  25.04.
- **Dataset snapshots on TrueNAS 25.10+.** The `dataset_snapshot` action
  failed because `zfs.snapshot.create` was removed; it now uses
  `pool.snapshot.create`.
- **System statistics on TrueNAS 27.0.** When TrueNAS returned no samples
  for a reporting window, the whole statistics update failed and CPU, load,
  memory, temperature, network and ARC sensors stopped updating. Missing
  samples are now handled; CPU temperature ignores sensors without a value.
- **Memory reported as 100 % used during reporting gaps.** When TrueNAS
  had no memory samples, free memory dropped to 0 and usage jumped to 100 %,
  which could trigger automations. The last known memory values are now
  kept.
- **Apps shown as "unknown" instead of "up to date".** TrueNAS reports no
  latest version for apps that are up to date (and, on 27.0, when the
  catalog cannot be checked). The app update entity now reports the
  installed version in that case.
- **Entities failing after a temporary connection error.** A failed VM or
  container query (for example a network timeout) emptied their data, which
  raised errors and stopped the update of every entity after them. The last
  known data is now kept until the next successful query.
- **VM memory shrinking to 0 GiB on TrueNAS 25.04** after a failed query,
  caused by the memory conversion being applied again to already converted
  values.
- **Pool usage percentage** reported free space instead of used space.
- **Wrong minimum Home Assistant version.** HACS allowed installing the
  integration on Home Assistant 2024.3 to 2024.10, where it failed to load.
  HACS now requires 2024.11.0.

### Included from upstream

Changes made in tomaae/homeassistant-truenas after 1.3.1, released upstream
only as 1.4 betas or not released yet:

- New JSON-RPC 2.0 websocket API client, replacing the REST API, for
  TrueNAS 25.04 and later. Support for older TrueNAS versions was removed.
- Reconfigure option to change the host, API key or SSL verification of an
  existing entry without removing it.
- Detailed connection errors in the setup and reconfigure flows: DNS
  resolution, certificate verification, TLS handshake, HTTP request and
  "websocket not supported" errors. Connection errors are logged once
  instead of on every update.
- Reconnection when TrueNAS is offline while Home Assistant starts, and
  automatic disconnect and reconnect after API failures.
- App update entities: show and install app updates, with progress while an
  update is running. Pending updates are no longer reported for stopped
  apps.
- Fixed app start and stop actions.
- Updated VM and app attributes and fixed the VM state for the new API.
- Larger maximum websocket message size for big TrueNAS systems.
- Xen and Hyper-V are recognised as hypervisors in the "virtual machine"
  system attribute.
- Translation updates.

### Development

- CI rebuilt with separate lint (black, flake8, JSON), security (bandit),
  hassfest and import jobs. The import job loads every module on both the
  minimum supported Home Assistant (2024.11.0) and the latest release.
- HACS validation, CodeQL (v4, security-and-quality queries), stale and
  lock workflows updated to current action versions; Dependabot keeps
  GitHub Actions up to date.
- Release workflow rebuilt: it validates the tag, sets the manifest version
  and attaches `truenas.zip`, which HACS installs from. Release notes come
  from this changelog.

[Unreleased]: https://github.com/anto294/homeassistant-truenas/compare/v2.1.1b1...HEAD
[2.1.1b1]: https://github.com/anto294/homeassistant-truenas/compare/v2.1.0...v2.1.1b1
[2.1.0]: https://github.com/anto294/homeassistant-truenas/compare/v2.0.1...v2.1.0
[2.1.0b3]: https://github.com/anto294/homeassistant-truenas/compare/v2.1.0b2...v2.1.0b3
[2.1.0b2]: https://github.com/anto294/homeassistant-truenas/compare/v2.1.0b1...v2.1.0b2
[2.1.0b1]: https://github.com/anto294/homeassistant-truenas/compare/v2.0.1...v2.1.0b1
[2.0.1]: https://github.com/anto294/homeassistant-truenas/compare/v2.0.0...v2.0.1
[2.0.0]: https://github.com/anto294/homeassistant-truenas/compare/v1.5.3...v2.0.0
[1.5.3]: https://github.com/anto294/homeassistant-truenas/compare/v1.5.2...v1.5.3
[1.5.2]: https://github.com/anto294/homeassistant-truenas/compare/v1.5.1...v1.5.2
[1.5.1]: https://github.com/anto294/homeassistant-truenas/compare/v1.5.0...v1.5.1
[1.5.0]: https://github.com/anto294/homeassistant-truenas/releases/tag/v1.5.0
