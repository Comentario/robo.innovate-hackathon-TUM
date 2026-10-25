"""Rest-to-rest triangular/trapezoidal kinematics; no contact dynamics."""
import math

def profile(distance,speed,acceleration):
    peak=min(speed,math.sqrt(distance*acceleration))
    ramp=peak/acceleration
    duration=distance/peak+ramp
    return {'duration':duration,'acceleration':acceleration,'peak':peak,'ramp':ramp,'distance':distance}

def fraction(elapsed,p):
    t=max(0,min(p['duration'],elapsed));a=p['acceleration'];v=p['peak'];r=p['ramp'];d=p['distance']
    if t<r:x=.5*a*t*t
    elif t>p['duration']-r:x=d-.5*a*(p['duration']-t)**2
    else:x=.5*a*r*r+v*(t-r)
    return max(0,min(1,x/d))
