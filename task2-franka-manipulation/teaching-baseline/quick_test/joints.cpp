#include <algorithm>
#include <array>
#include <cmath>
#include <csignal>
#include <exception>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <stdexcept>
#include <string>
#include <franka/model.h>
#include <franka/robot.h>

// Initial hardware check only. No homing, gripper, recovery, or safety-setting changes.
using Q = std::array<double, 7>;
using Pose = std::array<double, 16>;
constexpr Q lower{-2.7437,-1.7837,-2.9007,-3.0421,-2.8065,0.5445,-3.0159};
constexpr Q upper{2.7437,1.7837,2.9007,-0.1518,2.8065,4.5169,3.0159};
volatile std::sig_atomic_t interrupted=0;
void interrupt(int) { interrupted=1; }
double distance(const Pose& a, const Pose& b) {
  return std::hypot(std::hypot(a[12]-b[12], a[13]-b[13]), a[14]-b[14]);
}
double blend(double u) {
  u=std::clamp(u,0.0,1.0);
  return u*u*u*(10+u*(-15+6*u));
}
void ready(const franka::RobotState& s) {
  if (s.robot_mode != franka::RobotMode::kIdle || s.current_errors)
    throw std::runtime_error("Robot must be idle and fault-free; no automatic recovery.");
  if (!std::isfinite(s.m_ee) || s.m_ee < 0.2)
    throw std::runtime_error("Check configured attached tool mass.");
  for (int j=0;j<7;++j)
    if (!std::isfinite(s.q[j]) || std::abs(s.q[j]-s.q_d[j])>0.003 ||
        std::abs(s.dq[j])>0.01 || s.q[j]<lower[j]+0.05 || s.q[j]>upper[j]-0.05)
      throw std::runtime_error("Joint state, stationary check, or FR3 joint-limit margin failed.");
}
int main(int argc, char** argv) {
  const bool execute=argc==2 && std::string(argv[1])=="--execute";
  if (argc!=2 || (!execute && std::string(argv[1])!="--preview")) return 2;
  std::cout << std::setprecision(9) << std::unitbuf;
  std::signal(SIGINT,interrupt);
  std::signal(SIGTERM,interrupt);
  try {
    franka::Robot robot("172.16.0.2",franka::RealtimeConfig::kEnforce);
    auto initial=robot.readOnce();
    ready(initial);
    auto model=robot.loadModel();
    auto fk=[&](const Q& q) { return model.pose(franka::Frame::kEndEffector,q,initial.F_T_EE,initial.EE_T_K); };
    const auto origin=fk(initial.q_d);
    if (distance(origin,initial.O_T_EE)>0.003)
      throw std::runtime_error("Robot FK and measured TCP disagree by more than 3 mm.");
    Q deltas{};
    std::cout << "TCP_start_m " << initial.O_T_EE[12] << ' ' << initial.O_T_EE[13] << ' ' << initial.O_T_EE[14]
              << " tool_mass_kg " << initial.m_ee << " payload_kg " << initial.m_load << '\n';
    std::cout << "Q_start_rad";
    for(double q:initial.q) std::cout << ' ' << q;
    std::cout << '\n';
    for (int j=0;j<7;++j) {
      Q plus=initial.q_d, minus=initial.q_d;
      plus[j]+=0.1; minus[j]-=0.1;
      double dz=fk(plus)[14]-fk(minus)[14];
      deltas[j]=std::abs(dz)>1e-5 ? (dz>0 ? 0.1:-0.1) :
          (initial.q_d[j]<(lower[j]+upper[j])/2 ? 0.1:-0.1);
      double peak=0, min_z=origin[14];
      for(int k=0;k<=100;++k) {
        Q q=initial.q_d; q[j]+=deltas[j]*k/100.0;
        if(q[j]<lower[j]+0.05 || q[j]>upper[j]-0.05)
          throw std::runtime_error("Planned joint excursion exceeds joint-limit margin.");
        auto p=fk(q); peak=std::max(peak,distance(p,origin)); min_z=std::min(min_z,p[14]);
      }
      if(peak>0.075 || min_z<origin[14]-1e-7)
        throw std::runtime_error("Planned path exceeds 75 mm TCP margin or lowers TCP.");
      std::cout << "PLAN joint " << j+1 << " delta_rad " << deltas[j] << " predicted_peak_mm " << peak*1000
                << " endpoint_dz_mm " << (fk([&]{Q q=initial.q_d;q[j]+=deltas[j];return q;}())[14]-origin[14])*1000 << '\n';
    }
    if(!execute) { std::cout << "PREVIEW_ONLY no motion sent\n"; return 0; }
    std::ofstream trace("quick_test/joint_trace.csv");
    trace << "joint,time_s,tcp_displacement_m,joint_delta_rad,command_success_rate\n";
    // Store sparse samples in a fixed buffer; no file I/O or allocation in control callback.
    struct Sample { double t, d, q, rate; };
    for(int j=0;j<7;++j) {
      auto before=robot.readOnce(); ready(before);
      for(int k=0;k<7;++k)
        if(std::abs(before.q_d[k]-initial.q_d[k])>0.001)
          throw std::runtime_error("Commanded joint start drifted; stop.");
      if(distance(before.O_T_EE,initial.O_T_EE)>0.003)
        throw std::runtime_error("TCP failed to return within 3 mm of original start.");
      std::array<Sample,700> samples{}; size_t count=0;
      double elapsed=0, peak_tcp=0, peak_joint=0, min_rate=1;
      bool first=true;
      std::exception_ptr control_error;
      std::cout << "START joint " << j+1 << " out_6s back_6s settle_0.5s\n";
      try {
      robot.control([&](const franka::RobotState& s, franka::Duration period)->franka::JointPositions {
        if(first) first=false; else elapsed+=period.toSec();
        const double d=distance(s.O_T_EE,initial.O_T_EE);
        peak_tcp=std::max(peak_tcp,d);
        peak_joint=std::max(peak_joint,std::abs(s.q[j]-before.q[j]));
        if(elapsed>0.1) min_rate=std::min(min_rate,s.control_command_success_rate);
        if(interrupted || s.current_errors || !std::isfinite(d) || d>0.100 ||
            s.O_T_EE[14]<initial.O_T_EE[14]-0.002)
          throw std::runtime_error("Interrupted, robot fault, 100 mm TCP bound or 2 mm downward tracking margin exceeded.");
        for(int k=0;k<7;++k)
          if(!std::isfinite(s.q[k]) || s.q[k]<lower[k]+0.02 || s.q[k]>upper[k]-0.02 ||
              std::abs(s.q[k]-s.q_d[k])>0.02)
            throw std::runtime_error("Measured joint limit or tracking bound exceeded.");
        if(count<samples.size() && elapsed>=count*0.02)
          samples[count++]={elapsed,d,s.q[j]-before.q[j],s.control_command_success_rate};
        Q target=before.q_d;
        target[j]+=deltas[j]*(elapsed<=6 ? blend(elapsed/6):1-blend((elapsed-6)/6));
        franka::JointPositions command(target);
        if(elapsed>=12.5) return franka::MotionFinished(command);
        return command;
      },franka::ControllerMode::kJointImpedance,true,100.0);
      } catch(...) { control_error=std::current_exception(); }
      for(size_t k=0;k<count;++k) trace << j+1 << ',' << samples[k].t << ',' << samples[k].d << ',' << samples[k].q << ',' << samples[k].rate << '\n';
      trace.flush();
      if(control_error) std::rethrow_exception(control_error);
      auto after=robot.readOnce(); ready(after);
      double joint_return=0;
      for(int k=0;k<7;++k) joint_return=std::max(joint_return,std::abs(after.q[k]-initial.q[k]));
      const double tcp_return=distance(after.O_T_EE,initial.O_T_EE);
      std::cout << "RESULT joint " << j+1 << " peak_tcp_mm " << peak_tcp*1000
                << " peak_joint_rad " << peak_joint << " return_tcp_mm " << tcp_return*1000
                << " return_joint_max_rad " << joint_return << " min_command_success_rate " << min_rate << '\n';
      if(peak_joint<0.09 || peak_joint>0.115 || joint_return>0.003 || tcp_return>0.003)
        throw std::runtime_error("Excursion or return verification failed; stop.");
      std::cout << "PASS joint " << j+1 << '\n';
    }
    std::cout << "PASS all 7 joints; returned to initial pose.\n";
  } catch(const std::exception& e) { std::cerr << "STOP " << e.what() << '\n'; return 1; }
}
