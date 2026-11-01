"""Sample a timed joint path on one continuous playback timeline."""
from bisect import bisect_right
import math


class TimedPath:
    def __init__(self,times,positions):
        self.times=list(times)
        self.positions=[list(p) for p in positions]
        if not times or len(times)!=len(positions):raise ValueError('empty or inconsistent trajectory')
        size=len(positions[0])
        if not size or any(len(p)!=size for p in positions):raise ValueError('inconsistent joint dimensions')
        if any(not math.isfinite(v) for v in self.times+[v for p in self.positions for v in p]):raise ValueError('non-finite trajectory')
        if self.times[0]<0 or any(b<=a for a,b in zip(self.times,self.times[1:])):raise ValueError('trajectory times must increase')

    @property
    def duration(self):return self.times[-1]

    def sample(self,elapsed):
        if elapsed<=self.times[0]:return list(self.positions[0])
        if elapsed>=self.duration:return list(self.positions[-1])
        i=bisect_right(self.times,elapsed)-1
        fraction=(elapsed-self.times[i])/(self.times[i+1]-self.times[i])
        return [a+fraction*(b-a) for a,b in zip(self.positions[i],self.positions[i+1])]
