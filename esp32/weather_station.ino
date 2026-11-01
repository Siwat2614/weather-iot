/*
  IoT Weather & Air Quality Monitoring System
  ESP32 / ESP8266 Firmware

  Implements:
    FR-01 Sensor Acquisition   (Temperature, Humidity, PM2.5)
    FR-02 Sensor Sampling      (Default interval = 5 seconds)
    FR-03 Sensor Validation    (reject NaN / invalid frames before publish)
    FR-04 Wi-Fi Connectivity   (status via Serial Monitor)
    FR-05 MQTT Connection      (TCP 1883, auto-reconnect)
    FR-06 MQTT Publisher       (weather/{station_id}/data)

  Libraries required (Arduino Library Manager):
    - PubSubClient      (Nick O'Leary)
    - ArduinoJson        (Benoit Blanchon)
    - DHT sensor library (Adafruit)  + Adafruit Unified Sensor

  Hardware: DHT22 (select DHT11 if that is your actual sensor) + PMS7003 UART.
  ESP32 PMS RX=16 TX=17. ESP8266 PMS RX=14(D5) TX=12(D6).
  PMS TX -> board RX; shared GND; power sensor according to its datasheet.
  No estimated/analog PM values are published.
*/

#if defined(ESP8266)
#include <ESP8266WiFi.h>
#include <SoftwareSerial.h>
SoftwareSerial pmSerial(14,12); // RX, TX (NodeMCU D5, D6)
#else
#include <WiFi.h>
HardwareSerial pmSerial(2); // ESP32 UART2
#endif
#include "pms_frame.h"
#include <PubSubClient.h>
#include <ArduinoJson.h>
#include <DHT.h>

// ---------------------------------------------------------------------------
// Configuration (NFR-05 — keep all magic values here, not scattered)
// ---------------------------------------------------------------------------
const char* WIFI_SSID     = "YOUR_WIFI_SSID";
const char* WIFI_PASSWORD = "YOUR_WIFI_PASSWORD";

const char* MQTT_BROKER   = "192.168.1.100";   // Host PC IP (see SRS External Networking)
const int   MQTT_PORT     = 28883;
const char* STATION_ID    = "station01";

const unsigned long SAMPLING_INTERVAL_MS = 5000;  // FR-02 default = 5 seconds

#define DHTPIN 4
#define DHTTYPE DHT22


// ---------------------------------------------------------------------------
// Globals
// ---------------------------------------------------------------------------
DHT dht(DHTPIN, DHTTYPE);
WiFiClient espClient;
PubSubClient mqttClient(espClient);

char mqttTopic[64];
unsigned long lastSampleTime = 0;

// ---------------------------------------------------------------------------
// Wi-Fi (FR-04)
// ---------------------------------------------------------------------------
void connectWiFi() {
  Serial.println("WiFi Connecting...");
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);

  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
  }

  Serial.println();
  Serial.println("WiFi Connected");
  Serial.print("IP Address: ");
  Serial.println(WiFi.localIP());
}

void ensureWiFi() {
  if (WiFi.status() != WL_CONNECTED) {
    Serial.println("WiFi Disconnected -- reconnecting...");
    connectWiFi();
  }
}

// ---------------------------------------------------------------------------
// MQTT (FR-05, FR-06)
// ---------------------------------------------------------------------------
void connectMQTT() {
  while (!mqttClient.connected()) {
    Serial.print("Connecting to MQTT Broker...");
    String clientId = "ESP32Client-" + String(STATION_ID);

    if (mqttClient.connect(clientId.c_str())) {
      Serial.println(" connected.");
    } else {
      Serial.print(" failed, rc=");
      Serial.print(mqttClient.state());
      Serial.println(" retrying in 5s");
      delay(5000);
    }
  }
}

void ensureMQTT() {
  if (!mqttClient.connected()) {
    connectMQTT();
  }
  mqttClient.loop();
}

// ---------------------------------------------------------------------------
// Sensor Reading (FR-01) + Validation (FR-03)
// ---------------------------------------------------------------------------
void initPM(){
#if defined(ESP8266)
  pmSerial.begin(9600);
#else
  pmSerial.begin(9600,SERIAL_8N1,16,17);
#endif
}
float readPM25() {
  uint8_t frame[32];size_t used=0;uint16_t value=0;
  unsigned long start=millis();
  while(millis()-start<2000){
    if(!pmSerial.available()){mqttClient.loop();delay(1);continue;}
    uint8_t byte=pmSerial.read();
    if(used==0&&byte!=0x42)continue;
    if(used==1&&byte!=0x4d){used=(byte==0x42)?1:0;continue;}
    frame[used++]=byte;
    if(used==32){if(decodePM25(frame,32,value))return float(value);used=0;}
  }
  Serial.println("PMS7003 timeout or invalid frame; no reading published");
  return NAN;
}

bool readSensors(float &temperature, float &humidity, float &pm25) {
  temperature = dht.readTemperature();
  humidity = dht.readHumidity();
  pm25 = readPM25();

  // FR-03: reject NaN / out-of-range / invalid frames
  if (isnan(temperature) || isnan(humidity) || isnan(pm25)) {
    Serial.println("Sensor Read Error: NaN value detected");
    return false;
  }
  if (temperature < -40 || temperature > 80) {
    Serial.println("Sensor Read Error: Temperature out of range");
    return false;
  }
  if (humidity < 0 || humidity > 100) {
    Serial.println("Sensor Read Error: Humidity out of range");
    return false;
  }
  if (pm25 < 0 || pm25 > 1000) {
    Serial.println("Sensor Read Error: PM2.5 out of range");
    return false;
  }
  return true;
}

// ---------------------------------------------------------------------------
// Publish (FR-06)
// ---------------------------------------------------------------------------
void publishReading(float temperature, float humidity, float pm25) {
  StaticJsonDocument<256> doc;
  doc["station_id"] = STATION_ID;
  doc["temperature"] = temperature;
  doc["humidity"] = humidity;
  doc["pm25"] = pm25;

  char payload[256];
  size_t len = serializeJson(doc, payload);

  bool ok = mqttClient.publish(mqttTopic, payload, len);
  Serial.print("Publish [");
  Serial.print(mqttTopic);
  Serial.print("]: ");
  Serial.print(payload);
  Serial.println(ok ? "  -> OK" : "  -> FAILED");
}

// ---------------------------------------------------------------------------
// Setup / Loop
// ---------------------------------------------------------------------------
void setup() {
  Serial.begin(115200);
  delay(200);

  snprintf(mqttTopic, sizeof(mqttTopic), "weather/%s/data", STATION_ID);

  dht.begin();
  initPM();
  connectWiFi();

  mqttClient.setServer(MQTT_BROKER, MQTT_PORT);
  connectMQTT();
}

void loop() {
  ensureWiFi();
  ensureMQTT();

  unsigned long now = millis();
  if (now - lastSampleTime >= SAMPLING_INTERVAL_MS) {
    lastSampleTime = now;

    float temperature, humidity, pm25;
    if (readSensors(temperature, humidity, pm25)) {
      publishReading(temperature, humidity, pm25);
    } else {
      // FR-03: do NOT publish incomplete/invalid data
      Serial.println("Skipping publish -- invalid sensor reading");
    }
  }
}
