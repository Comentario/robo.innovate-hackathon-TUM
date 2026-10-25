#!/usr/bin/env python3
import argparse,json,sys,math
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from greenfield.clearance import pose
from greenfield.motion import fraction
from greenfield.junctions import at
from greenfield.interference import sweep_hit
parser=argparse.ArgumentParser(description='Sample guided transfers and their moving paddle-head clearances');parser.add_argument('report',type=Path);parser.add_argument('--output',type=Path,required=True);args=parser.parse_args();r=json.loads(args.report.read_text());m=r['mechanics'];index={i:[s['t0'] for s in seq] for i,seq in m['tracks'].items()};hits=[];checks=0
for identity,seq in m['tracks'].items():
 if not identity.startswith('B'):continue
 for s in seq:
  if 'path' not in s and not s['station'].endswith('_outlet'):continue
  cell=int(s['station'].split('_')[1]);tool=('REJECT-PUSHER-' if s['station'].endswith('_router') else 'ROW-PUSHER-')+str(cell);size=[.27,.09,.024] if tool.startswith('REJECT') else [.024,.09,.69]
  for k in range(33):
   t=s['t0']+(s['t1']-s['t0'])*k/32;u=fraction(t-s['t0'],s['motion']);p=at(s['path'],u) if 'path' in s else [a+(b-a)*u for a,b in zip(s['from'],s['to'])]+[0.];q=pose(m,tool,t,index);half=[v/2 for v in size];o={'min':[q[a]-half[a] for a in range(3)],'max':[q[a]+half[a] for a in range(3)]};co,si=math.cos(p[3]),math.sin(p[3]);checks+=1
   if sweep_hit(p[:3],p[:3],[.1225,.0345,.0335],o,moving_axes=[[co,0,-si],[0,1,0],[si,0,co]]) is not None:
    if len(hits)<12:hits.append({'brick':identity,'tool':tool,'time':t,'brick_pose':p,'tool_pose':q})
args.output.write_text(json.dumps({'passed':not hits,'checks':checks,'examples':hits,'scope':'33 temporal samples per guided transfer and straight row-pocket nose against the reject/row paddle heads; allowed face contact within 0.1 mm. Not full-machine dynamics.'},indent=2))
