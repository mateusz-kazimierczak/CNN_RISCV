#pragma once
#include "bank.h"
#include "kernels/rv64imc/depthwise.h"
#include "kernels/xqmac8/dot8.h"
#include "kernels/xpostinc/memory.h"

namespace arch_project {
template <int Batches,int InputHeight,int InputWidth,int Channels,int OutputHeight,int OutputWidth,
 int FilterSize,int StrideHeight,int StrideWidth,int PaddingTop,int PaddingLeft,int InputOffset,
 int OutputOffset,int ActivationMin,int ActivationMax,class Requantization,int InputAlignment,int WeightAlignment>
struct DepthwiseBank8 {
 static_assert(InputOffset==0,"zero point must be folded into region biases");
 template<bool Interior> __attribute__((noinline)) static void pixel(const int8_t* input,const int8_t* weights,
    const int32_t* biases,const int32_t* descriptors,int y,int x,int8_t* output){
   const int oy=y*StrideHeight-PaddingTop,ox=x*StrideWidth-PaddingLeft;
   const int y0=Interior?0:(oy<0?-oy:0),x0=Interior?0:(ox<0?-ox:0);
   const int y1=Interior?FilterSize:(oy+FilterSize>InputHeight?InputHeight-oy:FilterSize);
   const int x1=Interior?FilterSize:(ox+FilterSize>InputWidth?InputWidth-ox:FilterSize);
   int ch=0;
   for(;ch+8<=Channels;ch+=8){
     dw::Bank bank;
     bank.set<0>(dw::bias_pair(biases+ch));bank.set<1>(dw::bias_pair(biases+ch+2));
     bank.set<2>(dw::bias_pair(biases+ch+4));bank.set<3>(dw::bias_pair(biases+ch+6));
     if constexpr(Interior){
#pragma GCC unroll 5
       for(int fy=0;fy<FilterSize;++fy){
#pragma GCC unroll 5
         for(int fx=0;fx<FilterSize;++fx){
           const auto* a=input+((oy+fy)*InputWidth+ox+fx)*Channels+ch;
           const auto* w=weights+(fy*FilterSize+fx)*Channels+ch;
           bank.mac(packed8<InputAlignment>(a),packed8<WeightAlignment>(w));
         }
       }
     }else{
       for(int fy=y0;fy<y1 && x0<x1;++fy){
         const int8_t* a=input+((oy+fy)*InputWidth+ox+x0)*Channels+ch;
         const int8_t* w=weights+(fy*FilterSize+x0)*Channels+ch;
         for(int fx=x0;fx<x1;++fx){
           if constexpr(InputAlignment==8 && WeightAlignment==8 && Channels<=2047)
             bank.mac(postinc::load<uint64_t,Channels>(a),postinc::load<uint64_t,Channels>(w));
           else {bank.mac(packed8<InputAlignment>(a),packed8<WeightAlignment>(w));if(fx+1<x1){a+=Channels;w+=Channels;}}
         }
       }
     }
     const uint64_t pairs[4]={bank.get<0>(),bank.get<1>(),bank.get<2>(),bank.get<3>()};
#pragma GCC unroll 8
     for(int lane=0;lane<8;++lane){
       const int32_t acc=int32_t(uint32_t(pairs[lane/2]>>(32*(lane%2))));
       const int8_t value=int8_t(Requantization::finish(acc,Requantization::load(descriptors,ch+lane)));
       postinc::store<int8_t,1>(output,value);
     }
   }
   // Tail channels never read a fictitious adjacent channel or weight.
   for(;ch<Channels;++ch){
     int32_t acc=biases[ch];
     for(int fy=y0;fy<y1;++fy)for(int fx=x0;fx<x1;++fx)
       acc+=int32_t(input[((oy+fy)*InputWidth+ox+fx)*Channels+ch])*weights[(fy*FilterSize+fx)*Channels+ch];
     postinc::store<int8_t,1>(output,int8_t(Requantization::finish(acc,Requantization::load(descriptors,ch))));
   }
 }
 static void run(const int8_t* input,const int8_t* weights,const int32_t* bias,const int32_t* descriptors,
    const int32_t*,int8_t* output,const int32_t* regions){
   for(int b=0;b<Batches;++b){
     for(int y=0;y<OutputHeight;++y)for(int x=0;x<OutputWidth;++x){
       const int oy=y*StrideHeight-PaddingTop,ox=x*StrideWidth-PaddingLeft;
       const int32_t* corrected=bias+regions[y*OutputWidth+x]*Channels;
       if(oy>=0 && ox>=0 && oy+FilterSize<=InputHeight && ox+FilterSize<=InputWidth)
         pixel<true>(input,weights,corrected,descriptors,y,x,output);
       else pixel<false>(input,weights,corrected,descriptors,y,x,output);
       output+=Channels;
     }
     input+=InputHeight*InputWidth*Channels;
   }
 }
};
template <int B,int H,int W,int C,int OH,int OW,int F,int SH,int SW,int PT,int PL,int IO,int OO,int LO,int HI,
 class R,int IA,int WA>
inline void depthwise_bank8(const int8_t* input,const int8_t* weights,const int32_t* bias,const int32_t* m,
 const int32_t* s,int8_t* output,const int32_t* regions){
 DepthwiseBank8<B,H,W,C,OH,OW,F,SH,SW,PT,PL,IO,OO,LO,HI,R,IA,WA>::run(input,weights,bias,m,s,output,regions);
}
}
