#include <cmath>
#include <chrono>
#include <thread>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <stdexcept>
#include <string>
#include <franka/gripper.h>
#include <franka/robot.h>

// Explicit finger-position command only. No homing, recovery or arm motion.
int main(int argc,char** argv) {
  if(argc==2 && std::string(argv[1])=="--state") {
    try { franka::Gripper hand("172.16.0.2");std::cout<<std::setprecision(17)<<hand.readOnce()<<'\n';return 0; }
    catch(const std::exception& e) {std::cerr<<e.what()<<'\n';return 1;}
  }
  if(argc!=3 || std::string(argv[2])!="--execute")return 2;
  std::cout<<std::unitbuf<<std::setprecision(17);
  try {
    std::ifstream input(argv[1]);double width=0,speed=0,tolerance=0,contact_upper=0;int approach=0;
    input>>width>>speed>>tolerance>>approach;
    if(approach==2)input>>contact_upper;
    if(!input || !std::isfinite(width) || !std::isfinite(speed) || !std::isfinite(tolerance) ||
       width<0 || width>.08 || speed<=0 || speed>.1 || tolerance<=0 || tolerance>.001 || (approach<0||approach>2) || (approach==2&&(!std::isfinite(contact_upper)||contact_upper<width||contact_upper>.08)))
      throw std::runtime_error("Invalid gripper position command");
    franka::Robot arm("172.16.0.2",franka::RealtimeConfig::kIgnore);
    auto state=arm.readOnce();
    if(state.robot_mode!=franka::RobotMode::kIdle || state.current_errors)
      throw std::runtime_error("Gripper command requires an idle, fault-free arm");
    for(double velocity:state.dq)if(!std::isfinite(velocity)||std::abs(velocity)>.01)
      throw std::runtime_error("Arm is not stationary");
    franka::Gripper gripper("172.16.0.2");const auto before=gripper.readOnce();
    std::cout<<"START_GRIPPER "<<before<<'\n';
    if(!std::isfinite(before.max_width)||before.max_width<width)
      throw std::runtime_error("Requested opening exceeds the calibrated gripper range; no homing was sent");
    if(approach==1 && before.is_grasped)
      throw std::runtime_error("Gripper reports a held object; complete its placement before a new grasp approach");
    bool moved=false;
    if(std::abs(before.width-width)>tolerance) {
      moved=true;
      if(!gripper.move(width,speed))throw std::runtime_error("Finger position command did not complete");
    }
    auto after=gripper.readOnce();
    using Clock=std::chrono::steady_clock;
    const auto deadline=Clock::now()+std::chrono::seconds(2);
    auto stable_since=Clock::now();bool stable=false,inside=false;
    while(Clock::now()<deadline) {
      const auto now=Clock::now();
      if(std::isfinite(after.width)&&(approach==2 ? after.width>=width-tolerance&&after.width<=contact_upper : std::abs(after.width-width)<=tolerance)) {
        if(!inside) {inside=true;stable_since=now;}
        if(now-stable_since>=std::chrono::milliseconds(100)) {stable=true;break;}
      } else inside=false;
      std::this_thread::sleep_for(std::chrono::milliseconds(10));after=gripper.readOnce();
    }
    std::cout<<"FINAL_GRIPPER "<<after<<'\n';
    if(!stable)
      throw std::runtime_error("Gripper opening verification failed");
    if(approach==2)std::cout<<"POSITION_CLOSE_CONTACT_RANGE max_m "<<contact_upper<<"; object presence is not inferred from finger width\n";
    std::cout<<"WIDTH_VERIFIED target_m "<<width<<" actual_m "<<after.width<<" moved "<<moved<<"\nPASS gripper width\n";
  } catch(const std::exception& e) {std::cerr<<"STOP "<<e.what()<<'\n';return 1;}
}
