import json
import random
import time
from datetime import datetime, timedelta, timezone

import paho.mqtt.client as mqtt


# ==========================================
# CONFIG
# ==========================================

MQTT_BROKER = "localhost"
MQTT_PORT = 1883

MQTT_TOPIC = "weather/station01/data"

STATION_ID = "station01"

DAYS = 365

INTERVAL_MINUTES = 5

NORMAL_RATIO = 0.90

BATCH_DELAY = 0.01


# ==========================================
# GENERATE SENSOR DATA
# ==========================================

def generate_sensor_data(timestamp):

    # Normal values
    temperature = random.uniform(24, 30)
    humidity = random.uniform(40, 70)
    pm25 = random.uniform(5, 25)

    # Abnormal approximately 10%
    if random.random() > NORMAL_RATIO:

        abnormal_type = random.choice([
            "temperature",
            "humidity",
            "pm25",
            "multiple"
        ])

        if abnormal_type == "temperature":

            temperature = random.choice([
                random.uniform(15, 20),
                random.uniform(35, 42)
            ])

        elif abnormal_type == "humidity":

            humidity = random.choice([
                random.uniform(20, 30),
                random.uniform(80, 95)
            ])

        elif abnormal_type == "pm25":

            pm25 = random.uniform(38, 150)

        elif abnormal_type == "multiple":

            temperature = random.uniform(35, 42)
            humidity = random.uniform(80, 95)
            pm25 = random.uniform(38, 150)

    return {
        "station_id": STATION_ID,
        "timestamp": timestamp.isoformat(),
        "temperature": round(temperature, 2),
        "humidity": round(humidity, 2),
        "pm25": round(pm25, 2)
    }


# ==========================================
# MAIN
# ==========================================

def main():

    client = mqtt.Client()

    print("Connecting to MQTT...")

    client.connect(
        MQTT_BROKER,
        MQTT_PORT,
        60
    )

    print("MQTT connected.")

    end_time = datetime.now(
        timezone(timedelta(hours=7))
    )

    start_time = end_time - timedelta(
        days=DAYS
    )

    current_time = start_time

    total_records = (
        DAYS * 24 * 60
    ) // INTERVAL_MINUTES

    count = 0

    print("=" * 60)
    print("WEATHER DATA SIMULATOR")
    print("=" * 60)

    print(f"Station       : {STATION_ID}")
    print(f"Start         : {start_time}")
    print(f"End           : {end_time}")
    print(f"Interval      : {INTERVAL_MINUTES} minutes")
    print(f"Total records : {total_records:,}")
    print("=" * 60)

    while current_time < end_time:

        data = generate_sensor_data(
            current_time
        )

        payload = json.dumps(
            data
        )

        client.publish(
            MQTT_TOPIC,
            payload,
            qos=1
        )

        count += 1

        if count % 1000 == 0:

            print(
                f"Sent "
                f"{count:,}/"
                f"{total_records:,}"
            )

        current_time += timedelta(
            minutes=INTERVAL_MINUTES
        )

        # ป้องกันการยิงเร็วเกินไป
        time.sleep(BATCH_DELAY)

    client.disconnect()

    print()
    print("=" * 60)
    print("COMPLETED")
    print("=" * 60)

    print(
        f"Total sent: {count:,}"
    )


if __name__ == "__main__":
    main()
