"""Build only offline math from pinned source; no libfranka/network dependency."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess

ROOT=Path(__file__).resolve().parents[2]


def main():
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);args=p.parse_args()
    if os.environ.get('ROBO_PUEUE_JOB')!='1':raise RuntimeError('Compile via default Pueue')
    out=args.output;out.mkdir(parents=True,exist_ok=True)
    source=ROOT/'vendor/jacob_teaching/teaching/joint_move.cpp';text=source.read_text()
    core=text.split('void check(const franka::RobotState&',1)[0]
    if core.count('#include <franka/robot.h>')!=1 or 'struct Plan{' not in core:raise RuntimeError('Unexpected pinned C++ core')
    core=core.replace('#include <franka/robot.h>\n','')
    (out/'plan_core.hpp').write_text(core)
    (out/'checker.cpp').write_text('''#include "plan_core.hpp"
int main(int argc,char**argv){
 if(argc!=4||std::string(argv[3])!="--check")return 2;
 try{Plan p(argv[1]);double maximum=0;
 for(int k=0;k<=2000;++k){double u=k/2000.0;auto q=p.q(u);p.guard(q);auto a=p.model.evaluate(q).first;auto b=p.expected(u);
 double error=(a.block<3,1>(0,3)-b.block<3,1>(0,3)).norm();maximum=std::max(maximum,error);
 if(error>.001||Eigen::Quaterniond(a.topLeftCorner<3,3>()).angularDistance(Eigen::Quaterniond(b.topLeftCorner<3,3>()))>.005)throw std::runtime_error("Joint path leaves intended Cartesian arc");}
 std::ofstream trace(argv[2]);trace<<std::setprecision(17)<<"u,x,y,z,full_sigma,fixed_sigma,condition,q2,extension\\n";
 for(int k=0;k<=1000;++k){double u=k/1000.0;auto q=p.q(u);auto t=p.model.evaluate(q).first;auto m=p.model.metrics(q);trace<<u<<','<<t(0,3)<<','<<t(1,3)<<','<<t(2,3)<<','<<m.full<<','<<m.fixed<<','<<m.condition<<','<<m.q2<<','<<m.extension<<'\\n';}
 if(!trace)throw std::runtime_error("Cannot write model check");std::cout<<"PASS offline fixed-model check; maximum arc deviation m "<<maximum<<'\\n';return 0;
 }catch(const std::exception&e){std::cerr<<"STOP "<<e.what()<<'\\n';return 1;}}
''')
    sdk=ROOT/'vendor/libfranka_0_20';rate=(sdk/'src/rate_limiting.cpp').read_text()
    start=rate.index('double limitRate(double upper_limits_velocity,');end=rate.index('std::array<double, 6> limitRate(',start)
    (out/'limiter.cpp').write_text('// Apache-2.0 Franka Robotics math; source/license retained under vendor/libfranka_0_20.\n#include <franka/rate_limiting.h>\n#include <stdexcept>\nnamespace franka {\n'+rate[start:end]+'''\n}
extern "C" int robo_limit(const double*parameters,const double*command,const double*q,const double*dq,const double*ddq,double*out){
 try{std::array<double,7> hi,lo,c,p,v,a;
 for(int i=0;i<7;++i){const double*r=parameters+5*i;
 hi[i]=std::min(r[0],std::max(0.0,-r[1]+std::sqrt(std::max(0.0,2*r[2]*(r[3]-q[i])))))-franka::kJointVelocityLimitsTolerance[i];
 lo[i]=std::max(-r[0],std::min(0.0,r[1]-std::sqrt(std::max(0.0,2*r[2]*(-r[4]+q[i])))))+franka::kJointVelocityLimitsTolerance[i];
 c[i]=command[i];p[i]=q[i];v[i]=dq[i];a[i]=ddq[i];}
 auto result=franka::limitRate(hi,lo,franka::kMaxJointAcceleration,franka::kMaxJointJerk,c,p,v,a);
 std::copy(result.begin(),result.end(),out);return 0;}catch(...){return 1;}}
''')
    commands=[['g++','-std=c++17','-O2','-I/usr/include/eigen3',str(out/'checker.cpp'),'-o',str(out/'joint_check')],
              ['g++','-std=c++17','-O2','-fPIC','-shared','-I'+str(sdk/'include'),str(out/'limiter.cpp'),'-o',str(out/'libjoint_limiter.so')]]
    for command in commands:subprocess.run(command,check=True)
    report={'source_joint_move_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),'core_extraction':'Unchanged prefix before hardware check; exactly one franka/robot.h include removed','libfranka_tag':'0.20.0','real_binary_patch':'UNKNOWN (SONAME0.20)','robot_or_network_code_linked':False,'commands':commands,'sha256':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(out.iterdir()) if p.is_file()}}
    (out/'build.json').write_text(json.dumps(report,indent=2)+'\n')


if __name__=='__main__':main()
