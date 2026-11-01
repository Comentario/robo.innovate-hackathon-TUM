"""Portable English report; execution acknowledgements and visual evidence remain distinct."""
from collections import Counter
from html import escape


def render_report(result):
    esc=lambda value:escape(str(value))
    plan=result['job']['plan']
    report=result['execution_report']
    validation=result['final_validation']
    expected=plan['blend']
    actual=Counter(p['color_group'] for p in report['confirmed_placements'])
    rows=''.join(f'<tr><td>{esc(g)}</td><td>{n}</td><td>{actual[g]}</td></tr>' for g,n in expected.items())
    events=''.join('<tr>'+''.join(f'<td>{esc(e.get(k,""))}</td>' for k in ('step','phase','outcome','reason'))+'</tr>' for e in report['events'][-16:])
    issues=''.join(f'<li>{esc(issue)}</li>' for issue in validation['issues'])
    if validation['status']=='awaiting_observation':
        evidence='No independent final observation has been supplied. Successful acknowledgements do not prove the physical result.'
    elif not validation['independent']:
        evidence='Synthetic observation only. This checks the validator, not a real pallet.'
    else:
        evidence='Result compared with the supplied perception observation. Source metadata is declared by its producer.'
    status=result.get('view_status',report['status'])
    cells=''
    for layer in range(plan['shape']['layers']):
        bricks=''.join(f'<div class="brick {esc(p["color_group"])}"><strong>#{p["step"]} {esc(p["color_group"])}</strong><small>{esc(p.get("visible_face","face not modeled"))}</small></div>' for p in plan['placements'] if p['layer']==layer)
        cells+=f'<h3>Layer {layer+1}</h3><div class="grid">{bricks}</div>'
    return f'''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Brick blending · integration report</title><style>
body{{font:15px system-ui;background:#122027;color:#e5edf1;max-width:1000px;margin:40px auto;padding:0 24px}}h1{{font-size:34px}}h2{{font-size:20px;margin-top:30px}}p{{line-height:1.6;color:#c2d2da}}.cards{{display:flex;gap:14px;flex-wrap:wrap}}.card{{padding:20px;background:#1d323c;border:1px solid #45606d;border-radius:10px;flex:1;min-width:180px}}.card strong{{display:block;font-size:23px;color:#9de5cc}}table{{border-collapse:collapse;width:100%}}td,th{{border-bottom:1px solid #3c535f;padding:10px;text-align:left;overflow-wrap:anywhere}}small{{display:block;margin-top:6px}}.grid{{display:grid;grid-template-columns:repeat({plan['shape']['columns']},1fr);gap:8px}}.brick{{padding:16px;border-radius:5px}}.dark{{background:#704331}}.medium{{background:#b77852}}.light{{background:#e7c8a1;color:#30271f}}code{{overflow-wrap:anywhere}}.notice{{border-left:4px solid #e6be6c;padding:12px 18px;background:#34332c}}@media(max-width:600px){{body{{margin:20px auto}}td,th{{padding:7px;font-size:12px}}}}
</style><h1>Brick blending · integration report</h1>
<p>Run <code>{esc(result['run_id'])}</code><br>Inventory snapshot: {esc(result['snapshot']['snapshot_id'])} · Source: {esc(result['snapshot']['source'])}</p>
<div class="cards"><div class="card">Execution<strong>{esc(status)}</strong>{len(report['confirmed_placements'])} / {len(plan['placements'])} confirmed</div><div class="card">Final observation<strong>{esc(validation['status'].replace('_',' ').capitalize())}</strong>{validation['observed_positions']} positions observed</div></div>
<p class="notice">{esc(evidence)}</p><h2>Confirmed shade quantities</h2><table><tr><th>Shade</th><th>Planned</th><th>Confirmed</th></tr>{rows}</table>
<h2>Inventory and gripper state</h2><p>Available: {len(report['available_ids'])} · Held: {esc(report['held_brick'])} · Placed but unconfirmed: {esc(report['placed_unconfirmed'])} · Uncertain: {esc(report['uncertain_brick'])}</p>
<h2>Target pattern · all layers in order</h2><p>This is the planned pattern, not a camera observation.</p>{cells}
<h2>Recent action acknowledgements</h2><table><tr><th>Step</th><th>Phase</th><th>Outcome</th><th>Reason</th></tr>{events}</table>
<h2>Final observation differences</h2><ul>{issues or '<li>No differences recorded. Check whether an observation was supplied above.</li>'}</ul>
<p>Simulation integration report · no articulated arm, IK, collision-free motion or physical grasp has been verified.</p></html>'''
