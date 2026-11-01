import collections,gzip,hashlib,json,math
from pathlib import Path
import argparse
parser=argparse.ArgumentParser(description='Check recorded revision 37 material, recipes, orders and interlocks.');parser.add_argument('replay',type=Path);args=parser.parse_args()
m=json.load(gzip.open(args.replay));rs={r['id']:r for r in m['records']};bs=[b for b in rs.values() if b['kind']=='brick'];good={b['id'] for b in bs if b['good']};bad={b['id'] for b in bs if not b['good']};out=[i for pal in m['pallets'] for i in pal['ids']]
assert len(bs)==m['totalInput']==m['inspected']==57600 and m['completeInput']
assert m['rejected']==len(bad) and len(out)==len(set(out)) and set(out)<=good
assert m['produced']==m['delivered']==m['stored']==len(m['pallets'])
assert math.isclose(m['bph'],len(out)*3600/m.get('productionWindow',m['productionEnd'])) and math.isclose(m['pph'],len(m['pallets'])*3600/m.get('productionWindow',m['productionEnd']))
for p0 in m['pallets']:
 assert len(p0['ids'])==560
 c=[rs[i]['shade'] for i in p0['ids']]
 if p0['category']:
  assert set(c)=={p0['category']-1}
 else:
  for z in range(14):
   for row in range(4):
    for col in range(10):
     k=z*40+row*10+col
     for step,n,limit in [(1,col,8),(10,row,2),(40,z,12)]:
      if n<limit: assert len({c[k],c[k+step],c[k+2*step]})>1
for o in m['orders']:
 assert len(o['palletIds'])==o['loaded'] and o['loaded']<=8
 assert all(m['pallets'][i]['category']==o['category'] for i in o['palletIds'])
 if o['status']=='shipped':assert o['loaded']==8
assert sum(o['loaded'] for o in m['orders'] if o['status']=='shipped')==m['shipped']
assert len({(pal['lane'],pal['well']) for pal in m['pallets']})==18
interlocks=0
for lane in range(6):
 seq=sorted((b for b in bs if b['c']==lane),key=lambda b:b['rejectZoneEntry'])
 for a,b in zip(seq,seq[1:]):
  if a.get('ejectionCycle'):
   assert b['rejectZoneEntry']+1e-6>=a['ejectionCycle']['home'];interlocks+=1

if 'discardLedger' in m:
 assert m['disposed']==len(bad)
 assert {v['id'] for v in m['discardLedger']}==bad
 assert len(m['discardLedger'])==len(bad)
def tracks(r):
 for v in r['tracks']:
  if isinstance(v,list):yield {'t0':v[0],'t1':v[1],'kind':m['kinds'][v[6]]}
  else:yield v
for layer in m['layers']:
 arrivals=[next(t['t1'] for t in tracks(rs[i]) if t['kind']=='direct-row-routing') for i in layer['ids']]
 assert all(arrivals[(r-1)*10+c]<=arrivals[r*10+c]+1e-6 for r in range(1,4) for c in range(10))
 for kind in ['layer-buffer-zone-one','layer-buffer-zone-two']:
  spans=[[(t['t0'],t['t1']) for t in tracks(rs[i]) if t['kind']==kind] for i in layer['ids']]
  assert all(v==spans[0] for v in spans)
carryover=sum(len({rs[i]['cart'] for i in pal['ids']})==2 for pal in m['pallets'])
assert carryover>0
print(json.dumps({'complete':True,'bricks':len(bs),'rejected':len(bad),'pallets':len(m['pallets']),'products':dict(collections.Counter(pal['category'] for pal in m['pallets'])),'bricks_h':m['bph'],'pallets_h':m['pph'],'production_seconds':m['productionEnd'],'replay_seconds':m['total'],'warehouse':dict(collections.Counter(s['category'] for s in m['storage'] if s['state']=='stored')),'loaded':m['loaded'],'shipped':m['shipped'],'interlock_checks':interlocks,'mixed_cart_pallets':carryover,'approved_WIP':len(good-set(out)),'fleet_tasks':len(m['fleetPlans'])},indent=2))
