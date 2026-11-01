#pragma once
#include <stdint.h>
#include <stddef.h>
// Plantower active protocol: header 42 4d, length 28, checksum bytes 30-31.
inline bool decodePM25(const uint8_t* frame, size_t size, uint16_t& pm25) {
  if(size!=32||frame[0]!=0x42||frame[1]!=0x4d||frame[2]!=0||frame[3]!=28)return false;
  uint16_t sum=0;for(size_t i=0;i<30;i++)sum+=frame[i];
  if(sum!=((uint16_t(frame[30])<<8)|frame[31]))return false;
  // Atmospheric PM2.5 (Data 5), not CF=1 calibration data.
  pm25=(uint16_t(frame[12])<<8)|frame[13];return pm25<=1000;
}
