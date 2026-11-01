#include <fstream>
#include <iomanip>
#include <iostream>
#include <franka/robot.h>
// Read-only model/state export. No control or configuration commands.
int main() {
  try {
    franka::Robot robot("172.16.0.2",franka::RealtimeConfig::kIgnore);
    const std::string urdf=robot.getRobotModel();
    std::ofstream model("teaching/robot_model.urdf");model<<urdf;
    std::ofstream state("teaching/robot_model_state.json");state<<std::setprecision(17)<<robot.readOnce()<<'\n';
    if(!model || !state) return 1;
    std::cout<<"Exported connected robot model and state; no motion. Model bytes: "<<urdf.size()<<'\n';
  } catch(const std::exception& e) {std::cerr<<e.what()<<'\n';return 1;}
}
