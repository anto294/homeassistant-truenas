# CLAUDE.md

Home Assistant custom integration (HACS) for TrueNAS, named "TrueNAS Link". Domain: `truenas_link` (renamed from `truenas` in 2.0.0 so it can sit next to upstream). All code lives in `custom_components/truenas_link/`. Repository: `anto294/homeassistant-truenas`, which started as a fork of `tomaae/homeassistant-truenas` (domain `truenas`) and is distributed separately through HACS. Repository links (manifest, README, release scripts) must point to the fork, not upstream.

## TrueNAS API reference

- Index of all versions: https://api.truenas.com/
- 25.10: https://api.truenas.com/v25.10/
- 27.0: https://api.truenas.com/v27.0/

Check a method's name, parameters and return shape in these docs before adding or changing any `api.query(...)` call. Methods get renamed or removed between releases. For example, 25.04 managed VMs through `virt.instance.*`, 25.10 removed that namespace and went back to `vm.*`, and 27.0 added `container.*`. When behavior differs between versions, write code that handles both, and branch with `coordinator.version_at_least(major, minor)`. The README has a table of which methods each release uses ("Supported TrueNAS versions").

## Architecture

- **`api.py`**: `TrueNASAPI` is an **asynchronous** JSON-RPC 2.0 client over websocket (`websockets.asyncio.client`) that connects to `wss://<host>/api/current` and logs in with `auth.login_with_api_key`. `query(method, params)` returns `result`, or `None` on an exception, and disconnects when that happens. It never reconnects: a poll connects once at its start, so a lost connection always ends the poll in `UpdateFailed`. Every answer is awaited for at most `RESPONSE_TIMEOUT` seconds, and a timeout or a cancellation always closes the connection, because all requests use `id` 0 and a late answer would be read as the next request's. A new call that TrueNAS can keep waiting for longer must stay below that value. `call(method, params)` raises instead, and says with `request_sent` whether the request went out. An `asyncio.Lock` serializes calls. Connection errors map to string codes in `self._error`, and those codes match the keys in `strings.json` / `translations/*.json`. A rejected login returns `result: false`, which gives `invalid_key` and starts reauthentication.
- **`coordinator.py`**: `TrueNASCoordinator(DataUpdateCoordinator)` polls every 60s. `_async_update_data` awaits each `get_*` method. The update check runs every 12h. All state is stored in `self.ds[<section>]` (`system_info`, `interface`, `disk`, `pool`, `dataset`, `service`, `vm`, `cloudsync`, `replication`, `snapshottask`, `app`, `container`, `cronjob`).
- **`apiparser.py`**: `parse_api(data, source, key, vals, ensure_vals)` normalizes API responses into `self.ds`. `source` paths use `/` to select nested fields (for example, `"progress/percent"`). `type: "bool"` uses `from_entry_bool`. Prefer `parse_api` over hand-written dict access.
- **Entities**: these are declarative. `sensor_types.py`, `binary_sensor_types.py`, `update_types.py` and `switch_types.py` define `*EntityDescription` dataclasses with these fields:
  - `data_path`: key in `ds`
  - `data_attribute`: value
  - `data_reference`: uid field for per-item entities
  - `data_name`
  - `data_attributes_list`: extra attributes
  - `ha_group`: device
  - `func`: class name in the platform's dispatcher
- **`entity.py`**: `async_add_entities` creates entities from the descriptions. `SENSOR_SERVICES` lists actions as `[service, schema, method_name]`. `TrueNASEntity` builds `unique_id` as `<name>-<key>[-<uid>]`. Don't change this format, because existing users' entities would break.
- **Items that come and go**: `entity.py` adds an entity for each new item from a coordinator listener. Every `get_*` wraps its query in `_seen`, so a failed query (None) leaves `present` as it was. `stale.py` removes entities after `STALE_AFTER_POLLS` successful polls without the item. A failed query, an empty list, and a dataset whose pool is gone never count. `async_remove_config_entry_device` is the manual way out. A new section must use `_seen` too.
- **Actions** (start/stop/snapshot/reboot…) are async methods on the entity subclasses in `sensor.py` / `binary_sensor.py` / `update.py` / `switch.py`, and they call `await self._async_call("<method>", [params])` from `TrueNASEntity`, which raises a translated `HomeAssistantError` if the call fails. An action that does not apply to the current state raises `invalid_state_error` (a `ServiceValidationError`). `api.query` returns None on failure and is only for polling; a successful call can return None too, so actions never use it.
- **Entry data and options**: `entry.data` holds only what is needed to connect (`host`, `api_key`, `verify_ssl`). `entry.options` holds `name` and `access_level`. The name still cannot change, because entity ids are built from it. Entry version 2 made this move: `async_migrate_entry` does it, and an older release refuses to load a version 2 entry, instead of treating a read-only entry as Administrator.
- **Access level**: `access_level` in the entry options (`admin` or `read_only`; new entries default to `read_only`, entries migrated without one get `admin`, and a missing key means `read_only`) is exposed as `coordinator.read_only`. It changes with the entry's Configure button (`TrueNASOptionsFlow`), which reloads the entry. Actions are registered once in `async_setup` in `__init__.py`, from the `SENSOR_SERVICES` lists of `sensor_types.py` and `binary_sensor_types.py`, so they exist even without entries. They stay registered on read-only entries, and `entity_service_handler` in `entity.py` refuses them with `read_only_action`: that is the integration's only protection there, so never bypass it. It also refuses an action on any entity class but the one in its `SENSOR_SERVICES` entry, because methods share names (`stop` on the uptime sensor shuts TrueNAS down). Entities must keep working on `READONLY_ADMIN`, so a read in `coordinator.py` must not need more than a `*_READ` role (the API docs list each method's roles). A new write action just needs a `SENSOR_SERVICES` entry, with its entity class, and `services.yaml`; a new install-like entity feature must be off when `coordinator.read_only` is set. An entity that cannot work read-only must not exist on a read-only entry, and must be removed from the registry when an entry becomes read-only, as `switch.py` does (`async_remove_switches`).
- **Safety rules** (the README's "Security" section promises them): power and workload controls are actions, not switches. Actions take no free-form input (commands, users, API methods). Do not request fields that can hold secrets, such as a cron job's `command`. A new switch that controls TrueNAS is disabled by default and has `EntityCategory.CONFIG`.
- **Names and icons**: a description's `name` stays in English and builds the entity id (`_english_name`, never the translated name), and it must not change. `translation_key` gives the name shown, from `entity` in `strings.json` and `translations/*.json`, where a per-item entity uses `{name}` for the item. Icons are in `icons.json`, by `translation_key`.
- **Services**: constants and schemas go in `const.py`, the definitions go in `services.yaml`, and the descriptions go in `strings.json`.

## Adding a feature (typical flow)

1. Check the method in the API docs (see above).
2. Add a `get_<x>` method in `coordinator.py`, add the `ds["<x>"]` section in `__init__`, and add the job to the list in `_async_update_data`.
3. Add descriptions in the right `*_types.py` file, plus an entity class if it needs actions.
4. Update `strings.json` and every file in `translations/`: `tests/test_translations.py` fails if a language lacks a key or a placeholder.
5. If there is new sensitive data, including a free-text field, add its name to `TO_REDACT` in `const.py`, which `diagnostics.py` and the debug logs of `api.py` and `apiparser.py` use. Redaction goes by field name and cannot see secrets inside a text.

## Conventions

- Format with **black** (CI runs `black . --check`). Run `black .` before committing.
- Types: CI runs `mypy -p custom_components.truenas_link`, strict, configured in `setup.cfg`. A `type: ignore` needs a comment that says why.
- Lint: CI runs `flake8` with `max-line-length=127`. `setup.cfg` sets 220 for local use.
- Every function and class gets a docstring, and section comments use this banner style:
  ```python
  # ---------------------------
  #   function_name
  # ---------------------------
  ```
- Never block the event loop. The client is asynchronous, so nothing needs an executor. Close connections on every path, because each one keeps tasks running.
- Keep `DEFAULT_DEVICE_NAME = "TrueNAS"` in `const.py`. Entity IDs are built from the entry name (`build_entity_id` in `entity.py`), and the 1.x → 2.0 migration relies on users getting the same entity IDs back when they add the entry again with the same name.
- `manifest.json` keeps `"version": "0.0.0"`. The release workflow (`.github/update_version.py`) sets the real version.
- HACS installs from the `truenas_link.zip` asset that `release.yml` attaches to each published GitHub release (`zip_release` in `hacs.json`). Publish a full GitHub release, not just a tag; mark betas as pre-releases. Tags are `vX.Y.Z` or `vX.Y.ZbN` (the release workflow rejects anything else). Every user-facing change gets an entry under `## [Unreleased]` in `CHANGELOG.md` (Keep a Changelog format); the release notes are that version's section, passed with `gh release create --notes-file`. README.md is the page HACS shows (no `info.md`).
- Keep `hacs.json` `homeassistant` at the oldest core that has every HA API the code uses.
- Minimum HA version: 2026.11.0, Python 3.14. See `hacs.json` (`homeassistant`) and `Pipfile` (dev dependency). Do not lower it, and do not add code for older cores.

## Development commands

```bash
pipenv install --dev            # or: python .github/generate_requirements.py && pip install -r requirements_tests.txt
black .
flake8 . --count --select=E9,F63,F7,F82 --show-source --statistics
```

Tests live in `tests/` (pytest, `[tool:pytest]` in `setup.cfg`) and run against an installed Home Assistant: `python -m pytest`. `tests/conftest.py` provides a `FakeWebSocket`, a `connected_api` fixture that runs each call to the end, and `run_in_hass` for a real core, so `TrueNASAPI.query()` and the coordinator run unmodified against canned JSON-RPC responses; build payloads from the real API shapes. CI runs them in the "Import and test" job on the oldest supported and the latest Home Assistant. CI also runs hassfest (`home-assistant/actions/hassfest`) and Bandit. To check changes by hand, copy `custom_components/truenas_link` into the `config/custom_components/` directory of a Home Assistant dev instance that is connected to a real TrueNAS system. Turn on debug logging for `custom_components.truenas_link` to see every query and response.
