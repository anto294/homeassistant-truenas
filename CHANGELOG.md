# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- **Access level** option on the setup and Reconfigure forms: Administrator
  or Read-only. With Read-only, all entities keep working, update entities
  have no install button, actions are no longer offered, and cron job
  switches are removed. New entries start as Read-only; existing entries
  stay on Administrator.
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
- Reauthentication: when TrueNAS rejects the API key, Home Assistant asks for
  a new one instead of retrying forever. The new key is tested before it is
  saved.

### Changed

- **Verify SSL is now on by default for new entries.** If TrueNAS uses a
  self-signed certificate, turn it off in the form, and the error message now
  says so. Existing entries keep their setting.
- TrueNAS Link is now in the HACS default repositories: search for it in
  HACS, without adding a custom repository. The README is updated to match.
- Actions now fail with a clear error when TrueNAS refuses them, cannot be
  reached, or reports that the operation failed, instead of only writing to
  the log or doing nothing. An action that does not apply, such as starting a
  running VM or a scrub during a resilver, is also an error now: an automation
  that relies on it being ignored should use `continue_on_error`. A reboot or
  shutdown does not count as failed if the NAS closes the connection while
  going down.

### Fixed

- On TrueNAS 25.04, stopping a VM cut its power immediately. It now gets 60
  seconds to shut down cleanly. If it does not, it keeps running.
- The 2.0.0 upgrade steps (README and changelog) told 1.x users to update
  the integration in HACS. That fails, because HACS keeps the old domain:
  the download and the repository refresh stop with "No manifest.json file
  found custom_components/truenas/manifest.json". The steps now say to
  remove TrueNAS Link in HACS (three-dot menu → **Remove**, which also
  deletes `config/custom_components/truenas/`) and download it again.
- Reconfigure forgot what was entered when the connection test failed, and
  showed the stored values again.
- Reconfigure would have failed from Home Assistant 2026.12, which no longer accepts an update listener together with a config
  flow that reloads. The integration has no options flow, so the listener is
  gone, and an entry can no longer reload twice after Reconfigure.
- Connections to TrueNAS were left open, each with its own threads, after a
  rejected login, the connection test of the setup and Reconfigure forms, a
  failed setup, and an unload or reload.
- `cloudsync_run` and `cloudsync_abort` crashed with a `TypeError` when the
  task could not be read, or had never run.
- A failed update install no longer leaves an empty job id behind.
- A TrueNAS that kept the connection up but stopped answering blocked the
  integration indefinitely: entities stayed available with old data, and
  actions waited without an end. Requests now give up after 150 seconds, the
  update fails, entities become unavailable, and the next update reconnects.
- Entities could stay available with old data when the connection dropped
  during an update, if a later request of that update reconnected. The update
  now fails, entities become unavailable, and the next update reconnects.
- The setup and Reconfigure forms showed an empty error when TrueNAS accepted
  the connection but did not answer, or for any failure the integration did
  not recognize. A timeout now gets its own message, and everything else a
  general "could not connect" one.

### Security

- Cloud sync and replication tasks are now read with only the fields the
  integration uses, so their credentials, encryption password and encryption
  key do not reach Home Assistant, not even its debug log.
- The debug log now hides secrets in everything TrueNAS sends or receives.
- Diagnostics now also hide the hostname, the network interfaces' MAC
  addresses, and those secrets.

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

[Unreleased]: https://github.com/anto294/homeassistant-truenas/compare/v2.0.1...HEAD
[2.0.1]: https://github.com/anto294/homeassistant-truenas/compare/v2.0.0...v2.0.1
[2.0.0]: https://github.com/anto294/homeassistant-truenas/compare/v1.5.3...v2.0.0
[1.5.3]: https://github.com/anto294/homeassistant-truenas/compare/v1.5.2...v1.5.3
[1.5.2]: https://github.com/anto294/homeassistant-truenas/compare/v1.5.1...v1.5.2
[1.5.1]: https://github.com/anto294/homeassistant-truenas/compare/v1.5.0...v1.5.1
[1.5.0]: https://github.com/anto294/homeassistant-truenas/releases/tag/v1.5.0
