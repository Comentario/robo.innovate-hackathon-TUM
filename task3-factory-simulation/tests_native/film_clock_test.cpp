#include "FilmTiming.h"
#include <cassert>
#include <cmath>
int main(){
    using namespace brickflow::film;
    for(auto rates:{std::pair{1.,0.},std::pair{0.,1.},std::pair{1.,16.},std::pair{16.,1.},std::pair{1.,40.}}){
        constexpr double d=4,h=1e-5;
        assert(elapsed(d,0,rates.first,rates.second)==0);
        assert(std::abs(elapsed(d,d,rates.first,rates.second)-d*(rates.first+rates.second)/2)<1e-12);
        assert(std::abs(speed(d,0,rates.first,rates.second)-rates.first)<1e-12);
        assert(std::abs(speed(d,d,rates.first,rates.second)-rates.second)<1e-12);
        for(int i=1;i<400;++i){double t=i/100.;double v=(elapsed(d,t+h,rates.first,rates.second)-elapsed(d,t-h,rates.first,rates.second))/(2*h);
            assert(std::abs(v-speed(d,t,rates.first,rates.second))<1e-7);assert(v>=-1e-7);}
    }
    assert(blend(0)==0&&blend(1)==1);
    assert(std::abs(blend(1e-4))<1e-10&&std::abs(1-blend(1-1e-4))<1e-10);
}
