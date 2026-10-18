// Compare exact pre-requantization accumulators against independent INT64 math.
#include "kernels/xdwmac8/depthwise.h"
#include "kernels/xdwmac8/scalar.h"
#include <array>
#include <vector>
#include <cstdio>
struct Capture {
  static constexpr bool packed_output=true;
  static inline std::vector<int64_t> values;
  static int load(const int32_t*, int ch) { return ch; }
  static int64_t finish(int64_t x, int) { values.push_back(x); return x % 127; }
};
template<int B,int H,int W,int C,int F,int S,int P> void check() {
  constexpr int OH=(H+2*P-F)/S+1, OW=(W+2*P-F)/S+1, N=B*OH*OW*C;
  alignas(8) std::array<int8_t,B*H*W*C> input;
  alignas(8) std::array<int8_t,F*F*C> weights;
  alignas(8) std::array<int32_t,OH*OW*C> biases;
  std::array<int32_t,OH*OW> regions;
  std::array<int8_t,N> output;
  std::vector<int64_t> expected;
  for(unsigned i=0;i<input.size();++i) input[i]=int8_t((i*97+13)%256-128);
  for(unsigned i=0;i<weights.size();++i) weights[i]=int8_t((i*31+61)%256-128);
  for(int y=0;y<OH;++y)for(int x=0;x<OW;++x){
    regions[y*OW+x]=y*OW+x;
    for(int c=0;c<C;++c){
      int64_t corrected=c*7919-20000;
      for(int fy=0;fy<F;++fy)for(int fx=0;fx<F;++fx){
        int iy=y*S-P+fy,ix=x*S-P+fx;
        if(iy>=0&&iy<H&&ix>=0&&ix<W)corrected+=128*int(weights[(fy*F+fx)*C+c]);
      }
      biases[(y*OW+x)*C+c]=int32_t(corrected);
    }
  }
  for(int b=0;b<B;++b)for(int y=0;y<OH;++y)for(int x=0;x<OW;++x)for(int c=0;c<C;++c){
    int64_t acc=c*7919-20000;
    for(int fy=0;fy<F;++fy)for(int fx=0;fx<F;++fx){
      int iy=y*S-P+fy,ix=x*S-P+fx;
      if(iy>=0&&iy<H&&ix>=0&&ix<W)acc+=(int64_t(input[((b*H+iy)*W+ix)*C+c])+128)*weights[(fy*F+fx)*C+c];
    }
    expected.push_back(acc);
  }
  auto verify=[&](){if(Capture::values!=expected)__builtin_trap();for(int i=0;i<N;++i)if(output[i]!=int8_t(expected[i]%127))__builtin_trap();Capture::values.clear();};
  using Packed=arch_project::DepthwiseBank8<B,H,W,C,OH,OW,F,S,S,P,P,0,0,-128,127,Capture,C%8==0?8:1,C%8==0?8:1>;
  Packed::run(input.data(),weights.data(),biases.data(),nullptr,nullptr,output.data(),regions.data());verify();
  using Scalar=arch_project::DepthwiseCorrected<B,H,W,C,OH,OW,F,S,S,P,P,0,0,-128,127,Capture,true,false,true>;
  Scalar::run(input.data(),weights.data(),biases.data(),nullptr,nullptr,output.data(),regions.data());verify();
  using Postinc=arch_project::DepthwiseCorrected<B,H,W,C,OH,OW,F,S,S,P,P,0,0,-128,127,Capture,true,true,true>;
  Postinc::run(input.data(),weights.data(),biases.data(),nullptr,nullptr,output.data(),regions.data());verify();
}
int main(){
  check<2,7,9,1,3,1,1>();check<1,8,6,7,5,2,2>();
  check<2,7,9,8,3,1,1>();check<2,9,11,16,5,2,2>();
  check<1,8,8,9,5,1,2>();check<1,3,4,17,3,1,0>();
  check<1,1,1,8,5,1,2>();check<1,2,2,9,5,2,2>();
  std::puts("Depthwise scalar/postinc/bank: exact accumulators, borders, batches and tails PASS");
}
