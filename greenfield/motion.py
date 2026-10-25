"""Triangular/trapezoidal kinematics with explicit boundary speeds."""
import math

def profile(distance,speed,acceleration,start_speed=0.,end_speed=0.):
    if min(distance,speed,acceleration)<=0 or min(start_speed,end_speed)<0 or max(start_speed,end_speed)>speed+1e-9:raise ValueError('Invalid motion envelope')
    if distance+1e-9<abs(end_speed**2-start_speed**2)/(2*acceleration):raise ValueError('Insufficient braking distance')
    peak=min(speed,math.sqrt(acceleration*distance+(start_speed**2+end_speed**2)/2))
    ta=(peak-start_speed)/acceleration;td=(peak-end_speed)/acceleration
    da=(peak**2-start_speed**2)/(2*acceleration);dd=(peak**2-end_speed**2)/(2*acceleration)
    cruise=max(0,(distance-da-dd)/peak);duration=ta+cruise+td
    return {'duration':duration,'acceleration':acceleration,'peak':peak,'ramp':ta,'accel_time':ta,'decel_time':td,'start_speed':start_speed,'end_speed':end_speed,'distance':distance}

def fraction(elapsed,p):
    t=max(0,min(p['duration'],elapsed));a=p['acceleration'];v=p['peak'];ta=p.get('accel_time',p['ramp']);td=p.get('decel_time',p['ramp']);v0=p.get('start_speed',0);v1=p.get('end_speed',0);d=p['distance']
    if t<ta:x=v0*t+.5*a*t*t
    elif t>p['duration']-td:x=d-v1*(p['duration']-t)-.5*a*(p['duration']-t)**2
    else:x=v0*ta+.5*a*ta*ta+v*(t-ta)
    return max(0,min(1,x/d))
