#pragma once
#include <array>
#include <cstdint>
#include <string>
#include <vector>
#include <unordered_map>

namespace brickflow::replay {
using Pose=std::array<double,4>;
using Point=std::array<double,3>;
struct State {Pose pose{};Point normal{0,1,0};bool visible=false;};
struct Rigid {Pose from{},to{};Point local{};double yaw=0;};
struct Track {
    double start=0,end=0;Pose from{},to{};std::uint16_t kind=0,flags=0;
    std::vector<Point> path;std::vector<double> cumulative;double length=0;Rigid rigid;
};
struct Record {
    std::string id,kind,producerGroup;Pose initial{};
    double visible=0,hidden=1e100,producerScore=0;
    int cart=-1,c=-1,j=-1,layer=-1,row=-1,column=-1,shade=-1;
    bool good=true,extreme=false;std::vector<Track> tracks;
};
class Replay {
public:
    std::vector<Record> records;std::vector<std::string> kinds;std::unordered_map<std::string,int> names;
    std::uint64_t trackCount=0;
    void load(const std::string& file);
    int named(const std::string& name) const;
    const Track* segment(int id,double time) const;
    State state(int id,double time) const;
    const std::string& kind(const Track* track) const;
};
}
