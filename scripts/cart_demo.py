#!/usr/bin/env python3
"""Package the full-cart production demo as a single offline HTML file."""
import argparse,base64,json,mimetypes,hashlib
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir',type=Path,default=ROOT/'artifacts/greenfield_33')
    args=parser.parse_args()
    folder=args.output_dir;folder.mkdir(parents=True,exist_ok=True)
    catalog=json.loads((ROOT/'greenfield/catalog.json').read_text())
    for item in catalog:
        asset=ROOT/'greenfield/assets'/item.get('image_asset','_missing')
        if asset.is_file():item['image']='data:'+str(mimetypes.guess_type(asset.name)[0])+';base64,'+base64.b64encode(asset.read_bytes()).decode()
    model=(ROOT/'greenfield/cart_model.js').read_text();fingerprint=hashlib.sha256(model.split('/* snapshot-loader */')[0].encode()).hexdigest()[:16]
    replays={}
    for mode in ('mixed','single'):
        cache=folder/(mode+'-'+fingerprint+'.json.gz')
        if cache.exists():replays[mode]=base64.b64encode(cache.read_bytes()).decode()
    html=(ROOT/'greenfield/viewer_cart.html').read_text()
    for key,value in {'__REPLAYS__':json.dumps(replays),'__THREE__':(ROOT/'third_party/three/three.min.js').read_text(),'__CATALOG__':json.dumps(catalog).replace('<','\u003c'),'__MODEL__':(ROOT/'greenfield/cart_model.js').read_text(),'__VIEWER__':(ROOT/'greenfield/viewer_cart.js').read_text()}.items():html=html.replace(key,value)
    (folder/'index.html').write_text(html)
    print(folder/'index.html')
if __name__=='__main__':main()
