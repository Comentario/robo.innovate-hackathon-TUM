#include "Simulation.h"
#include <chrono>
#include <iomanip>
#include <iostream>

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
        std::cout<<"]}\n";
    }catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 1;}
}
