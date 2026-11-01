"""Simulation-only mirror of joint_move.cpp callback, with explicit backend state.

    io.read_state() -> actual measured/base-configured-EE and public target state
    io.advance(limited_q, period_s=.001) -> poststep state, one physics step
    io.read_gripper(); io.move_gripper(width,total_width_speed) -> blocking bool

No libfranka connection, hardware fault emulation, state pose writes or IK here.
The official0.20.0 limiter is injected; the real binary's patch is unknown.
"""
import bisect
import json
import math
from pathlib import Path
import subprocess
import numpy as np
from scipy.spatial.transform import Rotation

DT=.001


def blend(x):
    x=float(np.clip(x,0,1));return x*x*x*(10+x*(-15+6*x))


def pose(values):return np.asarray(values,float).reshape(4,4,order='F')
def angle(a,b):return float(Rotation.from_matrix(pose(a)[:3,:3].T@pose(b)[:3,:3]).magnitude())


def sample_command(plan,elapsed,reference):
    u=blend(elapsed/plan.seconds);raw=plan.q(u)
    command=raw+(np.asarray(reference)-plan.q0)*(1-blend(u))
    if elapsed==0:command=np.asarray(reference).copy()
    return u,raw,command


class JointPlan:
    def __init__(self,path):
        values=list(map(float,Path(path).read_text().split()));index=0
        def take(n):
            nonlocal index
            result=np.asarray(values[index:index+n],float);index+=n
            if len(result)!=n or not np.isfinite(result).all():raise ValueError('Invalid finite frozen joint input')
            return result
        version,n=take(2)
        if version not in (1,2) or n!=int(n) or not 2<=n<=2001:raise ValueError('Invalid joint plan header')
        self.start,self.target,self.tool,self.q0=take(16),take(16),take(16),take(7)
        self.control=take(18).reshape(6,3);self.lower,self.upper=take(3),take(3)
        names=('seconds','gap','speed','omega','q_speed','position_tolerance','angle_tolerance','stable','timeout','cpu',
               'length','min_full','min_fixed','max_condition','min_q2','min_extension','long_rotation')
        for name,value in zip(names,take(len(names))):setattr(self,name,float(value))
        rate=float(take(1)[0]) if version>=2 else 0
        if rate not in (0,1):raise ValueError('Invalid rate-limiter setting')
        self.rate_limiting=int(rate)
        self.lower_q,self.upper_q=take(7),take(7)
        self.origins=[pose(take(16)) for _ in range(7)];self.ee=pose(take(16))
        self.knots=[];self.coefficients=[]
        for _ in range(int(n)-1):self.knots.append(float(take(1)[0]));self.coefficients.append(take(28).reshape(7,4))
        self.end=float(take(1)[0])
        valid=(index==len(values) and 1<=self.seconds<=600 and 0<self.gap<=.0200001 and 0<self.q_speed<=1.0000001
            and 0<self.speed<=.4000001 and 0<self.omega<=.3000001 and 0<self.position_tolerance<=.0010001
            and 0<self.angle_tolerance<=.017454 and self.stable>=.5 and self.stable<=self.timeout<=5
            and self.cpu==int(self.cpu) and 0<=self.cpu<1024 and .1<=self.length<=1 and self.min_full>=.1 and self.min_fixed>=.08
            and self.max_condition<=50 and self.min_q2>=0 and self.min_extension>=.15 and self.rate_limiting in (0,1)
            and self.end==1 and self.knots[0]==0 and all(a<b for a,b in zip(self.knots,self.knots[1:])) and self.knots[-1]<1
            and np.all(self.control>=self.lower-1e-9) and np.all(self.control<=self.upper+1e-9))
        if not valid:raise ValueError('Invalid frozen joint plan limits')

    def q(self,u):
        u=float(np.clip(u,0,1));i=max(0,bisect.bisect_right(self.knots,u)-1);x=u-self.knots[i];c=self.coefficients[i]
        return ((c[:,0]*x+c[:,1])*x+c[:,2])*x+c[:,3]

    def expected(self,u):
        points=self.control.copy()
        for n in range(5,0,-1):points[:n]=(1-u)*points[:n]+u*points[1:n+1]
        a=Rotation.from_matrix(pose(self.start)[:3,:3]).as_matrix();b=Rotation.from_matrix(pose(self.target)[:3,:3]).as_matrix()
        rotation=Rotation.from_matrix(a.T@b).as_rotvec();magnitude=np.linalg.norm(rotation)
        if self.long_rotation and magnitude>1e-6:rotation*=1-2*math.pi/magnitude
        result=np.eye(4);result[:3,:3]=a@Rotation.from_rotvec(rotation*blend(u)).as_matrix();result[:3,3]=points[0]
        return result.reshape(-1,order='F')

    def evaluate(self,q):
        t=np.eye(4);axes=[];positions=[]
        for origin,value in zip(self.origins,q):
            t=t@origin;axes.append(t[:3,2].copy());positions.append(t[:3,3].copy())
            c,s=math.cos(value),math.sin(value);r=np.eye(4);r[:2,:2]=[[c,-s],[s,c]];t=t@r
        t=t@self.ee;j=np.zeros((6,7))
        for i,(axis,position) in enumerate(zip(axes,positions)):j[:3,i]=np.cross(axis,t[:3,3]-position)/self.length;j[3:,i]=axis
        return t,j

    def guard(self,q):
        q=np.asarray(q,float)
        if q.shape!=(7,) or not np.isfinite(q).all() or np.any(q<self.lower_q) or np.any(q>self.upper_q):raise RuntimeError('Live joint limit violated')
        j=self.evaluate(q)[1];fixed=j[:,[0,1,3,4,5,6]]
        a=np.linalg.eigvalsh(j@j.T);b=np.linalg.eigvalsh(fixed@fixed.T)
        full=math.sqrt(max(0,float(a[0])));f=math.sqrt(max(0,float(b[0])))
        condition=max(math.sqrt(max(0,float(a[-1])))/max(full,1e-12),math.sqrt(max(0,float(b[-1])))/max(f,1e-12))
        metric={'full':full,'fixed':f,'condition':condition,'q2':abs(q[1]),'extension':abs(q[3]+.467002423653011)}
        if full<self.min_full or f<self.min_fixed or condition>self.max_condition or metric['q2']<self.min_q2 or metric['extension']<self.min_extension:raise RuntimeError('Live singularity margin violated')
        return metric


class _Process:
    def __init__(self,executor,args):self.executor=executor;self.args=args;self.returncode=None;self.stdout=self._stream()
    def _stream(self):
        mode=getattr(self.executor.io,'mode',None)
        try:
            yield from self.executor._joint(self.args)
            self.returncode=0
        except Exception as error:
            self.returncode=1;yield 'STOP '+str(error)+'\n'
            try:yield 'LAST_STATE '+json.dumps(self.executor.io.read_state(),allow_nan=False)+'\n'
            except Exception:pass
        finally:
            if mode is not None:self.executor.io.mode=mode
    def wait(self):
        if self.returncode is None:
            for _ in self.stdout:pass
        return self.returncode
    def send_signal(self,number):self.executor.interrupted=True


class JointExecutor:
    def __init__(self,io,limiter,checker_path,output_directory):
        self.io,self.limiter=io,limiter;self.checker=Path(checker_path).resolve();self.output=Path(output_directory)
        self.output.mkdir(parents=True,exist_ok=True);self.interrupted=False;self.callback_index=0

    def _advance(self,q):return self.io.advance(np.asarray(q,float),period_s=DT)

    @staticmethod
    def _result(args,code,stdout='',stderr=''):return subprocess.CompletedProcess(args,code,stdout,stderr)

    def check(self,args):
        # Only the network-free Eigen executable is invoked, always --check.
        return subprocess.run([str(self.checker),args[1],args[2],'--check'],capture_output=True,text=True)

    def read_pose(self,args):
        try:
            initial=self.io.read_state();last=initial;speed=drift=tcp_drift=0.
            for _ in range(500):
                last=self._advance(last['q_d'])
                if last['current_errors'] or last['robot_mode'] not in ('Idle','Guiding'):raise RuntimeError('Recording requires stationary fault-free arm')
                q=np.asarray(last['q']);dq=np.asarray(last['dq']);tcp=np.asarray(last['O_T_EE'])[12:15]
                if not np.isfinite(np.r_[q,dq,tcp]).all():raise RuntimeError('Nonfinite state')
                speed=max(speed,float(np.max(abs(dq))));drift=max(drift,float(np.max(abs(q-initial['q']))))
                tcp_drift=max(tcp_drift,float(np.linalg.norm(tcp-np.asarray(initial['O_T_EE'])[12:15])))
            if speed>.01 or drift>.001 or tcp_drift>.0005:raise RuntimeError('Arm moved during recording')
            result={'state':last,'stationary_check':{'duration_ms':500,'max_joint_speed_rad_s':speed,'max_joint_drift_rad':drift,'max_tcp_drift_m':tcp_drift}}
            return self._result(args,0,json.dumps(result,allow_nan=False)+'\n')
        except Exception as error:return self._result(args,1,stderr=str(error))

    def process(self,args):return _Process(self,args)

    def _state_guard(self,s,p,idle=False):
        if self.interrupted or s['current_errors'] or (idle and s['robot_mode']!='Idle'):raise RuntimeError('Stop requested, fault or arm not Idle')
        q,dq,qd=map(lambda key:np.asarray(s[key],float),('q','dq','q_d'))
        if not np.isfinite(dq).all() or np.max(abs(dq))>(.01 if idle else p.q_speed) or np.max(abs(q-qd))>.02:raise RuntimeError('Joint velocity/tracking bound exceeded')

    def _joint(self,args):
        p=JointPlan(args[1])
        # The real executable repeats its offline check before opening control.
        for k in range(2001):
            u=k/2000.;q=p.q(u);p.guard(q);actual=p.evaluate(q)[0].reshape(-1,order='F');desired=p.expected(u)
            if np.linalg.norm(actual[12:15]-desired[12:15])>.001 or angle(actual,desired)>.005:raise RuntimeError('Joint path leaves intended Cartesian arc')
        initial=self.io.read_state();self._state_guard(initial,p,True);p.guard(initial['q'])
        if not math.isfinite(initial['m_ee']) or initial['m_ee']<.2:raise RuntimeError('Check attached tool configuration')
        if np.max(abs(np.asarray(initial['F_T_EE'])-p.tool))>1e-6:raise RuntimeError('Configured tool frame changed')
        if np.max(abs(np.asarray(initial['q'])-p.q0))>.001:raise RuntimeError('Arm moved since joint preflight')
        if np.linalg.norm(np.asarray(initial['O_T_EE'])[12:15]-p.start[12:15])>.001 or angle(initial['O_T_EE'],p.start)>.005:raise RuntimeError('TCP moved since preflight')
        if np.linalg.norm(p.evaluate(initial['q'])[0][:3,3]-np.asarray(initial['O_T_EE'])[12:15])>.0001:raise RuntimeError('Live FK model mismatch')
        yield 'START_STATE '+json.dumps(initial,allow_nan=False)+'\n'
        if args[3]=='--preview':yield 'PREVIEW_ONLY no motion sent\n';return
        if hasattr(self.io,'mode'):self.io.mode='Move'
        elapsed=startup=stable=0.;first=True;warmed=False;filter_first=True;next_sample=0.;last=initial
        with Path(args[2]).open('w') as csv,(self.output/'joint_callback_trace.jsonl').open('a') as trace:
            csv.write('time_s,x_m,y_m,z_m,full_sigma,fixed_sigma,condition,abs_joint2,period_s,command_success_rate'+''.join(',q'+str(i) for i in range(1,8))+''.join(',command_q'+str(i) for i in range(1,8))+'\n')
            while elapsed<p.seconds+.8:
                state=self.io.read_state();self._state_guard(state,p);period=0. if first else DT
                if first:
                    reference=np.asarray(state['q_d'],float);offset=reference-p.q0
                    if np.max(abs(offset))>.001:raise RuntimeError('Control reference changed since planning')
                    first=False
                measured=p.guard(state['q']);p.guard(state['q_d'])
                if not warmed:
                    startup+=period;stable=stable+period if period<=p.gap else 0.
                    if stable>=p.stable:warmed=True;elapsed=0.
                    elif startup>p.timeout:raise RuntimeError('Stationary startup timing failed')
                else:
                    elapsed+=period
                    if period>p.gap:raise RuntimeError('Callback gap exceeded bound')
                u,raw,command=sample_command(p,elapsed,reference)
                expected=p.expected(u);xyz=np.asarray(state['O_T_EE'])[12:15]
                if not np.isfinite(xyz).all() or np.any(xyz<p.lower-.003) or np.any(xyz>p.upper+.003):raise RuntimeError('TCP left cleared workspace')
                if np.linalg.norm(xyz-expected[12:15])>.005 or angle(state['O_T_EE'],expected)>.03491:raise RuntimeError('TCP left planned arc corridor')
                velocity=np.asarray(state['O_dP_EE_c'],float)
                if np.linalg.norm(velocity[:3])>p.speed*1.5+.002 or np.linalg.norm(velocity[3:])>p.omega*1.5+.002:raise RuntimeError('Cartesian speed exceeded bound')
                p.guard(command)
                limit_reference=command if filter_first else np.asarray(state['q_d'],float)
                limited=self.limiter.limit(command,limit_reference,state['dq_d'],state['ddq_d']) if p.rate_limiting else command.copy()
                filter_first=False
                post=self._advance(limited);self.callback_index+=1
                row={'step':self.callback_index,'period_s':period,'elapsed_s':elapsed,'startup_s':startup,'warmed':warmed,'u':u,
                     'raw_spline_q':raw.tolist(),'rebased_command_q':command.tolist(),'limited_command_q':np.asarray(limited).tolist(),
                     'state_before':state,'state_after':post,'expected_O_T_EE':expected.tolist(),'metrics':measured,
                     'guard_status':'PASS','hardware_network_feedback':'UNAVAILABLE'}
                trace.write(json.dumps(row,allow_nan=False)+'\n')
                if elapsed>=next_sample:
                    values=[elapsed,*xyz,measured['full'],measured['fixed'],measured['condition'],measured['q2'],period,float('nan'),*state['q'],*command]
                    csv.write(','.join(format(float(v),'.17g') for v in values)+'\n');next_sample+=.02
                last=post
        if hasattr(self.io,'mode'):self.io.mode='Idle'
        after=self.io.read_state();self._state_guard(after,p,True);p.guard(after['q'])
        error=float(np.linalg.norm(np.asarray(after['O_T_EE'])[12:15]-p.target[12:15]));rotation_error=angle(after['O_T_EE'],p.target)
        yield f'ENDPOINT position_error_mm {error*1000} orientation_error_deg {math.degrees(rotation_error)}\n'
        if error>p.position_tolerance or rotation_error>p.angle_tolerance:raise RuntimeError('Endpoint verification failed')
        yield 'FINAL_STATE '+json.dumps(after,allow_nan=False)+'\n';yield 'PASS certified joint arc\n'

    def gripper(self,args):
        try:
            values=list(map(float,Path(args[1]).read_text().split()));width,speed,tolerance,mode=values[:4]
            if len(values)!=(5 if mode==2 else 4) or mode not in (0,1,2) or not np.isfinite(values).all() or not 0<=width<=.08 or not 0<speed<=.1 or not 0<tolerance<=.001:raise ValueError('Invalid gripper position command')
            upper=values[4] if mode==2 else width+tolerance
            if mode==2 and not width<=upper<=.08:raise ValueError('Invalid contact width upper bound')
            state=self.io.read_state()
            if state['robot_mode']!='Idle' or state['current_errors'] or np.max(abs(np.asarray(state['dq'])))>.01:raise RuntimeError('Gripper requires stationary fault-free Idle arm')
            before=self.io.read_gripper()
            if not math.isfinite(before['max_width']) or before['max_width']<width:raise RuntimeError('Opening exceeds calibrated simulation range')
            if mode==1 and before.get('is_grasped') is not False:raise RuntimeError('Held-object gripper flag TRUE or UNAVAILABLE; approach refused')
            moved=abs(before['width']-width)>tolerance
            if moved and self.io.move_gripper(width,speed) is not True:raise RuntimeError('Finger position command did not complete')
            # SDK verification timeout starts AFTER blocking move() returns.
            inside=None;after=self.io.read_gripper()
            for tick in range(2000):
                valid=math.isfinite(after['width']) and width-tolerance<=after['width']<=upper
                if valid:
                    if inside is None:inside=tick
                    if tick-inside>=100:break
                else:inside=None
                self._advance(self.io.read_state()['q_d']);after=self.io.read_gripper()
            else:raise RuntimeError('Gripper opening verification failed')
            lines=['START_GRIPPER '+json.dumps(before),'FINAL_GRIPPER '+json.dumps(after),
                f'WIDTH_VERIFIED target_m {width} actual_m {after["width"]} moved {int(moved)}','PASS gripper width']
            return self._result(args,0,'\n'.join(lines)+'\n')
        except Exception as error:return self._result(args,1,'STOP '+str(error)+'\n')
