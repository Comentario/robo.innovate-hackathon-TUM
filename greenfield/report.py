"""Material and track audits plus source-qualified reference-envelope checks."""
from pathlib import Path
import json,math,base64,mimetypes


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
    if report['config'].get('max_same_shade_run')==2:
        def triples(grid,rows,cols):
            return sum(grid[r*cols+c]==grid[r*cols+c+1]==grid[r*cols+c+2] for r in range(rows) for c in range(cols-2))+sum(grid[r*cols+c]==grid[(r+1)*cols+c]==grid[(r+2)*cols+c] for r in range(rows-2) for c in range(cols))
        for layer in report['layers']:
            if triples([material[i]['shade'] for i in layer['ids']],4,10):raise AssertionError('Three adjacent equal shades in formed layer')
        by_layer={layer['index']:layer['ids'] for layer in report['layers']};stacks={}
        for event in report['events']:
            if event['kind']=='layer_stacked':stacks.setdefault(event.get('pallet',0),[]).append(by_layer[event['layer']])
        for rows in stacks.values():
            grids=[[material[i]['shade'] for i in row] for row in rows]
            if any(grids[n][k]==grids[n+1][k]==grids[n+2][k] for n in range(len(grids)-2) for k in range(40)):raise AssertionError('Three vertically adjacent equal shades')
    for e in report['events']:
        if e['kind']=='step' and e['speed_m_s'] is not None:
            expected=e['motion']['duration'] if e.get('motion') else e['distance_m']/e['speed_m_s']
            if not math.isclose(e['duration'],expected,rel_tol=1e-9):raise AssertionError('Stroke time not derived')
    return {'material_identity_unique':True,'continuous_tracks':True,'single_motion_per_identity':True,
        'no_duplicate_shipment':True,'pallets_560_each':True,'layer_mix_valid':True,
        'stroke_time_matches_declared_profile':True,'mass_balance':report['kpis']['material_balance_ok'],
        'scope':'Identity, sequence and kinematic accounting; not full tool/brick collision or gripping validation.'}


def equipment_checks(c):
    mass=c['brick_mass_kg'];g=c['geometry'];layer=40*mass+c['layer_tool_mass_kg']
    checks=[
        {'component':'Layer gantry','selected':f'{layer:.1f} kg including assumed tool',
         'reference':'2000 N high-load axis envelope (~204 kg); selected X/Z speed <= 1.25 m/s',
         'within_envelope':layer<=2000/9.80665 and c['speeds']['gantry_xy_m_s']<=1.25},
        {'component':'Each powered roller zone','selected':f'{mass:.1f} kg/zone; 0.50 m reference roller; {c["speeds"]["buffer_m_s"]} m/s',
         'reference':'EC5000 35 W 30:1: 0.60 m/s, 350 N with drive head; custom 300 mm zone assembly requires validation',
         'within_envelope':mass*9.80665<=350 and c['speeds']['buffer_m_s']<=.6 and c['speeds']['belt_m_s']<=.6},
        {'component':'Input pallet conveyor','selected':f'{800*mass+25:.1f} kg incl. assumed 25 kg pallet',
         'reference':'Interroll PM9710: 3000 kg/drive, 1250 kg/m; assumed 1.2 m supported pallet',
         'within_envelope':800*mass+25<=3000 and (800*mass+25)/1.2<=1250},
        {'component':'Output pallet conveyor','selected':f'{560*mass+25:.1f} kg incl. assumed pallet',
         'reference':'Same pallet-conveyor envelope; support distribution still requires verification',
         'within_envelope':560*mass+25<=3000 and (560*mass+25)/1.2<=1250},
    ]
    if c.get('flow_loop'):
        checks[1]['component']='Inspection roller zones'
        checks[1]['selected']=f"{mass:.1f} kg/zone; 0.50 m reference roller; {c['speeds']['belt_m_s']} m/s"
    if c.get('layout')=='dual':
        checks=[row for row in checks if row['component']!='Input pallet conveyor']
        log=c['logistics'];stack=800*mass+25
        checks.extend([
            {'component':'Complete-stack bridge','selected':f'{stack+log["fork_tool_kg"]:.1f} kg including assumed fork',
             'reference':f'{log["bridge_capacity_kg"]} kg design target; Demag family is a principle reference, not span/EOAT certification',
             'within_envelope':stack+log['fork_tool_kg']<=log['bridge_capacity_kg']},
            {'component':'Inventory rail cart','selected':f'{c["input_stacks"]*stack+1000:.1f} kg including assumed 1000 kg cart',
             'reference':f'{log["rail_cart_capacity_kg"]} kg custom design target; configuration not supplier-qualified',
             'within_envelope':c['input_stacks']*stack+1000<=log['rail_cart_capacity_kg']},
        ])
    return checks



def visual_payload(report):
    """Preserve every physical trajectory; omit engineering-only repetition."""
    view=dict(report);m=dict(report['mechanics']);view['mechanics']=m
    m['tracks']={identity:[{key:stroke[key] for key in ('t0','t1','from','to','motion','loop_s0','loop_s1','loop_cell','path') if key in stroke} for stroke in seq]
                 for identity,seq in m['tracks'].items()}
    keys=sorted({e['zone'] for e in report['events'] if e['kind']=='stop_command'});lookup={key:i for i,key in enumerate(keys)}
    m['stop_keys']=keys
    m['stop_commands']=[[e['t'],lookup[e['zone']],int(e['opened'])] for e in report['events'] if e['kind']=='stop_command']
    def visible(e):
        if e['kind'] in ('stop_command','buffer_admitted','attach','detach'):return False
        return e['kind']!='step' or e['station'] in ('dehack','stacker','elevator','guide_gate','pallet_out','dock') or e['station'].startswith(('dehack_','stacker_','elevator_','guide_gate_','inventory_','output_','pallet_out_')) or e['station'].endswith(('_former','_reserve'))
    view['events']=[e for e in report['events'] if visible(e)]
    if report['config'].get('flow_loop'):
        view['junctions']=[{'cell':int(e['station'].split('_')[1]),'kind':'inlet' if e['label']=='Guided servo merge into reserved loop gap' else 'outlet','t':e['t']} for e in report['events'] if e['kind']=='step' and e['label'] in ('Guided servo merge into reserved loop gap','Fixed selected-tone outlet aligns outside the loop bend')]
    return view


def render_view(report,folder,study=None):
    suffix='_dual' if report['mechanics'].get('layout')=='dual' else ''
    template=Path(__file__).with_name('viewer'+suffix+'.html').read_text()
    code=Path(__file__).with_name('viewer'+suffix+'.js').read_text()
    library=Path(__file__).parents[1]/'third_party/three/three.min.js'
    view=visual_payload(report)
    view['catalog']=json.loads(Path(__file__).with_name('catalog.json').read_text())
    for row in view['catalog']:
        if row.get('image_asset'):
            asset=Path(__file__).with_name('assets')/row['image_asset']
            if asset.is_file():row['image']='data:'+str(mimetypes.guess_type(asset.name)[0])+';base64,'+base64.b64encode(asset.read_bytes()).decode('ascii')
    payload=json.dumps(view,separators=(',',':')).replace('<','\\u003c')
    template=template.replace('__STUDY__',json.dumps(study or [])).replace('__THREE__',library.read_text()).replace('__REPORT__',payload).replace('__CODE__',code)
    (Path(folder)/'index.html').write_text(template)


def write_report(report,folder):
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=False)
    from .clearance import sampled_material_clearance
    report['sampled_clearance']=sampled_material_clearance(report,96)
    if not report['sampled_clearance']['passed']:
        (folder/'failed-clearance.json').write_text(json.dumps(report['sampled_clearance'],indent=2))
        raise AssertionError('Sampled brick envelope intersection; inspect mechanics before publishing')
    report['audit']=audit(report);report['equipment_checks']=equipment_checks(report['config'])
    report['catalog']=json.loads(Path(__file__).with_name('catalog.json').read_text())
    (folder/'run.json').write_text(json.dumps(report,indent=2))
    render_view(report,folder)
