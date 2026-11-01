#pragma once
#include <algorithm>

namespace brickflow::film {
inline double smooth(double u) { u=std::clamp(u,0.,1.);return u*u*(3-2*u); }
inline double blend(double u) { u=std::clamp(u,0.,1.);return u*u*u*(u*(u*6-15)+10); }
inline double elapsed(double duration,double local,double a,double b) {
    const double u=std::clamp(local/duration,0.,1.);
    return duration*(a*u+(b-a)*(u*u*u-.5*u*u*u*u));
}
inline double speed(double duration,double local,double a,double b) {
    return a+(b-a)*smooth(local/duration);
}
}
