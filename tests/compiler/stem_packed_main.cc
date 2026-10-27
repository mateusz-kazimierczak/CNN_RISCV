#include "kernels/xqmac8/stem.h"
#include <array>
#include <vector>
#include <cstring>
#include <cstdio>
struct Capture {
  static inline std::vector<int64_t> values;
  static int load(const int32_t*,int){return 0;}
  static int64_t finish(int64_t x,int){values.push_back(x);return x%127;}
};
template<int H,int W,int OC,int P,int Offset,bool Bias=true> void check(){
  constexpr int OH=(H+1)/2,OW=(W+1)/2;
  std::vector<int8_t> storage(H*W*3+1);
  auto* input=storage.data()+1; // Deliberately unaligned NHWC input.
  std::array<int8_t,OC*27> weights;
  alignas(8) std::array<int32_t,OC*8> packed;
  std::array<int32_t,OH*OW*OC> biases;
  std::array<int32_t,OH*OW> regions;
  std::array<int8_t,OH*OW*OC> output;
  for(int seed=0;seed<8;++seed){
    for(int i=0;i<H*W*3;++i)input[i]=int8_t(seed<2?(seed==0?-128:127):(i*97+seed*71)%256-128);
    for(int i=0;i<OC*27;++i)weights[i]=int8_t(seed==2?-128:seed==3?127:(i*31+seed*13)%256-128);
    for(int c=0;c<OC;++c){
      int8_t row[32]{};std::memcpy(row,weights.data()+c*27,27);
      std::memcpy(packed.data()+c*8,row,32);
    }
    std::vector<int64_t> expected;
    for(int y=0;y<OH;++y)for(int x=0;x<OW;++x){
      regions[y*OW+x]=y*OW+x;
      for(int c=0;c<OC;++c){
        int64_t b=Bias?c*7919-20000:0,acc=b;
        for(int fy=0;fy<3;++fy)for(int fx=0;fx<3;++fx){
          const int iy=y*2-P+fy,ix=x*2-P+fx;
          if(iy<0||iy>=H||ix<0||ix>=W)continue;
          for(int ic=0;ic<3;++ic){
            int weight=weights[c*27+(fy*3+fx)*3+ic];
            b+=Offset*weight;
            acc+=(int64_t(input[(iy*W+ix)*3+ic])+Offset)*weight;
          }
        }
        biases[(y*OW+x)*OC+c]=int32_t(b);expected.push_back(acc);
      }
    }
    arch_project::stem_qmac8<H,W,OC,OH,OW,P,P,Capture>(input,packed.data(),biases.data(),regions.data(),nullptr,output.data());
    if(Capture::values!=expected)__builtin_trap();
    for(unsigned i=0;i<output.size();++i)if(output[i]!=int8_t(expected[i]%127))__builtin_trap();
    Capture::values.clear();
  }
}
int main(){
  check<1,1,1,0,128>();check<1,2,3,1,-127>();check<2,2,7,0,0>();
  check<3,3,8,1,128>();check<4,6,32,0,128>();check<5,7,32,1,-127>();
  check<9,11,33,0,128,false>();check<8,10,16,1,0,false>();
  std::puts("Packed RGB stem: 64 exact accumulator cases, borders, extremes, missing bias and unaligned inputs PASS");
}
