/*
 * rvtc_tank_level_fdc1004.ino — RVTC Holding Tank Level Sensor
 *
 * One ESP32 + one ProtoCentral FDC1004 breakout board per tank — deliberately
 * NOT sharing a single I2C bus across boards. The FDC1004 has a single fixed
 * I2C address (0x50, no address-select pin), so multiple boards cannot share
 * one bus without an external I2C multiplexer — and even with a mux, the
 * datasheet is explicit that CINn sensing leads must stay short and shielded,
 * which a centrally-mounted board can't achieve for tanks scattered around
 * the RV. Four independent nodes solves both problems: no address collision,
 * and each board sits right at its own tank with a short sensing lead.
 *
 * Library: Protocentral_FDC1004 (https://github.com/Protocentral/ProtoCentral_fdc1004_breakout)
 * Install via Arduino Library Manager: "Protocentral FDC1004"
 * Also requires: PubSubClient (MQTT) — install via Library Manager
 *
 * TO FLASH A NEW NODE: change TANK_NAME below, nothing else.
 *
 * Wiring (per node):
 *   ESP32 SDA -> FDC1004 SDA
 *   ESP32 SCL -> FDC1004 SCL
 *   ESP32 3V3 -> FDC1004 VCC (board has onboard regulator, 5V tolerant too)
 *   ESP32 GND -> FDC1004 GND
 *   Tank probe/electrode -> FDC1004 CIN1 (single-ended; SHLD1/SHLD2 are
 *     internally shorted together automatically in this mode — no extra
 *     shield wiring needed unless the sensing lead itself runs any real
 *     distance, in which case shield that lead and tie the shield to GND)
 */

#include <Wire.h>
#include <WiFi.h>
#include <PubSubClient.h>
#include <Protocentral_FDC1004.h>

// ---------------------------------------------------------------------------
// PER-NODE CONFIG — this is the only block that should change between the
// four flashes.
// ---------------------------------------------------------------------------
#define TANK_NAME "fresh"   // "fresh", "grey", "black", or the 4th tank's name

// ---------------------------------------------------------------------------
// Shared config — same across all four nodes
// ---------------------------------------------------------------------------
const char* WIFI_SSID     = "CHANGE_ME";
const char* WIFI_PASSWORD = "CHANGE_ME";

const char* MQTT_HOST = "192.168.88.3";   // Mosquitto — same broker as every
const int   MQTT_PORT = 1883;             // other RVTC sensor bridge

const unsigned long POLL_INTERVAL_MS = 10000;  // 10s — matches epever_mqtt.py /
                                                // kws_mqtt.py polling cadence

// FDC1004 channel — using CH1 only; other 3 channels on the board are unused
// (each tank gets its own dedicated board, so no need to multiplex channels)
#define SENSE_CHANNEL   0        // library is 0-indexed: channel 1 = index 0
#define MEASUREMENT     0        // measurement slot 1 (of 4 available)
#define CAPDAC_VALUE    0        // offset capacitance trim — leave at 0 until
                                  // calibration; see notes at bottom of file

// ---------------------------------------------------------------------------
// Calibration placeholders — MUST be set per tank after physically measuring
// empty and full readings. Raw capacitance (pF) is published regardless, so
// this can be left uncalibrated initially and back-filled once you've taken
// reference readings with the tank empty and full.
// ---------------------------------------------------------------------------
float CAP_EMPTY_PF = NAN;   // e.g. 2.5  — raw pF reading with tank empty
float CAP_FULL_PF  = NAN;   // e.g. 14.0 — raw pF reading with tank full

// ---------------------------------------------------------------------------

FDC1004 sensor(FDC1004_100HZ);
WiFiClient espClient;
PubSubClient mqtt(espClient);

char topic_raw[64];
char topic_pct[64];
unsigned long lastPoll = 0;

void connectWiFi() {
  if (WiFi.status() == WL_CONNECTED) return;
  Serial.printf("Connecting to WiFi '%s'...\n", WIFI_SSID);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  unsigned long start = millis();
  while (WiFi.status() != WL_CONNECTED && millis() - start < 20000) {
    delay(500);
    Serial.print(".");
  }
  if (WiFi.status() == WL_CONNECTED) {
    Serial.printf("\nWiFi connected — IP: %s\n", WiFi.localIP().toString().c_str());
  } else {
    Serial.println("\nWiFi connect failed — will retry next loop");
  }
}

void connectMQTT() {
  if (mqtt.connected()) return;
  String clientId = String("rvtc_tank_") + TANK_NAME;
  Serial.printf("Connecting to MQTT broker %s:%d as '%s'...\n",
                MQTT_HOST, MQTT_PORT, clientId.c_str());
  if (mqtt.connect(clientId.c_str())) {
    Serial.println("MQTT connected");
  } else {
    Serial.printf("MQTT connect failed, rc=%d — will retry next loop\n", mqtt.state());
  }
}

void setup() {
  Serial.begin(115200);
  delay(500);

  snprintf(topic_raw, sizeof(topic_raw), "rvtc/sensors/tanks/%s/level_raw_pf", TANK_NAME);
  snprintf(topic_pct, sizeof(topic_pct), "rvtc/sensors/tanks/%s/level_pct", TANK_NAME);

  Wire.begin();
  sensor.configureMeasurement(MEASUREMENT, SENSE_CHANNEL, CAPDAC_VALUE);

  connectWiFi();
  mqtt.setServer(MQTT_HOST, MQTT_PORT);
  connectMQTT();

  Serial.printf("RVTC tank node '%s' started — publishing to %s\n", TANK_NAME, topic_raw);
}

void loop() {
  connectWiFi();
  connectMQTT();
  mqtt.loop();

  if (millis() - lastPoll < POLL_INTERVAL_MS) return;
  lastPoll = millis();

  sensor.triggerSingleMeasurement(MEASUREMENT, FDC1004_100HZ);
  delay(15);  // datasheet-required minimum delay between trigger and read

  uint16_t rawData[2];
  if (sensor.readMeasurement(MEASUREMENT, rawData) != 0) {
    Serial.println("FDC1004 read failed — skipping this cycle");
    return;
  }

  int16_t msb = (int16_t)rawData[0];
  // Raw register -> picofarads per datasheet: capacitance = MSB / 2^19 * 1pF,
  // plus the CAPDAC offset contribution (0 here since CAPDAC_VALUE = 0)
  float capacitance_pF = (float)msb / (1 << 19);

  char payload_raw[16];
  dtostrf(capacitance_pF, 0, 4, payload_raw);
  mqtt.publish(topic_raw, payload_raw, false);

  if (!isnan(CAP_EMPTY_PF) && !isnan(CAP_FULL_PF) && CAP_FULL_PF != CAP_EMPTY_PF) {
    float pct = (capacitance_pF - CAP_EMPTY_PF) / (CAP_FULL_PF - CAP_EMPTY_PF) * 100.0;
    pct = constrain(pct, 0.0, 100.0);
    char payload_pct[8];
    dtostrf(pct, 0, 1, payload_pct);
    mqtt.publish(topic_pct, payload_pct, false);
    Serial.printf("[%s] %.4f pF -> %.1f%%\n", TANK_NAME, capacitance_pF, pct);
  } else {
    Serial.printf("[%s] %.4f pF (uncalibrated — set CAP_EMPTY_PF/CAP_FULL_PF)\n",
                  TANK_NAME, capacitance_pF);
  }
}

/*
 * CALIBRATION PROCEDURE (do this once per tank, after mounting):
 *   1. Flash with CAP_EMPTY_PF / CAP_FULL_PF left as NAN.
 *   2. With the tank genuinely empty, watch Serial output, note the
 *      stabilized pF reading, set CAP_EMPTY_PF to that value.
 *   3. Fill the tank completely, note the stabilized pF reading, set
 *      CAP_FULL_PF to that value.
 *   4. Re-flash. level_pct will now publish a calibrated 0-100% value
 *      alongside the raw pF reading.
 *   5. If readings look noisy or unstable, check that the sensing lead
 *      is shielded (shield tied to GND) and that CIN wiring is as short
 *      as the physical install allows — see file header notes.
 */
