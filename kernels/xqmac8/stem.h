// One signed RGB patch, reused for all output channels. No whole-image im2col.
#pragma once
#include "dot8.h"
#include "kernels/xrequant/requant.h"

namespace arch_project {
template<int H,int W,int OC,int OH,int OW,int PT,int PL,class Requantization=XRequantization>
inline void stem_qmac8(const int8_t* input,const int32_t* packed_weights,
    const int32_t* biases,const int32_t* regions,const int32_t* descriptors,int8_t* output){
  const auto* weights=reinterpret_cast<const int8_t*>(packed_weights);
  for(int y=0;y<OH;++y)for(int x=0;x<OW;++x){
    const int oy=2*y-PT,ox=2*x-PL;
    uint64_t patch[4]={0,0,0,0};
    // Missing spatial taps and the five padding lanes are signed integer zero.
#pragma GCC unroll 3
    for(int fy=0;fy<3;++fy){
#pragma GCC unroll 3
      for(int fx=0;fx<3;++fx){
        if(oy+fy>=0 && oy+fy<H && ox+fx>=0 && ox+fx<W){
          const auto* pixel=input+((oy+fy)*W+ox+fx)*3;
#pragma GCC unroll 3
          for(int c=0;c<3;++c){
            const int lane=(fy*3+fx)*3+c;
            patch[lane/8]|=uint64_t(uint8_t(pixel[c]))<<(8*(lane%8));
          }
        }
      }
    }
    const int32_t* corrected=biases+regions[y*OW+x]*OC;
#pragma GCC unroll 1
    for(int ch=0;ch<OC;++ch){
      int64_t acc=corrected[ch];
      acc=xqmac8_register(acc,patch[0],packed8<8>(weights+ch*32));
      acc=xqmac8_register(acc,patch[1],packed8<8>(weights+ch*32+8));
      acc=xqmac8_register(acc,patch[2],packed8<8>(weights+ch*32+16));
      acc=xqmac8_register(acc,patch[3],packed8<8>(weights+ch*32+24));
      *output++=int8_t(Requantization::finish(acc,Requantization::load(descriptors,ch)));
    }
  }
}
}
