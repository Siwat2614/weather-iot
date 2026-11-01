"""
Historical Weather Sensor Simulator
-----------------------------------
Publishes 1 year of simulated weather data to MQTT.

Architecture:
    Simulator -> MQTT -> Collector -> MongoDB -> FastAPI -> Dashboard

Data:
    station01
    365 days
    every 5 minutes
    105,120 records

Approximately:
    90% normal
    10% abnormal

Payload:
    {
        "station_id": "station01",
        "timestamp": "2025-09-05T13:00:00+07:00",
        "temperature": 27.4,
        "humidity": 61.2,
        "pm25": 14.8
    }
"""

import json
import math
import random
import time
from datetime import datetime, timedelta, timezone

import paho.mqtt.client as mqtt


# ============================================================
# Configuration
# ============================================================

MQTT_BROKER = "localhost"
MQTT_PORT = 1883
MQTT_TOPIC = "weather/station01/data"

STATION_ID = "station01"

DAYS = 365
INTERVAL_MINUTES = 5

# True = actually wait between every MQTT message.
# False = send as fast as possible.
REALTIME_DELAY = False

# Small delay when sending historical data quickly.
SEND_DELAY_SECONDS = 0.01

# Approximately 10% abnormal data.
ABNORMAL_RATE = 0.10

LOCAL_TZ = timezone(timedelta(hours=7))


# ============================================================
# Weather generation
# ============================================================

def clamp(value, minimum, maximum):
    return max(minimum, min(maximum, value))


def generate_normal_value(timestamp):
    """
    Generate realistic environmental values.

    Temperature:
        approximately 24-30 C

    Humidity:
        approximately 40-70 %

    PM2.5:
        approximately 0-25 ug/m3
    """

    hour = timestamp.hour + timestamp.minute / 60

    # Daily temperature pattern.
    # Cooler around early morning, warmer in afternoon.
    daily_cycle = math.sin(
        ((hour - 6) / 24) * 2 * math.pi
    )

    # Seasonal cycle.
    day_of_year = timestamp.timetuple().tm_yday
    seasonal_cycle = math.sin(
        ((day_of_year - 80) / 365) * 2 * math.pi
    )

    temperature = (
        27
        + 2.0 * daily_cycle
        + 0.8 * seasonal_cycle
        + random.gauss(0, 0.5)
    )

    temperature = clamp(
        temperature,
        24.0,
        30.0
    )

    # Humidity generally moves opposite to temperature.
    humidity = (
        58
        - 8 * daily_cycle
        - 2 * seasonal_cycle
        + random.gauss(0, 2.0)
    )

    humidity = clamp(
        humidity,
        40.0,
        70.0
    )

    # PM2.5 has more random variation.
    pm25 = (
        12
        + random.gauss(0, 4)
        + (4 if hour < 9 or hour > 18 else 0)
    )

    pm25 = clamp(
        pm25,
        0.0,
        25.0
    )

    return (
        round(temperature, 1),
        round(humidity, 1),
        round(pm25, 1),
    )


def generate_abnormal_value(timestamp):
    """
    Generate abnormal environmental values.

    At least one measurement will be outside
    the normal operating range.
    """

    temperature, humidity, pm25 = generate_normal_value(timestamp)

    abnormal_type = random.choice([
        "high_temperature",
        "low_temperature",
        "high_humidity",
        "low_humidity",
        "high_pm25",
    ])

    if abnormal_type == "high_temperature":
        temperature = round(
            random.uniform(35.0, 42.0),
            1
        )

    elif abnormal_type == "low_temperature":
        temperature = round(
            random.uniform(15.0, 19.9),
            1
        )

    elif abnormal_type == "high_humidity":
        humidity = round(
            random.uniform(81.0, 95.0),
            1
        )

    elif abnormal_type == "low_humidity":
        humidity = round(
            random.uniform(20.0, 29.9),
            1
        )

    elif abnormal_type == "high_pm25":
        pm25 = round(
            random.uniform(38.0, 150.0),
            1
        )

    return temperature, humidity, pm25


def generate_reading(timestamp):
    """
    Generate one weather reading.

    Approximately 90% normal and 10% abnormal.
    """

    if random.random() < ABNORMAL_RATE:
        return generate_abnormal_value(timestamp)

    return generate_normal_value(timestamp)


# ============================================================
# MQTT
# ============================================================

def connect_mqtt():
    client = mqtt.Client(
        client_id="historical_weather_simulator"
    )

    print(
        f"Connecting to MQTT broker "
        f"{MQTT_BROKER}:{MQTT_PORT}..."
    )

    client.connect(
        MQTT_BROKER,
        MQTT_PORT,
        keepalive=60
    )

    client.loop_start()

    print("MQTT connected.")

    return client


# ============================================================
# Main simulation
# ============================================================

def main():

    print("=" * 60)
    print("Historical Weather Sensor Simulator")
    print("=" * 60)

    total_records = (
        DAYS
        * 24
        * 60
        // INTERVAL_MINUTES
    )

    print(f"Station       : {STATION_ID}")
    print(f"Period        : {DAYS} days")
    print(f"Interval      : {INTERVAL_MINUTES} minutes")
    print(f"Total records : {total_records:,}")
    print(f"Abnormal rate : {ABNORMAL_RATE * 100:.0f}%")
    print(f"MQTT topic    : {MQTT_TOPIC}")
    print("=" * 60)

    client = connect_mqtt()

    # End at the current time.
    end_time = datetime.now(LOCAL_TZ)

    # Start exactly DAYS days before the end time.
    start_time = end_time - timedelta(days=DAYS)

    current_time = start_time

    success_count = 0
    failed_count = 0

    start_run = time.time()

    try:

        while current_time <= end_time:

            temperature, humidity, pm25 = generate_reading(
                current_time
            )

            payload = {
                "station_id": STATION_ID,
                "timestamp": current_time.isoformat(),
                "temperature": temperature,
                "humidity": humidity,
                "pm25": pm25,
            }

            payload_json = json.dumps(
                payload,
                separators=(",", ":")
            )

            try:

                result = client.publish(
                    MQTT_TOPIC,
                    payload_json,
                    qos=1
                )

                if result.rc == mqtt.MQTT_ERR_SUCCESS:
                    success_count += 1
                else:
                    failed_count += 1
                    print(
                        f"MQTT publish failed: rc={result.rc}"
                    )

            except Exception as e:
                failed_count += 1
                print(
                    f"Publish error: {e}"
                )

            # Progress every 1,000 records.
            processed = success_count + failed_count

            if processed % 1000 == 0:

                elapsed = time.time() - start_run

                percentage = (
                    processed / total_records
                ) * 100

                print(
                    f"Progress: "
                    f"{processed:,}/{total_records:,} "
                    f"({percentage:.2f}%) | "
                    f"Success: {success_count:,} | "
                    f"Failed: {failed_count:,} | "
                    f"Elapsed: {elapsed:.1f}s"
                )

            if REALTIME_DELAY:
                time.sleep(
                    INTERVAL_MINUTES * 60
                )
            else:
                time.sleep(
                    SEND_DELAY_SECONDS
                )

            current_time += timedelta(
                minutes=INTERVAL_MINUTES
            )

    except KeyboardInterrupt:

        print("\nSimulation stopped by user.")

    finally:

        # Wait briefly so QoS 1 messages can finish sending.
        time.sleep(2)

        client.loop_stop()
        client.disconnect()

    elapsed = time.time() - start_run

    print()
    print("=" * 60)
    print("Simulation finished")
    print("=" * 60)
    print(f"Success : {success_count:,}")
    print(f"Failed  : {failed_count:,}")
    print(f"Elapsed : {elapsed:.1f} seconds")
    print("=" * 60)


if __name__ == "__main__":
    main()
