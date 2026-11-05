"""Constants used by the TrueNAS integration."""

import voluptuous as vol

from homeassistant.const import Platform
from homeassistant.helpers import config_validation as cv

PLATFORMS = [
    Platform.SENSOR,
    Platform.BINARY_SENSOR,
    Platform.UPDATE,
    Platform.SWITCH,
]

DOMAIN = "truenas_link"
DEFAULT_NAME = "root"
ATTRIBUTION = "Data provided by TrueNAS integration"

DEFAULT_HOST = "10.0.0.1"
DEFAULT_USERNAME = "admin"

DEFAULT_DEVICE_NAME = "TrueNAS"
DEFAULT_SSL_VERIFY = False

CONF_ACCESS_LEVEL = "access_level"
ACCESS_LEVEL_ADMIN = "admin"
ACCESS_LEVEL_READ_ONLY = "read_only"
# New entries start read-only, so actions are always a deliberate choice
DEFAULT_ACCESS_LEVEL = ACCESS_LEVEL_READ_ONLY
# Entries created before the option existed have always had every action
LEGACY_ACCESS_LEVEL = ACCESS_LEVEL_ADMIN

TO_REDACT = {
    "username",
    "password",
    "encryption_password",
    "encryption_salt",
    "host",
    "api_key",
    "serial",
    "system_serial",
    "ip4_addr",
    "ip6_addr",
    "account",
    "key",
    "alert_messages",
    "hostname",
    "link_address",
    "access_key_id",
    "secret_access_key",
    "client_secret",
    "token",
    "pass",
    "private_key",
    "encryption_key",
    "service_account_credentials",
}

SCAN_IDLE = "idle"
SCAN_SCRUBBING = "scrubbing"
SCAN_PAUSED = "paused"
SCAN_RESILVERING = "resilvering"
BOOT_POOL_NAMES = ("boot-pool", "freenas-boot")

SERVICE_CLOUDSYNC_RUN = "cloudsync_run"
SCHEMA_SERVICE_CLOUDSYNC_RUN = {}

SERVICE_CLOUDSYNC_ABORT = "cloudsync_abort"
SCHEMA_SERVICE_CLOUDSYNC_ABORT = {}

SERVICE_POOL_SCRUB_START = "pool_scrub_start"
SCHEMA_SERVICE_POOL_SCRUB_START = {}
SERVICE_POOL_SCRUB_PAUSE = "pool_scrub_pause"
SCHEMA_SERVICE_POOL_SCRUB_PAUSE = {}
SERVICE_POOL_SCRUB_STOP = "pool_scrub_stop"
SCHEMA_SERVICE_POOL_SCRUB_STOP = {}

SERVICE_REPLICATION_RUN = "replication_run"
SCHEMA_SERVICE_REPLICATION_RUN = {}

SERVICE_DATASET_SNAPSHOT = "dataset_snapshot"
SCHEMA_SERVICE_DATASET_SNAPSHOT = {}

SERVICE_SYSTEM_REBOOT = "system_reboot"
SCHEMA_SERVICE_SYSTEM_REBOOT = {}

SERVICE_SYSTEM_SHUTDOWN = "system_shutdown"
SCHEMA_SERVICE_SYSTEM_SHUTDOWN = {}

SERVICE_SERVICE_START = "service_start"
SCHEMA_SERVICE_SERVICE_START = {}
SERVICE_SERVICE_STOP = "service_stop"
SCHEMA_SERVICE_SERVICE_STOP = {}
SERVICE_SERVICE_RESTART = "service_restart"
SCHEMA_SERVICE_SERVICE_RESTART = {}
SERVICE_SERVICE_RELOAD = "service_reload"
SCHEMA_SERVICE_SERVICE_RELOAD = {}

SERVICE_VM_START = "vm_start"
SERVICE_VM_START_OVERCOMMIT = "overcommit"
SCHEMA_SERVICE_VM_START = {vol.Optional(SERVICE_VM_START_OVERCOMMIT): cv.boolean}
SERVICE_VM_STOP = "vm_stop"
SCHEMA_SERVICE_VM_STOP = {}

SERVICE_CONTAINER_START = "container_start"
SCHEMA_SERVICE_CONTAINER_START = {}
SERVICE_CONTAINER_STOP = "container_stop"
SCHEMA_SERVICE_CONTAINER_STOP = {}

SERVICE_APP_START = "app_start"
SCHEMA_SERVICE_APP_START = {}
SERVICE_APP_STOP = "app_stop"
SCHEMA_SERVICE_APP_STOP = {}
