"""Material and track audits plus source-qualified reference-envelope checks."""
from pathlib import Path
import json,math


def audit(report):
    material={b['id']:b for b in report['material']};m=report['mechanics'];tol=1e-6
    if len(material)!=len(report['material']):raise AssertionError('Duplicate material identity')
    for identity,seq in m['tracks'].items():
        previous=m['initial'][identity];end=0
        for s in seq:
            if s['t0']<end-tol:raise AssertionError('Overlapping material motion: '+identity)
            if s['t1']<=s['t0']:raise AssertionError('Nonpositive stroke')
            if max(abs(a-b) for a,b in zip(previous,s['from']))>tol:raise AssertionError('Position jump: '+identity)
            if not all(math.isfinite(x) for x in s['from']+s['to']):raise AssertionError('Nonfinite pose')
            previous=s['to'];end=s['t1']
    output=[i for pallet in report['pallets'] for i in pallet]
    if len(set(output))!=len(output):raise AssertionError('Brick shipped twice')
    for pallet in report['pallets']:
        if len(pallet)!=560:raise AssertionError('Wrong output pallet size')
        if len({material[i]['product_id'] for i in pallet})!=1:raise AssertionError('Product mixing')
    for layer in report['layers']:
        if layer['monochrome_rows'] or layer['monochrome_columns']:raise AssertionError('Invalid layer mix')
    for e in report['events']:
        if e['kind']=='step' and e['speed_m_s'] is not None:
            if not math.isclose(e['duration'],e['distance_m']/e['speed_m_s'],rel_tol=1e-9):raise AssertionError('Stroke time not derived')
    return {'material_identity_unique':True,'continuous_tracks':True,'single_motion_per_identity':True,
        'no_duplicate_shipment':True,'pallets_560_each':True,'layer_mix_valid':True,
        'stroke_time_distance_over_speed':True,'mass_balance':report['kpis']['material_balance_ok'],
        'scope':'Identity, sequence and kinematic accounting; not full tool/brick collision or gripping validation.'}


def equipment_checks(c):
    mass=c['brick_mass_kg'];g=c['geometry'];layer=40*mass+c['layer_tool_mass_kg']
    return [
        {'component':'Layer gantry','selected':f'{layer:.1f} kg including assumed tool',
         'reference':'2000 N high-load axis envelope (~204 kg); selected X/Z speed <= 1.25 m/s',
         'within_envelope':layer<=2000/9.80665 and c['speeds']['gantry_xy_m_s']<=1.25},
        {'component':'Each 6 m tone conveyor','selected':f'{c["buffer_cells_per_shade"]*mass:.1f} kg; {c["speeds"]["buffer_m_s"]} m/s',
         'reference':'mk GUF-P 2000: up to 125 kg, up to 80 m/min (variant dependent)',
         'within_envelope':c['buffer_cells_per_shade']*mass<=125},
        {'component':'Input pallet conveyor','selected':f'{800*mass+25:.1f} kg incl. assumed 25 kg pallet',
         'reference':'Interroll PM9710: 3000 kg/drive, 1250 kg/m; assumed 1.2 m supported pallet',
         'within_envelope':800*mass+25<=3000 and (800*mass+25)/1.2<=1250},
        {'component':'Output pallet conveyor','selected':f'{560*mass+25:.1f} kg incl. assumed pallet',
         'reference':'Same pallet-conveyor envelope; support distribution still requires verification',
         'within_envelope':560*mass+25<=3000 and (560*mass+25)/1.2<=1250},
    ]


def write_report(report,folder):
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=False)
    from .clearance import sampled_material_clearance
    report['sampled_clearance']=sampled_material_clearance(report,96)
    if not report['sampled_clearance']['passed']:raise AssertionError('Sampled brick envelope intersection; inspect mechanics before publishing')
    report['audit']=audit(report);report['equipment_checks']=equipment_checks(report['config'])
    report['catalog']=json.loads(Path(__file__).with_name('catalog.json').read_text())
    (folder/'run.json').write_text(json.dumps(report,indent=2))
    template=Path(__file__).with_name('viewer.html').read_text()
    code=Path(__file__).with_name('viewer.js').read_text()
    library=Path(__file__).parents[1]/'third_party/three/three.min.js'
    payload=json.dumps(report,separators=(',',':')).replace('<','\\u003c')
    template=template.replace('__THREE__',library.read_text()).replace('__REPORT__',payload).replace('__CODE__',code)
    (folder/'index.html').write_text(template)
