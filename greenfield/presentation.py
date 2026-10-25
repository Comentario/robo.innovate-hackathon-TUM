"""Traceable presentation metrics, separate from the production simulation."""
import json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]

def union_seconds(intervals):
    total=0.;end=0.
    for a,b in sorted(intervals):
        total+=max(0.,b-max(a,end));end=max(end,b)
    return total

def build_presentation(report,scenario=None,envelope=None):
    scenario=scenario or json.loads((ROOT/'config/presentation_scenario.json').read_text())
    envelope=envelope or json.loads((ROOT/'config/presentation_envelope.json').read_text())
    c=report['config'];m=report['mechanics'];k=report['kpis'];seconds=report['simulated_seconds'];cells=c['cells'];lines=2
    counts={'one':1,'cells':cells,'lines':lines,'gantries':lines*2,'nests':len(m['bay_z'])*2,'slides':len(m['bay_z']),'branches':cells*2,'zones':cells*8,'inspection_controllers':cells*2,'collector_zones':lines*50,'controllers':cells*2+lines*13,'pushers':cells*3,'cameras':cells*2,'lights':cells*2,'presence':cells*11+lines*50,'bins':lines}
    duties={}
    for group,prefixes,count in [('pushers',('INFEED-','ROW-PUSHER-','REJECT-PUSHER-'),counts['pushers']),('slides',('ROW-SHUTTLE-',),counts['slides'])]:
        active=sum(union_seconds([(s['t0'],s['t1']) for s in seq]) for id,seq in m['tracks'].items() if id.startswith(prefixes))
        duties[group]=min(1.,active/(seconds*count)) if seconds and count else 0.
    active=sum(v.get('travel_s',0.) for name,v in report.get('timing',{}).items() if name.startswith(('dehack_','stacker_')))
    duties['gantry']=min(1.,active/(seconds*counts['gantries'])) if seconds else 0.
    hardware=[0.,0.];power=[0.,0.];rows=[]
    for item in scenario['items']:
        qty=counts[item['count_key']];duty=duties.get(item['duty'],item['duty']) if isinstance(item['duty'],str) else item['duty'];cost=[qty*x for x in item['unit_cost_usd']]
        # Assumed electrical conversion/drive losses for motor assemblies. Electronics/lights use direct inputs.
        efficiency=1. if item['id'] in ('zone_controls','cameras','lighting','presence','controls','air','bins','divert_guides') else scenario['energy_efficiency']
        kw=[qty*x*duty/efficiency for x in item['unit_power_kw']]
        rows.append(dict(item,quantity=qty,duty_fraction=duty,power_basis='Recorded command-duty proxy' if isinstance(item['duty'],str) else 'Assumed utilization',hardware_usd=cost,average_power_kw=kw))
        hardware=[a+b for a,b in zip(hardware,cost)];power=[a+b for a,b in zip(power,kw)]
    investment=[hardware[i]*(1+scenario['integration_fraction'][i]) for i in range(2)]
    energy=[x*seconds/3600 for x in power];per_thousand=[x/k['shipped_good']*1000 if k['shipped_good'] else None for x in energy]
    return {'scenario':scenario,'counts':counts,'items':rows,'hardware_usd':hardware,'investment_usd':investment,'average_power_kw':power,'batch_energy_kwh':energy,'kwh_per_1000_shipped':per_thousand,'electricity_usd_per_1000':[x*scenario['electricity_usd_per_kwh'] if x is not None else None for x in per_thousand],'envelope':envelope,'production':{'good_shipped':k['shipped_good'],'full_pallets':k['full_pallets'],'input_bricks':k['input_bricks'],'input_stacks':c['input_stacks'],'seconds':seconds,'hours':seconds/3600,'normalized_bph':k['shipped_good']*3600/seconds if seconds else 0,'basis':'Complete conforming pallets divided by full batch elapsed time; start-up and drain included. Not a one-hour or steady-state test.'}}
