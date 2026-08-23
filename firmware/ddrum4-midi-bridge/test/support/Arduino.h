#pragma once

#include <stddef.h>
#include <stdint.h>

#define LED_BUILTIN 13
#define OUTPUT 1
#define LOW 0
#define HIGH 1

class Stream {
 public:
  virtual ~Stream() = default;
  virtual int available() = 0;
  virtual int read() = 0;
  virtual int availableForWrite() { return 64; }
  virtual size_t write(uint8_t byte) = 0;
};

class HardwareSerial : public Stream {};

uint32_t millis();
void pinMode(uint8_t pin, uint8_t mode);
void digitalWrite(uint8_t pin, uint8_t value);
