# Weather & Air Quality IoT

ESP32/ESP8266 → MQTT (Mosquitto) → validated Collector → MongoDB → FastAPI → dashboard.

## Online demo

[Open the interactive demo](https://siwat2614.github.io/demos/weather/) — uses fixed, synthetic readings and runs without sensors or a backend. It is not live weather or air-quality data. Station and month filters and charts are interactive. The demo source is in [`demo/`](demo/).

## Run locally

```sh
cp .env.example .env
docker compose -p weather-iot up -d --build
```

Dashboard: http://127.0.0.1:18001 · API docs: http://127.0.0.1:18001/docs
MQTT host port: 28883. MongoDB is internal to Docker. No personal database backup is included or automatically restored.

Stop: `docker compose -p weather-iot down` (keeps the database volume).

## Data validation

Required: station_id (1–64 ASCII letters, digits, `_` or `-`), temperature -40..80°C, humidity 0..100%, pm25 0..1000 µg/m³. Numbers must be finite and not booleans. Optional PM1/PM10 and other measurements are also checked. If timestamp is supplied it must be ISO-8601 and no more than 60 seconds in the future. Naive timestamps use Asia/Bangkok. Missing timestamp uses server time. These are acceptance bounds, not sensor accuracy guarantees or health classifications.

API: `/api/stations`, `/api/stations/{id}/latest`, `/api/stations/{id}/months`, `/api/stations/{id}/history?month=2026-09&limit=100`. Month boundaries use Thailand local time.

## Firmware and sensors

Sketch: `esp32/weather_station.ino`. Arduino libraries: PubSubClient, ArduinoJson 6.x, DHT sensor library and Adafruit Unified Sensor.

- Default DHT22, GPIO4. Select DHT11 in DHTTYPE if that is your hardware.
- PMS7003 UART active mode at 9600 baud. ESP32 UART2 RX16/TX17; ESP8266 SoftwareSerial RX14 (D5)/TX12 (D6). PMS TX connects to board RX; connect common GND and verify the module power/logic requirements before wiring.
- Decoder validates 32-byte header, frame length and checksum; uses atmospheric PM2.5 (Data 5). Timeout or invalid frame prevents publishing; the old analog-voltage estimate has been removed.
- Configure Wi-Fi and broker host in the sketch. Broker is the Mac LAN address and port 28883, not localhost. Set MQTT_BIND to the Mac LAN address (or 0.0.0.0 for a trusted isolated lab) in `.env` for hardware testing. Sketch MQTT_PORT must match that host port. Default sketch port is 28883.
- Allow startup time recommended by the sensor manufacturer; readings before sensor stabilization are not validated for accuracy.
- Protocol reference: [Plantower PMS7003 manual](https://www.espruino.com/datasheets/PMS7003.pdf).

## Tests

```sh
docker run --rm --network none -v "$PWD:/work:ro" -w /work weather-iot-collector python -m unittest discover -s tests -v
c++ tests/test_pms_frame.cpp -o /tmp/test-pms && /tmp/test-pms
MQTT_CONTAINER=weather-iot-mqtt-1 python3 tests/integration.py
```

Integration tests need a fresh test database (fixed qa-* station names) and insert simulated records. Use a separate Compose project/volume rather than running these against your data. Set BASE_URL and MQTT_CONTAINER when using a different project/port.

See TEST_RESULTS.md. Server tests and native parser tests passed; full Arduino build and physical sensor calibration remain unverified.

## Scope and credentials

This is a local educational prototype. MQTT is unauthenticated; keep it isolated. It has not been deployed. Before exposing it beyond a trusted lab, add MQTT authentication/TLS, API authentication and network restrictions. Never commit `.env`, real Wi-Fi credentials or MongoDB backups.
