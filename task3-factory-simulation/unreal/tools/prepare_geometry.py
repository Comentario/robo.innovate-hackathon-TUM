"""Extract authoring geometry and actuator bindings from immutable revision 30.

No simulator implementation or replay tracks are shipped in this asset.
"""
import argparse
import base64
import hashlib
import json
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT=Path(__file__).resolve().parents[2]
EXPECTED='7573180b519dfa27f1b97b6cd682659b5235f129f1ad7d4f9b73f25db808805b'

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reference',type=Path,default=ROOT/'artifacts/greenfield_30/index.html')
    parser.add_argument('--output',type=Path,default=ROOT/'unreal/Brickflow/Content/Data/factory.json')
    args=parser.parse_args()
    data=args.reference.read_bytes();fingerprint=hashlib.sha256(data).hexdigest()
    if fingerprint!=EXPECTED:raise ValueError('The greenfield_30 reference changed; explicit migration review required')
    html=data.decode();needle='window.CART_DEMO={model,scene,camera,renderer,'
    if html.count(needle)!=1:raise ValueError('Unexpected viewer instrumentation boundary')
    html=html.replace(needle,needle+'actorMeshes,sourceBeams,rowCenters,bricks,',1)
    temp=ROOT/'artifacts/cinematic/reference_30/authoring.html'
    temp.parent.mkdir(parents=True,exist_ok=True);temp.write_text(html)
    with sync_playwright() as p:
        browser=p.chromium.launch(headless=True,args=['--use-gl=angle','--use-angle=swiftshader','--enable-unsafe-swiftshader'])
        page=browser.new_page()
        # Geometry inspection does not need a continuously rendered WebGL loop.
        page.add_init_script('window.requestAnimationFrame=()=>0')
        page.goto(temp.resolve().as_uri(),timeout=120000,wait_until='load')
        page.wait_for_function('window.CART_DEMO||window.CART_ERROR',timeout=900000,polling=250)
        failure=page.evaluate('window.CART_ERROR||null')
        if failure:raise RuntimeError(failure)
        page.evaluate('CART_DEMO.seek(0);CART_DEMO.scene.updateMatrixWorld(true)')
        page.add_script_tag(path=str(ROOT/'unreal/tools/export_geometry.js'))
        result=page.evaluate('exportNativeFactory()');browser.close()
    result['referenceSha256']=fingerprint
    args.output.parent.mkdir(parents=True,exist_ok=True)
    for key,material in result['materials'].items():
        if 'image' in material:
            image=args.output.parent/(key+'.png')
            image.write_bytes(base64.b64decode(material.pop('image').split(',',1)[1]))
            material['texture']=image.name
    args.output.write_text(json.dumps(result,separators=(',',':')))
    print(json.dumps({'asset':str(args.output),'instances':len(result['instances']),
        'geometries':len(result['geometries']),'materials':len(result['materials']),
        'referenceSha256':fingerprint},indent=2))

if __name__=='__main__':main()
