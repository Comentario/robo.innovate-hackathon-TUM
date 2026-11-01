#include "Simulation.h"
#include <chrono>
#include <iomanip>
#include <iostream>
#include <set>

int main(int argc,char** argv){
    try{
        std::string mode=argc>1?argv[1]:"mixed";
        brickflow::Simulation model(mode=="mixed"?std::vector<brickflow::Request>{}:std::vector<brickflow::Request>{{0,mode}});
        auto start=std::chrono::steady_clock::now();model.run();
        std::cerr<<"Native simulation: "<<model.clock.executed<<" events, "
            <<std::chrono::duration<double>(std::chrono::steady_clock::now()-start).count()<<" seconds\n";
        std::cout<<std::setprecision(17)<<"{\"mode\":\""<<mode<<"\",\"total\":"<<model.total
            <<",\"inspected\":"<<model.inspected<<",\"rejected\":"<<model.rejected
            <<",\"formed\":"<<model.formed<<",\"delivered\":"<<model.delivered
            <<",\"bph\":"<<model.bricksPerHour<<",\"pph\":"<<model.palletsPerHour
            <<",\"completeInput\":"<<(model.completeInput?"true":"false")<<",\"pallets\":[";
        bool first=true;
        for(const auto& p:model.pallets){
            if(!first)std::cout<<',';first=false;
            std::cout<<"{\"t\":"<<p.time<<",\"shade\":"<<p.shade<<",\"lane\":"<<p.lane
                <<",\"cart\":"<<p.cart<<",\"slot\":"<<p.slot<<",\"ids\":[";
            bool firstID=true;for(int id:p.ids){if(!firstID)std::cout<<',';firstID=false;std::cout<<model.records[id].id;}
            std::cout<<"]}";
        }
        std::cout<<"],\"samples\":[";
        bool firstSample=true;
        for(const std::string& Name:std::vector<std::string>{"0","760","799","800","10000","28799","head-0-0","row-0-0","stacker-0","dispatch","wood-0"}){
            auto Found=model.names.find(Name);if(Found==model.names.end())continue;int ID=Found->second;
            std::vector<double> Times{0,37,1200,2400,5000,model.total};std::set<std::string_view> Kinds;
            for(const auto& Track:model.records[ID].tracks)if(Kinds.insert(Track.kind).second){Times.push_back(Track.start);Times.push_back((Track.start+Track.end)/2);Times.push_back(Track.end);}
            for(double Time:Times){auto P=model.pose(ID,Time);if(!firstSample)std::cout<<',';firstSample=false;
                std::cout<<"{\"id\":\""<<Name<<"\",\"t\":"<<Time<<",\"pose\":["<<P[0]<<','<<P[1]<<','<<P[2]<<','<<P[3]<<"]}";}
        }
        std::cout<<"]}\n";
    }catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 1;}
}
