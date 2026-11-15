# Repository Guidelines

## Project Structure & Module Organization

- `wifi_csi_tx/`: ESP32-S3 ESP-NOW probe transmitter; source and probe encoding live in `main/`.
- `wifi_csi_rx/`: shared receiver firmware for RX1/RX2; `main/protocol.h` defines UDP packet encoding.
- Both firmware projects use `main/Kconfig.projbuild` for configuration options and have independent CMake builds.
- `host/`: Python UDP collector and capture checker; automated tests are in `host/tests/test_host.py`.
- `captures/`: recorded `.dat` packets and CSV metadata. `reports/`: dataset audits and supporting evidence.
- Read the root and component READMEs before changing deployment behavior.

## Build, Test, and Development Commands

Use ESP-IDF **v6.0.2**, targeting `esp32s3`, for both firmware projects. Activate your ESP-IDF environment first.

Run these inside `wifi_csi_tx/` or `wifi_csi_rx/`:

```bash
idf.py menuconfig                  # Configure Wi-Fi and application settings
idf.py build                       # Compile the selected firmware
idf.py -p /dev/ttyACM0 flash monitor # Flash and inspect board logs; adjust port
```

Run `idf.py set-target esp32s3` only during initial setup, before entering local configuration; it regenerates configuration. Build and flash RX1/RX2 separately with distinct node IDs.

From the repository root, using Python 3.10+:

```bash
python3 -m unittest discover -s host/tests -v
python3 -m py_compile host/collector.py host/check_capture.py
python3 host/collector.py --bind 0.0.0.0 --port 5005 --out captures/session_new
python3 host/check_capture.py captures/session_new.dat
```

Stop collection before checking captures. Use a fresh output prefix; existing files are appended.

## Coding Style & Naming Conventions

Match existing four-space indentation. Use `snake_case` for C/Python functions and variables, uppercase constants and `CONFIG_APP_*` settings, and PascalCase Python classes. Keep C function opening braces on separate lines. No repository-wide formatter or linter is configured.

## Testing Guidelines

Use standard-library `unittest`, with `test_*` methods. Extend protocol, malformed-packet, storage, or UDP-loopback coverage when changing host behavior or packet formats. Loopback tests require socket access. No numeric coverage threshold is configured. Build affected firmware and report hardware validation separately: `WTX1` events alone do not prove CSI capture; verify `WCS1` from both receivers.

## Commit & Pull Request Guidelines

Git history is unavailable in this checkout, so no established message convention can be verified. Use concise imperative subjects, optionally scoped, such as `host: reject truncated CSI packets`. PRs should describe the change, affected components, validation results, and hardware/configuration requirements; link relevant issues.

## Configuration & Security

Keep credentials in local `sdkconfig`; keep shared `sdkconfig.defaults` free of secrets. Exclude generated builds and local configuration from commits. Use a trusted LAN: ESP-NOW broadcast and UDP traffic are unencrypted.
