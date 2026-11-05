# CLAUDE.md

Home Assistant custom integration (HACS) for TrueNAS, named "TrueNAS Link". Domain: `truenas_link` (renamed from `truenas` in 2.0.0 so it can sit next to upstream). All code lives in `custom_components/truenas_link/`. Repository: `anto294/homeassistant-truenas`, which started as a fork of `tomaae/homeassistant-truenas` (domain `truenas`) and is distributed separately through HACS. Repository links (manifest, README, release scripts) must point to the fork, not upstream.

## TrueNAS API reference

- Index of all versions: https://api.truenas.com/
- 25.10: https://api.truenas.com/v25.10/
- 27.0: https://api.truenas.com/v27.0/

Check a method's name, parameters and return shape in these docs before adding or changing any `api.query(...)` call. Methods get renamed or removed between releases. For example, 25.04 managed VMs through `virt.instance.*`, 25.10 removed that namespace and went back to `vm.*`, and 27.0 added `container.*`. When behavior differs between versions, write code that handles both, and branch with `coordinator.version_at_least(major, minor)`. The README has a table of which methods each release uses ("Supported TrueNAS versions").

## Architecture

- **`api.py`**: `TrueNASAPI` is a **synchronous** JSON-RPC 2.0 client over websocket (`websockets.sync.client`) that connects to `wss://<host>/api/current` and logs in with `auth.login_with_api_key`. `query(method, params)` returns `result`, or `None` on an exception, and disconnects when that happens. A `threading.Lock` serializes calls. Connection errors map to string codes in `self._error`, and those codes match the keys in `strings.json` / `translations/*.json`.
- **`coordinator.py`**: `TrueNASCoordinator(DataUpdateCoordinator)` polls every 60s. `_async_update_data` runs each `get_*` method through `hass.async_add_executor_job`, because the API is blocking. The update check runs every 12h. All state is stored in `self.ds[<section>]` (`system_info`, `interface`, `disk`, `pool`, `dataset`, `service`, `vm`, `cloudsync`, `replication`, `snapshottask`, `app`, `container`).
- **`apiparser.py`**: `parse_api(data, source, key, vals, ensure_vals, val_proc, only, skip)` normalizes API responses into `self.ds`. `source` paths use `/` to select nested fields (for example, `"progress/percent"`). `type: "bool"` uses `from_entry_bool`. Prefer `parse_api` over hand-written dict access.
- **Entities**: these are declarative. `sensor_types.py`, `binary_sensor_types.py` and `update_types.py` define `*EntityDescription` dataclasses with these fields:
  - `data_path`: key in `ds`
  - `data_attribute`: value
  - `data_reference`: uid field for per-item entities
  - `data_name`
  - `data_attributes_list`: extra attributes
  - `ha_group`: device. `"data__<field>"` takes the value from the data.
  - `func`: class name in the platform's dispatcher
- **`entity.py`**: `async_add_entities` creates entities from the descriptions and registers the `SENSOR_SERVICES` entity services, given as `[service, schema, method_name]`. `TrueNASEntity` builds `unique_id` as `<name>-<key>[-<uid>]`. Don't change this format, because existing users' entities would break.
- **Actions** (start/stop/snapshot/reboot…) are async methods on the entity subclasses in `sensor.py` / `binary_sensor.py` / `update.py`, and they call `await hass.async_add_executor_job(self.coordinator.api.query, "<method>", [params])`.
- **Access level**: `access_level` in the entry data (`admin`, or `read_only`; missing means `admin`) is exposed as `coordinator.read_only`. Entity services are registered through `entity_service_handler` and `async_update_services` in `entity.py`, which refuse them on read-only entities. Entities must keep working on `READONLY_ADMIN`, so a read in `coordinator.py` must not need more than a `*_READ` role (the API docs list each method's roles). A new write action just needs a `SENSOR_SERVICES` entry; a new install-like entity feature must be off when `coordinator.read_only` is set.
- **Services**: constants and schemas go in `const.py`, the definitions go in `services.yaml`, and the descriptions go in `strings.json`.

## Adding a feature (typical flow)

1. Check the method in the API docs (see above).
2. Add a `get_<x>` method in `coordinator.py`, add the `ds["<x>"]` section in `__init__`, and add the job to the list in `_async_update_data`.
3. Add descriptions in the right `*_types.py` file, plus an entity class if it needs actions.
4. Update `strings.json` **and** `translations/en.json`. Other languages are contributed by pull request to `translations/`.
5. If there is new sensitive data, add it to `TO_REDACT` in `const.py`, which `diagnostics.py` uses.

## Conventions

- Format with **black** (CI runs `black . --check`). Run `black .` before committing.
- Lint: CI runs `flake8` with `max-line-length=127`. `setup.cfg` sets 220 for local use.
- Every function and class gets a docstring, and section comments use this banner style:
  ```python
  # ---------------------------
  #   function_name
  # ---------------------------
  ```
- Never block the event loop. Every `api.query` call from async code goes through `async_add_executor_job`.
- Keep `DEFAULT_DEVICE_NAME = "TrueNAS"` in `const.py`. Entity IDs are built from the entry name (`build_entity_id` in `entity.py`), and the 1.x → 2.0 migration relies on users getting the same entity IDs back when they add the entry again with the same name.
- `manifest.json` keeps `"version": "0.0.0"`. The release workflow (`.github/update_version.py`) sets the real version.
- HACS installs from the `truenas_link.zip` asset that `release.yml` attaches to each published GitHub release (`zip_release` in `hacs.json`). Publish a full GitHub release, not just a tag; mark betas as pre-releases. Tags are `vX.Y.Z` or `vX.Y.ZbN` (the release workflow rejects anything else). Every user-facing change gets an entry under `## [Unreleased]` in `CHANGELOG.md` (Keep a Changelog format); the release notes are that version's section, passed with `gh release create --notes-file`. README.md is the page HACS shows (no `info.md`).
- Keep `hacs.json` `homeassistant` at the oldest core that has every HA API the code uses.
- Minimum HA version: see `hacs.json` (`homeassistant`) and `Pipfile` (dev dependency).

## Development commands

```bash
pipenv install --dev            # or: python .github/generate_requirements.py && pip install -r requirements_tests.txt
black .
flake8 . --count --select=E9,F63,F7,F82 --show-source --statistics
```

Tests live in `tests/` (pytest, `[tool:pytest]` in `setup.cfg`) and run against an installed Home Assistant: `python -m pytest`. `tests/conftest.py` provides a `FakeWebSocket` and a `connected_api` fixture, so `TrueNASAPI.query()` and the coordinator run unmodified against canned JSON-RPC responses; build payloads from the real API shapes. CI runs them in the "Import and test" job on the oldest supported and the latest Home Assistant. CI also runs hassfest (`home-assistant/actions/hassfest`) and Bandit. To check changes by hand, copy `custom_components/truenas_link` into the `config/custom_components/` directory of a Home Assistant dev instance that is connected to a real TrueNAS system. Turn on debug logging for `custom_components.truenas_link` to see every query and response.
