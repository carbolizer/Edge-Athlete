#include <Arduino.h>
#include <errno.h>
#include <PubSubClient.h>
#include <WiFi.h>
#include <Wire.h>
#include <math.h>
#include <sys/time.h>
#include <time.h>

#include "secrets.h"

#ifndef USB_BRIDGE_ENABLED
#define USB_BRIDGE_ENABLED 0
#endif

namespace {

constexpr char NODE_ID[] = "rack-1-c6-01";
constexpr char FIRMWARE_VERSION[] = "1.0.0";
constexpr uint8_t MPU_ADDRESS = 0x68;
constexpr int SDA_PIN = 2;
constexpr int SCL_PIN = 1;
constexpr int VERTICAL_AXIS = 2;  // Z axis; change after confirming the mounted orientation.
constexpr uint32_t SAMPLE_INTERVAL_MS = 10;
constexpr uint32_t STILLNESS_DURATION_MS = 750;
constexpr uint32_t PULSE_INTERVAL_MS = 5000;
constexpr uint32_t MOTION_INTERVAL_MS = 100;
constexpr uint32_t WIFI_RECONNECT_INTERVAL_MS = 10000;
constexpr uint32_t MQTT_RECONNECT_INTERVAL_MS = 2000;
constexpr float ACCEL_SCALE = 8192.0F;  // MPU-6050 configured for +/-4 g.
constexpr float GRAVITY_MPS2 = 9.80665F;
constexpr float MOVEMENT_THRESHOLD_MPS2 = 0.35F;
constexpr float STILLNESS_THRESHOLD_MPS2 = 0.12F;
constexpr uint32_t MIN_REP_DURATION_MS = 250;
constexpr uint32_t MAX_REP_DURATION_MS = 15000;
constexpr float MIN_REP_PEAK_VELOCITY_MPS = 0.05F;
constexpr float MAX_CONTRACT_VELOCITY_MPS = 10.0F;
constexpr int BATTERY_LEVEL_PERCENT = 100;  // USB-powered v1 hardware.
constexpr uint8_t MAX_CONSECUTIVE_SENSOR_FAILURES = 5;
static_assert(sizeof(NODE_ID) - 1 <= 64, "NODE_ID exceeds the MQTT contract limit");

WiFiClient networkClient;
PubSubClient mqttClient(networkClient);

float accelBaseline[3] = {0.0F, 0.0F, 0.0F};
float gravityBaselineMps2 = GRAVITY_MPS2;
bool repActive = false;
uint32_t repStartedAt = 0;
uint32_t stillnessStartedAt = 0;
uint32_t previousSampleAt = 0;
uint32_t lastSampleAttemptAt = 0;
uint32_t lastPulseAt = 0;
uint32_t lastMotionAt = 0;
uint32_t lastWifiReconnectAt = 0;
uint32_t lastMqttReconnectAt = 0;
uint8_t repNumber = 0;
uint8_t consecutiveSensorFailures = 0;
float velocityMps = 0.0F;
float velocityTotal = 0.0F;
float peakVelocityMps = 0.0F;
uint32_t velocitySamples = 0;
char usbCommand[64];
size_t usbCommandLength = 0;
bool usbDiscardUntilNewline = false;

bool writeMpuRegister(uint8_t registerAddress, uint8_t value) {
  Wire.beginTransmission(MPU_ADDRESS);
  Wire.write(registerAddress);
  Wire.write(value);
  if (Wire.endTransmission() != 0) {
    return false;
  }
  return true;
}

bool readMpuRegister(uint8_t registerAddress, uint8_t &value) {
  Wire.beginTransmission(MPU_ADDRESS);
  Wire.write(registerAddress);
  if (Wire.endTransmission(false) != 0 ||
      Wire.requestFrom(MPU_ADDRESS, static_cast<uint8_t>(1), true) != 1) {
    return false;
  }
  value = Wire.read();
  return true;
}

bool configureMpu() {
  uint8_t identity = 0;
  if (!readMpuRegister(0x75, identity) || identity != 0x68) {
    return false;
  }
  if (!writeMpuRegister(0x6B, 0x00) ||  // Wake the MPU-6050.
      !writeMpuRegister(0x1A, 0x03) ||  // ~44 Hz accel bandwidth.
      !writeMpuRegister(0x1C, 0x08) ||  // Accelerometer range +/-4 g.
      !writeMpuRegister(0x19, 0x09)) {  // 100 Hz sample rate.
    return false;
  }
  delay(10);

  uint8_t power = 0;
  uint8_t filter = 0;
  uint8_t accelRange = 0;
  uint8_t sampleDivider = 0;
  return readMpuRegister(0x6B, power) && power == 0x00 &&
         readMpuRegister(0x1A, filter) && filter == 0x03 &&
         readMpuRegister(0x1C, accelRange) && accelRange == 0x08 &&
         readMpuRegister(0x19, sampleDivider) && sampleDivider == 0x09;
}

bool readAcceleration(float output[3]) {
  Wire.beginTransmission(MPU_ADDRESS);
  Wire.write(0x3B);
  if (Wire.endTransmission(false) != 0) {
    return false;
  }
  if (Wire.requestFrom(MPU_ADDRESS, static_cast<uint8_t>(6), true) != 6) {
    return false;
  }

  for (int axis = 0; axis < 3; ++axis) {
    const int16_t raw = static_cast<int16_t>((Wire.read() << 8) | Wire.read());
    output[axis] = (static_cast<float>(raw) / ACCEL_SCALE) * GRAVITY_MPS2;
  }
  return true;
}

float filterVerticalAcceleration(float accelerationMps2) {
  // Noise-reduction hook: return the raw calibrated axis for v1. Tune only
  // after collecting physical validation evidence for the final mounting.
  return accelerationMps2;
}

bool formatUtcTimestamp(char *output, size_t outputSize) {
  const time_t now = time(nullptr);
  if (now < 1704067200) {  // 2024-01-01; reject an unsynchronized boot clock.
    return false;
  }
  tm utcTime;
  gmtime_r(&now, &utcTime);
  return strftime(output, outputSize, "%Y-%m-%dT%H:%M:%SZ", &utcTime) > 0;
}

bool publishJson(const char *eventType, const char *topic, const char *payload) {
  if (USB_BRIDGE_ENABLED) {
    Serial.printf("EDGE_MQTT\t%s\t%s\n", topic, payload);
    return true;
  }
  if (!mqttClient.connected()) {
    if (strcmp(eventType, "motion") != 0) {
      Serial.printf("MQTT offline; dropped %s event\n", eventType);
    }
    return false;
  }
  if (!mqttClient.publish(topic, payload, false)) {
    if (strcmp(eventType, "motion") != 0) {
      Serial.printf("MQTT %s publish failed\n", eventType);
    }
    return false;
  }
  if (strcmp(eventType, "motion") != 0) {
    Serial.printf("Published %s event\n", eventType);
  }
  return true;
}

void applyUsbTimeCommand() {
  constexpr char prefix[] = "EDGE_TIME\t";
  if (strncmp(usbCommand, prefix, sizeof(prefix) - 1) != 0) {
    return;
  }
  char *end = nullptr;
  errno = 0;
  const long long epoch = strtoll(usbCommand + sizeof(prefix) - 1, &end, 10);
  if (errno == ERANGE || end == usbCommand + sizeof(prefix) - 1 || *end != '\0' ||
      epoch < 1704067200LL || epoch > 4102444800LL) {
    return;
  }
  timeval currentTime = {static_cast<time_t>(epoch), 0};
  if (settimeofday(&currentTime, nullptr) == 0) {
    Serial.println("USB host time synchronized");
  }
}

void maintainUsbCommands() {
  if (!USB_BRIDGE_ENABLED) {
    return;
  }
  while (Serial.available() > 0) {
    const char next = static_cast<char>(Serial.read());
    if (usbDiscardUntilNewline) {
      if (next == '\n') {
        usbDiscardUntilNewline = false;
      }
      continue;
    }
    if (next == '\n') {
      usbCommand[usbCommandLength] = '\0';
      applyUsbTimeCommand();
      usbCommandLength = 0;
    } else if (next != '\r') {
      if (usbCommandLength + 1 < sizeof(usbCommand)) {
        usbCommand[usbCommandLength++] = next;
      } else {
        usbCommandLength = 0;
        usbDiscardUntilNewline = true;
      }
    }
  }
}

void publishPulse() {
  char timestamp[25];
  if (!formatUtcTimestamp(timestamp, sizeof(timestamp))) {
    Serial.println("Clock not synchronized; pulse skipped");
    return;
  }

  char topic[96];
  char payload[256];
  const int topicLength = snprintf(topic, sizeof(topic), "edgeathlete/node/%s/pulse", NODE_ID);
  const int signalStrength = constrain(WiFi.RSSI(), -120, 0);
  const int payloadLength = snprintf(
      payload,
      sizeof(payload),
      "{\"node_id\":\"%s\",\"event_type\":\"pulse\",\"battery_level\":%d,"
      "\"signal_strength\":%d,\"firmware_version\":\"%s\",\"timestamp\":\"%s\"}",
      NODE_ID,
      BATTERY_LEVEL_PERCENT,
      signalStrength,
      FIRMWARE_VERSION,
      timestamp);
  if (topicLength < 0 || static_cast<size_t>(topicLength) >= sizeof(topic) ||
      payloadLength < 0 || static_cast<size_t>(payloadLength) >= sizeof(payload)) {
    Serial.println("Pulse formatting failed");
    return;
  }
  publishJson("pulse", topic, payload);
}

void publishMotion() {
  char timestamp[25];
  if (!formatUtcTimestamp(timestamp, sizeof(timestamp))) {
    return;
  }

  float currentVelocityMps = repActive ? fabsf(velocityMps) : 0.0F;
  if (!isfinite(currentVelocityMps)) {
    currentVelocityMps = 0.0F;
  }
  currentVelocityMps = constrain(currentVelocityMps, 0.0F, MAX_CONTRACT_VELOCITY_MPS);

  char topic[96];
  char payload[192];
  const int topicLength = snprintf(topic, sizeof(topic), "edgeathlete/node/%s/motion", NODE_ID);
  const int payloadLength = snprintf(
      payload,
      sizeof(payload),
      "{\"node_id\":\"%s\",\"event_type\":\"motion\",\"velocity\":%.3f,\"timestamp\":\"%s\"}",
      NODE_ID,
      currentVelocityMps,
      timestamp);
  if (topicLength < 0 || static_cast<size_t>(topicLength) >= sizeof(topic) ||
      payloadLength < 0 || static_cast<size_t>(payloadLength) >= sizeof(payload)) {
    return;
  }
  publishJson("motion", topic, payload);
}

void publishRep(uint32_t durationMs) {
  if (velocitySamples == 0 || !isfinite(peakVelocityMps) ||
      peakVelocityMps < MIN_REP_PEAK_VELOCITY_MPS ||
      peakVelocityMps > MAX_CONTRACT_VELOCITY_MPS) {
    Serial.println("Discarded movement outside velocity limits");
    return;
  }

  char timestamp[25];
  if (!formatUtcTimestamp(timestamp, sizeof(timestamp))) {
    Serial.println("Clock not synchronized; completed rep dropped");
    return;
  }

  repNumber = (repNumber % 100) + 1;
  const float meanVelocityMps = velocityTotal / static_cast<float>(velocitySamples);
  if (!isfinite(meanVelocityMps) || meanVelocityMps > peakVelocityMps) {
    Serial.println("Discarded movement with invalid mean velocity");
    return;
  }
  char topic[96];
  char payload[256];
  const int topicLength = snprintf(topic, sizeof(topic), "edgeathlete/node/%s/rep", NODE_ID);
  const int payloadLength = snprintf(
      payload,
      sizeof(payload),
      "{\"node_id\":\"%s\",\"rep_number\":%u,\"mean_velocity\":%.3f,"
      "\"peak_velocity\":%.3f,\"duration_ms\":%lu,\"timestamp\":\"%s\"}",
      NODE_ID,
      static_cast<unsigned int>(repNumber),
      meanVelocityMps,
      peakVelocityMps,
      static_cast<unsigned long>(durationMs),
      timestamp);
  if (topicLength < 0 || static_cast<size_t>(topicLength) >= sizeof(topic) ||
      payloadLength < 0 || static_cast<size_t>(payloadLength) >= sizeof(payload)) {
    Serial.println("Rep formatting failed");
    return;
  }
  publishJson("rep", topic, payload);
}

void resetRep() {
  repActive = false;
  stillnessStartedAt = 0;
  velocityMps = 0.0F;
  velocityTotal = 0.0F;
  peakVelocityMps = 0.0F;
  velocitySamples = 0;
}

void processSample(const float acceleration[3], uint32_t sampledAt) {
  const float linearX = acceleration[0] - accelBaseline[0];
  const float linearY = acceleration[1] - accelBaseline[1];
  const float linearZ = acceleration[2] - accelBaseline[2];
  const float orientationMovementMps2 = sqrtf(
      linearX * linearX + linearY * linearY + linearZ * linearZ);
  const float measuredMagnitudeMps2 = sqrtf(
      acceleration[0] * acceleration[0] +
      acceleration[1] * acceleration[1] +
      acceleration[2] * acceleration[2]);
  const float movementMps2 = fabsf(measuredMagnitudeMps2 - gravityBaselineMps2);
  const float linearAcceleration[3] = {linearX, linearY, linearZ};
  const float verticalAccelerationMps2 = filterVerticalAcceleration(linearAcceleration[VERTICAL_AXIS]);

  if (!repActive) {
    if (orientationMovementMps2 >= MOVEMENT_THRESHOLD_MPS2) {
      repActive = true;
      repStartedAt = sampledAt;
      previousSampleAt = sampledAt;
      stillnessStartedAt = 0;
      velocityMps = 0.0F;
      velocityTotal = 0.0F;
      peakVelocityMps = 0.0F;
      velocitySamples = 0;
      Serial.println("Movement started");
    }
    return;
  }

  const uint32_t elapsedMs = sampledAt - previousSampleAt;
  previousSampleAt = sampledAt;
  if (elapsedMs > SAMPLE_INTERVAL_MS * 5) {
    Serial.println("Sampling gap detected; discarded in-progress movement");
    resetRep();
    return;
  }
  const float elapsedSeconds = static_cast<float>(elapsedMs) / 1000.0F;
  velocityMps += verticalAccelerationMps2 * elapsedSeconds;
  const float speedMps = fabsf(velocityMps);
  velocityTotal += speedMps;
  peakVelocityMps = fmaxf(peakVelocityMps, speedMps);
  ++velocitySamples;

  if (movementMps2 < STILLNESS_THRESHOLD_MPS2) {
    if (stillnessStartedAt == 0) {
      stillnessStartedAt = sampledAt;
    }
  } else {
    stillnessStartedAt = 0;
  }

  const uint32_t durationMs = sampledAt - repStartedAt;
  const bool stillForBoundary = stillnessStartedAt != 0 && sampledAt - stillnessStartedAt >= STILLNESS_DURATION_MS;
  if (stillForBoundary && durationMs >= MIN_REP_DURATION_MS) {
    publishRep(durationMs);
    resetRep();
    for (int axis = 0; axis < 3; ++axis) {
      accelBaseline[axis] = acceleration[axis];
    }
    gravityBaselineMps2 = measuredMagnitudeMps2;
  } else if (durationMs >= MAX_REP_DURATION_MS) {
    Serial.println("Discarded movement without a stillness boundary");
    resetRep();
    for (int axis = 0; axis < 3; ++axis) {
      accelBaseline[axis] = acceleration[axis];
    }
    gravityBaselineMps2 = measuredMagnitudeMps2;
  }
}

void calibrateAccelerometer() {
  constexpr uint16_t calibrationSamples = 200;
  uint16_t validSamples = 0;
  Serial.println("Keep the sensor still for calibration");
  for (uint16_t sample = 0; sample < calibrationSamples; ++sample) {
    float acceleration[3];
    if (readAcceleration(acceleration)) {
      for (int axis = 0; axis < 3; ++axis) {
        accelBaseline[axis] += acceleration[axis];
      }
      ++validSamples;
    }
    delay(SAMPLE_INTERVAL_MS);
  }
  if (validSamples < calibrationSamples * 9 / 10) {
    Serial.println("MPU-6050 calibration failed; restarting");
    delay(1000);
    ESP.restart();
  }
  for (float &axisBaseline : accelBaseline) {
    axisBaseline /= static_cast<float>(validSamples);
  }
  gravityBaselineMps2 = sqrtf(
      accelBaseline[0] * accelBaseline[0] +
      accelBaseline[1] * accelBaseline[1] +
      accelBaseline[2] * accelBaseline[2]);
  Serial.println("Calibration complete");
}

void maintainConnections(uint32_t now) {
  if (USB_BRIDGE_ENABLED) {
    return;
  }
  if (WiFi.status() != WL_CONNECTED) {
    if (now - lastWifiReconnectAt >= WIFI_RECONNECT_INTERVAL_MS) {
      lastWifiReconnectAt = now;
      Serial.println("Reconnecting Wi-Fi");
      WiFi.reconnect();
    }
    return;
  }

  if (!mqttClient.connected() && !repActive &&
      now - lastMqttReconnectAt >= MQTT_RECONNECT_INTERVAL_MS) {
    lastMqttReconnectAt = now;
    char clientId[80];
    const int clientIdLength = snprintf(clientId, sizeof(clientId), "edgeathlete-%s", NODE_ID);
    if (clientIdLength < 0 || static_cast<size_t>(clientIdLength) >= sizeof(clientId)) {
      Serial.println("MQTT client ID formatting failed");
      return;
    }
    if (mqttClient.connect(clientId)) {
      Serial.printf("Connected to MQTT at %s:%u\n", MQTT_HOST, MQTT_PORT);
    } else {
      Serial.printf("MQTT connection failed: %d\n", mqttClient.state());
    }
  }
  mqttClient.loop();
}

}  // namespace

void setup() {
  Serial.begin(115200);
  delay(500);
  Wire.begin(SDA_PIN, SCL_PIN);
  Wire.setClock(400000);

  if (!configureMpu()) {
    Serial.println("MPU-6050 identity or configuration check failed; restarting");
    delay(1000);
    ESP.restart();
  }
  calibrateAccelerometer();

  if (!USB_BRIDGE_ENABLED) {
    WiFi.mode(WIFI_STA);
    WiFi.setAutoReconnect(true);
    WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
    mqttClient.setServer(MQTT_HOST, MQTT_PORT);
    mqttClient.setBufferSize(512);
    mqttClient.setSocketTimeout(1);
    configTime(0, 0, NTP_SERVER);
  } else {
    Serial.println("USB bridge mode enabled");
  }
  previousSampleAt = millis();
  lastSampleAttemptAt = previousSampleAt;
  lastWifiReconnectAt = previousSampleAt;
}

void loop() {
  const uint32_t now = millis();
  maintainUsbCommands();

  if (now - lastSampleAttemptAt >= SAMPLE_INTERVAL_MS) {
    lastSampleAttemptAt = now;
    float acceleration[3];
    if (readAcceleration(acceleration)) {
      consecutiveSensorFailures = 0;
      processSample(acceleration, now);
    } else if (++consecutiveSensorFailures >= MAX_CONSECUTIVE_SENSOR_FAILURES) {
      consecutiveSensorFailures = 0;
      if (repActive) {
        resetRep();
      }
      Serial.println("MPU-6050 read failures; movement state reset");
    }
  }

  maintainConnections(now);

  if (now - lastPulseAt >= PULSE_INTERVAL_MS) {
    lastPulseAt = now;
    publishPulse();
  }

  if (now - lastMotionAt >= MOTION_INTERVAL_MS) {
    lastMotionAt = now;
    publishMotion();
  }
}
