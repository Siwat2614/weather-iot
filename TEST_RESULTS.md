# Test results — 2026-11-01

Executed on macOS ARM64 with Docker Desktop, MongoDB 7 and Mosquitto 2.

- PASS: stations API
- PASS: dashboard HTTP
- PASS: chart asset HTTP
- PASS: MQTT to MongoDB to latest API
- PASS: history API
- PASS: invalid payloads rejected / collector survives
- PASS: Thai month boundary
- PASS: invalid month rejected
- PASS: missing station 404
- PASS: out-of-range sensor values rejected

- Python validation unit tests: PASS (including invalid types, ranges and non-finite numbers).
- MQTT broker restart and automatic reconnection: PASS.
- Native C++ protocol/risk regression tests: PASS.

Hardware sensor readings, full Arduino firmware compilation and physical LED output have not been verified. No deployment configured.
