#pragma once
#include "EventRuntime.h"
#include <array>
#include <map>
#include <optional>
#include <string>
#include <string_view>
#include <unordered_map>

namespace brickflow {
using Pose = std::array<double,4>;
using Point = std::array<double,3>;
constexpr double Length=.245, Depth=.067, Height=.069, BeltHeight=1.25;
struct Rigid { Pose from,to; Point local; double yaw; };
struct Track {
    double start,end;
    Pose from,to;
    std::string_view kind;
    bool linear=false;
    std::shared_ptr<std::vector<Point>> path;
    std::shared_ptr<Rigid> rigid;
};
struct Record {
    std::string id,kind;
    Pose initial,position;
    std::vector<Track> tracks;
    double visible=0;
    int c=0,j=0,layer=0,row=0,column=0,shade=0;
    bool good=true,extreme=false;
    // Adapter data is retained independently of the synthetic demo classifier.
    std::optional<double> producerScore;
    std::string producerGroup;
};
struct Request { double time; std::string mode; };
struct Station;
struct Job;
struct Phase;
struct Slot {
    Station* station;
    Job* job;
    int layer,row,column,shade;
    bool reserved=false,arrived=false;
    int id=-1;
};
struct Row { std::vector<Slot> slots; Signal ready; };
struct ReadyLayer { Station* station; Job* job; std::vector<int> ids; int layer; };
struct Lane {
    int id,group,side;
    double z;
    std::array<Resource,8> inspection;
    std::array<Resource,24> main;
    std::array<std::array<std::array<Resource,24>,3>,3> bank;
    std::array<Resource,3> branches;
    Resource routing,reject;
    std::array<std::unique_ptr<Station>,3> stations;
    Phase* plan=nullptr;
    Signal sideFree;
    std::vector<ReadyLayer> ready;
    std::array<int,3> bankCount{},bankPeaks{},counts{};
    int mixCount=0,inspected=0,rejected=0;
    // Shared continuously driven V2 belt, with one reserved admission.
    std::deque<int> beltIDs;
    std::deque<Signal> beltRequests;
    bool beltReserved=false;
    std::optional<double> beltStepEnd;
};
struct Station {
    Lane* lane;
    int id,pusher;
    double z;
    std::shared_ptr<Row> current;
    Resource first,second;
};
struct Job {
    Lane* lane;
    Phase* phase;
    int well,shade=-1,assigned=0,stacked=0,wood=-1;
    std::vector<std::array<int,40>> grids;
    std::vector<int> ids;
    Signal prepared,closed;
};
struct Phase {
    std::string mode;
    Signal done;
    std::vector<std::unique_ptr<Job>> jobs;
};
struct Pallet { double time; std::vector<int> ids; int shade,lane,cart,slot; };
struct Layer { double time; std::vector<int> ids; int shade,lane,station; };
struct Metrics {
    double time=0;
    int inspected=0,rejected=0,formed=0,delivered=0,cycles=0;
    std::array<std::array<int,3>,6> banks{};
};

class Simulation {
public:
    Clock clock;
    Signal changed,demandChanged;
    std::vector<Request> requests;
    std::deque<Record> records;
    std::unordered_map<std::string,int> names;
    std::vector<int> bricks,actors,heads,rowHeads;
    std::vector<Metrics> history;
    std::vector<Pallet> pallets;
    std::vector<Layer> layers;
    std::array<std::unique_ptr<Lane>,6> lanes;
    int inspected=0,rejected=0,formed=0,delivered=0,headCycles=0;
    double total=0,bricksPerHour=0,palletsPerHour=0;
    bool completeInput=false,sourceFinished=false;
    explicit Simulation(std::vector<Request> recipeRequests={});
    void run();
    Pose pose(int id,double time) const;
    const Track* segment(int id,double time) const;
    Metrics metrics(double time) const;
    int named(const std::string& id) const;
    void wake();
    void wakeDemand();
    void mark();
private:
    std::uint32_t seed=8;
    int woods=0,cartSlots=0;
    std::array<Signal,3> layerLoadFree,extractionFree;
    std::vector<std::unique_ptr<Phase>> phases;
    Resource dispatch;
    std::map<int,std::unordered_map<std::string,int>> matrices;
    double random();
    int add(std::string id,Pose p,std::string kind);
    void append(int id,Pose to,double time,double duration,std::string_view kind,
                bool linear=false,std::shared_ptr<std::vector<Point>> path={},
                std::shared_ptr<Rigid> rigid={});
    Task move(std::vector<int> ids,std::vector<Pose> targets,double speed,
              std::string_view kind,bool linear=false,double minimum=0);
    struct Group { int head; std::vector<int> ids; Pose target; int c=0,j=0; Lane* lane=nullptr; };
    Task carry(std::vector<Group> groups,double speed,std::string_view kind);
    Task path(int id,std::vector<Point> points,int matrix,double speed,
              std::string_view kind,std::function<void()> release={});
    Task source();
    Task mainBatch(int group,std::vector<Group> batch,int cycle);
    Task feedSide(Lane& lane,std::vector<int> ids);
    Task sharedBelt(Lane& lane);
    Signal reserveBelt(Lane& lane);
    Signal loadBelt(Lane& lane,int id);
    Task inspectBrick(int id,Lane& lane);
    Task rejectDrop(int id,Lane& lane);
    bool canPlace(const Slot& slot,int shade) const;
    Slot* findSlot(Lane& lane,int shade);
    void reserveSlot(Slot& slot,int shade);
    std::string policy() const;
    Phase& ensurePhase(Lane& lane);
    Task prepare(Job& job);
    Task formStation(Station& station);
    Task bufferedLayer(Station& station,Job& job,std::vector<int> ids,int layer);
    Task stackLane(Lane& lane);
    Task dispatchPallet(Job& job);
};
}
