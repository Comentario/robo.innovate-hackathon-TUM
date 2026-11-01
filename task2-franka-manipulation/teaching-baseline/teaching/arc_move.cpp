#include <algorithm>
#include <array>
#include <atomic>
#include <chrono>
#include <cmath>
#include <csignal>
#include <exception>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <stdexcept>
#include <thread>
#include <vector>
#include <pthread.h>
#include <sched.h>
#include <sys/mman.h>
#include <Eigen/Geometry>
#include <franka/robot.h>

using Pose=std::array<double,16>;
using Point=Eigen::Vector3d;
using Curve=std::array<Point,6>;
constexpr std::array<double,7> lo{-2.7437,-1.7837,-2.9007,-3.0421,-2.8065,.5445,-3.0159};
constexpr std::array<double,7> hi{2.7437,1.7837,2.9007,-.1518,2.8065,4.5169,3.0159};
volatile std::sig_atomic_t interrupted=0;
void stop(int) { interrupted=1; }
double blend(double u) { u=std::clamp(u,0.0,1.0);return u*u*u*(10+u*(-15+6*u)); }
Point xyz(const Pose& p) { return {p[12],p[13],p[14]}; }
Eigen::Quaterniond orientation(const Pose& p) {
  Eigen::Matrix3d r;
  for(int c=0;c<3;++c) for(int i=0;i<3;++i) r(i,c)=p[4*c+i];
  Eigen::Quaterniond q(r);q.normalize();return q;
}
double angle(const Pose& a,const Pose& b) { return orientation(a).angularDistance(orientation(b)); }
Point bezier(Curve p,double u) {
  for(int count=5;count>0;--count) for(int k=0;k<count;++k) p[k]=(1-u)*p[k]+u*p[k+1];
  return p[0];
}
void check(const franka::RobotState& s,bool idle,double max_joint_speed=.20) {
  if(interrupted || s.current_errors || (idle && s.robot_mode!=franka::RobotMode::kIdle))
    throw std::runtime_error("Stop requested, robot fault or arm not idle.");
  for(int j=0;j<7;++j)
    if(!std::isfinite(s.q[j]) || !std::isfinite(s.dq[j]) || s.q[j]<lo[j]+.02 || s.q[j]>hi[j]-.02 ||
       std::abs(s.q[j]-s.q_d[j])>.02 || std::abs(s.dq[j])>(idle ? .01:max_joint_speed))
      throw std::runtime_error("Joint position, velocity, tracking or stationary bound exceeded.");
}
int main(int argc,char** argv) {
  if(argc!=4) return 2;
  const bool execute=std::string(argv[3])=="--execute";
  if(!execute && std::string(argv[3])!="--preview") return 2;
  if(execute) { std::cerr<<"STOP retired unverified Cartesian backend; use teaching/move_xyz.py\n";return 1; }
  std::cout<<std::unitbuf<<std::setprecision(17);
  std::signal(SIGINT,stop);std::signal(SIGTERM,stop);
  franka::RobotState last{};bool have_state=false;
  try {
    std::ifstream input(argv[1]);Pose expected{},target{},tool{};std::array<double,7> expected_q{};
    Curve control{};Point lower,upper;
    for(double& v:expected) input>>v;
    for(double& v:target) input>>v;
    for(double& v:tool) input>>v;
    for(double& v:expected_q) input>>v;
    for(auto& p:control) for(int a=0;a<3;++a) input>>p[a];
    for(int a=0;a<3;++a) input>>lower[a];
    for(int a=0;a<3;++a) input>>upper[a];
    double seconds=0,height=0,cutoff=0,position_tolerance=0,angle_tolerance=0,max_gap=0,max_speed=0,max_omega=0;
    int rate_limiting=0,control_cpu=0;double max_joint_speed=0,stable_required=0,start_timeout=0;
    input>>seconds>>height>>cutoff>>position_tolerance>>angle_tolerance>>max_gap>>max_speed>>max_omega>>rate_limiting;
    input>>max_joint_speed>>control_cpu>>stable_required>>start_timeout;
    if(!input || !std::isfinite(seconds) || seconds<1 || seconds>600 || height<=0 || height>.1000001 ||
       max_speed<=0 || max_speed>.4000001 || max_omega<=0 || max_omega>.3000001 ||
       max_joint_speed<=0 || max_joint_speed>1.0000001 || control_cpu<0 || control_cpu>=CPU_SETSIZE ||
       stable_required<.5 || start_timeout<stable_required || start_timeout>5)
      throw std::runtime_error("Invalid arc input, duration, standoff or speed limits.");
    Point path_min=control[0],path_max=control[0];
    for(const auto& p:control) {
      if(!p.allFinite() || (p.array()<lower.array()-1e-8).any() || (p.array()>upper.array()+1e-8).any())
        throw std::runtime_error("Arc control points exceed the cleared workspace.");
      path_min=path_min.cwiseMin(p);path_max=path_max.cwiseMax(p);
    }
    cpu_set_t cpu_set;CPU_ZERO(&cpu_set);CPU_SET(control_cpu,&cpu_set);
    if(sched_setaffinity(0,sizeof(cpu_set),&cpu_set)!=0)
      throw std::runtime_error("Cannot pin controller to configured CPU.");
    franka::Robot robot("172.16.0.2",franka::RealtimeConfig::kEnforce);
    const auto initial=robot.readOnce();last=initial;have_state=true;check(initial,true);
    if(!std::isfinite(initial.m_ee) || initial.m_ee<.2) throw std::runtime_error("Check configured attached tool mass.");
    for(int k=0;k<16;++k) if(std::abs(initial.F_T_EE[k]-tool[k])>1e-6)
      throw std::runtime_error("Configured tool frame changed since teaching.");
    for(int j=0;j<7;++j) if(std::abs(initial.q[j]-expected_q[j])>.01)
      throw std::runtime_error("Joint start changed since preflight.");
    if((xyz(initial.O_T_EE)-xyz(expected)).norm()>.002 || angle(initial.O_T_EE,expected)>.01746 ||
       (xyz(initial.O_T_EE)-xyz(initial.O_T_EE_c)).norm()>.002 || angle(initial.O_T_EE,initial.O_T_EE_c)>.01746)
      throw std::runtime_error("Start pose changed or measured/commanded reference mismatch.");
    std::cout<<"START_STATE "<<initial<<"\nPLAN continuous C2 arc; duration_s "<<seconds
             <<" guide_standoff_mm "<<height*1000<<" target_XYZ_m "<<target[12]<<' '<<target[13]<<' '<<target[14]<<'\n';
    if(!execute) { std::cout<<"PREVIEW_ONLY no motion sent\n";return 0; }
    struct Sample {double t;Point actual,command;double rate,period;};
    // Touch and lock sample pages before control; no allocation/page faults for logging.
    std::vector<Sample> samples(static_cast<size_t>((seconds+start_timeout+2)*50)+10);
    size_t sample_count=0;
    if(mlock(samples.data(),samples.size()*sizeof(Sample))!=0)
      throw std::runtime_error("Cannot lock preallocated trajectory logging memory.");
    std::ofstream trace(argv[2]);if(!trace) throw std::runtime_error("Cannot open arc trace.");
    trace<<"time_s,x_m,y_m,z_m,command_x_m,command_y_m,command_z_m,command_success_rate,period_s\n";
    double elapsed=0,min_rate=1,max_period=0,max_tracking=0,peak_z=initial.O_T_EE[14];
    double startup_elapsed=0,stable_elapsed=0,max_startup_period=0;
    bool first=true,warmed=false;Pose reference{};Eigen::Quaterniond qa,qb=orientation(target);
    const Point departure_offset=control[1]-control[0];
    std::atomic<double> progress{0};std::atomic<bool> done{false};
    std::atomic<bool> reporter_ready{false},reporter_valid{false};
    std::thread reporter([&] {
      // Robot construction raised the parent to FIFO priority. Explicitly demote
      // this logging thread so it cannot compete with the 1 kHz controller.
      sched_param ordinary{};
      reporter_valid.store(pthread_setschedparam(pthread_self(),SCHED_OTHER,&ordinary)==0);
      reporter_ready.store(true);
      int last_decile=0;
      while(!done.load()) {
        int decile=std::min(10,static_cast<int>(progress.load()*10));
        if(decile>last_decile) { std::cout<<"PROGRESS "<<decile*10<<"%\n";last_decile=decile; }
        std::this_thread::sleep_for(std::chrono::milliseconds(100));
      }
    });
    while(!reporter_ready.load()) std::this_thread::sleep_for(std::chrono::milliseconds(1));
    if(!reporter_valid.load()) { done.store(true);reporter.join();throw std::runtime_error("Cannot demote non-control reporting thread."); }
    std::exception_ptr error;
    try {
      robot.control([&](const franka::RobotState& s,franka::Duration period)->franka::CartesianPose {
        last=s;have_state=true;
        if(first) {
          reference=s.O_T_EE_c;qa=orientation(reference);
          if((xyz(reference)-control[0]).norm()>.002 || angle(reference,expected)>.01746)
            throw std::runtime_error("Control-start reference shifted beyond tolerance.");
          control[0]=xyz(reference);control[1]=control[2]=control[0]+departure_offset;
          first=false;
        }
        check(s,false,max_joint_speed);
        if(!warmed) {
          startup_elapsed+=period.toSec();max_startup_period=std::max(max_startup_period,period.toSec());
          if(period.toSec()<=max_gap) stable_elapsed+=period.toSec();else stable_elapsed=0;
          if(stable_elapsed>=stable_required) { warmed=true;elapsed=0; }
          else if(startup_elapsed>start_timeout) throw std::runtime_error("Stationary startup did not achieve stable callback timing.");
        } else {
          elapsed+=period.toSec();max_period=std::max(max_period,period.toSec());
          if(period.toSec()>max_gap) throw std::runtime_error("Callback timing gap exceeded bound.");
        }
        const Point measured=xyz(s.O_T_EE);
        if(!measured.allFinite() || (measured.array()<lower.array()-.003).any() || (measured.array()>upper.array()+.003).any() ||
           (measured.array()<path_min.array()-.003).any() || (measured.array()>path_max.array()+.003).any())
          throw std::runtime_error("Measured TCP left the cleared arc envelope.");
        double tracking=(measured-xyz(s.O_T_EE_c)).norm();max_tracking=std::max(max_tracking,tracking);
        if(tracking>.005 || angle(s.O_T_EE,s.O_T_EE_c)>.03491)
          throw std::runtime_error("Cartesian tracking bound exceeded.");
        double speed=std::hypot(std::hypot(s.O_dP_EE_c[0],s.O_dP_EE_c[1]),s.O_dP_EE_c[2]);
        double omega=std::hypot(std::hypot(s.O_dP_EE_c[3],s.O_dP_EE_c[4]),s.O_dP_EE_c[5]);
        if(speed>max_speed*1.5+.002 || omega>max_omega*1.5+.002)
          throw std::runtime_error("Commanded Cartesian speed exceeded bound.");
        double u=blend(elapsed/seconds);Point command_xyz=bezier(control,u);
        const Eigen::Matrix3d r=qa.slerp(blend(u),qb).toRotationMatrix();
        Pose pose=reference;
        for(int c=0;c<3;++c) for(int i=0;i<3;++i) pose[4*c+i]=r(i,c);
        for(int a=0;a<3;++a) pose[12+a]=command_xyz[a];
        if(elapsed==0) pose=reference;
        peak_z=std::max(peak_z,measured[2]);if(elapsed>.1) min_rate=std::min(min_rate,s.control_command_success_rate);
        if(sample_count<samples.size() && elapsed>=sample_count*.02)
          samples[sample_count++]={elapsed,measured,command_xyz,s.control_command_success_rate,period.toSec()};
        progress.store(std::min(elapsed/seconds,1.0));
        franka::CartesianPose command(pose);
        if(elapsed>=seconds+.8) return franka::MotionFinished(command);
        return command;
      },franka::ControllerMode::kJointImpedance,rate_limiting!=0,cutoff);
    } catch(...) { error=std::current_exception(); }
    done.store(true);reporter.join();
    for(size_t i=0;i<sample_count;++i) {const auto& s=samples[i];trace<<std::setprecision(12)<<s.t<<','<<s.actual[0]<<','<<s.actual[1]<<','<<s.actual[2]<<','
      <<s.command[0]<<','<<s.command[1]<<','<<s.command[2]<<','<<s.rate<<','<<s.period<<'\n';}
    trace.flush();
    std::cout<<"ARC_METRICS min_command_success_rate "<<min_rate<<" max_callback_period_ms "<<max_period*1000
             <<" max_tracking_mm "<<max_tracking*1000<<" peak_Z_m "<<peak_z
             <<" startup_s "<<startup_elapsed<<" max_startup_period_ms "<<max_startup_period*1000<<'\n';
    if(error) std::rethrow_exception(error);
    const auto after=robot.readOnce();last=after;check(after,true);
    const double position_error=(xyz(after.O_T_EE)-xyz(target)).norm();const double orientation_error=angle(after.O_T_EE,target);
    std::cout<<"ENDPOINT position_error_mm "<<position_error*1000<<" orientation_error_deg "<<orientation_error*180/M_PI<<'\n';
    if(position_error>position_tolerance || orientation_error>angle_tolerance)
      throw std::runtime_error("Arc endpoint verification failed.");
    std::cout<<"FINAL_STATE "<<after<<"\nPASS continuous arc\n";
  } catch(const std::exception& e) {
    std::cerr<<"STOP "<<e.what()<<'\n';if(have_state) std::cout<<"LAST_STATE "<<last<<'\n';return 1;
  }
}
