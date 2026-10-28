"""Build a self-contained A/B viewer for actual Unreal lighting-review captures."""
import argparse
import base64
import io
import json
from pathlib import Path

from PIL import Image


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    args = parser.parse_args()
    cases = [
        ("input-input", "Input pallets", "Side fill helps stack faces. The source input preset is wide; a closer camera is needed for the final dehacking shot."),
        ("inspection-closed-inspection", "Inspection: closed housing", "Keep opaque service panels. Exterior light cannot reveal an occluded camera. Reduce the trial roof hotspot."),
        ("inspection-cutaway-inspection", "Inspection: service cutaway", "Existing source cutaway, not invented transparency. Housing detail improves, but the trial fill is too strong on bright rails; reduce and localize it."),
        ("warehouse-warehouse", "Classified warehouse", "Broad overhead and side fill improve coverage. Rebalance the brightest floor patch before approval."),
        ("warehouse-stock-detail", "Stock and pallet base", "Pallet side faces and fork clearance are clearer. Retain contact shadows and reduce excessive light on stack tops."),
        ("side-loading-shipping", "Side-loading area", "The original lighting leaves the outer trailers in deep shadow. Add dedicated area coverage for all four loading positions."),
        ("side-loading-fork-detail", "Forks, pallet and trailer", "First-priority improvement: the real source pose becomes readable with side fill. Preserve separation of forks, pallet underside and trailer edge."),
        ("warehouse-overview", "Whole-layout review", "The new logistics area needs separate light coverage. Reframe the source overview to include the complete loading area in the final camera path.")
    ]
    values = []
    for stem, title, note in cases:
        item = dict(title=title, note=note, stem=stem)
        for variant in ["baseline", "candidate"]:
            p = args.root / "unreal-stills" / (stem + "-" + variant + ".png")
            with Image.open(p) as image:
                buffer = io.BytesIO();image.convert("RGB").save(buffer, "JPEG", quality=90)
            item[variant] = "data:image/jpeg;base64," + base64.b64encode(buffer.getvalue()).decode()
        values.append(item)
    data = json.dumps(values).replace("</", "<\\/")
    page = '''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Brickflow | Latest Unreal lighting review</title><style>
body{background:#101820;color:#e6eef4;font:16px/1.5 system-ui;margin:24px auto;max-width:1600px;padding:0 20px}h1{font-size:27px}button,select{padding:10px;margin:5px 12px 10px 0;background:#d9e8f0;color:#10232f;border:0;border-radius:6px;font:inherit}figure{margin:0}img{width:100%;display:block;border-radius:10px}#label{color:#88d6ed}p{max-width:1100px}
</style><h1>Latest Unreal scene: lighting A/B</h1><p>Unvalidated greenfield 37 reference, f8bacc33. Frozen source states rendered in Unreal Vulkan. This is an authoring review; the new native simulation is not ported. Trial lights are not approved.</p>
<select id="case"></select><button id="base">Baseline</button><button id="trial">Trial lighting</button><strong id="label"></strong><figure><img id="image" alt="Unreal lighting comparison"></figure><p id="note"></p>
<script>const cases=DATA;let active=0,variant='candidate';const picker=document.getElementById('case');cases.forEach((c,i)=>{const o=document.createElement('option');o.value=i;o.textContent=c.title;picker.appendChild(o)});function show(){const c=cases[active];document.getElementById('image').src=c[variant];document.getElementById('label').textContent=variant==='candidate'?'TRIAL LIGHTING':'BASELINE';document.getElementById('note').textContent=c.note}picker.onchange=()=>{active=+picker.value;show()};document.getElementById('base').onclick=()=>{variant='baseline';show()};document.getElementById('trial').onclick=()=>{variant='candidate';show()};show();</script></html>'''
    (args.root / "lighting-ab.html").write_text(page.replace("DATA", data))
    print(json.dumps({"abPairs": len(cases), "viewer": str(args.root / "lighting-ab.html")}))


if __name__ == "__main__":
    main()
