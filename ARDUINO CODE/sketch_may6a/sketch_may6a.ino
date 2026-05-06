#include <WiFi.h>
#include <WebSocketsClient.h>
#include <ArduinoJson.h>
#include <HTTPClient.h>

// ── WiFi ──
const char* ssid     = "saksham";
const char* password = "123456789";

// ── Server ──
const char* host = "server-only-capstone.onrender.com";
const int   port = 443;
const char* path = "/ws/traffic-light";

// ── Pins ──
#define PIN_RED    25
#define PIN_YELLOW 26
#define PIN_GREEN  27

// ── Traffic Light Identity ──
const char* TL_ID   = "esp32-tl-1";
const char* TL_NAME = "Main Gate";
const float TL_LAT  = 30.356472;
const float TL_LNG  = 76.371972;

WebSocketsClient ws;

void setLight(String state) {
  if (state == "triggered") {
    digitalWrite(PIN_RED,    LOW);
    digitalWrite(PIN_YELLOW, LOW);
    digitalWrite(PIN_GREEN,  HIGH);
    Serial.println("GREEN — TRIGGERED");
  } else if (state == "clear") {
    digitalWrite(PIN_RED,    HIGH);
    digitalWrite(PIN_YELLOW, LOW);
    digitalWrite(PIN_GREEN,  LOW);
    Serial.println("RED — CLEAR");
  } else if (state == "warning") {
    digitalWrite(PIN_RED,    LOW);
    digitalWrite(PIN_YELLOW, HIGH);
    digitalWrite(PIN_GREEN,  LOW);
    Serial.println("YELLOW — WARNING");
  } else {
    digitalWrite(PIN_RED,    LOW);
    digitalWrite(PIN_YELLOW, LOW);
    digitalWrite(PIN_GREEN,  LOW);
    Serial.println("ALL OFF — DISCONNECTED");
  }
}

void onWebSocketEvent(WStype_t type, uint8_t* payload, size_t length) {
  switch (type) {
    case WStype_CONNECTED:
      Serial.println("WebSocket connected");
      setLight("clear");
Serial.println("Connected to server — waiting for status");
      break;

    case WStype_TEXT: {
      Serial.printf("Received: %s\n", payload);
      StaticJsonDocument<1024> doc;
      DeserializationError err = deserializeJson(doc, payload, length);
      if (err) { Serial.println("JSON parse error"); return; }
      String status = doc["status"].as<String>();
Serial.printf("Status: %s\n", status.c_str());
if (status != "connected") {
  setLight(status);
}
      break;
    }

    case WStype_DISCONNECTED:
      Serial.println("WebSocket disconnected — retrying...");
      setLight("disconnected");
      break;

    default:
      break;
  }
}

void registerTrafficLight() {
  HTTPClient http;
  http.begin("https://server-only-capstone.onrender.com/traffic-lights");
  http.addHeader("Content-Type", "application/json");
  String body = "{\"id\":\"" + String(TL_ID) + "\",\"name\":\"" + String(TL_NAME) + "\",\"latitude\":" + String(TL_LAT, 6) + ",\"longitude\":" + String(TL_LNG, 6) + "}";
  int code = http.POST(body);
  Serial.printf("Registered traffic light: HTTP %d\n", code);
  http.end();
}

void setup() {
  Serial.begin(115200);

  pinMode(PIN_RED,    OUTPUT);
  pinMode(PIN_YELLOW, OUTPUT);
  pinMode(PIN_GREEN,  OUTPUT);
  setLight("disconnected");

  Serial.printf("Connecting to WiFi: %s\n", ssid);
  WiFi.begin(ssid, password);
  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
  }
  Serial.printf("\nConnected! IP: %s\n", WiFi.localIP().toString().c_str());

  registerTrafficLight();

  ws.beginSSL(host, port, path);
  ws.onEvent(onWebSocketEvent);
  ws.setReconnectInterval(4000);
  ws.enableHeartbeat(15000, 3000, 2);
}

void loop() {
  ws.loop();
}