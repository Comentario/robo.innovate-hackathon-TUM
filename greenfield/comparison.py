import html
from pathlib import Path

def write_comparison(results,path):
    keys=['scenario','status','released_good_bph','formed_good_bph','full_pallets','partial_pallet_bricks','residual_wip','reject_bricks','quarantine_bricks','automatic_recoveries']
    labels=['Configuration','Run status','Released good/h','Formed good/h','Full pallets','Partial pallet','Carryover / WIP','Reject','Quarantine','Auto recoveries']
    rows=[]
    for r in results:
        cells=[]
        for k in keys:
            value=html.escape(str(r[k]))
            if k=='scenario':value=f'<a href="{html.escape(r["link"])}">{value}</a>'
            if k in ('released_good_bph','formed_good_bph') and r['status']=='safe_hold':value+=' (censored)'
            cells.append('<td>'+value+'</td>')
        rows.append('<tr>'+''.join(cells)+'</tr>')
    Path(path).write_text('''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Greenfield configuration study</title><style>body{font:15px Arial;background:#edf0f1;color:#223039;padding:24px}table{border-collapse:collapse;background:#fff}td,th{padding:10px;border:1px solid #b7c7cc;text-align:left}th{background:#dce7e9}a{color:#24576a}.note{max-width:1000px;line-height:1.5}</style><h1>Greenfield · configuration study</h1><p class="note">Autonomous nominal flow. No human review station. Same product and input seed; bounded reinspection, automatic quarantine, finite stock and safe hold.</p><p class="note">Released rates count complete pallets only. Formed rates include the partial pallet. Safe-held runs are censored and are not completed-batch capacity comparisons. No blanket labor reduction, ROI or field-validated throughput claim.</p><table><tr>'''+''.join('<th>'+x+'</th>' for x in labels)+'</tr>'+''.join(rows)+'''</table><p class="note">Equipment reference bounds do not qualify the integrated machine. Speeds, footprint orientation, EOAT, brick mass and classification error model remain engineering assumptions. All residual material is retained by identity.</p></html>''')
