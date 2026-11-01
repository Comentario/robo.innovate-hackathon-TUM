#include <algorithm>
#include <array>
#include <atomic>
#include <chrono>
#include <cmath>
#include <csignal>
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <iterator>
#include <stdexcept>
#include <thread>
#include <vector>
#include <pthread.h>
#include <sched.h>
#include <sys/mman.h>
#include <Eigen/Geometry>
#include <Eigen/Eigenvalues>
#include <franka/robot.h>

using Pose=std::array<double,16>;
using Q=std::array<double,7>;
using M4=Eigen::Matrix4d;
using V3=Eigen::Vector3d;
using J67=Eigen::Matrix<double,6,7>;
volatile std::sig_atomic_t interrupted=0;
void stop(int){interrupted=1;}
double blend(double x){x=std::clamp(x,0.0,1.0);return x*x*x*(10+x*(-15+6*x));}
M4 matrix(const Pose& p){return Eigen::Map<const M4>(p.data());}
V3 xyz(const Pose& p){return {p[12],p[13],p[14]};}
double angle(const Pose& a,const Pose& b){return Eigen::Quaterniond(matrix(a).topLeftCorner<3,3>()).normalized().angularDistance(Eigen::Quaterniond(matrix(b).topLeftCorner<3,3>()).normalized());}
struct Metrics{double full,fixed,condition,q2,extension;};
struct Model{
  std::array<M4,7> origins;M4 ee;double length=.3;
  std::pair<M4,J67> evaluate(const Q& q)const{
    M4 t=M4::Identity();std::array<V3,7> axis,position;
    for(int i=0;i<7;++i){
      t=t*origins[i];axis[i]=t.block<3,1>(0,2);position[i]=t.block<3,1>(0,3);
      M4 rotation=M4::Identity();rotation.topLeftCorner<3,3>()=Eigen::AngleAxisd(q[i],V3::UnitZ()).toRotationMatrix();t=t*rotation;
    }
    t=t*ee;J67 j;
    for(int i=0;i<7;++i){j.block<3,1>(0,i)=axis[i].cross(t.block<3,1>(0,3)-position[i])/length;j.block<3,1>(3,i)=axis[i];}
    return {t,j};
  }
  Metrics metrics(const Q& q)const{
    const auto j=evaluate(q).second;Eigen::Matrix<double,6,6> fixed;
    constexpr int columns[6]={0,1,3,4,5,6};for(int i=0;i<6;++i)fixed.col(i)=j.col(columns[i]);
    Eigen::SelfAdjointEigenSolver<Eigen::Matrix<double,6,6>> a(j*j.transpose(),Eigen::EigenvaluesOnly),b(fixed*fixed.transpose(),Eigen::EigenvaluesOnly);
    if(a.info()!=Eigen::Success||b.info()!=Eigen::Success)throw std::runtime_error("Jacobian eigensolver failed");
    double full=std::sqrt(std::max(0.0,a.eigenvalues()[0])),f=std::sqrt(std::max(0.0,b.eigenvalues()[0]));
    double condition=std::max(std::sqrt(a.eigenvalues()[5])/std::max(full,1e-12),std::sqrt(b.eigenvalues()[5])/std::max(f,1e-12));
    return {full,f,condition,std::abs(q[1]),std::abs(q[3]+.467002423653011)};
  }
};
struct Segment{double u;std::array<std::array<double,4>,7> c;};
struct Plan{
  Pose start{},target{},tool{};Q q0{},lower_q{},upper_q{};std::array<V3,6> control;V3 lower,upper;
  double seconds=0,gap=0,speed=0,omega=0,q_speed=0,position_tolerance=0,angle_tolerance=0,stable=0,timeout=0;
  double min_full=0,min_fixed=0,max_condition=0,min_q2=0,min_extension=0;int cpu=0;bool long_rotation=false;int rate_limiting=0;
  Model model;std::vector<Segment> segments;double end=1;
  explicit Plan(const char* name){
    std::ifstream in(name);int version=0,n=0,rotation=0;in>>version>>n;
    if((version!=1&&version!=2)||n<2||n>2001)throw std::runtime_error("Invalid joint plan header");
    auto read=[&](auto& v){for(auto& a:v)in>>a;};
    read(start);read(target);read(tool);read(q0);for(auto& p:control)for(int k=0;k<3;++k)in>>p[k];
    for(int k=0;k<3;++k)in>>lower[k];
    for(int k=0;k<3;++k)in>>upper[k];
    in>>seconds>>gap>>speed>>omega>>q_speed>>position_tolerance>>angle_tolerance>>stable>>timeout>>cpu;
    in>>model.length>>min_full>>min_fixed>>max_condition>>min_q2>>min_extension>>rotation;long_rotation=rotation!=0;
    if(version>=2)in>>rate_limiting;
    read(lower_q);read(upper_q);
    for(auto& t:model.origins)for(int k=0;k<16;++k)in>>t.data()[k];
    for(int k=0;k<16;++k)in>>model.ee.data()[k];
    segments.resize(n-1);for(auto& s:segments){in>>s.u;for(auto& c:s.c)read(c);}in>>end;
    if(!in||!std::isfinite(seconds)||seconds<1||seconds>600||gap<=0||gap>.0200001||q_speed<=0||q_speed>1.0000001||
       speed<=0||speed>.4000001||omega<=0||omega>.3000001||position_tolerance<=0||position_tolerance>.0010001||
       angle_tolerance<=0||angle_tolerance>.017454||stable<.5||timeout<stable||timeout>5||cpu<0||cpu>=CPU_SETSIZE||
       model.length<.1||model.length>1||min_full<.1||min_fixed<.08||max_condition>50||min_q2<0||min_extension<.15||rate_limiting<0||rate_limiting>1||end!=1||segments.front().u!=0)
      throw std::runtime_error("Invalid joint plan limits");
    for(size_t k=0;k<segments.size();++k){const auto& s=segments[k];if(!std::isfinite(s.u)||(k&&s.u<=segments[k-1].u)||s.u>=1)throw std::runtime_error("Invalid spline knots");
      for(const auto& c:s.c)for(double x:c)if(!std::isfinite(x))throw std::runtime_error("Invalid spline coefficients");}
    for(const auto& p:control)if(!p.allFinite()||(p.array()<lower.array()-1e-9).any()||(p.array()>upper.array()+1e-9).any())throw std::runtime_error("Arc exceeds workspace");
  }
  Q q(double u)const{
    u=std::clamp(u,0.0,1.0);auto it=std::upper_bound(segments.begin(),segments.end(),u,[](double v,const Segment& s){return v<s.u;});
    if(it!=segments.begin())--it;
    double x=u-it->u;Q result{};
    for(int j=0;j<7;++j){const auto& c=it->c[j];result[j]=((c[0]*x+c[1])*x+c[2])*x+c[3];}return result;
  }
  V3 curve(double u)const{auto p=control;for(int n=5;n>0;--n)for(int i=0;i<n;++i)p[i]=(1-u)*p[i]+u*p[i+1];return p[0];}
  M4 expected(double u)const{
    M4 result=matrix(start);Eigen::Matrix3d a=Eigen::Quaterniond(result.topLeftCorner<3,3>()).normalized().toRotationMatrix();
    Eigen::Matrix3d b=Eigen::Quaterniond(matrix(target).topLeftCorner<3,3>()).normalized().toRotationMatrix();Eigen::AngleAxisd aa(a.transpose()*b);
    double theta=aa.angle();if(long_rotation&&theta>1e-6)theta-=2*M_PI;
    result.topLeftCorner<3,3>()=a*Eigen::AngleAxisd(theta*blend(u),aa.axis()).toRotationMatrix();
    result.block<3,1>(0,3)=curve(u);return result;
  }
  Metrics guard(const Q& joints)const{
    for(int j=0;j<7;++j)if(!std::isfinite(joints[j])||joints[j]<lower_q[j]||joints[j]>upper_q[j])throw std::runtime_error("Live joint limit violated");
    const auto m=model.metrics(joints);
    if(m.full<min_full||m.fixed<min_fixed||m.condition>max_condition||m.q2<min_q2||m.extension<min_extension)throw std::runtime_error("Live singularity margin violated");
    return m;
  }
};
void check(const franka::RobotState& s,bool idle,const Plan& p){
  if(interrupted||s.current_errors||(idle&&s.robot_mode!=franka::RobotMode::kIdle))throw std::runtime_error("Stop requested, robot fault or arm not Idle");
  for(int j=0;j<7;++j)if(!std::isfinite(s.dq[j])||std::abs(s.dq[j])>(idle?.01:p.q_speed)||std::abs(s.q[j]-s.q_d[j])>.02)throw std::runtime_error("Joint velocity/tracking bound exceeded");
}
std::string contents(const std::filesystem::path& p){std::ifstream in(p);if(!in)throw std::runtime_error("Cannot open frozen robot model");return {std::istreambuf_iterator<char>(in),{}};}
int main(int argc,char** argv){
  if(argc!=4)return 2;
  std::string mode=argv[3];if(mode!="--execute"&&mode!="--preview"&&mode!="--check")return 2;
  const bool execute=mode=="--execute";std::cout<<std::unitbuf<<std::setprecision(17);std::signal(SIGINT,stop);std::signal(SIGTERM,stop);
  franka::RobotState last{};bool have_state=false;
  try{
    Plan p(argv[1]);
    // Model checks are repeated in the executable before opening control.
    double max_deviation=0;
    for(int k=0;k<=2000;++k){double u=k/2000.0;auto q=p.q(u);p.guard(q);auto actual=p.model.evaluate(q).first;auto desired=p.expected(u);
      double deviation=(actual.block<3,1>(0,3)-desired.block<3,1>(0,3)).norm();max_deviation=std::max(max_deviation,deviation);
      if(deviation>.001||Eigen::Quaterniond(actual.topLeftCorner<3,3>()).angularDistance(Eigen::Quaterniond(desired.topLeftCorner<3,3>()))>.005)
        throw std::runtime_error("Joint path leaves intended Cartesian arc");}
    if(mode=="--check"){
      std::ofstream out(argv[2]);out<<std::setprecision(17)<<"u,x,y,z,full_sigma,fixed_sigma,condition,q2,extension\n";
      for(int k=0;k<=1000;++k){double u=k/1000.0;auto q=p.q(u);auto t=p.model.evaluate(q).first;auto m=p.model.metrics(q);out<<u<<','<<t(0,3)<<','<<t(1,3)<<','<<t(2,3)<<','<<m.full<<','<<m.fixed<<','<<m.condition<<','<<m.q2<<','<<m.extension<<'\n';}
      if(!out)throw std::runtime_error("Cannot write model check");
      std::cout<<"PASS offline fixed-model check; maximum arc deviation m "<<max_deviation<<'\n';return 0;
    }
    cpu_set_t cpus;CPU_ZERO(&cpus);CPU_SET(p.cpu,&cpus);if(sched_setaffinity(0,sizeof(cpus),&cpus))throw std::runtime_error("Cannot pin controller CPU");
    franka::Robot robot("172.16.0.2",franka::RealtimeConfig::kEnforce);
    if(robot.getRobotModel()!=contents(std::filesystem::path(argv[1]).parent_path()/"robot_model.urdf"))throw std::runtime_error("Robot kinematic model changed since planning");
    auto initial=robot.readOnce();last=initial;have_state=true;check(initial,true,p);p.guard(initial.q);
    if(!std::isfinite(initial.m_ee)||initial.m_ee<.2)throw std::runtime_error("Check attached tool configuration");
    for(int k=0;k<16;++k)if(std::abs(initial.F_T_EE[k]-p.tool[k])>1e-6)throw std::runtime_error("Configured tool frame changed");
    for(int j=0;j<7;++j)if(std::abs(initial.q[j]-p.q0[j])>.001)throw std::runtime_error("Arm moved since joint preflight");
    if((xyz(initial.O_T_EE)-xyz(p.start)).norm()>.001||angle(initial.O_T_EE,p.start)>.005)throw std::runtime_error("TCP moved since preflight");
    auto predicted=p.model.evaluate(initial.q).first;
    if((predicted.block<3,1>(0,3)-xyz(initial.O_T_EE)).norm()>.0001)throw std::runtime_error("Live FK model mismatch");
    std::cout<<"START_STATE "<<initial<<"\nPLAN certified joint realization of continuous arc; duration_s "<<p.seconds<<'\n';
    if(!execute){std::cout<<"PREVIEW_ONLY no motion sent\n";return 0;}
    struct Sample{double t;Pose pose;Q q,command;Metrics metrics;double period,rate;};
    std::vector<Sample> samples(static_cast<size_t>((p.seconds+p.timeout+2)*50)+10);size_t count=0;
    // Prefaulted memory and ordinary-priority progress thread follow the working Cartesian controller.
    for(auto& s:samples)s.t=0;
    if(mlock(samples.data(),samples.size()*sizeof(Sample)))throw std::runtime_error("Cannot lock logging memory");
    std::ofstream trace(argv[2]);if(!trace)throw std::runtime_error("Cannot open joint trace");
    trace<<"time_s,x_m,y_m,z_m,full_sigma,fixed_sigma,condition,abs_joint2,period_s,command_success_rate";for(int j=0;j<7;++j)trace<<",q"<<j+1;for(int j=0;j<7;++j)trace<<",command_q"<<j+1;trace<<'\n';
    double elapsed=0,startup=0,stable=0,max_period=0,min_full=1e9,min_fixed=1e9,min_q2=1e9,max_tracking=0,min_rate=1;
    bool first=true,warmed=false;Q reference{},offset{};
    std::atomic<double> progress{0};std::atomic<bool> done{false},ready{false},valid{false};
    std::thread reporter([&]{sched_param ordinary{};valid.store(pthread_setschedparam(pthread_self(),SCHED_OTHER,&ordinary)==0);ready.store(true);int previous=0;while(!done.load()){int decile=std::min(10,int(progress.load()*10));if(decile>previous){std::cout<<"PROGRESS "<<decile*10<<"%\n";previous=decile;}std::this_thread::sleep_for(std::chrono::milliseconds(100));}});
    while(!ready.load())std::this_thread::sleep_for(std::chrono::milliseconds(1));
    if(!valid.load()){done.store(true);reporter.join();throw std::runtime_error("Cannot demote reporter thread");}
    std::exception_ptr error;
    try{
      robot.control([&](const franka::RobotState& s,franka::Duration period)->franka::JointPositions{
        last=s;have_state=true;check(s,false,p);
        if(first){reference=s.q_d;for(int j=0;j<7;++j){offset[j]=reference[j]-p.q0[j];if(std::abs(offset[j])>.001)throw std::runtime_error("Control reference changed since planning");}first=false;}
        const auto measured=p.guard(s.q);p.guard(s.q_d);
        min_full=std::min(min_full,measured.full);min_fixed=std::min(min_fixed,measured.fixed);min_q2=std::min(min_q2,measured.q2);
        if(!warmed){startup+=period.toSec();if(period.toSec()<=p.gap)stable+=period.toSec();else stable=0;if(stable>=p.stable){warmed=true;elapsed=0;}else if(startup>p.timeout)throw std::runtime_error("Stationary startup timing failed");}
        else{elapsed+=period.toSec();max_period=std::max(max_period,period.toSec());if(period.toSec()>p.gap)throw std::runtime_error("Callback gap exceeded bound");}
        V3 measured_xyz=xyz(s.O_T_EE);
        if(!measured_xyz.allFinite()||(measured_xyz.array()<p.lower.array()-.003).any()||(measured_xyz.array()>p.upper.array()+.003).any())throw std::runtime_error("TCP left cleared workspace");
        auto expected=p.expected(blend(elapsed/p.seconds));double tracking=(measured_xyz-expected.block<3,1>(0,3)).norm();max_tracking=std::max(max_tracking,tracking);
        if(tracking>.005||Eigen::Quaterniond(matrix(s.O_T_EE).topLeftCorner<3,3>()).normalized().angularDistance(Eigen::Quaterniond(expected.topLeftCorner<3,3>()))>.03491)throw std::runtime_error("TCP left planned arc corridor");
        double speed=Eigen::Map<const Eigen::Vector3d>(s.O_dP_EE_c.data()).norm(),omega=Eigen::Map<const Eigen::Vector3d>(s.O_dP_EE_c.data()+3).norm();
        if(speed>p.speed*1.5+.002||omega>p.omega*1.5+.002)throw std::runtime_error("Cartesian speed exceeded bound");
        double u=blend(elapsed/p.seconds);Q command=p.q(u);for(int j=0;j<7;++j)command[j]+=offset[j]*(1-blend(u));
        if(elapsed==0)command=reference;
        p.guard(command);
        if(count<samples.size()&&elapsed>=count*.02)samples[count++]={elapsed,s.O_T_EE,s.q,command,measured,period.toSec(),s.control_command_success_rate};
        if(elapsed>.1)min_rate=std::min(min_rate,s.control_command_success_rate);
        progress.store(std::min(elapsed/p.seconds,1.0));
        franka::JointPositions result(command);if(elapsed>=p.seconds+.8)return franka::MotionFinished(result);return result;
      },franka::ControllerMode::kJointImpedance,p.rate_limiting!=0,1000);
    }catch(...){error=std::current_exception();}
    done.store(true);reporter.join();
    for(size_t k=0;k<count;++k){const auto& s=samples[k];trace<<std::setprecision(12)<<s.t<<','<<s.pose[12]<<','<<s.pose[13]<<','<<s.pose[14]<<','<<s.metrics.full<<','<<s.metrics.fixed<<','<<s.metrics.condition<<','<<s.metrics.q2<<','<<s.period<<','<<s.rate;for(double v:s.q)trace<<','<<v;for(double v:s.command)trace<<','<<v;trace<<'\n';}trace.flush();
    std::cout<<"JOINT_METRICS min_full_sigma "<<min_full<<" min_fixed_sigma "<<min_fixed<<" min_abs_joint2_rad "<<min_q2<<" max_callback_period_ms "<<max_period*1000<<" max_tracking_mm "<<max_tracking*1000<<" min_command_success_rate "<<min_rate<<'\n';
    if(error)std::rethrow_exception(error);
    auto after=robot.readOnce();last=after;check(after,true,p);p.guard(after.q);
    double position_error=(xyz(after.O_T_EE)-xyz(p.target)).norm(),orientation_error=angle(after.O_T_EE,p.target);
    std::cout<<"ENDPOINT position_error_mm "<<position_error*1000<<" orientation_error_deg "<<orientation_error*180/M_PI<<'\n';
    if(position_error>p.position_tolerance||orientation_error>p.angle_tolerance)throw std::runtime_error("Endpoint verification failed");
    std::cout<<"FINAL_STATE "<<after<<"\nPASS certified joint arc\n";
  }catch(const std::exception& e){std::cerr<<"STOP "<<e.what()<<'\n';if(have_state)std::cout<<"LAST_STATE "<<last<<'\n';return 1;}
}
