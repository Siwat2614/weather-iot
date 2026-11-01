"""
Data Collector
--------------
Subscribes to MQTT topic weather/+/data, validates JSON payloads,
uses the payload timestamp when provided, and stores each valid
reading as a historical record in MongoDB.

Pipeline (per SRS FR-08):
    Receive -> Decode UTF-8 -> Parse JSON -> Validate
    -> Use Timestamp -> Insert MongoDB

Design goals (NFR-02 Reliability):
    A single malformed / invalid MQTT payload must never crash the collector.
"""

import os
import sys
import json
import math
import re
import logging
import time
from datetime import datetime, timezone, timedelta

import paho.mqtt.client as mqtt
from pymongo import MongoClient
from pymongo.errors import PyMongoError

# ---------------------------------------------------------------------------
# Configuration (NFR-05 — no hard-coded values, everything from environment)
# ---------------------------------------------------------------------------
MQTT_BROKER = os.getenv("MQTT_BROKER", "mqtt")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))
MQTT_TOPIC = os.getenv("MQTT_TOPIC", "weather/+/data")

MONGO_URL = os.getenv("MONGO_URL", "mongodb://mongodb:27017")
MONGO_DB_NAME = os.getenv("MONGO_DB_NAME", "weather_db")
MONGO_COLLECTION = os.getenv("MONGO_COLLECTION", "weather_readings")

RECONNECT_DELAY_SECONDS = 5

# Thailand local time zone
LOCAL_TZ = timezone(timedelta(hours=7))

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [collector] %(levelname)s: %(message)s",
)

log = logging.getLogger("collector")

# ---------------------------------------------------------------------------
# Payload validation
# ---------------------------------------------------------------------------
REQUIRED_FIELDS = {
    "station_id": str,
    "temperature": (int, float),
    "humidity": (int, float),
    "pm25": (int, float),
}

OPTIONAL_NUMERIC_FIELDS = [
    "pm10",
    "pm1_0",
    "pressure",
    "light",
    "co2",
]


def validate_payload(data: dict) -> tuple[bool, str]:
    if not isinstance(data, dict):
        return False, "Payload must be a JSON object"
    station = data.get("station_id")
    if not isinstance(station, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", station):
        return False, "station_id must contain 1-64 letters, digits, hyphens or underscores"
    ranges = {"temperature": (-40, 80), "humidity": (0, 100), "pm25": (0, 1000),
              "pm10": (0, 1000), "pm1_0": (0, 1000), "pressure": (0, 2000),
              "light": (0, 1000000), "co2": (0, 1000000)}
    for field, (low, high) in ranges.items():
        if field not in data:
            if field in REQUIRED_FIELDS:
                return False, f"Missing required field: {field}"
            continue
        value = data[field]
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return False, f"{field} must be numeric"
        if not low <= value <= high or not math.isfinite(value):
            return False, f"{field} must be finite and between {low} and {high}"
    if "timestamp" in data:
        timestamp = parse_timestamp(data["timestamp"])
        if timestamp is None:
            return False, "timestamp must be an ISO-8601 string"
        if timestamp > datetime.now(LOCAL_TZ) + timedelta(seconds=60):
            return False, "timestamp must not be more than 60 seconds in the future"
    return True, "ok"


def parse_timestamp(timestamp_value):
    """
    Convert an incoming ISO-8601 timestamp into a timezone-aware datetime.

    Example accepted value:
        2025-09-05T13:00:00+07:00

    If timestamp is invalid, return None.
    """

    if not timestamp_value:
        return None

    if not isinstance(timestamp_value, str):
        log.warning(
            "Invalid timestamp type: %s",
            type(timestamp_value).__name__,
        )
        return None

    try:
        received_at = datetime.fromisoformat(timestamp_value)

        # If timestamp has no timezone information,
        # assume Thailand local time.
        if received_at.tzinfo is None:
            received_at = received_at.replace(tzinfo=LOCAL_TZ)

        return received_at

    except ValueError:
        log.warning(
            "Invalid timestamp format: %s",
            timestamp_value,
        )
        return None


def build_document(data: dict) -> dict:
    """
    Build MongoDB document.

    Priority:
        1. Use timestamp from MQTT payload
        2. If missing/invalid, use current server time

    MongoDB field:
        received_at
    """

    # ---------------------------------------------------------------
    # Historical timestamp
    # ---------------------------------------------------------------
    timestamp = data.get("timestamp")

    received_at = parse_timestamp(timestamp)

    # If timestamp is missing or invalid,
    # fall back to current server time.
    if received_at is None:
        received_at = datetime.now(LOCAL_TZ)

    # ---------------------------------------------------------------
    # Main document
    # ---------------------------------------------------------------
    doc = {
        "station_id": data["station_id"],
        "temperature": float(data["temperature"]),
        "humidity": float(data["humidity"]),
        "pm25": float(data["pm25"]),
        "received_at": received_at,
    }

    # ---------------------------------------------------------------
    # Optional numeric fields
    # ---------------------------------------------------------------
    for field in OPTIONAL_NUMERIC_FIELDS:

        if (
            field in data
            and isinstance(data[field], (int, float))
            and not isinstance(data[field], bool)
        ):
            doc[field] = float(data[field])

    return doc


class Collector:

    def __init__(self):

        self.mongo_client = None
        self.collection = None
        self.mqtt_client = None

        self._connect_mongo()
        self._setup_mqtt()

    # ------------------------------------------------------------------
    # MongoDB
    # ------------------------------------------------------------------

    def _connect_mongo(self):

        try:

            self.mongo_client = MongoClient(
                MONGO_URL,
                serverSelectionTimeoutMS=5000,
            )

            self.mongo_client.admin.command("ping")

            db = self.mongo_client[MONGO_DB_NAME]

            self.collection = db[MONGO_COLLECTION]

            # Index for history queries
            self.collection.create_index(
                [
                    ("station_id", 1),
                    ("received_at", -1),
                ]
            )

            log.info(
                "Connected to MongoDB at %s (db=%s)",
                MONGO_URL,
                MONGO_DB_NAME,
            )

        except PyMongoError as e:

            # MongoDB unavailable must not crash collector
            log.error(
                "MongoDB connection failed: %s",
                e,
            )

            self.collection = None

    def _insert_reading(self, doc: dict) -> bool:

        if self.collection is None:
            self._connect_mongo()

        if self.collection is None:

            log.error(
                "Insert skipped — MongoDB unavailable"
            )

            return False

        try:

            self.collection.insert_one(doc)

            return True

        except PyMongoError as e:

            log.error(
                "MongoDB insert failed: %s",
                e,
            )

            self.collection = None

            return False

    # ------------------------------------------------------------------
    # MQTT
    # ------------------------------------------------------------------

    def _setup_mqtt(self):

        self.mqtt_client = mqtt.Client(
            client_id="weather_collector"
        )

        self.mqtt_client.on_connect = self._on_connect
        self.mqtt_client.on_disconnect = self._on_disconnect
        self.mqtt_client.on_message = self._on_message

    def _on_connect(
        self,
        client,
        userdata,
        flags,
        rc,
    ):

        if rc == 0:

            log.info(
                "MQTT Connected to %s:%s",
                MQTT_BROKER,
                MQTT_PORT,
            )

            client.subscribe(
                MQTT_TOPIC,
                qos=1,
            )

            log.info(
                "Subscribed to topic: %s",
                MQTT_TOPIC,
            )

        else:

            log.error(
                "MQTT Connect failed, rc=%s",
                rc,
            )

    def _on_disconnect(
        self,
        client,
        userdata,
        rc,
    ):

        log.warning(
            "MQTT Disconnected (rc=%s) "
            "— will attempt to reconnect",
            rc,
        )

    def _on_message(
        self,
        client,
        userdata,
        msg,
    ):

        log.info(
            "Received message on topic=%s",
            msg.topic,
        )

        # --------------------------------------------------------------
        # Decode UTF-8
        # --------------------------------------------------------------

        try:

            raw = msg.payload.decode("utf-8")

        except UnicodeDecodeError as e:

            log.error(
                "Invalid UTF-8 payload on %s: %s",
                msg.topic,
                e,
            )

            return

        log.info(
            "Payload: %s",
            raw,
        )

        # --------------------------------------------------------------
        # Parse JSON
        # --------------------------------------------------------------

        try:

            data = json.loads(raw)

        except json.JSONDecodeError as e:

            log.error(
                "Invalid JSON on %s: %s "
                "-- message ignored",
                msg.topic,
                e,
            )

            return

        # --------------------------------------------------------------
        # Validate
        # --------------------------------------------------------------

        is_valid, reason = validate_payload(data)

        if not is_valid:

            log.error(
                "Validation failed for topic=%s "
                "reason=%s payload=%s",
                msg.topic,
                reason,
                data,
            )

            return

        log.info(
            "Validation OK for station_id=%s",
            data.get("station_id"),
        )

        # --------------------------------------------------------------
        # Build document
        # --------------------------------------------------------------

        doc = build_document(data)

        log.info(
            "Using received_at=%s for station_id=%s",
            doc["received_at"],
            doc["station_id"],
        )

        # --------------------------------------------------------------
        # Insert MongoDB
        # --------------------------------------------------------------

        ok = self._insert_reading(doc)

        if ok:

            log.info(
                "MongoDB insert OK for station_id=%s",
                doc["station_id"],
            )

        else:

            log.error(
                "MongoDB insert FAILED for station_id=%s",
                doc["station_id"],
            )

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    def run(self):

        while True:

            try:

                self.mqtt_client.connect(
                    MQTT_BROKER,
                    MQTT_PORT,
                    keepalive=60,
                )

                self.mqtt_client.loop_forever()

            except (
                ConnectionRefusedError,
                OSError,
            ) as e:

                log.warning(
                    "MQTT broker unreachable (%s). "
                    "Retrying in %ss...",
                    e,
                    RECONNECT_DELAY_SECONDS,
                )

                time.sleep(
                    RECONNECT_DELAY_SECONDS
                )

            except Exception as e:

                # Collector must never die
                log.error(
                    "Unexpected error in MQTT loop: %s",
                    e,
                )

                time.sleep(
                    RECONNECT_DELAY_SECONDS
                )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":

    log.info(
        "Starting Data Collector..."
    )

    collector = Collector()

    try:

        collector.run()

    except KeyboardInterrupt:

        log.info(
            "Shutting down collector."
        )

        sys.exit(0)
