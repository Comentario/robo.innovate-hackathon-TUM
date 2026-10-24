import argparse,json
from pathlib import Path
from copy import deepcopy
from .model import Plant
from .report import write_report

def main():
    p=argparse.ArgumentParser(description='Concept 1: autonomous new-facility brick blending')
    p.add_argument('--config',type=Path,default=Path('config/greenfield.json'))
    p.add_argument('--output-dir',type=Path,default=Path('artifacts/greenfield_01'))
    p.add_argument('--compare',action='store_true');p.add_argument('--cells',type=int,choices=(2,4))
    args=p.parse_args()
    if args.output_dir.exists():p.error('Select a new output directory; previous evidence is preserved')
    c=json.loads(args.config.read_text())
    if args.cells:c['cells']=args.cells;c['accepted_overflow_capacity']=50*args.cells
    scenarios=[('Autonomous reference',{})]
    if args.compare:
        scenarios.extend([
            ('Two-cell alternative',{'cells':2,'accepted_overflow_capacity':100}),
            ('One cell isolated before dispatch',{'faults':{**c['faults'],'disabled_cells':[0]}}),
            ('More uncertain observations',{'uncertain_rate':.20}),
            ('High rejection',{'defect_rate':.25}),
            ('Alignment outside recovery range',{'faults':{**c['faults'],'alignment_error_m':.020}}),
            ('Missing source confirmation',{'faults':{**c['faults'],'critical_sensor_layer':2}}),
        ])
    results=[]
    for i,(name,changes) in enumerate(scenarios):
        config=deepcopy(c);config.update(changes);r=Plant(config).run()
        folder=args.output_dir if i==0 else args.output_dir/f'scenario_{i}'
        write_report(r,folder)
        results.append({'scenario':name,'link':'index.html' if not i else f'scenario_{i}/index.html','status':r['status'],**r['kpis']})
        print(name,r['status'],r['kpis']['released_good_bph'],flush=True)
    (args.output_dir/'comparison.json').write_text(json.dumps(results,indent=2))
    from .comparison import write_comparison
    write_comparison(results,args.output_dir/'comparison.html')
    return 0

if __name__=='__main__':raise SystemExit(main())
