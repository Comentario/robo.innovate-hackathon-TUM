#include <algorithm>
#include <array>
#include <cmath>
#include <iomanip>
#include <iostream>
#include <stdexcept>
#include <franka/robot.h>

// Read-only: no control, configuration, recovery, homing or gripper calls.
int main() {
  try {
    franka::Robot robot("172.16.0.2", franka::RealtimeConfig::kIgnore);
    franka::RobotState first{}, last{};
    bool started=false;
    uint64_t begin_ms=0;
    double max_speed=0, max_drift=0, max_tcp_drift=0;
    robot.read([&](const franka::RobotState& s) {
      if (!started) { first=s; begin_ms=s.time.toMSec(); started=true; }
      if (s.current_errors || (s.robot_mode!=franka::RobotMode::kIdle &&
                              s.robot_mode!=franka::RobotMode::kGuiding))
        throw std::runtime_error("Recording requires idle or stationary guiding mode, without faults.");
      for(int i=0;i<7;++i) {
        if (!std::isfinite(s.q[i]) || !std::isfinite(s.dq[i]))
          throw std::runtime_error("Non-finite joint state.");
        max_speed=std::max(max_speed,std::abs(s.dq[i]));
        max_drift=std::max(max_drift,std::abs(s.q[i]-first.q[i]));
      }
      double d=0;
      for(int i=12;i<15;++i) {
        if(!std::isfinite(s.O_T_EE[i])) throw std::runtime_error("Non-finite TCP state.");
        d+=std::pow(s.O_T_EE[i]-first.O_T_EE[i],2);
      }
      max_tcp_drift=std::max(max_tcp_drift,std::sqrt(d));
      last=s;
      return s.time.toMSec()-begin_ms<500;
    });
    if(max_speed>0.01 || max_drift>0.001 || max_tcp_drift>0.0005)
      throw std::runtime_error("Arm moved during recording; hold stationary and record again.");
    std::cout << std::setprecision(17) << "{\"state\":" << last
              << ",\"stationary_check\":{\"duration_ms\":" << last.time.toMSec()-begin_ms
              << ",\"max_joint_speed_rad_s\":" << max_speed
              << ",\"max_joint_drift_rad\":" << max_drift
              << ",\"max_tcp_drift_m\":" << max_tcp_drift << "}}\n";
  } catch(const std::exception& e) { std::cerr << e.what() << '\n'; return 1; }
}
