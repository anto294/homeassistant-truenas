# TrueNAS Integration
![GitHub release (latest by date)](https://img.shields.io/github/v/release/anto294/homeassistant-truenas?style=plastic)
[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg?style=plastic)](https://hacs.xyz/docs/faq/custom_repositories/)
![Project Stage](https://img.shields.io/badge/project%20stage-development-yellow.svg?style=plastic)
![GitHub all releases](https://img.shields.io/github/downloads/anto294/homeassistant-truenas/total?style=plastic)

![GitHub commits since latest release](https://img.shields.io/github/commits-since/anto294/homeassistant-truenas/latest?style=plastic)
![GitHub commit activity](https://img.shields.io/github/commit-activity/m/anto294/homeassistant-truenas?style=plastic)
![GitHub Workflow Status](https://img.shields.io/github/actions/workflow/status/anto294/homeassistant-truenas/ci.yml?style=plastic)


![English](https://raw.githubusercontent.com/anto294/homeassistant-truenas/master/docs/assets/images/flags/us.png)
![Portuguese](https://raw.githubusercontent.com/anto294/homeassistant-truenas/master/docs/assets/images/flags/pt.png)
![Italian](https://raw.githubusercontent.com/anto294/homeassistant-truenas/master/docs/assets/images/flags/it.png)

![Truenas Logo](https://raw.githubusercontent.com/anto294/homeassistant-truenas/master/docs/assets/images/ui/header.png)

Monitor and control your TrueNAS CORE/SCALE device from Home Assistant.
 * Monitor System (Cpu, Load, Memory, Temperature, Network, ARC/L2ARC, Uptime)
 * Monitor Disks
 * Monitor Pools (including boot-pool)
 * Monitor Datasets
 * Monitor Replication Tasks
 * Monitor Snapshot Tasks
 * Control and Monitor Services
 * Control and Monitor Virtual Machines
 * Control and Monitor Containers (TrueNAS 27.0 and later)
 * Control and Monitor Jails (TrueNAS CORE only)
 * Control and Monitor Cloudsync
 * Create a Dataset Snapshot
 * Update Sensor
 * Reboot and Shutdown TrueNAS system
 

# Features
## Pools
Monitor status for each TrueNAS pool.

![Pools Health](https://raw.githubusercontent.com/anto294/homeassistant-truenas/master/docs/assets/images/ui/pool_healthy.png)
![Pools Free Space](https://raw.githubusercontent.com/anto294/homeassistant-truenas/master/docs/assets/images/ui/pool_free.png)

## Datasets
Monitor usage and attributes for each TrueNAS dataset.

![Datasets](https://raw.githubusercontent.com/anto294/homeassistant-truenas/master/docs/assets/images/ui/dataset.png)

## Disks
Monitor temperature and attributes for each TrueNAS disk.

![Disks](https://raw.githubusercontent.com/anto294/homeassistant-truenas/master/docs/assets/images/ui/disk.png)

## Virtual Machines
Control and monitor status and attributes for each TrueNAS Virtual Machines.
Virtual Machines control is available through services.

![Virtual Machines](https://raw.githubusercontent.com/anto294/homeassistant-truenas/master/docs/assets/images/ui/vm.png)

## Containers
*TrueNAS 27.0 and later*

Control and monitor status and attributes for each TrueNAS container.
Container control is available through the `container_start` and `container_stop` services.

## Jails
*TrueNAS CORE only*

Control and monitor status and attributes for each TrueNAS jail.
Jail control is available through services.

![Jails](https://raw.githubusercontent.com/anto294/homeassistant-truenas/master/docs/assets/images/ui/jail.png)

## Cloudsync
Control and monitor status and attributes for each TrueNAS cloudsync task.
Jail control is available through services.

![Cloudsync](https://raw.githubusercontent.com/anto294/homeassistant-truenas/master/docs/assets/images/ui/cloudsync.png)

## Replication Tasks
Monitor status and attributes for each TrueNAS replication task.

![Replication Tasks](https://raw.githubusercontent.com/anto294/homeassistant-truenas/master/docs/assets/images/ui/replication.png)

## Snapshot Tasks
Monitor status and attributes for each TrueNAS snapshot task.

![Snapshot Tasks](https://raw.githubusercontent.com/anto294/homeassistant-truenas/master/docs/assets/images/ui/snapshottask.png)

## Dataset Snapshot
Create a Dataset Snapshot using Homeassistant service.
Snapshot name will be automatically generated using datetime iso format with microseconds and "custom" prefix. 

![Snapshot UI](https://raw.githubusercontent.com/anto294/homeassistant-truenas/master/docs/assets/images/ui/snapshot_ui.png)
![Snapshot YAML](https://raw.githubusercontent.com/anto294/homeassistant-truenas/master/docs/assets/images/ui/snapshot_yaml.png)

## Services
Control and monitor status and attributes for each TrueNAS service.
Service control is available through services.

![Services](https://raw.githubusercontent.com/anto294/homeassistant-truenas/master/docs/assets/images/ui/service.png)

## Reboot and Shutdown
Reboot or Shutdown a TrueNAS system.
Service control is available through services.
Target system uptime sensor.

![image](https://user-images.githubusercontent.com/36953052/221521930-f8f789e6-deec-4cc2-b11e-740caa056e44.png)

# Install integration
This integration is distributed through [HACS](https://hacs.xyz/) as a custom repository.

[![Open your Home Assistant instance and open this repository inside HACS.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=anto294&repository=homeassistant-truenas&category=integration)

Or add it manually:
1. In Home Assistant open HACS, then the three-dot menu -> "Custom repositories".
2. Add `https://github.com/anto294/homeassistant-truenas` with type "Integration".
3. Search for "TrueNAS" in HACS, download it and restart Home Assistant.

This fork uses the same `truenas` domain as [tomaae/homeassistant-truenas](https://github.com/tomaae/homeassistant-truenas), so only one of the two can be installed at a time. If the upstream integration is already installed through HACS, remove it from HACS first, then download this one and restart Home Assistant. Removing it from HACS only deletes its files: your config entries and entities are kept, because the domain and entity unique IDs are the same.

Minimum requirements:
* TrueNAS 25.04 or later (the integration uses the versioned JSON-RPC websocket API introduced in 25.04)
* Home Assistant 2024.11.0

## Supported TrueNAS versions
The integration reads the TrueNAS version on every update and uses the API methods of that release, so it keeps working after an in-place TrueNAS upgrade without reconfiguration.

| Feature | 25.04 | 25.10 | 27.0 |
|---|---|---|---|
| System update check | `update.check_available` | `update.status` | `update.status` |
| System update install | `update.update` | `update.run` | `update.run` |
| Virtual Machines | `virt.instance.*` | `vm.*` | `vm.*` |
| Containers | listed with VMs (`virt.instance.*`) | not available | `container.*` |
| Dataset snapshot | `zfs.snapshot.create` | `pool.snapshot.create` | `pool.snapshot.create` |

API references: [TrueNAS 25.10](https://api.truenas.com/v25.10/), [TrueNAS 27.0](https://api.truenas.com/v27.0/).

## Using TrueNAS development branch
If you are using development branch for TrueNAS, some features may stop working.

## Setup integration
1. Create an API key for Home Assistant on your TrueNAS system.

![Setup step 1](https://raw.githubusercontent.com/anto294/homeassistant-truenas/master/docs/assets/images/ui/setup_1.png)
![Setup step 2](https://raw.githubusercontent.com/anto294/homeassistant-truenas/master/docs/assets/images/ui/setup_2.png)
![Setup step 3](https://raw.githubusercontent.com/anto294/homeassistant-truenas/master/docs/assets/images/ui/setup_3.png)

2. Setup this integration for your TrueNAS device in Home Assistant via `Configuration -> Integrations -> Add -> TrueNAS`.
You can add this integration several times for different devices.

NOTES: 
- If you dont see "TrueNAS" integration, clear your browser cache.

![Add Integration](https://raw.githubusercontent.com/anto294/homeassistant-truenas/master/docs/assets/images/ui/setup_integration.png)
* "Name of the integration" - Friendly name for this router
* "Host" - Use hostname or IP
* "API key" - TrueNAS API key for Home Assistant 

# Development

## Translation
English strings live in `custom_components/truenas/strings.json` and `custom_components/truenas/translations/en.json`. To add or improve a translation, open a pull request that adds or updates the matching file in `custom_components/truenas/translations/`.

## Enabling debug
To enable debug for TrueNAS integration, add following to your configuration.yaml:
```
logger:
  default: info
  logs:
    custom_components.truenas: debug
```

# Credits
This project is a fork of [tomaae/homeassistant-truenas](https://github.com/tomaae/homeassistant-truenas) by Tomaae, distributed under the Apache License 2.0.
