/*
 * RVTC IMU Node — heading/pitch/roll/bounce for wind-direction true-north
 * correction (OI-36) and a live "how much is the trailer bouncing" phone page.
 *
 * Deliberate exception to the project's RS-485-for-everything convention:
 * this node talks WiFi + MQTT directly (no RS-485/gateway hop) because the
 * data is real-time-only and never persisted to InfluxDB — nothing here
 * needs a query-able history, so the extra hop would add complexity for no
 * benefit. Documented in the reference doc as an intentional exception, not
 * an oversight.
 *
 * Hardware: NodeMCU ESP32-WROOM-32, Adafruit 10-DOF (LSM303DLHC + L3GD20 +
 * BMP180), 1.3" I2C OLED (SH1106 driver — 1.3" modules are SH1106 the vast
 * majority of the time, NOT the more common SSD1306 used on 0.96" modules;
 * wrong driver = shifted/garbled display, not blank, so it's worth getting
 * right up front rather than debugging a "broken" screen that's actually
 * just using the wrong driver).
 *
 * I2C wiring (default ESP32 pins): SDA -> GPIO21, SCL -> GPIO22.
 * Both the 10-DOF board and the OLED share this same I2C bus.
 */

#include <Wire.h>
#include <WiFi.h>
#include <PubSubClient.h>
#include <ESPAsyncWebServer.h>
#include <ArduinoJson.h>

#include <Adafruit_Sensor.h>
#include <Adafruit_LSM303_U.h>
#include <Adafruit_L3GD20_U.h>
#include <Adafruit_BMP085_U.h>
#include <Adafruit_10DOF.h>

#include <Adafruit_GFX.h>
#include <Adafruit_SH110X.h>

// ── Config ──────────────────────────────────────────────────────────────
const char* WIFI_SSID     = "YOUR_WIFI_SSID";
const char* WIFI_PASSWORD = "YOUR_WIFI_PASSWORD";

const char* MQTT_HOST = "192.168.88.3";   // RVTC unified Mosquitto broker, no auth
const uint16_t MQTT_PORT = 1883;
const char* MQTT_CLIENT_ID = "rvtc-imu";
const char* TOPIC_BASE = "rvtc/sensors/imu";
const char* TOPIC_AVAILABILITY = "rvtc/sensors/imu/availability";

const uint32_t MQTT_PUBLISH_INTERVAL_MS = 250;  // real-time only, nothing persisted
const uint32_t SENSOR_READ_INTERVAL_MS  = 50;   // ~20Hz internal sample rate

// Bounce/"heave" window: peak-to-peak vertical accel over this many samples.
// NOT true integrated heave (meters) — a raw accelerometer drifts too badly
// to integrate displacement cleanly. This is a bounce-intensity proxy:
// "how rough is it right now," not a position measurement.
const int HEAVE_WINDOW_SAMPLES = 40;  // ~2s at the 50ms sample interval

// ── Globals ─────────────────────────────────────────────────────────────
Adafruit_10DOF                dof;
Adafruit_LSM303_Accel_Unified accel(30301);
Adafruit_LSM303_Mag_Unified   mag(30302);
Adafruit_BMP085_Unified       bmp(18001);
// L3GD20 gyro is read but not currently used in the pitch/roll/heading math
// below (Adafruit's helper functions derive orientation from accel+mag
// alone) — wired up for future use if a complementary filter is added later.
Adafruit_L3GD20_Unified       gyro(20);

Adafruit_SH1106G display = Adafruit_SH1106G(128, 64, &Wire, -1);

WiFiClient   wifiClient;
PubSubClient mqttClient(wifiClient);
AsyncWebServer server(80);

float g_heading = 0, g_pitch = 0, g_roll = 0, g_heave = 0;
float heaveBuffer[HEAVE_WINDOW_SAMPLES];
int   heaveIndex = 0;
bool  heaveBufferFull = false;

uint32_t lastSensorRead = 0;
uint32_t lastMqttPublish = 0;

// ── Self-hosted phone page — no external CDN references (offline-first
// requirement, DD-04): fonts/CSS/JS are all inline, nothing fetched from
// the internet, so this works with zero connectivity beyond the ESP32's
// own WiFi. ──────────────────────────────────────────────────────────────
const char INDEX_HTML[] PROGMEM = R"HTML(
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>RVTC IMU</title>
<style>
  body { background:#0d1117; color:#e6edf3; font-family:-apple-system,Helvetica,Arial,sans-serif;
         margin:0; padding:20px; }
  h1 { font-size:1.1rem; color:#8b949e; font-weight:normal; margin-bottom:20px; }
  .grid { display:grid; grid-template-columns:1fr 1fr; gap:16px; }
  .card { background:#161b22; border:1px solid #30363d; border-radius:10px; padding:20px;
          text-align:center; }
  .label { color:#8b949e; font-size:0.85rem; text-transform:uppercase; letter-spacing:0.05em; }
  .value { font-size:2.5rem; font-weight:600; margin-top:6px; }
  .hdg   { color:#58a6ff; }
  .pitch { color:#3fb950; }
  .roll  { color:#d29922; }
  .heave { color:#f85149; }
  .unit  { font-size:1.2rem; color:#8b949e; }
  .status { text-align:center; margin-top:16px; font-size:0.8rem; color:#8b949e; }
</style>
</head>
<body>
  <h1>RVTC &mdash; IMU (heading / attitude / bounce)</h1>
  <div class="grid">
    <div class="card"><div class="label">Heading</div>
      <div class="value hdg" id="hdg">&mdash;<span class="unit">&deg;</span></div></div>
    <div class="card"><div class="label">Pitch</div>
      <div class="value pitch" id="pitch">&mdash;<span class="unit">&deg;</span></div></div>
    <div class="card"><div class="label">Roll</div>
      <div class="value roll" id="roll">&mdash;<span class="unit">&deg;</span></div></div>
    <div class="card"><div class="label">Bounce (2s p-p)</div>
      <div class="value heave" id="heave">&mdash;<span class="unit">g</span></div></div>
  </div>
  <div class="status" id="status">connecting&hellip;</div>
<script>
async function poll() {
  try {
    const r = await fetch('/data');
    const d = await r.json();
    document.getElementById('hdg').innerHTML   = d.heading.toFixed(0) + '<span class="unit">&deg;</span>';
    document.getElementById('pitch').innerHTML = d.pitch.toFixed(1)   + '<span class="unit">&deg;</span>';
    document.getElementById('roll').innerHTML  = d.roll.toFixed(1)    + '<span class="unit">&deg;</span>';
    document.getElementById('heave').innerHTML = d.heave.toFixed(2)   + '<span class="unit">g</span>';
    document.getElementById('status').textContent = 'live';
  } catch (e) {
    document.getElementById('status').textContent = 'connection lost, retrying...';
  }
}
setInterval(poll, 250);
poll();
</script>
</body>
</html>
)HTML";

// ── WiFi / MQTT ─────────────────────────────────────────────────────────
void connectWiFi() {
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  Serial.print("Connecting to WiFi");
  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
  }
  Serial.println();
  Serial.print("WiFi connected, IP: ");
  Serial.println(WiFi.localIP());
}

void connectMqtt() {
  while (!mqttClient.connected()) {
    Serial.print("Connecting to MQTT...");
    // Last-will marks us offline if power/wifi drops ungracefully — same
    // availability-topic pattern used by gps_mqtt.py and rtl_433 elsewhere
    // in the project.
    if (mqttClient.connect(MQTT_CLIENT_ID, TOPIC_AVAILABILITY, 0, true, "offline")) {
      Serial.println("connected");
      mqttClient.publish(TOPIC_AVAILABILITY, "online", true);
    } else {
      Serial.print("failed, rc=");
      Serial.print(mqttClient.state());
      Serial.println(" retrying in 2s");
      delay(2000);
    }
  }
}

void publishFloat(const char* field, float value) {
  char topic[64];
  char payload[16];
  snprintf(topic, sizeof(topic), "%s/%s", TOPIC_BASE, field);
  snprintf(payload, sizeof(payload), "%.2f", value);
  mqttClient.publish(topic, payload);
}

// ── Sensor read + orientation math (reuses Adafruit's own proven
// pitchrollheading example logic — no point reinventing tilt-compensated
// heading math when a working reference implementation ships with the
// library itself). ──────────────────────────────────────────────────────
void readSensors() {
  sensors_event_t accel_event, mag_event;
  sensors_vec_t orientation;

  accel.getEvent(&accel_event);
  if (dof.accelGetOrientation(&accel_event, &orientation)) {
    g_pitch = orientation.pitch;
    g_roll  = orientation.roll;
  }

  mag.getEvent(&mag_event);
  if (dof.magTiltCompensation(SENSOR_AXIS_Z, &mag_event, &accel_event)) {
    if (dof.magGetOrientation(SENSOR_AXIS_Z, &mag_event, &orientation)) {
      g_heading = orientation.heading;
    }
  }

  // Bounce proxy: gravity-compensated vertical (Z) acceleration, tracked
  // as a rolling peak-to-peak over the last ~2s. This is NOT integrated
  // displacement — see the header comment on HEAVE_WINDOW_SAMPLES.
  float verticalAccel = accel_event.acceleration.z - SENSORS_GRAVITY_EARTH;
  heaveBuffer[heaveIndex] = verticalAccel;
  heaveIndex = (heaveIndex + 1) % HEAVE_WINDOW_SAMPLES;
  if (heaveIndex == 0) heaveBufferFull = true;

  int samples = heaveBufferFull ? HEAVE_WINDOW_SAMPLES : heaveIndex;
  if (samples > 1) {
    float minV = heaveBuffer[0], maxV = heaveBuffer[0];
    for (int i = 1; i < samples; i++) {
      if (heaveBuffer[i] < minV) minV = heaveBuffer[i];
      if (heaveBuffer[i] > maxV) maxV = heaveBuffer[i];
    }
    g_heave = (maxV - minV) / SENSORS_GRAVITY_EARTH;  // in g
  }
}

void updateOled() {
  display.clearDisplay();
  display.setTextSize(1);
  display.setTextColor(SH110X_WHITE);
  display.setCursor(0, 0);
  display.printf("HDG   %.0f deg\n", g_heading);
  display.printf("PITCH %.1f deg\n", g_pitch);
  display.printf("ROLL  %.1f deg\n", g_roll);
  display.printf("BOUNCE %.2f g\n", g_heave);
  display.display();
}

// ── Setup ───────────────────────────────────────────────────────────────
void setup() {
  Serial.begin(115200);
  Wire.begin();  // SDA=21, SCL=22 (ESP32 defaults)

  if (!accel.begin()) Serial.println("ERROR: LSM303 accelerometer not detected");
  if (!mag.begin())   Serial.println("ERROR: LSM303 magnetometer not detected");
  if (!bmp.begin())   Serial.println("ERROR: BMP180 not detected");
  if (!gyro.begin())  Serial.println("ERROR: L3GD20 gyroscope not detected");

  if (!display.begin(0x3C, true)) {
    Serial.println("ERROR: SH1106 OLED not detected at 0x3C");
  } else {
    display.clearDisplay();
    display.setTextSize(1);
    display.setTextColor(SH110X_WHITE);
    display.setCursor(0, 0);
    display.println("RVTC IMU");
    display.println("starting...");
    display.display();
  }

  connectWiFi();

  mqttClient.setServer(MQTT_HOST, MQTT_PORT);
  connectMqtt();

  server.on("/", HTTP_GET, [](AsyncWebServerRequest *request) {
    request->send_P(200, "text/html", INDEX_HTML);
  });

  server.on("/data", HTTP_GET, [](AsyncWebServerRequest *request) {
    JsonDocument doc;
    doc["heading"] = g_heading;
    doc["pitch"]   = g_pitch;
    doc["roll"]    = g_roll;
    doc["heave"]   = g_heave;
    String json;
    serializeJson(doc, json);
    request->send(200, "application/json", json);
  });

  server.begin();
  Serial.println("Web server started");
}

// ── Loop ────────────────────────────────────────────────────────────────
void loop() {
  if (WiFi.status() != WL_CONNECTED) connectWiFi();
  if (!mqttClient.connected()) connectMqtt();
  mqttClient.loop();

  uint32_t now = millis();

  if (now - lastSensorRead >= SENSOR_READ_INTERVAL_MS) {
    lastSensorRead = now;
    readSensors();
    updateOled();
  }

  if (now - lastMqttPublish >= MQTT_PUBLISH_INTERVAL_MS) {
    lastMqttPublish = now;
    publishFloat("heading", g_heading);
    publishFloat("pitch", g_pitch);
    publishFloat("roll", g_roll);
    publishFloat("heave", g_heave);
  }
}
