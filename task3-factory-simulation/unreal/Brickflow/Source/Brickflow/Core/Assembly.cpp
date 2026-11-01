#include "Simulation.h"
#include <algorithm>
#include <cmath>
#include <set>

namespace brickflow {
namespace {
std::string tag(const char* name,int a,int b){return std::string(name)+std::to_string(a)+"-"+std::to_string(b);}
template<class F>std::vector<Pose> positions(const std::vector<int>& ids,F fn){std::vector<Pose> out;for(std::size_t k=0;k<ids.size();++k)out.push_back(fn(ids[k],int(k)));return out;}
}
bool Simulation::canPlace(const Slot& slot,int shade) const {
    if(slot.job->shade>=0)return slot.job->shade==shade;
    const auto& grid=slot.job->grids[slot.layer];int index=slot.row*10+slot.column;
    for(int stride:{1,10})for(int offset=-2;offset<=0;++offset){
        std::array<int,3> p{index+offset*stride,index+(offset+1)*stride,index+(offset+2)*stride};
        if(std::any_of(p.begin(),p.end(),[&](int i){return i<0||i>=40||(stride==1&&i/10!=slot.row);}))continue;
        if(std::all_of(p.begin(),p.end(),[&](int i){return i==index||grid[i]==shade;}))return false;
    }
    return true;
}
void Simulation::reserveSlot(Slot& slot,int shade){
    if(slot.reserved||!canPlace(slot,shade))throw std::runtime_error("Invalid row reservation");
    slot.shade=shade;slot.job->grids[slot.layer][slot.row*10+slot.column]=shade;slot.reserved=true;
}
Slot* Simulation::findSlot(Lane& lane,int shade){
    std::vector<Slot*> choices;for(auto& st:lane.stations)if(st->current)for(auto& slot:st->current->slots)if(!slot.reserved&&canPlace(slot,shade))choices.push_back(&slot);
    auto filled=[](const Slot* s){return int(std::count_if(s->station->current->slots.begin(),s->station->current->slots.end(),[](auto& x){return x.reserved;}));};
    std::stable_sort(choices.begin(),choices.end(),[&](auto a,auto b){
        if((a->shade==shade)!=(b->shade==shade))return a->shade==shade;
        int na=filled(a),nb=filled(b);if(na!=nb)return na>nb;
        if(a->station->id!=b->station->id)return a->station->id<b->station->id;
        return std::abs(a->column-4.5)<std::abs(b->column-4.5);
    });
    return choices.empty()?nullptr:choices.front();
}
std::string Simulation::policy() const {std::string value="mixed";for(const auto& r:requests)if(r.time<=clock.now)value=r.mode;return value;}
Phase& Simulation::ensurePhase(Lane& lane){
    if(lane.plan&&!lane.plan->done->done)return *lane.plan;
    auto phase=std::make_unique<Phase>();phase->mode=policy();phase->done=signal(clock);
    auto* p=phase.get();bool mono=p->mode!="mixed";
    std::vector<int> colours;
    if(p->mode=="single")colours={0,1,2};
    else{int shade=p->mode=="Copper"?1:p->mode=="Russet"?2:0;colours={shade};}
    std::vector<int> wells=mono&&p->mode=="single"?std::vector<int>{0,1,2}:std::vector<int>{1};
    for(std::size_t k=0;k<wells.size();++k){
        auto job=std::make_unique<Job>();job->lane=&lane;job->phase=p;job->well=wells[k];job->shade=mono?colours[k]:-1;
        job->prepared=signal(clock);job->closed=signal(clock);p->jobs.push_back(std::move(job));
    }
    lane.plan=p;phases.push_back(std::move(phase));for(auto& job:p->jobs)clock.spawn(prepare(*job));wake();return *p;
}
Task Simulation::prepare(Job& job){
    double z=job.lane->stations[job.well]->z;int wood=add("wood-"+std::to_string(woods++),{51.1,.224,z,0},"pallet");job.wood=wood;records[wood].visible=clock.now;
    co_await move({wood},{{53,.224,z,0}},.5,"empty-pallet-feed");
    co_await move({wood,named(tag("deck-",job.lane->id,job.well))},{{53,BeltHeight-.06,z,0},{53,BeltHeight-.12,z,0}},.15,"raise-pallet-well");
    job.prepared->succeed();wake();
}
Task Simulation::formStation(Station& st){
    auto& lane=*st.lane;
    while(true){
        auto& phase=ensurePhase(lane);auto& job=*phase.jobs[phase.jobs.size()==3?st.id:0];
        if(job.assigned>=14){co_await phase.done;continue;}
        int layer=job.assigned++;std::array<int,40> grid;grid.fill(-1);job.grids.push_back(grid);
        std::array<int,40> pattern;for(int k=0;k<40;++k)pattern[k]=job.shade<0?(k/10+k%10+layer)%3:job.shade;
        std::vector<int> ids;
        for(int row=0;row<4;++row){
            auto current=std::make_shared<Row>();current->ready=signal(clock);
            for(int col=0;col<10;++col)current->slots.push_back({&st,&job,layer,row,col,pattern[row*10+col]});
            st.current=current;wakeDemand();co_await current->ready;
            std::vector<int> rowIDs;for(const auto& slot:current->slots)rowIDs.push_back(slot.id);
            co_await move(rowIDs,positions(rowIDs,[&](int,int k){return Pose{44.25,BeltHeight+Height/2,st.z+(k-4.5)*Depth,0};}),.2,"guided-row-centering",false,.25);
            int tool=st.pusher;
            co_await move({tool},{{44.25-Length/2-.014,BeltHeight+.035,st.z,0}},.6,"lower-rigid-row-paddle");
            double x=46+(1.5-row)*Length;auto moving=rowIDs;moving.push_back(tool);
            auto to=positions(rowIDs,[&](int,int k){return Pose{x,BeltHeight+Height/2,st.z+(k-4.5)*Depth,0};});to.push_back({x-Length/2-.014,BeltHeight+.035,st.z,0});
            co_await move(moving,to,1.2,"push-complete-row");
            co_await move({tool},{{x-Length/2-.014,BeltHeight+.30,st.z,0}},.6,"raise-row-paddle");
            co_await move({tool},{{44.25-Length/2-.014,BeltHeight+.30,st.z,0}},1.2,"retract-raised-paddle");
            ids.insert(ids.end(),rowIDs.begin(),rowIDs.end());st.current.reset();wake();
        }
        formed+=40;layers.push_back({clock.now,ids,job.shade,lane.id,st.id});mark();co_await st.first.request();
        co_await move(ids,positions(ids,[&](int id,int){auto p=records[id].position;p[0]+=1.5;return p;}),.5,"layer-buffer-zone-one");
        clock.spawn(bufferedLayer(st,job,std::move(ids),layer));
    }
}
Task Simulation::bufferedLayer(Station& st,Job& job,std::vector<int> ids,int layer){
    co_await st.second.request();
    co_await move(ids,positions(ids,[&](int id,int){auto p=records[id].position;p[0]+=1.5;return p;}),.5,"layer-buffer-zone-two");
    st.first.release();st.lane->ready.push_back({&st,&job,std::move(ids),layer});wake();
}
Task Simulation::stackLane(Lane& lane){
    int tool=named("stacker-"+std::to_string(lane.id));
    while(true){
        auto find=[&]{return std::find_if(lane.ready.begin(),lane.ready.end(),[](auto& r){return r.layer==r.job->stacked;});};
        while(find()==lane.ready.end())co_await changed;
        auto it=find();ReadyLayer item=std::move(*it);lane.ready.erase(it);auto& st=*item.station;auto& job=*item.job;auto& ids=item.ids;
        co_await job.prepared;double z=st.z;
        co_await move({tool},{{49,2.8,z,0}},1.25,"stacker-empty-traverse");
        co_await move({tool},{{49,BeltHeight+Height/2,z,0}},.7,"stacker-pickup");co_await clock.sleep(.2);
        co_await carry({Group{tool,ids,{49,2.8,z,0}}},.7,"lift-complete-layer");st.second.release();
        double wellZ=lane.stations[job.well]->z;
        co_await carry({Group{tool,ids,{53,2.8,wellZ,0}}},1.25,"transfer-complete-layer");
        co_await carry({Group{tool,ids,{53,BeltHeight+Height/2,wellZ,0}}},.7,"place-guided-layer");co_await clock.sleep(.2);
        co_await move({tool},{{53,2.8,wellZ,0}},.7,"raise-empty-stacker");
        std::vector<int> jaws;for(int side:{-1,1})jaws.push_back(named(tag("jaw-",lane.id,job.well)+"-"+std::to_string(side)));
        co_await move(jaws,{{53,BeltHeight+.045,wellZ-.37,0},{53,BeltHeight+.045,wellZ+.37,0}},.4,"center-placed-layer");co_await clock.sleep(.15);
        co_await move(jaws,{{53,BeltHeight+.045,wellZ-.48,0},{53,BeltHeight+.045,wellZ+.48,0}},.4,"release-layer-centering");
        job.ids.insert(job.ids.end(),ids.begin(),ids.end());++job.stacked;
        auto moving=job.ids;moving.push_back(job.wood);moving.push_back(named(tag("deck-",lane.id,job.well)));
        co_await move(moving,positions(moving,[&](int id,int){auto p=records[id].position;p[1]-=Height;return p;}),.15,"guided-one-layer-lowering");
        if(job.stacked==14){
            if(job.ids.size()!=560||std::set<int>(job.ids.begin(),job.ids.end()).size()!=560)throw std::runtime_error("Invalid pallet count");
            if(job.shade>=0&&std::any_of(job.ids.begin(),job.ids.end(),[&](int id){return records[id].shade!=job.shade;}))throw std::runtime_error("Impure single-colour pallet");
            co_await lane.branches[job.well].request();int gate=named(tag("gate-",lane.id,job.well));
            co_await move({gate},{{53.65,2.3,wellZ,0}},.5,"raise-outfeed-gate");
            auto pack=job.ids;pack.push_back(job.wood);
            co_await move(pack,positions(pack,[&](int id,int){auto p=records[id].position;p[0]+=4;return p;}),.5,"finished-pallet-outfeed");
            clock.spawn(dispatchPallet(job));
            co_await move({gate},{{53.65,1.3,wellZ,0}},.5,"close-outfeed-gate");job.closed->succeed();
            if(std::all_of(job.phase->jobs.begin(),job.phase->jobs.end(),[](auto& j){return j->closed->done;})){job.phase->done->succeed();wake();}
        }
    }
}
Task Simulation::dispatchPallet(Job& job){
    co_await dispatch.request();int tool=named("dispatch");auto ids=job.ids;ids.push_back(job.wood);auto source=records[job.wood].position;
    int n=cartSlots++,cart=n/36,slot=n%36;Pose target{63+(5-slot%6)*1.4,.36,(cart?5:-5)+(slot/6-2.5)*1.1,0};double height=.96;
    co_await move({tool},{{57,3.,source[2],0}},1.25,"finished-frame-approach");
    co_await move({tool},{{57,source[1]+height,source[2],0}},.6,"lower-pallet-lifting-frame");co_await clock.sleep(.3);
    co_await carry({Group{tool,ids,{57,3.,source[2],0}}},.6,"lift-supported-output-pallet");job.lane->branches[job.well].release();
    co_await carry({Group{tool,ids,{target[0],3.,target[2],0}}},1.25,"finished-pallet-bridge");
    co_await carry({Group{tool,ids,{target[0],target[1]+height,target[2],0}}},.6,"lower-pallet-on-transport-cart");co_await clock.sleep(.2);
    ++delivered;pallets.push_back({clock.now,job.ids,job.shade,job.lane->id,cart,slot});mark();
    co_await move({tool},{{target[0],3.,target[2],0}},.6,"raise-empty-finished-frame");dispatch.release();
}
}
