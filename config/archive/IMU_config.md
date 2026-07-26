# RV IMU Leveling Node (SH1106 OLED & STANAG Compliant)

This document contains the complete, production-ready implementation for an ESP32-S3 node
utilizing a **diymore 10DOF IMU** (LSM303D/L3GD20 sensors) and an **I²C SH1106 1.3" OLED display**.

The node has three independent output paths:

1. **RS-485 Modbus RTU (primary — wired):** Exposes heading, pitch, and roll as holding registers. The J45 polls via the Waveshare gateway exactly as it polls EPEVER, SAMLUX, and KWS-303L. This is the authoritative path for stack integration and Phase 7 sensor fusion.
2. **MQTT over WiFi (secondary — convenience):** Publishes to Mosquitto on the J45 at 1 Hz. HA and Grafana consume this alongside the Modbus path. WiFi loss has zero effect on the Modbus path.
3. **Built-in web page (secondary — convenience):** A self-contained levelling display served directly from the ESP32. Any browser on the RV LAN — phone, tablet, or cab display — can connect without installing an app. Auto-refreshes at 1 Hz via JavaScript fetch.

---

## Network & Programming Architecture

* **RS-485 (`Serial1`):** Modbus RTU slave. Answers FC 03 (Read Holding Registers) from the Waveshare gateway. Slave address: **10** (decimal) — no conflict with existing RVTC bus devices. Baud: **9600 8N1**.
* **WiFi:** Connects to the MikroTik RV LAN. Hosts the web page on port 80 and publishes to Mosquitto. Failure of WiFi or MQTT does not affect the Modbus path in any way.
* **USB (`Serial`):** ESP32-S3 internal USB-Serial-JTAG — independent bidirectional debug/flash channel. Connect a laptop at any time without disturbing RS-485 or WiFi.
* **Coordinate Standard — STANAG:**
  * **Pitch:** Nose Up = Positive (+) / Nose Down = Negative (-)
  * **Roll:** Starboard Down = Positive (+) / Port Down = Negative (-)

---

## Register Map

All values are signed 16-bit integers scaled ×10. Divide by 10.0 to recover degrees.
Always use `mbpoll -0` — consistent with all other RVTC Modbus devices.

| Register (0-based) | Field   | Scale | Range     | Example raw | Decoded |
|--------------------|---------|-------|-----------|-------------|---------|
| 0                  | Heading | ×0.1° | 0–3599   | 2731        | 273.1°  |
| 1                  | Pitch   | ×0.1° | −900–900 | −42         | −4.2°   |
| 2                  | Roll    | ×0.1° | −900–900 | +18         | +1.8°   |

**Verify with mbpoll:**
```bash
mbpoll -m tcp -a 10 -t 4:int16 -r 0 -c 3 -0 192.168.88.XX -p 4001
```

## MQTT Topics

Published at 1 Hz when WiFi and Mosquitto are available. Values are floating-point degrees.

| Topic                        | Value        | Example  |
|------------------------------|--------------|----------|
| `rvtc/sensors/imu/heading`   | degrees      | `273.1`  |
| `rvtc/sensors/imu/pitch`     | degrees      | `-4.2`   |
| `rvtc/sensors/imu/roll`      | degrees      | `1.8`    |
| `rvtc/sensors/imu/status`    | text         | `OK` / `UNCALIBRATED` |

## Web Page

Browse to `http://imu.lan/` (Pi-hole DNS → 192.168.88.20, reserved in MikroTik DHCP). The page
auto-refreshes heading, pitch, and roll every second via a `/api/imu` JSON endpoint on the ESP32.
No app, no dependencies, works in any browser including phone and cab display.

> **NOTE — hard-iron calibration:** Heading output reflects uncalibrated magnetometer atan2 until
> `HARD_IRON_X/Y/Z` constants are populated after the one-time calibration procedure (see end of
> document). Do not use heading for wind direction correction (OI-36) until calibrated. The MQTT
> status topic will publish `UNCALIBRATED` until offsets are set.

---

## Hardware Configuration

### Component Mappings

* **diymore IMU** and **SH1106 OLED** share the I²C bus in parallel.
* **RS-485 transceiver module** connected to Hardware Serial 1. DE/RE driven by Pin 16 for proper half-duplex direction control — allows shared bus expansion if needed.

### Physical Pin Layout

```text
[ESP32-S3]                               [Peripherals]
  3.3V         ------------------------> IMU VCC
  5V / VBUS    ------------------------> SH1106 OLED VCC & RS-485 Converter VCC
  GND          ------------------------> Shared Ground Bus

  Pin 8 (SDA)  ------------------------> Shared I2C SDA (IMU & OLED)
  Pin 9 (SCL)  ------------------------> Shared I2C SCL (IMU & OLED)

  Pin 16       ------------------------> RS-485 Module DE & RE (direction control)
  Pin 17 (TX1) ------------------------> RS-485 Module DI (Data In)
  Pin 18 (RX1) ------------------------> RS-485 Module RO (Data Out)

  Native USB   ------------------------> Bidirectional Laptop (Programming/Debug)
```

---

## Arduino IDE Menu Configuration

* **Board:** `ESP32S3 Dev Module`
* **USB CDC On Boot:** `Enabled` **(CRITICAL)**
* **USB Mode:** `Hardware CDC and JTAG`
* **Upload Mode:** `UART0 / Hardware CDC`

**Required libraries (Library Manager):**
* `Pololu LSM303` — accelerometer + magnetometer
* `U8g2` — SH1106 OLED driver
* `ModbusSlave` by Yaacov Zamir — Modbus RTU slave
* `PubSubClient` by Nick O'Leary — MQTT client
* `ArduinoJson` by Benoît Blanchon — JSON for `/api/imu` endpoint

---

## Production Sketch

```cpp
#include <Arduino.h>
#include <Wire.h>
#include <LSM303.h>
#include <U8g2lib.h>
#include <ModbusSlave.h>
#include <WiFi.h>
#include <WebServer.h>
#include <PubSubClient.h>
#include <ArduinoJson.h>

// =============================================================================
// SITE CONFIGURATION — edit these before flashing
// =============================================================================
const char* WIFI_SSID      = "YOUR_SSID";
const char* WIFI_PASSWORD  = "YOUR_PASSWORD";

// Assign a static IP in MikroTik DHCP for this MAC, then set it here.
// This is the address you browse to: http://192.168.88.YY/
IPAddress WIFI_STATIC_IP(192, 168, 88, 20);   // Reserved in MikroTik DHCP — imu.lan
IPAddress WIFI_GATEWAY(192, 168, 88, 1);
IPAddress WIFI_SUBNET(255, 255, 255, 0);
IPAddress WIFI_DNS(192, 168, 88, 3);           // Pi-hole

const char* MQTT_BROKER    = "192.168.88.3";   // J45 Mosquitto
const int   MQTT_PORT      = 1883;
const char* MQTT_CLIENT_ID = "rvtc-imu-node";

// =============================================================================
// HARD-IRON CALIBRATION OFFSETS
// Must be derived from the figure-eight calibration procedure before heading
// data is trusted for wind direction correction (OI-36). Set all to 0.0 until
// calibration is complete — the MQTT status topic will report UNCALIBRATED.
// =============================================================================
const float HARD_IRON_X = 0.0;   // TODO: populate after calibration
const float HARD_IRON_Y = 0.0;   // TODO: populate after calibration
const float HARD_IRON_Z = 0.0;   // TODO: populate after calibration

// =============================================================================
// RS-485 / Modbus RTU
// =============================================================================
#define RS485_TX_PIN    17
#define RS485_RX_PIN    18
#define RS485_DE_PIN    16
#define MODBUS_SLAVE_ID 10      // No conflict with existing RVTC bus devices
#define MODBUS_BAUD     9600    // Match in Waveshare gateway port serial config

#define REG_HEADING  0
#define REG_PITCH    1
#define REG_ROLL     2
#define REG_COUNT    3

int16_t mb_registers[REG_COUNT] = {0, 0, 0};
Modbus slave(MODBUS_SLAVE_ID, Serial1, RS485_DE_PIN);

// =============================================================================
// IMU, OLED, WiFi, MQTT, Web server
// =============================================================================
LSM303 compass;
U8G2_SH1106_128X64_NONAME_F_HW_I2C u8g2(U8G2_R0, U8X8_PIN_NONE);

WiFiClient   wifiClient;
PubSubClient mqttClient(wifiClient);
WebServer    webServer(80);

// Low-pass filter — 0.1 suits a stationary RV; increase to ~0.3 during
// active levelling if pitch/roll feels sluggish under jack movement.
const float FILTER_FACTOR = 0.1;

float filtered_pitch = 0.0;
float filtered_roll  = 0.0;
float filtered_hdg   = 0.0;

bool calibrated = false;

// Timing
unsigned long lastMqttPublish = 0;
const unsigned long MQTT_INTERVAL_MS = 1000;   // 1 Hz MQTT + web data update

// =============================================================================
// Modbus callback — FC 03 Read Holding Registers
// =============================================================================
uint8_t readHoldingRegisters(uint8_t fc, uint16_t address, uint16_t length) {
  for (uint16_t i = 0; i < length; i++) {
    uint16_t reg = address + i;
    if (reg < REG_COUNT) {
      slave.writeRegisterToBuffer(i, (uint16_t)mb_registers[reg]);
    }
  }
  return STATUS_OK;
}

// =============================================================================
// Web page — served at http://<WIFI_STATIC_IP>/
// Auto-refreshes via JavaScript fetch to /api/imu every 1 second.
// Works in any browser — phone, tablet, or cab display.
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
      background: #1a1a2e;
      color: #eaeaea;
      font-family: 'Courier New', monospace;
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      min-height: 100vh;
      padding: 20px;
    }
    h1 { font-size: 1.4rem; color: #00d4aa; margin-bottom: 24px; letter-spacing: 2px; }
    .grid {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 16px;
      width: 100%;
      max-width: 420px;
    }
    .card {
      background: #16213e;
      border: 1px solid #0f3460;
      border-radius: 10px;
      padding: 18px 12px;
      text-align: center;
    }
    .card.full { grid-column: 1 / -1; }
    .label { font-size: 0.75rem; color: #888; letter-spacing: 1px; margin-bottom: 8px; }
    .value { font-size: 2.2rem; font-weight: bold; color: #00d4aa; }
    .value.warn { color: #ffaa00; }
    .value.alert { color: #ff4444; }
    .unit { font-size: 1rem; color: #aaa; }
    .status-bar {
      margin-top: 20px;
      font-size: 0.7rem;
      color: #555;
    }
    .dot { display: inline-block; width: 8px; height: 8px; border-radius: 50%;
           background: #00d4aa; margin-right: 6px; }
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
    function fmt(val, decimals) {
      return (val >= 0 ? '+' : '') + val.toFixed(decimals);
    }
    async function refresh() {
      try {
        const r = await fetch('/api/imu');
        const d = await r.json();
        document.getElementById('hdg').textContent   = d.heading.toFixed(1) + '°';
        document.getElementById('pitch').textContent = fmt(d.pitch, 2) + '°';
        document.getElementById('roll').textContent  = fmt(d.roll, 2) + '°';
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

// Pitch/roll colour thresholds on the web page:
//   green  = within ±1.5°  (level enough)
//   amber  = ±1.5° – ±3.0° (noticeable tilt)
//   red    = beyond ±3.0°  (needs correction)
// Adjust these in the JavaScript colorClass() call above to suit your preference.

void handleRoot() {
  webServer.send_P(200, "text/html", INDEX_HTML);
}

void handleApiImu() {
  StaticJsonDocument<128> doc;
  doc["heading"]    = filtered_hdg;
  doc["pitch"]      = filtered_pitch;
  doc["roll"]       = filtered_roll;
  doc["calibrated"] = calibrated;
  String json;
  serializeJson(doc, json);
  webServer.send(200, "application/json", json);
}

// =============================================================================
// WiFi connect
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

// =============================================================================
// MQTT reconnect (non-blocking attempt — does not stall the loop)
// =============================================================================
void mqttReconnect() {
  if (WiFi.status() != WL_CONNECTED) return;
  if (mqttClient.connect(MQTT_CLIENT_ID)) {
    Serial.println("MQTT connected");
  }
}

// =============================================================================
// setup
// =============================================================================
void setup() {
  Serial.begin(115200);
  delay(1000);
  Serial.println("--- RVTC IMU NODE BOOT ---");

  // Modbus RTU slave on RS-485
  Serial1.begin(MODBUS_BAUD, SERIAL_8N1, RS485_RX_PIN, RS485_TX_PIN);
  slave.cbVector[CB_READ_HOLDING_REGISTERS] = readHoldingRegisters;
  slave.begin(MODBUS_BAUD);
  Serial.println("Modbus RTU slave online — ID " + String(MODBUS_SLAVE_ID));

  // I2C
  Wire.begin();

  // OLED
  u8g2.begin();

  // IMU
  if (!compass.init()) {
    Serial.println("CRITICAL ERROR: LSM303D failed on I2C!");
    u8g2.clearBuffer();
    u8g2.setFont(u8g2_font_ncenB08_tr);
    u8g2.drawStr(0, 32, "IMU INIT ERROR!");
    u8g2.sendBuffer();
    while (1) { delay(100); }
  }
  compass.enableDefault();
  Serial.println("IMU online.");

  calibrated = !(HARD_IRON_X == 0.0 && HARD_IRON_Y == 0.0 && HARD_IRON_Z == 0.0);
  if (!calibrated) {
    Serial.println("WARNING: Hard-iron offsets are zero — heading is uncalibrated.");
  }

  // WiFi + web server + MQTT (convenience paths — failures do not affect Modbus)
  connectWifi();

  webServer.on("/",        handleRoot);
  webServer.on("/api/imu", handleApiImu);
  webServer.begin();
  Serial.println("Web server started.");

  mqttClient.setServer(MQTT_BROKER, MQTT_PORT);
  mqttReconnect();
}

// =============================================================================
// loop
// =============================================================================
void loop() {
  // --- PRIMARY: Service Modbus requests (non-blocking, always first) ---
  slave.poll();

  // --- SECONDARY: Service web requests ---
  webServer.handleClient();

  // --- SECONDARY: Keep MQTT alive ---
  if (WiFi.status() == WL_CONNECTED) {
    if (!mqttClient.connected()) mqttReconnect();
    mqttClient.loop();
  }

  // --- IMU read and filter (5 Hz) ---
  compass.read();

  float mx = compass.m.x - HARD_IRON_X;
  float my = compass.m.y - HARD_IRON_Y;

  float raw_pitch = atan2((float)compass.a.x,
                          sqrt((float)compass.a.y * compass.a.y +
                               (float)compass.a.z * compass.a.z)) * 180.0 / M_PI;
  float raw_roll  = atan2(-(float)compass.a.y, (float)compass.a.z) * 180.0 / M_PI;
  float raw_hdg   = atan2(my, mx) * 180.0 / M_PI;
  if (raw_hdg < 0) raw_hdg += 360.0;

  filtered_pitch = (raw_pitch * FILTER_FACTOR) + (filtered_pitch * (1.0 - FILTER_FACTOR));
  filtered_roll  = (raw_roll  * FILTER_FACTOR) + (filtered_roll  * (1.0 - FILTER_FACTOR));

  float diff = raw_hdg - filtered_hdg;
  if (diff < -180.0) diff += 360.0;
  if (diff >  180.0) diff -= 360.0;
  filtered_hdg += diff * FILTER_FACTOR;
  if (filtered_hdg <   0.0) filtered_hdg += 360.0;
  if (filtered_hdg >= 360.0) filtered_hdg -= 360.0;

  // Update Modbus registers (5 Hz — always)
  mb_registers[REG_HEADING] = (int16_t)(filtered_hdg   * 10.0);
  mb_registers[REG_PITCH]   = (int16_t)(filtered_pitch * 10.0);
  mb_registers[REG_ROLL]    = (int16_t)(filtered_roll  * 10.0);

  // OLED (5 Hz — always)
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

  // MQTT publish (1 Hz — convenience only)
  unsigned long now = millis();
  if (now - lastMqttPublish >= MQTT_INTERVAL_MS) {
    lastMqttPublish = now;
    if (mqttClient.connected()) {
      mqttClient.publish("rvtc/sensors/imu/heading", String(filtered_hdg,   1).c_str(), true);
      mqttClient.publish("rvtc/sensors/imu/pitch",   String(filtered_pitch, 2).c_str(), true);
      mqttClient.publish("rvtc/sensors/imu/roll",    String(filtered_roll,  2).c_str(), true);
      mqttClient.publish("rvtc/sensors/imu/status",
                         calibrated ? "OK" : "UNCALIBRATED", true);
    }
  }

  // USB debug (when terminal connected)
  if (Serial) {
    Serial.printf("[IMU] Hdg: %0.1f° Pitch: %+0.2f° Roll: %+0.2f° | Regs: [%d,%d,%d]\n",
                  filtered_hdg, filtered_pitch, filtered_roll,
                  mb_registers[0], mb_registers[1], mb_registers[2]);
  }

  delay(200);   // 5 Hz
}
```

---

## Hard-Iron Calibration Procedure

Before heading data is used for wind direction correction (OI-36), a one-time hard-iron
calibration must be performed. Raw atan2 heading will carry a consistent fixed offset due to
the RV steel chassis — the compass-boxing technique documented in Section 2.7 applies only
*after* calibration constants are derived.

1. Mount the IMU node in its permanent position.
2. With USB connected, log raw `compass.m.x / .y / .z` to Serial while rotating the RV
   through a full 360° (or figure-eight if full rotation is impractical).
3. Run the calibration Python script against the log: `offset = (max + min) / 2` per axis.
4. Populate `HARD_IRON_X/Y/Z` and reflash.
5. Verify corrected heading against a known reference bearing.
6. The MQTT `rvtc/sensors/imu/status` topic will change from `UNCALIBRATED` to `OK`.

Constants hold indefinitely as long as mounting position does not change.

---

## Gateway Port Configuration

Configure the Waveshare gateway port assigned to this node:

| Parameter   | Value              |
|-------------|--------------------|
| Mode        | TCP Server         |
| Protocol    | Modbus TCP ↔ RTU  |
| Baud        | 9600               |
| Data bits   | 8                  |
| Parity      | None               |
| Stop bits   | 1                  |
| TCP port    | 4001               |

Assign a gateway port and static IP in MikroTik DHCP, then update Section 2.6 of the
RVTC Project Reference accordingly.
