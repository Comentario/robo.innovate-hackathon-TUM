#!/usr/bin/env python3
"""Compare selective layer-repair capacities without replacing the 3D checkpoint."""
import sys,json,argparse,html
from pathlib import Path
root=Path(__file__).resolve().parents[1];sys.path[:0]=[str(root),str(root/'.deps/plant_sim')]
from greenfield.layer_study import synthetic_layers,LayerRepairStudy
p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output-dir',type=Path,required=True);p.add_argument('--stacks',type=int,default=36);p.add_argument('--seed',type=int,default=8)
a=p.parse_args()
if a.output_dir.exists():p.error('Choose a new output directory')
a.output_dir.mkdir(parents=True)
layers=synthetic_layers(a.seed,stacks=a.stacks);results=[]
for heads,cycle,availability in [(1,5.,1.),(2,5.,1.),(2,8.,1.),(2,5.,.85)]:
 r=LayerRepairStudy(layers,heads,cycle,availability).run();r['input_seed']=a.seed;r['defect_probability']=.12;results.append(r)
 print(f"{heads} head(s)/station, {cycle}s/repair, availability {availability}: {r['shipped_bph']:.0f} bricks/h",flush=True)
(a.output_dir/'results.json').write_text(json.dumps(results,indent=2))
rows=''.join('<tr>'+''.join('<td>'+html.escape(str(v))+'</td>' for v in [r['heads_per_station'],r['repair_cycle_s'],r['availability_factor'],round(r['shipped_bph']),r['full_pallets'],r['repaired_positions'],r['rejected_bricks']])+'</tr>' for r in results)
example=results[1]['layers'][0]
colors=['#c39a70','#a66d4d','#77503d']
def grid(after):
    cells=[]
    for k in range(40):
        shade=example['grid'][k] if after else example['original_shades'][k]
        color=colors[shade] if after or example['original_good'][k] else '#38343c'
        changed=after and k in example['changed_slots']
        cells.append('<span style="background:'+color+';border:3px '+('dashed #a1ffdb' if changed else 'solid transparent')+';padding:10px 0;text-align:center">'+('✓' if changed else str(k+1))+'</span>')
    return '<div style="display:grid;grid-template-columns:repeat(10,1fr);gap:3px">'+''.join(cells)+'</div>'
example_html='<h2>One layer, before and after</h2><p>Synthetic input. Dark gray marks rejected bricks. Dashed borders mark corrected positions in the output. The other accepted bricks stay in place.</p><h3>Input layer</h3>'+grid(False)+'<h3>Corrected layer</h3>'+grid(True)
(a.output_dir/'index.html').write_text('<!doctype html><html lang="en"><meta charset="utf-8"><title>Selective Layer Repair — Capacity Study</title><style>body{font:17px system-ui;background:#102b34;color:#e6f4f2;max-width:1100px;margin:50px auto;padding:24px}h1{font-size:40px}table{border-collapse:collapse;width:100%;background:#183c46}td,th{padding:17px;text-align:left;border-bottom:1px solid #38616a}p{line-height:1.7}.tag{color:#65dbc3}.flow{padding:25px;background:#1c424c;border-left:5px solid #65dbc3}a{color:#65dbc3}</style><p class="tag">ENGINEERING CAPACITY SCREENING · NOT COMMISSIONED THROUGHPUT</p><h1>Move layers. Repair exceptions.</h1><p class="flow">Kiln cart → two dehackers → layer inspection & spreading → selective repair → layer closing → two guided palletizers</p><p>Input: '+str(a.stacks)+' stacks × 800 bricks. Layer: 40 bricks. Output pallet: 560 bricks. Three accepted shades; no three equal consecutive shades in rows, columns or height. Good bricks removed for blending return to stock.</p><table><tr><th>Heads/station</th><th>Seconds/repair</th><th>Availability</th><th>Shipped bricks/h</th><th>Full pallets</th><th>Repairs</th><th>Rejects</th></tr>'+rows+'</table><p>Every repair includes removal and replacement. One head per station means two robots total; two heads means four. Cycle times are selected hypotheses, not manufacturer guarantees. Layer transfer times derive from triangular/trapezoidal axis profiles. Spread/close, inspection, verified-stock replenishment and pallet changes are timed. Buffers are finite. Each line retains its partial pallet at the end of the cart.</p><p>The model is independent of the existing 3D demo. It screens capacity and material accounting; it does not simulate gripping, robot reach, paths, contact or collisions. Equal thirds is a soft preference. The bounded search preserves accepted positions heuristically, not with a minimum-edit proof. The 0.85 factor is a sensitivity assumption, not measured OEE.</p><p><a href="results.json">Inspect all assumptions, stage times, layer grids and release events</a></p>'+example_html+'</html>')
