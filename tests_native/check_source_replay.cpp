#include "../unreal/Brickflow/Source/Brickflow/Core/SourceReplay.h"
#include <fstream>
#include <sstream>
#include <iostream>
#include <cmath>
#include <algorithm>
int main(int argc,char**argv){try{
    if(argc!=3)return 2;brickflow::replay::Replay replay;replay.load(argv[1]);std::ifstream f(argv[2]);std::string line;double maximum=0;int samples=0;
    while(std::getline(f,line)){std::stringstream in(line);std::string id,cell;std::getline(in,id,',');std::getline(in,cell,',');const double t=std::stod(cell);auto s=replay.state(replay.named(id),t);
        for(int j=0;j<7;++j){std::getline(in,cell,',');const double actual=j<4?s.pose[j]:s.normal[j-4];maximum=std::max(maximum,std::abs(actual-std::stod(cell)));}
        std::getline(in,cell,',');if(s.visible!=(std::stoi(cell)!=0))throw std::runtime_error("Visibility mismatch: "+id);++samples;}
    if(samples<1000||maximum>1e-6)throw std::runtime_error("Source pose audit failed");
    std::cout<<"{\"verified\":true,\"samples\":"<<samples<<",\"maximumPoseErrorMetres\":"<<maximum<<",\"records\":"<<replay.records.size()<<",\"tracks\":"<<replay.trackCount<<",\"backend\":\"native-cpp-source-replay\",\"independentNativePlanner\":false}\n";
    return 0;
}catch(const std::exception&e){std::cerr<<e.what()<<'\n';return 1;}}
