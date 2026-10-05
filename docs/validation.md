# Local validation

Run `uv run ruff check .` and `uv run pytest` for the lightweight protocol/retry/contract checks. These do not need a full HA installation.

The manual runtime smoke uses HA Core 2026.9.4 and Python 3.14 in a separate virtual environment. It copies only this custom component into a newly created `/tmp` configuration, initializes a separate Recorder, connects to a **synthetic loopback-only** service on port 18081, publishes fake local SoC, checks config flow/setup/options reload/input forwarding/ten entities, injects a synthetic two-second ready response to verify local expiry, then unloads/stops HA. It never connects to the household HA or any battery hardware.

```sh
uv venv --python 3.14 /tmp/energy-ha-validation
uv pip install --python /tmp/energy-ha-validation/bin/python homeassistant==2026.9.4
/tmp/energy-ha-validation/bin/python tests/manual_ha_smoke.py
```

The service must first be seeded with its separate synthetic demo loader. The script's demo password is deliberately synthetic; do not repoint it at a household deployment. Keep its generated config-entry token and Recorder artifacts in the private temporary directory.

Recorder call signatures and config entry/coordinator lifecycle were checked against the 2026.9.4 runtime. Raw/history unit/sign/topology semantics, inactive source continuity and installed hardware still require actual site commissioning. No live household access was available during this release.
