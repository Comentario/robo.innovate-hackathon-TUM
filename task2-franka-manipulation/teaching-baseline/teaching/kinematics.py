"""Read-only FK/IK and singularity checks using the URDF exported from this robot."""
import hashlib
import math
from pathlib import Path
import numpy as np
import pinocchio as pin
from scipy.optimize import least_squares, minimize

HERE=Path(__file__).resolve().parent


class Kinematics:
    def __init__(self,tool,policy):
        self.policy=policy
        self.model=pin.buildModelFromUrdf(str(HERE/'robot_model.urdf'))
        flange_id=self.model.getFrameId('link8')
        flange=self.model.frames[flange_id]
        matrix=np.array(tool).reshape((4,4),order='F')
        self.ee=self.model.addFrame(pin.Frame('configured_EE',flange.parentJoint,flange_id,
             flange.placement*pin.SE3(matrix[:3,:3],matrix[:3,3]),pin.FrameType.OP_FRAME))
        self.data=self.model.createData()
        self.lower=np.maximum(self.model.lowerPositionLimit,np.array([-2.7437,-1.7837,-2.9007,-3.0421,-2.8065,.5445,-3.0159]))+policy['joint_limit_margin_rad']
        self.upper=np.minimum(self.model.upperPositionLimit,np.array([2.7437,1.7837,2.9007,-.1518,2.8065,4.5169,3.0159]))-policy['joint_limit_margin_rad']
        self.scale=np.array([1/policy['characteristic_length_m']]*3+[1]*3)
        self.model_sha256=hashlib.sha256((HERE/'robot_model.urdf').read_bytes()).hexdigest()

    def fk(self,q):
        pin.framesForwardKinematics(self.model,self.data,np.asarray(q))
        return self.data.oMf[self.ee].copy()

    def jacobian(self,q,local=False):
        q=np.asarray(q)
        pin.computeJointJacobians(self.model,self.data,q)
        pin.updateFramePlacements(self.model,self.data)
        frame=pin.ReferenceFrame.LOCAL if local else pin.ReferenceFrame.LOCAL_WORLD_ALIGNED
        return pin.getFrameJacobian(self.model,self.data,self.ee,frame).copy()

    def metrics(self,q):
        q=np.asarray(q);j=self.jacobian(q)*self.scale[:,None]
        full=np.linalg.svd(j,compute_uv=False)
        fixed=np.linalg.svd(j[:,[0,1,3,4,5,6]],compute_uv=False)
        return dict(full_sigma_min=float(full[-1]),fixed_elbow_sigma_min=float(fixed[-1]),
                    full_condition=float(full[0]/max(full[-1],1e-12)),
                    fixed_elbow_condition=float(fixed[0]/max(fixed[-1],1e-12)),
                    abs_joint2_rad=abs(float(q[1])),abs_joint5_rad=abs(float(q[4])),
                    elbow_extension_margin_rad=abs(float(q[3])+.467002423653011),
                    joint_limit_margin_rad=float(min(np.min(q-self.lower),np.min(self.upper-q))))

    def acceptable(self,q):
        p=self.policy;m=self.metrics(q)
        return bool(m['full_sigma_min']>=p['min_full_sigma'] and m['fixed_elbow_sigma_min']>=p['min_fixed_elbow_sigma']
                    and m['full_condition']<=p['max_condition'] and m['fixed_elbow_condition']<=p['max_condition']
                    and m['abs_joint2_rad']>=p['min_abs_joint2_rad'] and m['abs_joint5_rad']>=p['min_abs_joint5_rad']
                    and m['elbow_extension_margin_rad']>=p['min_elbow_extension_margin_rad']
                    and m['joint_limit_margin_rad']>=-1e-8)

    @staticmethod
    def target(pose):
        matrix=np.array(pose).reshape((4,4),order='F')
        # Project rounded measured rotations onto SO(3).
        u,_,v=np.linalg.svd(matrix[:3,:3]);rotation=u@v
        if np.linalg.det(rotation)<0:rotation=u@np.diag([1,1,-1])@v
        return pin.SE3(rotation,matrix[:3,3])

    def solve(self,pose,seed,sign2=None,sign5=None,max_evaluations=150,diagnostic=False,preferred=None):
        target=self.target(pose);initial=np.asarray(seed).copy()
        optimize_posture=preferred is not None
        preferred=initial if preferred is None else np.asarray(preferred).copy()
        lo=self.lower.copy();hi=self.upper.copy()
        for index,sign,margin in ((1,sign2,self.policy['min_abs_joint2_rad']),(4,sign5,self.policy['min_abs_joint5_rad'])):
            if sign is not None:
                if sign>0:lo[index]=max(lo[index],margin)
                else:hi[index]=min(hi[index],-margin)
        seed=np.clip(initial,lo+1e-7,hi-1e-7)
        regularization=1e-4 if preferred is not initial else 1e-5
        def residual(q):
            error=pin.log6(self.fk(q).actInv(target)).vector
            return np.r_[error*self.scale,regularization*(q-preferred)]
        def jac(q):
            current=self.fk(q);difference=current.actInv(target)
            j=self.jacobian(q,local=True)
            j=-pin.Jlog6(difference.inverse())@j
            return np.vstack((j*self.scale[:,None],regularization*np.eye(7)))
        result=least_squares(residual,seed,jac=jac,bounds=(lo,hi),max_nfev=max_evaluations,
                             ftol=1e-10,xtol=1e-10,gtol=1e-10)
        q=result.x
        if optimize_posture:
            # Six exact task constraints leave one redundancy coordinate. Optimize
            # it explicitly; a tiny least-squares regularizer otherwise follows
            # the inherited elbow branch until it runs into a singularity/limit.
            def equality(x):return residual(x)[:6]
            def inequality(x):
                m=self.metrics(x)
                return np.array([m['full_sigma_min']-self.policy['min_full_sigma']-.03,
                                 m['fixed_elbow_sigma_min']-self.policy['min_fixed_elbow_sigma']-.03,
                                 self.policy['max_condition']-m['full_condition'],
                                 self.policy['max_condition']-m['fixed_elbow_condition']])
            polished=minimize(lambda x:.5*np.sum((x-preferred)**2),q,
                jac=lambda x:x-preferred,bounds=list(zip(lo,hi)),
                constraints=[dict(type='eq',fun=equality,jac=lambda x:jac(x)[:6]),dict(type='ineq',fun=inequality)],
                method='SLSQP',options=dict(maxiter=100,ftol=1e-10))
            if np.linalg.norm(equality(polished.x))<2e-5 and inequality(polished.x).min()>-1e-6:q=polished.x
        actual=self.fk(q);position=np.linalg.norm(actual.translation-target.translation)
        rotation=np.linalg.norm(pin.log3(actual.rotation.T@target.rotation))
        if position>self.policy['ik_position_tolerance_m'] or rotation>self.policy['ik_rotation_tolerance_rad']:
            return None
        accepted=self.acceptable(q)
        if not accepted and not diagnostic:return None
        return dict(q=q.tolist(),position_error_m=float(position),rotation_error_rad=float(rotation),
                    metrics=self.metrics(q),margin_validated=accepted,evaluations=result.nfev)

    def candidates(self,pose,seeds,limit=4):
        candidates=[]
        for sign2,sign5 in ((1,None),(-1,None)):
            for seed in seeds:
                result=self.solve(pose,seed,sign2,sign5)
                if result and all(np.linalg.norm(np.array(result['q'])-r['q'])>.05 for r in candidates):
                    candidates.append(result)
        candidates.sort(key=lambda r:min(r['metrics']['full_sigma_min'],r['metrics']['fixed_elbow_sigma_min']),reverse=True)
        return candidates[:limit]

    def solve_elbow(self,pose,seed,sign2,joint3):
        """Solve the six task equations with the redundancy coordinate specified."""
        target=self.target(pose);q=np.asarray(seed).copy();q[2]=joint3
        columns=np.array([0,1,3,4,5,6]);lo=self.lower.copy();hi=self.upper.copy()
        if sign2 is not None:
            if sign2>0:lo[1]=max(lo[1],self.policy['min_abs_joint2_rad'])
            else:hi[1]=min(hi[1],-self.policy['min_abs_joint2_rad'])
        if not lo[2]<=joint3<=hi[2]:return None
        def expand(x):
            result=q.copy();result[columns]=x;return result
        def residual(x):return pin.log6(self.fk(expand(x)).actInv(target)).vector*self.scale
        def jac(x):
            full=expand(x);difference=self.fk(full).actInv(target)
            return (-pin.Jlog6(difference.inverse())@self.jacobian(full,local=True))[:,columns]*self.scale[:,None]
        fit=least_squares(residual,np.clip(q[columns],lo[columns]+1e-8,hi[columns]-1e-8),
                          jac=jac,bounds=(lo[columns],hi[columns]),max_nfev=80,ftol=1e-11,xtol=1e-11,gtol=1e-11)
        result=expand(fit.x);actual=self.fk(result)
        if np.linalg.norm(actual.translation-target.translation)>self.policy['ik_position_tolerance_m'] or np.linalg.norm(pin.log3(actual.rotation.T@target.rotation))>self.policy['ik_rotation_tolerance_rad'] or not self.acceptable(result):return None
        return dict(q=result.tolist(),metrics=self.metrics(result))
