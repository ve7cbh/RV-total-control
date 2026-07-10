#include <Wire.h>
void setup() {
  Wire.begin();
  Serial.begin(115200);
  delay(500);
  Serial.println("Scanning...");
  for (byte addr = 1; addr < 127; addr++) {
    Wire.beginTransmission(addr);
    if (Wire.endTransmission() == 0) {
      Serial.printf("Found device at 0x%02X\n", addr);
    }
  }
}
void loop() {}