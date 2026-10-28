#include "SourceReplay.h"
#include <algorithm>
#include <bit>
#include <cmath>
#include <cstring>
#include <fstream>
#include <stdexcept>

namespace brickflow::replay {
namespace {
struct Reader {
    std::vector<char> bytes;std::size_t at=0;
    template<class T>T read(){if(at+sizeof(T)>bytes.size())throw std::runtime_error("Truncated source replay");T v;std::memcpy(&v,bytes.data()+at,sizeof(T));at+=sizeof(T);return v;}
    std::string string(){auto n=read<std::uint16_t>();if(at+n>bytes.size())throw std::runtime_error("Truncated replay string");std::string s(bytes.data()+at,n);at+=n;return s;}
    template<std::size_t N>std::array<double,N> values(){std::array<double,N>a{};for(auto&v:a){v=read<double>();if(!std::isfinite(v))throw std::runtime_error("Nonfinite source replay coordinate");}return a;}
};
double length(const Point& a,const Point& b){return std::hypot(b[0]-a[0],b[1]-a[1],b[2]-a[2]);}
}
void Replay::load(const std::string& file)
{
    static_assert(std::endian::native==std::endian::little);
    std::ifstream f(file,std::ios::binary|std::ios::ate);if(!f)throw std::runtime_error("Source replay file unavailable");
    const auto size=f.tellg();if(size<16||size>std::streamoff(2'000'000'000))throw std::runtime_error("Unexpected source replay size");
    Reader r;r.bytes.resize(std::size_t(size));f.seekg(0);f.read(r.bytes.data(),size);
    if(!f||std::memcmp(r.bytes.data(),"BFR37V1\0",8))throw std::runtime_error("Invalid source replay header");r.at=8;
    const auto count=r.read<std::uint32_t>(),kindCount=r.read<std::uint32_t>();if(count>100000||kindCount>65535)throw std::runtime_error("Replay table limit exceeded");
    kinds.clear();records.clear();names.clear();trackCount=0;
    for(std::uint32_t i=0;i<kindCount;++i)kinds.push_back(r.string());records.reserve(count);
    for(std::uint32_t i=0;i<count;++i){
        Record out;out.id=r.string();out.kind=r.string();out.initial=r.values<4>();out.visible=r.read<double>();out.hidden=r.read<double>();
        out.cart=r.read<std::int32_t>();out.c=r.read<std::int32_t>();out.j=r.read<std::int32_t>();out.layer=r.read<std::int32_t>();
        out.row=r.read<std::int32_t>();out.column=r.read<std::int32_t>();out.shade=r.read<std::int32_t>();
        out.good=r.read<std::uint8_t>()!=0;out.extreme=r.read<std::uint8_t>()!=0;r.read<std::uint16_t>();out.producerScore=r.read<double>();out.producerGroup=r.string();
        const auto n=r.read<std::uint32_t>();if(n>1'000'000)throw std::runtime_error("Unbounded record track count");out.tracks.reserve(n);Pose previous=out.initial;
        for(std::uint32_t j=0;j<n;++j){Track t;t.start=r.read<double>();t.end=r.read<double>();t.to=r.values<4>();t.from=previous;t.kind=r.read<std::uint16_t>();t.flags=r.read<std::uint16_t>();
            const auto pathCount=r.read<std::uint16_t>();r.read<std::uint16_t>();
            if(t.kind>=kinds.size()||!std::isfinite(t.start)||!std::isfinite(t.end)||t.end<=t.start||(j&&t.start<out.tracks.back().end-1e-6))throw std::runtime_error("Invalid source event schedule");
            for(int k=0;k<pathCount;++k){t.path.push_back(r.values<3>());if(k)t.length+=length(t.path[k-1],t.path[k]);t.cumulative.push_back(t.length);}
            if((t.flags&2)&&(pathCount<2||t.length<1e-10))throw std::runtime_error("Degenerate source route");
            if(t.flags&4){t.rigid.from=r.values<4>();t.rigid.to=r.values<4>();t.rigid.local=r.values<3>();t.rigid.yaw=r.read<double>();}
            previous=t.to;out.tracks.push_back(std::move(t));++trackCount;
        }
        if(names.contains(out.id))throw std::runtime_error("Duplicate replay identity");names[out.id]=int(records.size());records.push_back(std::move(out));
    }
    if(r.at!=r.bytes.size())throw std::runtime_error("Trailing bytes in source replay");
}
int Replay::named(const std::string& name) const {auto i=names.find(name);if(i==names.end())throw std::runtime_error("Missing replay actor: "+name);return i->second;}
const Track* Replay::segment(int id,double time) const
{
    const auto& tracks=records.at(id).tracks;auto it=std::upper_bound(tracks.begin(),tracks.end(),time,[](double t,const Track& s){return t<s.start;});
    return it==tracks.begin()?nullptr:&*--it;
}
const std::string& Replay::kind(const Track* track) const {static const std::string empty;return track?kinds.at(track->kind):empty;}
State Replay::state(int id,double time) const
{
    const auto& r=records.at(id);State out;out.pose=r.initial;out.visible=time>=r.visible&&time<r.hidden;
    const auto* s=segment(id,time);if(!s)return out;
    double u=std::clamp((time-s->start)/(s->end-s->start),0.,1.);if(!(s->flags&1))u=u*u*(3-2*u);
    if(s->flags&2){
        const double distance=s->length*u;std::size_t k=1;while(k+1<s->path.size()&&distance>s->cumulative[k])++k;
        const auto& a=s->path[k-1];const auto& b=s->path[k];const double d=s->cumulative[k]-s->cumulative[k-1],v=d>0?(distance-s->cumulative[k-1])/d:0;
        for(int j=0;j<3;++j)out.pose[j]=a[j]+(b[j]-a[j])*v;out.pose[3]=s->from[3]+(s->to[3]-s->from[3])*u;
        if(kind(s)=="supported-reject-decline"){
            const double dx=b[0]-a[0],dy=b[1]-a[1],dz=b[2]-a[2],horizontal=std::hypot(dx,dz);
            if(horizontal>1e-12&&d>1e-12){out.normal={-dy*dx/(horizontal*d),horizontal/d,-dy*dz/(horizontal*d)};
                out.pose[0]+=out.normal[0]*.069/2;out.pose[1]+=(out.normal[1]-1)*.069/2;out.pose[2]+=out.normal[2]*.069/2;}
        }
    }else if(s->flags&4){const auto& q=s->rigid;const double yaw=q.from[3]+(q.to[3]-q.from[3])*u,co=std::cos(yaw),si=std::sin(yaw);
        out.pose={q.from[0]+(q.to[0]-q.from[0])*u+co*q.local[0]+si*q.local[2],q.from[1]+(q.to[1]-q.from[1])*u+q.local[1],q.from[2]+(q.to[2]-q.from[2])*u-si*q.local[0]+co*q.local[2],yaw+q.yaw};
    }else for(int j=0;j<4;++j)out.pose[j]=s->from[j]+(s->to[j]-s->from[j])*u;
    return out;
}
}
