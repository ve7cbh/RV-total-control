/*
 * RVTC IMU Leveling Node (HW-25)
 *
 * THREE independent output paths, in priority order:
 *   1. RS-485 Modbus RTU (PRIMARY) — answers FC03 Read Holding Registers when
 *      polled by the Waveshare gateway, exactly like EPEVER/SAMLUX/KWS-303L.
 *      Dedicated gateway port RS-485/4 (192.168.88.8:4001), NOT a shared/
 *      multi-drop line — confirmed 2026-07-09 against the live gateway
 *      addressing table (an earlier draft of this comment incorrectly
 *      assumed all 8 ports were full and planned to multi-drop onto the
 *      EPEVER/MT50 line; that was wrong — RS-485/4 was already reserved for
 *      this device). Authoritative path for Phase 7 sensor fusion and
 *      wind-direction correction (OI-36).
 *   2. MQTT over WiFi (secondary/convenience) — publishes the same
 *      heading/pitch/roll at 1Hz, plus a bonus `heave` field NOT in the
 *      Modbus register map (see note below). WiFi/MQTT loss has zero effect
 *      on the Modbus path.
 *   3. Local web page (secondary/convenience) — self-contained leveling
 *      display at this node's own IP, auto-refreshing via /api/imu.
 *
 * Hardware actually on the bench (adapted from an earlier draft of this doc
 * that assumed an ESP32-S3 + diymore LSM303D board):
 *   - Plain ESP32-WROOM-32 DevKit (NOT S3 — no native USB-CDC, standard
 *     UART-bridge programming, different usable GPIO set)
 *   - Adafruit 10-DOF breakout: LSM303DLHC (accel+mag) + L3GD20 (gyro) +
 *     BMP180 (baro, not currently used) — same sensor family as the
 *     diymore board, different specific chip variant, hence Adafruit's own
 *     libraries + proven tilt-compensated orientation math instead of the
 *     Pololu LSM303 driver the S3 draft used.
 *   - 1.3" I2C OLED — SH1106 driver (1.3" modules are SH1106 the vast
 *     majority of the time, not the SSD1306 used on 0.96" modules).
 *
 * "Heave" is a bounce-INTENSITY proxy, not true integrated displacement — a
 * raw MEMS accelerometer drifts too badly to integrate cleanly into real
 * heave-in-meters. Kept as MQTT-only (not in the Modbus register map, which
 * mirrors this node's other RVTC bus peers) per 2026-07-09 discussion —
 * candidate for later fusion with GPS altitude data (Phase 7) if the simple
 * accelerometer approach doesn't hold up well enough on its own.
 */

#include <Arduino.h>
#include <Wire.h>
#include <WiFi.h>
#include <WebServer.h>
#include <PubSubClient.h>
#include <ArduinoJson.h>
#include <ModbusSlave.h>

#include <Adafruit_Sensor.h>
#include <Adafruit_LSM303_U.h>
#include <Adafruit_L3GD20_U.h>
#include <Adafruit_BMP085_U.h>
#include <Adafruit_10DOF.h>

#include <U8g2lib.h>

// =============================================================================
// SITE CONFIGURATION — edit before flashing
// =============================================================================
const char* WIFI_SSID     = "VE7CBH_Mikrotik";
const char* WIFI_PASSWORD = "2511670E4400";

// .20 was the doc's original suggestion but collides with the Brother
// printer's existing DHCP reservation — .13 is the next free address outside
// the .1-.12 (router/gateways) and .20-.24 (printer/phones) ranges, but
// VERIFY against the live MikroTik DHCP lease list before reserving it —
// this wasn't cross-checked against anything added since the printer
// discovery.
IPAddress WIFI_STATIC_IP(192, 168, 88, 13);
IPAddress WIFI_GATEWAY(192, 168, 88, 1);
IPAddress WIFI_SUBNET(255, 255, 255, 0);
IPAddress WIFI_DNS(192, 168, 88, 3);   // Pi-hole

const char* MQTT_BROKER    = "192.168.88.3";
const int   MQTT_PORT      = 1883;
const char* MQTT_CLIENT_ID = "rvtc-imu-node";

// =============================================================================
// HARD-IRON CALIBRATION OFFSETS — populate after the one-time figure-eight
// calibration procedure, done with the unit mounted in its FINAL position
// (mounting location affects magnetic interference). Until populated, the
// MQTT status topic reports UNCALIBRATED and heading should not be trusted
// for wind-direction correction (OI-36).
// =============================================================================
const float HARD_IRON_X = 0.0;   // TODO: populate after calibration
const float HARD_IRON_Y = 0.0;   // TODO: populate after calibration
const float HARD_IRON_Z = 0.0;   // TODO: populate after calibration

// =============================================================================
// RS-485 / Modbus RTU — PRIMARY path
// Pin choice for a plain ESP32-WROOM-32 DevKit (not S3): GPIO16/17 are NOT
// broken out on narrower 30-pin DevKit boards (only the wider 38-pin variant
// exposes them) — confirmed 2026-07-09 against the actual board in hand.
// GPIO18/19 used instead: safe general-purpose pins present on both 30-pin
// and 38-pin variants, not strapping pins, not flash pins, not shared with
// I2C (21/22). ESP32's UART peripheral routes through an internal GPIO
// matrix, so it isn't pinned to fixed hardware pins the way some MCUs are —
// any free GPIO works for RX/TX, this was purely about picking one that's
// actually present on your specific board.
// =============================================================================
#define RS485_RX_PIN    18
#define RS485_TX_PIN    19
#define RS485_DE_PIN    4
#define MODBUS_SLAVE_ID 10      // Dedicated line (RS-485/4) — no other device
                                 // to collide with, ID choice is arbitrary here
#define MODBUS_BAUD     9600    // Match the Waveshare gateway port's serial config
                                 // (RS-485/4, 192.168.88.8:4001)

#define REG_HEADING  0
#define REG_PITCH    1
#define REG_ROLL     2
#define REG_COUNT    3

int16_t mb_registers[REG_COUNT] = {0, 0, 0};
Modbus slave(Serial1, MODBUS_SLAVE_ID, RS485_DE_PIN);

// =============================================================================
// Sensors (Adafruit 10-DOF stack — matches the actual bench hardware)
// =============================================================================
Adafruit_10DOF                dof;
Adafruit_LSM303_Accel_Unified accel(30301);
Adafruit_LSM303_Mag_Unified   mag(30302);
Adafruit_BMP085_Unified       bmp(18001);   // present, not currently used
Adafruit_L3GD20_Unified       gyro(20);     // present, not currently used

U8G2_SH1106_128X64_NONAME_F_HW_I2C u8g2(U8G2_R0, U8X8_PIN_NONE);

WiFiClient   wifiClient;
PubSubClient mqttClient(wifiClient);
WebServer    webServer(80);

// Low-pass filter — 0.1 suits a stationary RV being leveled; increase toward
// ~0.3 if pitch/roll feels too sluggish while actively jacking up/down.
const float FILTER_FACTOR = 0.1;

float filtered_pitch = 0.0;
float filtered_roll  = 0.0;
float filtered_hdg   = 0.0;
float heave_g        = 0.0;

bool calibrated = false;

// Heave: rolling peak-to-peak of gravity-compensated vertical accel, ~2s window
const int HEAVE_WINDOW_SAMPLES = 40;  // ~2s at the 50ms sensor-read interval
float heaveBuffer[HEAVE_WINDOW_SAMPLES];
int   heaveIndex = 0;
bool  heaveBufferFull = false;

unsigned long lastMqttPublish = 0;
const unsigned long MQTT_INTERVAL_MS = 1000;   // 1Hz, convenience only

// =============================================================================
// Modbus callback — FC 03 Read Holding Registers
// =============================================================================
uint8_t readHoldingRegisters(uint8_t fc, uint16_t address, uint16_t length, void *callbackContext) {
  Serial.printf("Modbus request received: fc=%d address=%d length=%d\n", fc, address, length);
  for (uint16_t i = 0; i < length; i++) {
    uint16_t reg = address + i;
    if (reg < REG_COUNT) {
      slave.writeRegisterToBuffer(i, (uint16_t)mb_registers[reg]);
    }
  }
  return STATUS_OK;
}

// =============================================================================
// Web page — self-contained, no external CDN references (offline-first
// requirement for .lan pages). Adds a Bounce card on top of the original
// leveling-only layout, since heave was kept as a bonus MQTT field.
// =============================================================================
const char INDEX_HTML[] PROGMEM = R"rawliteral(
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>RVTC Leveling</title>
  <style>
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      background: #1a1a2e; color: #eaeaea; font-family: 'Courier New', monospace;
      display: flex; flex-direction: column; align-items: center; justify-content: center;
      min-height: 100vh; padding: 20px;
    }
    h1 { font-size: 1.4rem; color: #00d4aa; margin-bottom: 24px; letter-spacing: 2px; }
    .grid { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; width: 100%; max-width: 420px; }
    .card { background: #16213e; border: 1px solid #0f3460; border-radius: 10px; padding: 18px 12px; text-align: center; }
    .card.full { grid-column: 1 / -1; }
    .label { font-size: 0.75rem; color: #888; letter-spacing: 1px; margin-bottom: 8px; }
    .value { font-size: 2.2rem; font-weight: bold; color: #00d4aa; }
    .value.warn { color: #ffaa00; }
    .value.alert { color: #ff4444; }
    .unit { font-size: 1rem; color: #aaa; }
    .status-bar { margin-top: 20px; font-size: 0.7rem; color: #555; }
    .dot { display: inline-block; width: 8px; height: 8px; border-radius: 50%; background: #00d4aa; margin-right: 6px; }
    .dot.warn { background: #ffaa00; }
  </style>
</head>
<body>
  <h1>&#9654; RVTC LEVELING</h1>
  <div class="grid">
    <div class="card full">
      <div class="label">HEADING</div>
      <div class="value" id="hdg">---</div>
      <div class="unit">degrees magnetic</div>
    </div>
    <div class="card">
      <div class="label">PITCH</div>
      <div class="value" id="pitch">---</div>
      <div class="unit">nose up (+)</div>
    </div>
    <div class="card">
      <div class="label">ROLL</div>
      <div class="value" id="roll">---</div>
      <div class="unit">stbd down (+)</div>
    </div>
    <div class="card full">
      <div class="label">BOUNCE (2s peak-to-peak)</div>
      <div class="value" id="heave">---</div>
      <div class="unit">g &mdash; intensity proxy, not true heave</div>
    </div>
  </div>
  <div class="status-bar">
    <span class="dot" id="dot"></span>
    <span id="status-text">connecting...</span>
  </div>
  <script>
    function colorClass(val, warnDeg, alertDeg) {
      const abs = Math.abs(val);
      if (abs >= alertDeg) return 'alert';
      if (abs >= warnDeg)  return 'warn';
      return '';
    }
    function fmt(val, decimals) { return (val >= 0 ? '+' : '') + val.toFixed(decimals); }
    async function refresh() {
      try {
        const r = await fetch('/api/imu');
        const d = await r.json();
        document.getElementById('hdg').textContent   = d.heading.toFixed(1) + '°';
        document.getElementById('pitch').textContent = fmt(d.pitch, 2) + '°';
        document.getElementById('roll').textContent  = fmt(d.roll, 2) + '°';
        document.getElementById('heave').textContent = d.heave.toFixed(2) + ' g';
        document.getElementById('pitch').className = 'value ' + colorClass(d.pitch, 1.5, 3.0);
        document.getElementById('roll').className  = 'value ' + colorClass(d.roll,  1.5, 3.0);
        document.getElementById('dot').className = 'dot' + (d.calibrated ? '' : ' warn');
        document.getElementById('status-text').textContent =
          d.calibrated ? 'live' : 'live — heading uncalibrated';
      } catch(e) {
        document.getElementById('status-text').textContent = 'connection lost';
        document.getElementById('dot').className = 'dot warn';
      }
    }
    refresh();
    setInterval(refresh, 1000);
  </script>
</body>
</html>
)rawliteral";
// Pitch/roll colour thresholds: green within ±1.5° (level enough),
// amber ±1.5°-±3.0° (noticeable tilt), red beyond ±3.0° (needs correction).

void handleRoot() {
  webServer.send_P(200, "text/html", INDEX_HTML);
}

void handleApiImu() {
  JsonDocument doc;
  doc["heading"]    = filtered_hdg;
  doc["pitch"]      = filtered_pitch;
  doc["roll"]       = filtered_roll;
  doc["heave"]      = heave_g;
  doc["calibrated"] = calibrated;
  String json;
  serializeJson(doc, json);
  webServer.send(200, "application/json", json);
}

// =============================================================================
// WiFi / MQTT (secondary paths — failures never touch the Modbus path)
// =============================================================================
void connectWifi() {
  WiFi.config(WIFI_STATIC_IP, WIFI_GATEWAY, WIFI_SUBNET, WIFI_DNS);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  Serial.print("WiFi connecting");
  int attempts = 0;
  while (WiFi.status() != WL_CONNECTED && attempts < 20) {
    delay(500);
    Serial.print(".");
    attempts++;
  }
  if (WiFi.status() == WL_CONNECTED) {
    Serial.println("\nWiFi connected: " + WiFi.localIP().toString());
  } else {
    Serial.println("\nWiFi failed — continuing without network. Modbus unaffected.");
  }
}

void mqttReconnect() {
  if (WiFi.status() != WL_CONNECTED) return;
  if (mqttClient.connect(MQTT_CLIENT_ID)) {
    Serial.println("MQTT connected");
  }
}

// =============================================================================
// Setup
// =============================================================================
void setup() {
  Serial.begin(115200);
  delay(1000);
  Serial.println("--- RVTC IMU NODE BOOT ---");

  // RS-485 Modbus RTU slave — PRIMARY, brought up first
  Serial1.begin(MODBUS_BAUD, SERIAL_8N1, RS485_RX_PIN, RS485_TX_PIN);
  slave.cbVector[CB_READ_HOLDING_REGISTERS] = readHoldingRegisters;
  slave.begin(MODBUS_BAUD);
  Serial.println("Modbus RTU slave online — ID " + String(MODBUS_SLAVE_ID));

  Wire.begin();  // SDA=21, SCL=22 (ESP32 defaults) — shared by IMU + OLED

  // OLED address: confirmed via I2C scanner (2026-07-10, bench test) to be
  // the standard default 0x3C, NOT 0x3D as the silkscreen decode earlier
  // suggested — that decode was simply wrong, or this board's actual
  // strapping doesn't match what's printed on it. No setI2CAddress() call
  // needed; 0x3C is U8g2's own default.
  if (!u8g2.begin()) {
    Serial.println("WARNING: SH1106 OLED not detected — check wiring; expected at default address 0x3C");
  } else {
    Serial.println("SH1106 OLED initialized OK at address 0x3C");
  }

  if (!accel.begin() || !mag.begin()) {
    Serial.println("CRITICAL ERROR: LSM303DLHC failed on I2C!");
    u8g2.clearBuffer();
    u8g2.setFont(u8g2_font_ncenB08_tr);
    u8g2.drawStr(0, 32, "IMU INIT ERROR!");
    u8g2.sendBuffer();
    // Deliberately NOT halting here (unlike the earlier S3 draft) — Modbus
    // should keep answering even if the IMU itself is faulted, so a bad
    // sensor doesn't also take down bus communication for whatever's
    // polling it.
  }
  if (!bmp.begin())  Serial.println("NOTE: BMP180 not detected (not currently used)");
  if (!gyro.begin()) Serial.println("NOTE: L3GD20 not detected (not currently used)");

  calibrated = !(HARD_IRON_X == 0.0 && HARD_IRON_Y == 0.0 && HARD_IRON_Z == 0.0);
  if (!calibrated) {
    Serial.println("WARNING: Hard-iron offsets are zero — heading is uncalibrated.");
  }

  connectWifi();

  webServer.on("/",        handleRoot);
  webServer.on("/api/imu", handleApiImu);
  webServer.begin();
  Serial.println("Web server started.");

  mqttClient.setServer(MQTT_BROKER, MQTT_PORT);
  mqttReconnect();
}

// =============================================================================
// Loop
// =============================================================================
void loop() {
  // --- PRIMARY: service Modbus requests first, always ---
  slave.poll();

  // --- SECONDARY: web + MQTT ---
  webServer.handleClient();
  if (WiFi.status() == WL_CONNECTED) {
    if (!mqttClient.connected()) mqttReconnect();
    mqttClient.loop();
  }

  // --- Sensor read + tilt-compensated orientation (Adafruit's own proven
  //     math from their pitchrollheading example — not reinvented) ---
  sensors_event_t accel_event, mag_event;
  sensors_vec_t orientation;

  accel.getEvent(&accel_event);
  float raw_pitch = filtered_pitch, raw_roll = filtered_roll;
  if (dof.accelGetOrientation(&accel_event, &orientation)) {
    raw_pitch = orientation.pitch;
    raw_roll  = orientation.roll;
  }

  mag.getEvent(&mag_event);
  mag_event.magnetic.x -= HARD_IRON_X;
  mag_event.magnetic.y -= HARD_IRON_Y;
  mag_event.magnetic.z -= HARD_IRON_Z;
  float raw_hdg = filtered_hdg;
  if (dof.magTiltCompensation(SENSOR_AXIS_Z, &mag_event, &accel_event)) {
    if (dof.magGetOrientation(SENSOR_AXIS_Z, &mag_event, &orientation)) {
      raw_hdg = orientation.heading;
    }
  }

  filtered_pitch = (raw_pitch * FILTER_FACTOR) + (filtered_pitch * (1.0 - FILTER_FACTOR));
  filtered_roll  = (raw_roll  * FILTER_FACTOR) + (filtered_roll  * (1.0 - FILTER_FACTOR));

  float diff = raw_hdg - filtered_hdg;
  if (diff < -180.0) diff += 360.0;
  if (diff >  180.0) diff -= 360.0;
  filtered_hdg += diff * FILTER_FACTOR;
  if (filtered_hdg <   0.0) filtered_hdg += 360.0;
  if (filtered_hdg >= 360.0) filtered_hdg -= 360.0;

  // Heave/bounce proxy — MQTT-only, not in the Modbus register map
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
    heave_g = (maxV - minV) / SENSORS_GRAVITY_EARTH;
  }

  // Modbus registers — PRIMARY, always updated regardless of WiFi/MQTT state
  mb_registers[REG_HEADING] = (int16_t)(filtered_hdg   * 10.0);
  mb_registers[REG_PITCH]   = (int16_t)(filtered_pitch * 10.0);
  mb_registers[REG_ROLL]    = (int16_t)(filtered_roll  * 10.0);

  // OLED
  u8g2.clearBuffer();
  u8g2.setFont(u8g2_font_profont15_mf);
  u8g2.drawStr(0, 15, "HEADING:");
  u8g2.setCursor(75, 15);
  u8g2.print(filtered_hdg, 1);
  u8g2.print(char(176));
  u8g2.drawStr(0, 35, "PITCH:");
  u8g2.setCursor(75, 35);
  if (filtered_pitch > 0) u8g2.print("+");
  u8g2.print(filtered_pitch, 2);
  u8g2.print(char(176));
  u8g2.drawStr(0, 55, "ROLL:");
  u8g2.setCursor(75, 55);
  if (filtered_roll > 0) u8g2.print("+");
  u8g2.print(filtered_roll, 2);
  u8g2.print(char(176));
  u8g2.sendBuffer();

  // MQTT publish — 1Hz, convenience only
  unsigned long now = millis();
  if (now - lastMqttPublish >= MQTT_INTERVAL_MS) {
    lastMqttPublish = now;
    if (mqttClient.connected()) {
      mqttClient.publish("rvtc/sensors/imu/heading", String(filtered_hdg,   1).c_str(), true);
      mqttClient.publish("rvtc/sensors/imu/pitch",   String(filtered_pitch, 2).c_str(), true);
      mqttClient.publish("rvtc/sensors/imu/roll",    String(filtered_roll,  2).c_str(), true);
      mqttClient.publish("rvtc/sensors/imu/heave",   String(heave_g,        2).c_str(), true);
      mqttClient.publish("rvtc/sensors/imu/status",
                          calibrated ? "OK" : "UNCALIBRATED", true);
    }
  }

  if (Serial) {
    Serial.printf("[IMU] Hdg: %0.1f  Pitch: %+0.2f  Roll: %+0.2f  Heave: %0.2fg | Regs: [%d,%d,%d]\n",
                  filtered_hdg, filtered_pitch, filtered_roll, heave_g,
                  mb_registers[0], mb_registers[1], mb_registers[2]);
  }

  delay(200);   // ~5Hz sensor loop
}
