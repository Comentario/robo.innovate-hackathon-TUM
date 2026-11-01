#include "Simulation.h"
#include <algorithm>
#include <cmath>
#include <numbers>
#include <set>

namespace brickflow {
namespace {
constexpr double Pi=std::numbers::pi;
constexpr std::array<double,3> Groups{-10,0,10};
double distance(const Pose& a,const Pose& b) {
    return std::hypot(a[0]-b[0],a[1]-b[1],a[2]-b[2]);
}
double duration(double d,double v) { return std::max(1.5*d/v,std::sqrt(3*d)); }
double smooth(double u) { return u*u*(3-2*u); }
double pathLength(const std::vector<Point>& p) {
    double d=0; for(std::size_t i=1;i<p.size();++i)
        d+=std::hypot(p[i][0]-p[i-1][0],p[i][1]-p[i-1][1],p[i][2]-p[i-1][2]);
    return d;
}
Point pathAt(const std::vector<Point>& p,double u) {
    double q=pathLength(p)*u;
    for(std::size_t i=1;i<p.size();++i) {
        double d=std::hypot(p[i][0]-p[i-1][0],p[i][1]-p[i-1][1],p[i][2]-p[i-1][2]);
        if(q<=d && d>0) return {p[i-1][0]+(p[i][0]-p[i-1][0])*q/d,
            p[i-1][1]+(p[i][1]-p[i-1][1])*q/d,p[i-1][2]+(p[i][2]-p[i-1][2])*q/d};
        q-=d;
    }
    return p.back();
}
template<class F> std::vector<Pose> targets(const std::vector<int>& ids,F fn) {
    std::vector<Pose> result; result.reserve(ids.size());
    for(std::size_t i=0;i<ids.size();++i) result.push_back(fn(ids[i],i));
    return result;
}
std::string tag(const char* name,int a,int b) {
    return std::string(name)+std::to_string(a)+"-"+std::to_string(b);
}
}

Simulation::Simulation(std::vector<Request> recipeRequests):requests(std::move(recipeRequests)) {
    changed=signal(clock); demandChanged=signal(clock);
    auto init=[this](Resource& r){r.init(clock,[this]{wake();});};
    init(dispatch);
    for(int i=0;i<3;++i){layerLoadFree[i]=signal(clock,true);extractionFree[i]=signal(clock,true);}
    add("input-cart",{-16.75,.20,0,0},"inputCart");
    add("dispatch",{56.2,3,0,0},"dispatch");
    for(int c=0;c<6;++c) for(int j=0;j<6;++j) {
        heads.push_back(add(tag("head-",c,j),{-10+j*1.3,3.1,(c-2.5)*1.2,Pi/2},"layerHead"));
        for(int layer=0;layer<20;++layer) for(int row=0;row<4;++row) for(int col=0;col<10;++col) {
            bool good=random()>.12; int shade=int(std::floor(random()*3));
            int id=add(std::to_string(bricks.size()),{-20+j*1.3+(col-4.5)*Depth,
                .32+(layer+.5)*Height,(c-2.5)*1.2-(row-1.5)*Length,Pi/2},"brick");
            auto& b=records[id];b.c=c;b.j=j;b.layer=layer;b.row=row;b.column=col;
            b.shade=shade;b.good=good;b.extreme=random()>.5;
            bricks.push_back(id);
        }
    }
    for(int i=0;i<6;++i) {
        auto lane=std::make_unique<Lane>(); auto& a=*lane;
        a.id=i;a.group=i/2;a.side=i%2?1:-1;a.z=Groups[a.group]+a.side*3;
        for(auto& r:a.inspection)init(r);for(auto& r:a.main)init(r);
        for(auto& shade:a.bank)for(auto& tier:shade)for(auto& r:tier)init(r);
        for(auto& r:a.branches)init(r);init(a.routing);init(a.reject);
        a.sideFree=signal(clock,true);
        lanes[i]=std::move(lane);
        clock.spawn(sharedBelt(a));
        for(int k=0;k<6;++k)rowHeads.push_back(add(tag("row-",i,k),
            {14+k*1.5,2.6,Groups[a.group]+a.side*.6,Pi/2},"rowHead"));
        add("reject-"+std::to_string(i),{28.44,BeltHeight+.03,a.z-.33,0},"rejectPusher");
        add("stacker-"+std::to_string(i),{49,2.8,a.z,0},"layerHead");
        for(int s=0;s<3;++s) {
            auto st=std::make_unique<Station>();st->lane=&a;st->id=s;st->z=a.z+(s-1)*1.15;
            init(st->first);init(st->second);
            st->pusher=add(tag("rowpush-",i,s),{44.25-Length/2-.014,BeltHeight+.30,st->z,0},"rowPusher");
            add(tag("deck-",i,s),{53,.164,st->z,0},"wellDeck");
            add(tag("gate-",i,s),{53.65,1.3,st->z,0},"guideGate");
            for(int side:{-1,1})add(tag("jaw-",i,s)+"-"+std::to_string(side),
                {53,BeltHeight+.045,st->z+side*.48,0},"centeringJaw");
            a.stations[s]=std::move(st);
        }
        clock.spawn(stackLane(a));
        for(auto& st:a.stations)clock.spawn(formStation(*st));
    }
    clock.spawn(source());mark();
}
double Simulation::random() { seed=1664525u*seed+1013904223u;return seed/4294967296.; }
int Simulation::add(std::string id,Pose p,std::string kind) {
    int n=int(records.size());
    if(names.contains(id))throw std::runtime_error("Duplicate material identity");
    names[id]=n;Record r;r.id=std::move(id);r.kind=std::move(kind);r.initial=p;r.position=p;
    records.push_back(std::move(r));if(records.back().kind!="brick")actors.push_back(n);return n;
}
int Simulation::named(const std::string& id) const { return names.at(id); }
void Simulation::wake(){auto e=changed;changed=signal(clock);if(!e->done)e->succeed();}
void Simulation::wakeDemand(){auto e=demandChanged;demandChanged=signal(clock);if(!e->done)e->succeed();wake();}
void Simulation::mark(){Metrics m;m.time=clock.now;m.inspected=inspected;m.rejected=rejected;
    m.formed=formed;m.delivered=delivered;m.cycles=headCycles;
    for(int i=0;i<6;++i)if(lanes[i])m.banks[i]=lanes[i]->bankCount;
    history.push_back(m);
}
void Simulation::append(int id,Pose to,double time,double dt,std::string_view kind,bool linear,
    std::shared_ptr<std::vector<Point>> route,std::shared_ptr<Rigid> rigid) {
    auto& r=records[id];auto from=r.position;
    if(!r.tracks.empty()&&r.tracks.back().end>time+1e-6)throw std::runtime_error("Overlapping movement: "+r.id);
    bool merge=false;
    if(!r.tracks.empty()) {
        auto& last=r.tracks.back();
        merge=linear&&!route&&!rigid&&last.linear&&last.kind==kind&&std::abs(last.end-time)<1e-7&&!last.path&&!last.rigid;
        for(int j=0;j<4&&merge;++j)if(std::abs((to[j]-from[j])/dt-(last.to[j]-last.from[j])/(last.end-last.start))>=1e-5)merge=false;
    }
    if(merge){r.tracks.back().end=time+dt;r.tracks.back().to=to;}
    else r.tracks.push_back({time,time+dt,from,to,kind,linear,std::move(route),std::move(rigid)});
    r.position=to;
}
Task Simulation::move(std::vector<int> ids,std::vector<Pose> to,double v,std::string_view kind,bool linear,double minimum) {
    if(ids.empty())co_return;
    if(ids.size()!=to.size())throw std::runtime_error("Movement target count mismatch");
    double d=0;for(std::size_t i=0;i<ids.size();++i)d=std::max(d,distance(records[ids[i]].position,to[i]));
    double dt=std::max({minimum,linear?d/v:duration(d,v),.001});
    for(std::size_t i=0;i<ids.size();++i)append(ids[i],to[i],clock.now,dt,kind,linear);
    co_await clock.sleep(dt);wake();
}
Task Simulation::carry(std::vector<Group> groups,double v,std::string_view kind) {
    double d=0,angle=0;
    for(const auto& g:groups){const auto& p=records[g.head].position;d=std::max(d,distance(p,g.target));angle=std::max(angle,std::abs(p[3]-g.target[3]));}
    double dt=std::max({duration(d,v),1.5*angle/1.2,.001});
    for(const auto& g:groups) {
        Pose origin=records[g.head].position;double yaw=origin[3],co=std::cos(yaw),si=std::sin(yaw);
        for(int id:g.ids) {
            Pose a=records[id].position;double dx=a[0]-origin[0],dz=a[2]-origin[2];
            Point local{co*dx-si*dz,a[1]-origin[1],si*dx+co*dz};
            const auto& t=g.target;double cc=std::cos(t[3]),ss=std::sin(t[3]);
            append(id,{t[0]+cc*local[0]+ss*local[2],t[1]+local[1],t[2]-ss*local[0]+cc*local[2],a[3]+t[3]-yaw},
                clock.now,dt,kind,false,{},std::make_shared<Rigid>(Rigid{origin,t,local,a[3]-yaw}));
        }
        append(g.head,g.target,clock.now,dt,kind);
    }
    co_await clock.sleep(dt);wake();
}
Task Simulation::path(int id,std::vector<Point> points,int matrix,double speed,std::string_view kind,std::function<void()> release) {
    double dt=pathLength(points)/speed,stamp=clock.now,start=stamp;
    auto& table=matrices[matrix];constexpr double step=.20,grid=.12;
    struct Mask{double time;std::vector<std::string> cells;};std::vector<Mask> masks;
    for(double u=0;u<=dt+.0001;u+=step) {
        auto p=pathAt(points,std::min(1.,u/dt));Mask mask;mask.time=u;
        for(int x=int(std::floor((p[0]-Length/2-.008)/grid));x<=int(std::floor((p[0]+Length/2+.008)/grid));++x)
            for(int z=int(std::floor((p[2]-Depth/2-.004)/grid));z<=int(std::floor((p[2]+Depth/2+.004)/grid));++z)
                mask.cells.push_back(std::to_string(x)+","+std::to_string(z));
        masks.push_back(std::move(mask));
    }
    auto occupied=[&]{
        for(const auto& a:masks)for(const auto& c:a.cells){
            if(table.contains(c+","+std::to_string(int(std::floor((start+a.time)/step)))))return true;
        }
        return false;
    };
    int trials=0;while(occupied()){start+=step;if(++trials>6000)throw std::runtime_error("No free matrix route");}
    for(const auto& a:masks)for(const auto& c:a.cells)table[c+","+std::to_string(int(std::floor((start+a.time)/step)))]=id;
    if(table.size()>25000) {
        int before=int(std::floor(stamp/step))-2;
        for(auto i=table.begin();i!=table.end();) {
            if(std::stoi(i->first.substr(i->first.rfind(',')+1))<before)i=table.erase(i);else++i;
        }
    }
    if(start>clock.now)co_await clock.sleep(start-clock.now);
    const auto& p=points.back();Pose to{p[0],p[1],p[2],records[id].position[3]};
    append(id,to,clock.now,dt,kind,true,std::make_shared<std::vector<Point>>(std::move(points)));
    if(release)clock.at(clock.now+std::min(dt,.45/speed),std::move(release));
    co_await clock.sleep(dt);wake();
}
const Track* Simulation::segment(int id,double time) const {
    const auto& tracks=records[id].tracks;
    auto it=std::upper_bound(tracks.begin(),tracks.end(),time,[](double t,const Track& s){return t<s.start;});
    return it==tracks.begin()?nullptr:&*std::prev(it);
}
Pose Simulation::pose(int id,double time) const {
    const auto* s=segment(id,time);if(!s)return records[id].initial;
    double u=std::clamp((time-s->start)/(s->end-s->start),0.,1.);if(!s->linear)u=smooth(u);
    if(s->path){auto p=pathAt(*s->path,u);return {p[0],p[1],p[2],s->from[3]+(s->to[3]-s->from[3])*u};}
    if(s->rigid){const auto& r=*s->rigid;double yaw=r.from[3]+(r.to[3]-r.from[3])*u,co=std::cos(yaw),si=std::sin(yaw);
        return {r.from[0]+(r.to[0]-r.from[0])*u+co*r.local[0]+si*r.local[2],
            r.from[1]+(r.to[1]-r.from[1])*u+r.local[1],
            r.from[2]+(r.to[2]-r.from[2])*u-si*r.local[0]+co*r.local[2],yaw+r.yaw};}
    Pose p;for(int j=0;j<4;++j)p[j]=s->from[j]+(s->to[j]-s->from[j])*u;return p;
}
Metrics Simulation::metrics(double time) const {
    auto it=std::upper_bound(history.begin(),history.end(),time,[](double t,const Metrics& m){return t<m.time;});
    return it==history.begin()?Metrics{}:*std::prev(it);
}
void Simulation::run() {
    clock.run();total=clock.now;mark();std::set<int> output;
    for(const auto& pallet:pallets)for(int id:pallet.ids) {
        if(!output.insert(id).second)throw std::runtime_error("Duplicate pallet material");
        if(!records[id].good)throw std::runtime_error("Rejected brick in output pallet");
    }
    completeInput=inspected==28800;bricksPerHour=delivered*560*3600/total;palletsPerHour=delivered*3600/total;
}
}
