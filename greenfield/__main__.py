import argparse,json
from pathlib import Path
from copy import deepcopy
from .model import Plant
from .twin import TwinPlant
from .report import write_report,render_view

def main():
    p=argparse.ArgumentParser(description='Autonomous brick plant: eight cells, two parallel lines')
    p.add_argument('--config',type=Path,default=Path('config/greenfield_dual.json'))
    p.add_argument('--output-dir',type=Path,default=Path('artifacts/greenfield_04'))
    p.add_argument('--compare',action='store_true');p.add_argument('--cells',type=int,choices=(2,4,6,8))
    args=p.parse_args()
    if args.output_dir.exists():p.error('Select a new output directory; previous evidence is preserved')
    c=json.loads(args.config.read_text());dual=c.get('layout')=='dual'
    if args.cells:
        if dual and args.cells!=8:p.error('The dual layout keeps eight cells. Use the prior config for another cell count.')
        c['cells']=args.cells;c['accepted_overflow_capacity']=50*args.cells
    scenarios=[('Two parallel lines' if dual else 'Single-line reference',{})]
    if args.compare and dual:
        scenarios.extend([
            ('Previous layout · different logistics',{'layout':'single'}),
            ('Slower inventory bridge',{'logistics':{**c['logistics'],'bridge_xy_m_s':.3,'bridge_z_m_s':.2}}),
            ('Longer discard unloading service',{'logistics':{**c['logistics'],'unload_service_s':60}}),
            ('One cell isolated before dispatch',{'faults':{**c['faults'],'disabled_cells':[0]}}),
            ('High rejection',{'defect_rate':.25}),
            ('Discard collection unavailable',{'logistics':{**c['logistics'],'discard_collection_available':False}}),
            ('Missing layer confirmation',{'faults':{**c['faults'],'critical_sensor_layer':2}}),
        ])
    results=[];folders=[]
    for i,(name,changes) in enumerate(scenarios):
        config=deepcopy(c);config.update(changes);model=TwinPlant if config.get('layout')=='dual' else Plant
        r=model(config).run();folder=args.output_dir if i==0 else args.output_dir/f'scenario_{i}'
        write_report(r,folder);folders.append(folder)
        results.append({'scenario':name,'link':'index.html' if not i else f'scenario_{i}/index.html','status':r['status'],'cells':config['cells'],**r['kpis'],'discard_bricks':r['kpis']['reject_bricks']+r['kpis']['quarantine_bricks']})
        print(name,r['status'],r['kpis']['released_good_bph'],flush=True)
    study=[{'label':r['scenario'],'cells':r['cells'],'released_good_bph':r['released_good_bph'],'formed_good_bph':r['formed_good_bph'],'status':r['status']} for r in results[:3]]
    # Derived views share the same comparative evidence. Raw runs remain untouched.
    for folder in folders:
        page=folder/'index.html';page.write_text(page.read_text().replace('id="capacityStudy">[]</script>','id="capacityStudy">'+json.dumps(study)+'</script>'))
    (args.output_dir/'comparison.json').write_text(json.dumps(results,indent=2))
    from .comparison import write_comparison
    write_comparison(results,args.output_dir/'comparison.html')
    return 0

if __name__=='__main__':raise SystemExit(main())
