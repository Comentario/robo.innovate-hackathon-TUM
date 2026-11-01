#include "Simulation.h"
#include <algorithm>
#include <cmath>
#include <numbers>

namespace brickflow {
namespace {
constexpr double Pi=std::numbers::pi;
constexpr std::array<double,3> Groups{-10,0,10};
std::string tag(const char* name,int a,int b){return std::string(name)+std::to_string(a)+"-"+std::to_string(b);}
template<class F> std::vector<Pose> positions(const std::vector<int>& ids,F fn){
    std::vector<Pose> out;out.reserve(ids.size());for(std::size_t i=0;i<ids.size();++i)out.push_back(fn(ids[i],int(i)));return out;
}
template<class G> std::vector<int> headsOf(const std::vector<G>& groups){
    std::vector<int> out;for(const auto& g:groups)out.push_back(g.head);return out;
}
template<class G> std::vector<Pose> destinations(const std::vector<G>& groups){
    std::vector<Pose> out;for(const auto& g:groups)out.push_back(g.target);return out;
}
template<class G,class F> std::vector<G> retarget(const std::vector<G>& groups,F fn){
    auto out=groups;for(auto& g:out)g.target=fn(g);return out;
}
}

Task Simulation::source(){
    auto ids=bricks;ids.push_back(named("input-cart"));
    auto to=positions(ids,[&](int id,int){auto p=records[id].position;p[0]+=10;return p;});
    to.back()={-6.75,.20,0,0};
    co_await move(ids,to,.5,"cart-delivery");
    for(int cycle=0;cycle<20;++cycle){
        for(auto e:layerLoadFree)co_await e;
        std::vector<Group> groups;
        for(int c=0;c<6;++c)for(int j=0;j<6;++j){
            int base=((c*6+j)*20+(19-cycle))*40;std::vector<int> layer;
            for(int k=0;k<40;++k)layer.push_back(bricks[base+k]);
            groups.push_back({named(tag("head-",c,j)),std::move(layer),
                {-10+j*1.3,.32+(19-cycle+.5)*Height,(c-2.5)*1.2,Pi/2},c,j});
        }
        co_await move(headsOf(groups),destinations(groups),.7,"lower-layer-head");
        co_await clock.sleep(.3);
        co_await carry(retarget(groups,[](auto& g){return Pose{g.target[0],3.1,g.target[2],Pi/2};}),.7,"lift-36-top-layers");
        co_await carry(retarget(groups,[](auto& g){return Pose{1+g.j*1.5,3.1,Groups[g.c/2]+(g.c%2?.6:-.6),Pi/2};}),1.25,"distribute-2x6-layers");
        co_await carry(retarget(groups,[](auto& g){return Pose{1+g.j*1.5,BeltHeight+Height/2,Groups[g.c/2]+(g.c%2?.6:-.6),Pi/2};}),.7,"place-on-loading-belts");
        co_await clock.sleep(.2);
        auto raised=retarget(groups,[](auto& g){return Pose{1+g.j*1.5,3.1,Groups[g.c/2]+(g.c%2?.6:-.6),Pi/2};});
        co_await move(headsOf(raised),destinations(raised),.7,"raise-empty-layer-heads");
        for(int group=0;group<3;++group){
            std::vector<Group> batch;for(const auto& g:groups)if(g.c/2==group)batch.push_back(g);
            layerLoadFree[group]=signal(clock);clock.spawn(mainBatch(group,std::move(batch),cycle));
        }
        auto returned=retarget(groups,[](auto& g){return Pose{-10+g.j*1.3,3.1,(g.c-2.5)*1.2,Pi/2};});
        co_await move(headsOf(returned),destinations(returned),1.25,"return-empty-layer-heads");
        ++headCycles;mark();
    }
    sourceFinished=true;wake();
}
Task Simulation::mainBatch(int group,std::vector<Group> batch,int /*cycle*/){
    co_await extractionFree[group];extractionFree[group]=signal(clock);
    std::vector<int> ids;for(const auto& g:batch)ids.insert(ids.end(),g.ids.begin(),g.ids.end());
    co_await move(ids,positions(ids,[&](int id,int){auto p=records[id].position;p[0]+=13;return p;}),.5,"common-main-belt",true);
    layerLoadFree[group]->succeed();
    for(int extraction=0;extraction<4;++extraction){
        for(auto& lane:lanes)if(lane->group==group)co_await lane->sideFree;
        std::vector<Group> packets;
        for(const auto& g:batch){
            auto* lane=lanes[group*2+g.c%2].get();int row=lane->side<0?3-extraction:extraction;
            std::vector<int> rowIDs(g.ids.begin()+row*10,g.ids.begin()+row*10+10);
            packets.push_back({named(tag("row-",lane->id,g.j)),std::move(rowIDs),
                {14+g.j*1.5,BeltHeight+Height/2,Groups[group]+lane->side*.6-(row-1.5)*Length,Pi/2},0,g.j,lane});
        }
        co_await move(headsOf(packets),destinations(packets),.7,"lower-row-grippers");
        co_await clock.sleep(.15);
        co_await carry(retarget(packets,[](auto& g){return Pose{g.target[0],2.4,g.target[2],Pi/2};}),.7,"raise-six-rows-each-side");
        co_await carry(retarget(packets,[](auto& g){return Pose{14+g.j*1.5,2.4,g.lane->z,Pi/2};}),1.25,"side-pick-and-transfer-rows");
        co_await carry(retarget(packets,[](auto& g){return Pose{14+g.j*1.5,BeltHeight+Height/2,g.lane->z,Pi/2};}),.7,"place-six-rows-on-v1");
        co_await clock.sleep(.15);
        auto raised=retarget(packets,[](auto& g){return Pose{14+g.j*1.5,2.6,g.lane->z,Pi/2};});
        co_await move(headsOf(raised),destinations(raised),.7,"raise-row-grippers-clear");
        for(auto& lane:lanes)if(lane->group==group){
            std::vector<int> rows;for(const auto& g:packets)if(g.lane==lane.get())rows.insert(rows.end(),g.ids.begin(),g.ids.end());
            lane->sideFree=signal(clock);clock.spawn(feedSide(*lane,std::move(rows)));
        }
    }
    extractionFree[group]->succeed();wake();
}
Signal Simulation::reserveBelt(Lane& lane){auto e=signal(clock);lane.beltRequests.push_back(e);wake();return e;}
Signal Simulation::loadBelt(Lane& lane,int id){
    if(!lane.beltReserved)throw std::runtime_error("Unreserved belt entry");
    if(lane.beltStepEnd&&*lane.beltStepEnd>clock.now){double dt=*lane.beltStepEnd-clock.now;auto p=records[id].position;p[0]+=.6*dt;append(id,p,clock.now,dt,"v2",true);}
    lane.beltIDs.push_back(id);lane.beltReserved=false;auto e=signal(clock);e->succeed();wake();return e;
}
Task Simulation::sharedBelt(Lane& lane){
    while(true){
        bool space=lane.beltIDs.empty()||records[lane.beltIDs.back()].position[0]-23>.085-1e-6;
        if(!lane.beltReserved&&!lane.beltRequests.empty()&&space){lane.beltReserved=true;auto e=lane.beltRequests.front();lane.beltRequests.pop_front();e->succeed();}
        if(lane.beltIDs.empty()){co_await changed;continue;}
        int first=lane.beltIDs.front();double x=records[first].position[0];
        if(x>=26-1e-7){
            if(lane.inspection[0].free){--lane.inspection[0].free;lane.beltIDs.pop_front();clock.spawn(inspectBrick(first,lane));wake();continue;}
            co_await changed;continue;
        }
        double dx=std::min(.072,26-x);
        if(!lane.beltRequests.empty()&&!lane.beltReserved&&!lane.beltIDs.empty()&&records[lane.beltIDs.back()].position[0]<23.085)
            dx=std::min(dx,23.085-records[lane.beltIDs.back()].position[0]);
        std::vector<int> ids(lane.beltIDs.begin(),lane.beltIDs.end());lane.beltStepEnd=clock.now+dx/.6;
        co_await move(ids,positions(ids,[&](int id,int){auto p=records[id].position;p[0]+=dx;double t=std::clamp((p[0]-24)/1.6,0.,1.);p[3]=Pi/2*(1-t);return p;}),.6,"v2",true);
        lane.beltStepEnd.reset();
    }
}
Task Simulation::feedSide(Lane& lane,std::vector<int> ids){
    std::stable_sort(ids.begin(),ids.end(),[&](int a,int b){return records[b].position[0]<records[a].position[0];});
    while(!ids.empty()){
        co_await reserveBelt(lane);int first=ids.front();double dx=23-records[first].position[0];
        if(dx>1e-7)co_await move(ids,positions(ids,[&](int id,int){auto p=records[id].position;p[0]+=dx;return p;}),.12,"v1-common-drive",true);
        ids.erase(ids.begin());co_await loadBelt(lane,first);
    }
    lane.sideFree->succeed();wake();
}
Task Simulation::inspectBrick(int id,Lane& lane){
    double z=lane.z;
    co_await move({id},{{26.2,BeltHeight+Height/2,z,0}},.6,"inspection-entry",true);
    for(int k=1;k<8;++k){
        co_await lane.inspection[k].request();
        co_await move({id},{{26.2+k*.32,BeltHeight+Height/2,z,0}},.6,"inspection-zpa",true);
        lane.inspection[k-1].release();if(k==6){++inspected;++lane.inspected;mark();}
    }
    const auto& b=records[id];
    if(!b.good){
        co_await lane.reject.request();int tool=named("reject-"+std::to_string(lane.id));
        co_await move({tool},{{28.44,BeltHeight+.03,z-Depth/2-.02,0}},1.5,"reject-contact");
        co_await move({id,tool},{{28.44,BeltHeight+Height/2,z+.58,0},{28.44,BeltHeight+.03,z+.58-Depth/2-.02,0}},1.5,"reject-stroke");
        lane.inspection[7].release();++rejected;++lane.rejected;mark();clock.spawn(rejectDrop(id,lane));
        co_await move({tool},{{28.44,BeltHeight+.03,z-.33,0}},1.5,"reject-retract");lane.reject.release();co_return;
    }
    Slot* slot=nullptr;std::array<Resource,24>* channel=nullptr;int shade=b.shade,tier=1;
    while(!channel){
        slot=findSlot(lane,shade);
        if(slot&&lane.main[0].free){channel=&lane.main;reserveSlot(*slot,shade);}
        else{
            int freeTier=-1;for(int n:{1,0,2})if(lane.bank[shade][n][0].free){freeTier=n;break;}
            if(freeTier>=0){slot=nullptr;tier=freeTier;channel=&lane.bank[shade][tier];}
            else co_await changed;
        }
    }
    co_await (*channel)[0].request();co_await lane.routing.request();
    co_await move({id},{{28.72,BeltHeight+Height/2,z,0}},.6,"clear-inspection-tail",true);lane.inspection[7].release();
    co_await move({id},{{29.1,BeltHeight+Height/2,z,0}},.8,"routing-entry",true);
    double zz=slot?z:z-.65-shade*.60+(tier-1)*.14;
    co_await path(id,{{29.1,BeltHeight+Height/2,z},{29.45,BeltHeight+Height/2,z},{29.7,BeltHeight+Height/2,zz},{30.2,BeltHeight+Height/2,zz}},lane.id,1.,
        slot?"route-to-approved-channel":"horizontal-colour-reserve",[&lane]{lane.routing.release();});
    if(slot)++lane.mixCount;else{++lane.bankCount[shade];lane.bankPeaks[shade]=std::max(lane.bankPeaks[shade],lane.bankCount[shade]);mark();}
    for(int k=1;k<24;++k){co_await (*channel)[k].request();co_await move({id},{{30.2+k*.32,BeltHeight+Height/2,zz,0}},.6,"approved-zpa",true);(*channel)[k-1].release();}
    std::function<void()> releaseOutlet;
    if(!slot){
        while(!(slot=findSlot(lane,shade)))co_await demandChanged;
        reserveSlot(*slot,shade);
        releaseOutlet=[this,channel,&lane,shade]{(*channel)[23].release();--lane.bankCount[shade];mark();};
    }else releaseOutlet=[channel,&lane]{--lane.mixCount;(*channel)[23].release();};
    auto start=records[id].position;double targetZ=slot->station->z+(slot->column-4.5)*.075;
    co_await path(id,{{start[0],start[1],start[2]},{38.5,BeltHeight+Height/2,zz},{39.3,BeltHeight+Height/2,z},{40.6,BeltHeight+Height/2,z},
        {43.65,BeltHeight+Height/2,targetZ},{44.25,BeltHeight+Height/2,targetZ}},lane.id+6,1.2,"thirty-position-distribution",std::move(releaseOutlet));
    slot->id=id;slot->arrived=true;++lane.counts[shade];auto row=slot->station->current;
    if(row&&!row->ready->done&&std::all_of(row->slots.begin(),row->slots.end(),[](auto& s){return s.arrived;}))row->ready->succeed();wake();
}
Task Simulation::rejectDrop(int id,Lane& lane){
    double z=lane.z;
    co_await path(id,{{28.44,BeltHeight+Height/2,z+.58},{28.44,BeltHeight+Height/2,z+.92},{29.2,1.08,z+1.3},{30.25,.96,z+1.3}},100+lane.id,.8,"supported-reject-decline");
    int n=lane.rejected-1;double xx=31+(n%8-3.5)*Length,zz=z+1.3+((n/8)%10-4.5)*Depth,yy=.18+(n/80+.5)*Height;
    co_await move({id},{{xx,yy,zz,0}},1.,"bin-settling",true,.25);
}
}
