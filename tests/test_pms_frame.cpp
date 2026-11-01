#include "../esp32/pms_frame.h"
#include <cassert>
#include <iostream>
int main(){uint8_t f[32]={0x42,0x4d,0,28};f[12]=0;f[13]=42;uint16_t sum=0,v=0;for(int i=0;i<30;i++)sum+=f[i];f[30]=sum>>8;f[31]=sum&255;
assert(decodePM25(f,32,v)&&v==42);assert(!decodePM25(f,31,v));f[0]=0;assert(!decodePM25(f,32,v));f[0]=0x42;f[13]=43;assert(!decodePM25(f,32,v));std::cout<<"PMS valid frame / length / header / checksum: PASS\n";}
