#include <pitchwing/LiveEngine.hpp>
#include <array>
#include <cmath>
#include <cstdio>
int main() {
 for (double rate : {44100.,48000.,96000.}) {
  pitchwing::LiveEngine e({rate,-7});
  std::array<double,32> l{},r{},o{},p{};
  for (int i=0;i<24000;i+=32) {
   if(e.setPitchSemitones(-7+9*std::sin(i*.003))!=pitchwing::Status::Ok) return 1;
   for(int k=0;k<32;++k){double t=(i+k)/rate;l[k]=.2*std::sin(6.283185307179586*38.89*t)+.1*std::sin(6.283185307179586*311.12*t);r[k]=.3*std::sin(6.283185307179586*58.27*t);}
   if(e.process(l.data(),r.data(),o.data(),p.data(),32)!=pitchwing::Status::Ok) return 2;
   if(std::fwrite(o.data(),sizeof(double),32,stdout)!=32||std::fwrite(p.data(),sizeof(double),32,stdout)!=32) return 3;
  }
 }
}
