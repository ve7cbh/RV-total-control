# RV IMU Leveling Node (SH1106 OLED & STANAG Compliant)

This document contains the complete, production-ready implementation for an ESP32-S3 node utilizing a **diymore 10DOF IMU** (LSM303D/L3GD20 sensors) and an **I²C SH1106 1.3" OLED display**. 

## Network & Programming Architecture
* **RS-485 Line (`Serial1`):** A dedicated, continuous, one-way simplex broadcast channel running at 115200 baud to feed your 6-channel gateway.
* **USB Line (`Serial`):** Leverages the ESP32-S3's internal **USB-Serial-JTAG Controller** to open a completely independent, bidirectional debugging and code-flashing channel. You can plug in a computer to flash software or monitor debugging metrics at any time without disconnecting your RS-485 wiring.
* **Coordinate Standard:** Follows the **STANAG** convention:
  * **Pitch:** Nose Up = Positive (+) / Nose Down = Negative (-)
  * **Roll:** Starboard Down = Positive (+) / Port Down = Negative (-)

---

## Hardware Configuration

### 1. Component Level Mappings
* The **diymore IMU** and the **SH1106 OLED Display** share the primary I²C bus wires in parallel.
* The **5V RS-485 Transceiver Converter Module** is connected directly to Hardware Serial 1. 

### 2. Physical Pin Layout
```text
[ESP32-S3]                               [Peripherals]
  3.3V         ------------------------> IMU VCC
  5V / VBUS    ------------------------> SH1106 OLED VCC & RS-485 Converter VCC
  GND          ------------------------> Shared Ground Bus
  
  Pin 8 (SDA)  ------------------------> Shared I2C SDA (IMU & OLED)
  Pin 9 (SCL)  ------------------------> Shared I2C SCL (IMU & OLED)
  
  Pin 17 (TX1) ------------------------> RS-485 Module DI (Data In)
                                         RS-485 Module DE & RE tied to 5V (Always TX)
                                         
  Native USB Port ---------------------> Bidirectional Laptop Connection (Programming/Debug)
```

---

## Arduino IDE Menu Configuration
Before compiling and uploading the sketch to your ESP32-S3, verify that your options under the **Tools** menu match these properties exactly:

* **Board:** `ESP32S3 Dev Module`
* **USB CDC On Boot:** `Enabled` **(CRITICAL: Maps 'Serial' directly to the physical USB port)**
* **USB Mode:** `Hardware CDC and JTAG`
* **Upload Mode:** `UART0 / Hardware CDC`

---

## Production Sketch Block

```cpp
#include <Arduino.h>
#include <Wire.h>
#include <LSM303.h>
#include <U8g2lib.h>

// --- RS-485 Hardware Pins ---
#define RS485_TX_PIN 17
#define RS485_RX_PIN 18 // Assigned but physically unused in simplex mode

LSM303 compass;

// --- OLED Display Configuration (SH1106 Driver Native) ---
// Using full buffer hardware I2C mode optimized for the 1.3" SH1106 layout 
U8G2_SH1106_128X64_NONAME_F_HW_I2C u8g2(U8G2_R0, /* reset=*/ U8X8_PIN_NONE);

// --- Low-Pass Filter Factor ---
// Lower values give smoother tracking but react slower. 0.1 is optimized for a parked RV.
const float FILTER_FACTOR = 0.1; 

// --- Global Filter Variables ---
float filtered_pitch = 0.0;
float filtered_roll  = 0.0;
float filtered_hdg   = 0.0;

// --- Standard NMEA-0183 Checksum Generator ---
String appendChecksum(String sentence) {
  int checksum = 0;
  for (int i = 1; i < sentence.length(); i++) {
    checksum ^= sentence[i];
  }
  char hexStr[3];
  sprintf(hexStr, "%02X", checksum);
  return sentence + "*" + String(hexStr);
}

void setup() {
  // --- CHANNEL 1: Native USB Bidirectional Port ---
  Serial.begin(115200); 
  delay(1000); // Give the host OS time to recognize the hardware interface
  Serial.println("--- SYSTEM BOOT IN DEBUG MODE ---");

  // --- CHANNEL 2: Wired RS-485 Dedicated Network ---
  // Adjust 9600 to match your gateway's configuration channel profile speed
  Serial1.begin(9600, SERIAL_8N1, RS485_RX_PIN, RS485_TX_PIN);

  // Boot the shared I2C wire profile
  Wire.begin();

  // Initialize SH1106 OLED Display
  u8g2.begin();

  // Initialize Accel + Mag Registers (LSM303D)
  if (!compass.init()) {
    Serial.println("CRITICAL ERROR: LSM303D failed to respond via I2C!");
    u8g2.clearBuffer();
    u8g2.setFont(u8g2_font_ncenB08_tr);
    u8g2.drawStr(0, 32, "IMU INIT ERROR!");
    u8g2.sendBuffer();
    while (1) { delay(100); } // System safe halt on hardware loop failure
  }
  compass.enableDefault();
  Serial.println("Sensors online. Beginning concurrent tracking loop...");
}

void loop() {
  // 1. Fetch raw matrix indices from registers
  compass.read();

  // 2. Compute STANAG Compliant Flight Geometry Coordinates
  // Nose up = positive pitch, Starboard down = positive roll
  float raw_pitch = atan2(compass.a.x, sqrt((float)compass.a.y * compass.a.y + (float)compass.a.z * compass.a.z)) * 180.0 / M_PI;
  float raw_roll  = atan2(-compass.a.y, compass.a.z) * 180.0 / M_PI;
  
  float raw_hdg   = atan2((float)compass.m.y, (float)compass.m.x) * 180.0 / M_PI;
  if (raw_hdg < 0) raw_hdg += 360.0;

  // 3. Apply Low-Pass Smoothing Filters
  filtered_pitch = (raw_pitch * FILTER_FACTOR) + (filtered_pitch * (1.0 - FILTER_FACTOR));
  filtered_roll  = (raw_roll * FILTER_FACTOR) + (filtered_roll * (1.0 - FILTER_FACTOR));
  
  // Boundary wrapping mitigation for heading calculation (359° to 0° transitions)
  float diff = raw_hdg - filtered_hdg;
  if (diff < -180.0) diff += 360.0;
  if (diff > 180.0)  diff -= 360.0;
  filtered_hdg += diff * FILTER_FACTOR;
  if (filtered_hdg < 0.0)   filtered_hdg += 360.0;
  if (filtered_hdg >= 360.0) filtered_hdg -= 360.0;

  // 4. Update Local SH1106 OLED Display 
  u8g2.clearBuffer();					
  u8g2.setFont(u8g2_font_profont15_mf); // Crisp, fixed-width dashboard font
  
  // Render Heading Value
  u8g2.drawStr(0, 15, "HEADING:");
  u8g2.setCursor(75, 15);
  u8g2.print(filtered_hdg, 1);
  u8g2.print(char(176)); // Degree sign symbol
  
  // Render Pitch Value
  u8g2.drawStr(0, 35, "PITCH:");
  u8g2.setCursor(75, 35);
  if(filtered_pitch > 0) u8g2.print("+");
  u8g2.print(filtered_pitch, 2);
  u8g2.print(char(176));
  
  // Render Roll Value
  u8g2.drawStr(0, 55, "ROLL:");
  u8g2.setCursor(75, 55);
  if(filtered_roll > 0) u8g2.print("+");
  u8g2.print(filtered_roll, 2);
  u8g2.print(char(176));
  
  u8g2.sendBuffer(); 

  // 5. Construct NMEA-0183 Communication Strings
  float mag_heading = filtered_hdg; 
  String dummyTime  = "123456.789"; // Central sync time placeholder

  String hdt   = appendChecksum("\$HEHDT," + String(filtered_hdg, 1) + ",T");
  String hdg   = appendChecksum("\$HCHDG," + String(mag_heading, 1) + ",,,2.1,W");
  String pashr = appendChecksum("\$PASHR," + dummyTime + "," + String(filtered_hdg, 1) + ",T," + String(filtered_roll, 2) + ",," + String(filtered_pitch, 2) + ",,0.05,,,,");
  String prdid = appendChecksum("\$PRDID," + String(filtered_pitch, 2) + "," + String(filtered_roll, 2) + "," + String(filtered_hdg, 1));

  // 6. OUTPUT PATH A: Pipe raw lines down the dedicated wired RS-485 stream
  Serial1.println(hdt);
  Serial1.println(hdg);
  Serial1.println(pashr);
  Serial1.println(prdid);

  // 7. OUTPUT PATH B: Print human-readable diagnostics over USB connection
  // This will safely execute only if a laptop terminal is physically connected.
  if (Serial) {
    Serial.printf("[DEBUG LOG] Hdg: %0.1f deg | Pitch: %+0.2f deg | Roll: %+0.2f deg\n", 
                  filtered_hdg, filtered_pitch, filtered_roll);
  }

  // 5Hz operational refresh cycle rate
  delay(200); 
}
```
