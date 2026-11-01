#include <algorithm>
#include <array>
#include <cmath>
#include <csignal>
#include <exception>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <stdexcept>
#include <Eigen/Geometry>
#include <franka/robot.h>

using Pose=std::array<double,16>;
constexpr std::array<double,7> lo{-2.7437,-1.7837,-2.9007,-3.0421,-2.8065,.5445,-3.0159};
constexpr std::array<double,7> hi{2.7437,1.7837,2.9007,-.1518,2.8065,4.5169,3.0159};
volatile std::sig_atomic_t stopped=0;
void stop(int) { stopped=1; }
double distance(const Pose& a,const Pose& b) {
  return std::hypot(std::hypot(a[12]-b[12],a[13]-b[13]),a[14]-b[14]);
}
double rotation_difference(const Pose& a,const Pose& b) {
  double trace=0;
  for(int c=0;c<3;++c) for(int r=0;r<3;++r) trace+=a[4*c+r]*b[4*c+r];
  return std::acos(std::clamp((trace-1)/2,-1.0,1.0));
}
double blend(double u) { u=std::clamp(u,0.0,1.0); return u*u*u*(10+u*(-15+6*u)); }
Pose interpolate(const Pose& a,const Pose& b,double u) {
  if(u<=0) return a;
  if(u>=1) return b;
  Pose out=a;
  Eigen::Matrix3d ra,rb;
  for(int c=0;c<3;++c) for(int r=0;r<3;++r) { ra(r,c)=a[4*c+r]; rb(r,c)=b[4*c+r]; }
  Eigen::Quaterniond qa(ra),qb(rb); qa.normalize(); qb.normalize();
  const Eigen::Matrix3d rotation=qa.slerp(u,qb).toRotationMatrix();
  for(int c=0;c<3;++c) for(int r=0;r<3;++r) out[4*c+r]=rotation(r,c);
  for(int i=12;i<15;++i) out[i]=a[i]+u*(b[i]-a[i]);
  return out;
}
void check(const franka::RobotState& s,bool idle) {
  if(stopped || s.current_errors || (idle && s.robot_mode!=franka::RobotMode::kIdle))
    throw std::runtime_error("Stop requested, robot fault, or arm not idle.");
  for(int j=0;j<7;++j)
    if(!std::isfinite(s.q[j]) || s.q[j]<lo[j]+.02 || s.q[j]>hi[j]-.02 ||
       std::abs(s.q[j]-s.q_d[j])>.02 || (idle && std::abs(s.dq[j])>.01))
      throw std::runtime_error("Joint bound, tracking or stationary check failed.");
}
int main(int argc,char** argv) {
  if(argc!=4) return 2; // Frozen input plan, trace file, --execute or --preview.
  bool execute=std::string(argv[3])=="--execute";
  if(!execute && std::string(argv[3])!="--preview") return 2;
  if(execute) { std::cerr<<"STOP retired unverified Cartesian backend; use teaching/move_xyz.py\n";return 1; }
  std::cout<<std::setprecision(17)<<std::unitbuf;
  std::signal(SIGINT,stop); std::signal(SIGTERM,stop);
  franka::RobotState last{}; bool have_state=false;
  try {
    std::ifstream input(argv[1]);
    std::array<double,3> xyz{}; Pose expected{},tool{};
    std::array<double,7> expected_q{};
    double lift=0, clearance_z=0;
    Pose taught_target{}; int restore_orientation=0,direct_z=0; double relative_z=0;
    double max_xy=0,max_descent=0,max_lift=0;
    for(double& v:xyz) input>>v;
    input>>lift>>clearance_z;
    for(double& v:expected) input>>v;
    for(double& v:tool) input>>v;
    for(double& v:expected_q) input>>v;
    for(double& v:taught_target) input>>v;
    input>>restore_orientation>>direct_z>>relative_z;
    input>>max_xy>>max_descent>>max_lift;
    if(!input || !std::isfinite(clearance_z) || !std::all_of(xyz.begin(),xyz.end(),[](double x){return std::isfinite(x);}) ||
       !std::isfinite(lift) || lift<=0 || lift>.020 ||
       !std::isfinite(max_xy) || max_xy<=0 || max_xy>.750 ||
       !std::isfinite(max_descent) || max_descent<=0 || max_descent>.400 ||
       !std::isfinite(max_lift) || max_lift<=0 || max_lift>.400)
      throw std::runtime_error("Invalid plan or lift outside (0,20] mm.");
    franka::Robot robot("172.16.0.2",franka::RealtimeConfig::kEnforce);
    const auto initial=robot.readOnce(); last=initial; have_state=true;
    check(initial,true);
    if(!std::isfinite(initial.m_ee) || initial.m_ee<.2)
      throw std::runtime_error("Check configured attached tool mass.");
    for(int k=0;k<16;++k)
      if(std::abs(initial.F_T_EE[k]-tool[k])>1e-6)
        throw std::runtime_error("Configured tool frame changed since teaching.");
    for(int j=0;j<7;++j)
      if(std::abs(initial.q[j]-expected_q[j])>.01)
        throw std::runtime_error("Joint start changed since read-only capture.");
    if(distance(initial.O_T_EE,expected)>.002 || rotation_difference(initial.O_T_EE,expected)>.01746 ||
       distance(initial.O_T_EE,initial.O_T_EE_c)>.002 ||
       rotation_difference(initial.O_T_EE,initial.O_T_EE_c)>.01746)
      throw std::runtime_error("Start pose changed or measured/commanded poses disagree.");
    Pose base=initial.O_T_EE_c;
    std::array<Pose,3> goals{base,base,base};
    goals[0][14]=clearance_z>0 ? clearance_z : initial.O_T_EE[14]+lift;
    goals[1]=goals[0]; goals[1][12]=xyz[0]; goals[1][13]=xyz[1];
    if(restore_orientation) {
      for(int c=0;c<3;++c) for(int r=0;r<3;++r) goals[1][4*c+r]=taught_target[4*c+r];
      if(rotation_difference(base,goals[1])>.60)
        throw std::runtime_error("Requested high-clearance reorientation exceeds 0.60 rad.");
    }
    goals[2]=goals[1]; goals[2][14]=xyz[2];
    if(direct_z) {
      if(!std::isfinite(relative_z) || std::abs(relative_z)>.002)
        throw std::runtime_error("Relative Z jog exceeds 2 mm.");
      goals[0]=base;
      if(restore_orientation)
        for(int c=0;c<3;++c) for(int r=0;r<3;++r) goals[0][4*c+r]=taught_target[4*c+r];
      if(rotation_difference(base,goals[0])>.035)
        throw std::runtime_error("Direct jog reorientation exceeds 2 degrees.");
      goals[0][14]+=relative_z;
      goals[1]=goals[2]=goals[0];
    }
    if(!direct_z && (goals[0][14]<initial.O_T_EE[14]-.0001 || goals[0][14]>initial.O_T_EE[14]+max_lift ||
       goals[2][14]>goals[1][14])
       )
      throw std::runtime_error("Invalid lift/clearance or target above clearance.");
    if(std::hypot(xyz[0]-initial.O_T_EE[12],xyz[1]-initial.O_T_EE[13])>max_xy ||
       goals[0][14]-xyz[2]>max_descent)
      throw std::runtime_error("Route exceeds its frozen XY or vertical travel bounds.");
    double route_radius=0;
    std::array<double,3> route_min{},route_max{};
    for(int a=0;a<3;++a) route_min[a]=route_max[a]=initial.O_T_EE[12+a];
    for(const auto& g:goals) {
      route_radius=std::max(route_radius,distance(g,initial.O_T_EE));
      for(int a=0;a<3;++a) { route_min[a]=std::min(route_min[a],g[12+a]); route_max[a]=std::max(route_max[a],g[12+a]); }
    }
    const int stage_count=direct_z ? 1:3;
    const char* labels[] = {direct_z ? "relative_z_and_orientation":"lift","transfer_xy","descend"};
    const double durations[] = {std::max(4.0,1.875*distance(base,goals[0])/.012),std::max({6.0,1.875*distance(goals[0],goals[1])/.012,
              1.875*rotation_difference(goals[0],goals[1])/.030}),
              std::max(4.0,1.875*distance(goals[1],goals[2])/.012)};
    Pose previous=base;
    for(int i=0;i<3;++i) {
      const double d=distance(previous,goals[i]), angle=rotation_difference(previous,goals[i]), t=durations[i];
      // Analytic maxima for the minimum-jerk blend: velocity 1.875,
      // acceleration 10/sqrt(3), jerk 60, scaled by distance and duration.
      if(1.875*d/t>.020 || 5.774*d/(t*t)>.050 || 60*d/(t*t*t)>.250 ||
         1.875*angle/t>.050 || 5.774*angle/(t*t)>.100 || 60*angle/(t*t*t)>1.0)
        throw std::runtime_error("Analytic trajectory exceeds local velocity/acceleration/jerk limits.");
      previous=goals[i];
    }
    std::cout<<"START_STATE "<<initial<<'\n';
    for(int i=0;i<stage_count;++i)
      std::cout<<"PLAN "<<labels[i]<<" XYZ_m "<<goals[i][12]<<' '<<goals[i][13]<<' '<<goals[i][14]<<" duration_s "<<durations[i]<<'\n';
    std::cout<<"ORIENTATION "<<(restore_orientation ? "apply requested target orientation at clearance" : "held fixed")
             <<"; no gripper, recovery or safety-setting commands\n";
    if(!execute) { std::cout<<"PREVIEW_ONLY\n"; return 0; }
    std::ofstream trace(argv[2]);
    if(!trace) throw std::runtime_error("Cannot open trace file.");
    trace<<"stage,time_s,x_m,y_m,z_m,tracking_error_m,command_success_rate\n";
    const double floor=std::min(initial.O_T_EE[14],goals[stage_count-1][14])-(direct_z ? .0005:.002);
    for(int stage=0;stage<stage_count;++stage) {
      const auto before=robot.readOnce(); check(before,true);
      if(stage>0 && distance(before.O_T_EE,goals[stage-1])>.001)
        throw std::runtime_error("Previous waypoint drifted more than 1 mm; stop.");
      Pose start=before.O_T_EE_c;
      if(rotation_difference(start,stage>0 ? goals[stage-1]:base)>.0035)
        throw std::runtime_error("Commanded orientation changed unexpectedly.");
      struct Sample { double t,x,y,z,error,rate; };
      std::array<Sample,8000> samples{}; size_t count=0;
      double elapsed=0, min_rate=1, max_tracking=0, min_z=before.O_T_EE[14],max_period=0;
      bool first=true; std::exception_ptr error;
      std::cout<<"EXECUTE "<<labels[stage]<<'\n';
      try {
        robot.control([&](const franka::RobotState& s,franka::Duration period)->franka::CartesianPose {
          last=s; have_state=true;
          if(first) {
            // Starting control can reset the commanded pose to the measured pose.
            // Seed the first command from this callback, not the stale idle reference.
            start=s.O_T_EE_c;
            if(distance(start,before.O_T_EE_c)>.002 || rotation_difference(start,before.O_T_EE_c)>.01746)
              throw std::runtime_error("Control-start pose shifted beyond preflight tolerance.");
            if(direct_z) {
              goals[0][12]=start[12]; goals[0][13]=start[13];
              goals[0][14]=start[14]+relative_z;
              if(!restore_orientation)
                for(int c=0;c<3;++c) for(int r=0;r<3;++r) goals[0][4*c+r]=start[4*c+r];
            }
            first=false;
          } else elapsed+=period.toSec();
          max_period=std::max(max_period,period.toSec());
          if(period.toSec()>.005) throw std::runtime_error("Control callback gap exceeded 5 ms; stop.");
          check(s,false);
          double tracking=distance(s.O_T_EE,s.O_T_EE_c);
          if(!std::isfinite(tracking) || tracking>.005 || distance(s.O_T_EE,initial.O_T_EE)>route_radius+.005 ||
             s.O_T_EE[14]<floor || s.O_T_EE[14]>goals[0][14]+.002 ||
             rotation_difference(s.O_T_EE,s.O_T_EE_c)>.03491)
            throw std::runtime_error("TCP envelope, orientation or tracking check failed.");
          for(int a=0;a<3;++a)
            if(s.O_T_EE[12+a]<route_min[a]-.003 || s.O_T_EE[12+a]>route_max[a]+.003)
              throw std::runtime_error("TCP left the planned route bounding box.");
          if(stage==2 && std::hypot(s.O_T_EE[12]-xyz[0],s.O_T_EE[13]-xyz[1])>.002)
            throw std::runtime_error("Descent XY alignment exceeded 2 mm.");
          if(direct_z && (distance(s.O_T_EE,initial.O_T_EE)>.0015 ||
              std::hypot(s.O_T_EE[12]-start[12],s.O_T_EE[13]-start[13])>.0005))
            throw std::runtime_error("Direct jog displacement or 0.5 mm XY drift bound exceeded.");
          min_z=std::min(min_z,s.O_T_EE[14]); max_tracking=std::max(max_tracking,tracking);
          if(elapsed>.1) min_rate=std::min(min_rate,s.control_command_success_rate);
          if(count<samples.size() && elapsed>=count*.02)
            samples[count++]={elapsed,s.O_T_EE[12],s.O_T_EE[13],s.O_T_EE[14],tracking,s.control_command_success_rate};
          const double b=blend(elapsed/durations[stage]);
          Pose target=interpolate(start,goals[stage],b);
          franka::CartesianPose command(target);
          if(elapsed>=durations[stage]+.5) return franka::MotionFinished(command);
          return command;
        },franka::ControllerMode::kJointImpedance,true,20.0);
      } catch(...) { error=std::current_exception(); }
      for(size_t k=0;k<count;++k) {
        const auto& s=samples[k];
        trace<<std::setprecision(12)<<labels[stage]<<','<<s.t<<','<<s.x<<','<<s.y<<','<<s.z<<','<<s.error<<','<<s.rate<<'\n';
      }
      trace.flush();
      std::cout<<"CONTROL_START "<<labels[stage]<<" reference_shift_mm "<<distance(start,before.O_T_EE_c)*1000<<'\n';
      if(direct_z) {
        std::cout<<"JOG_REFERENCE_POSE [";
        for(int k=0;k<16;++k) std::cout<<(k ? ",":"")<<start[k];
        std::cout<<"]\nJOG_TARGET_POSE [";
        for(int k=0;k<16;++k) std::cout<<(k ? ",":"")<<goals[0][k];
        std::cout<<"]\n";
      }
      if(error) std::rethrow_exception(error);
      const auto after=robot.readOnce(); last=after; check(after,true);
      const double endpoint_error=distance(after.O_T_EE,goals[stage]);
      std::cout<<"RESULT "<<labels[stage]<<" measured_XYZ_m "<<after.O_T_EE[12]<<' '<<after.O_T_EE[13]<<' '<<after.O_T_EE[14]
               <<" endpoint_error_mm "<<endpoint_error*1000<<" max_tracking_mm "<<max_tracking*1000
               <<" min_command_success_rate "<<min_rate<<" min_Z_m "<<min_z<<" max_callback_period_ms "<<max_period*1000<<'\n';
      if(endpoint_error>.001 || rotation_difference(after.O_T_EE,goals[stage])>.01746)
        throw std::runtime_error("Waypoint missed by more than 1 mm or 1 degree; stop.");
      std::cout<<"PASS "<<labels[stage]<<'\n';
    }
    std::cout<<"FINAL_STATE "<<last<<"\nPASS all "<<stage_count<<" motion stages\n";
  } catch(const std::exception& e) {
    std::cerr<<"STOP "<<e.what()<<'\n';
    if(have_state) std::cout<<"LAST_STATE "<<last<<'\n';
    return 1;
  }
}
