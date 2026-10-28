"""Export the source's real service covers without changing replay or production data."""
import argparse,base64,hashlib,json
from pathlib import Path
from inspect_reference_cloud import check_geometry

def export(page,exporter,output,source_sha):
    page.add_script_tag(path=str(exporter.resolve()))
    page.evaluate('''()=>{for(const c of [...CART_DEMO.inspectionCovers,...CART_DEMO.routingCovers])c.visible=true;CART_DEMO.scene.updateMatrixWorld(true)}''')
    data=page.evaluate('exportNativeFactory({compactInstances:true,replayBindings:true,enclosuresOnly:true})')
    assert not data['instanceBatches'],'Expected ordinary service panel meshes'
    counts={}
    for item in data['instances']:
        group=item['serviceEnclosure'];key=group['system']+'-'+str(group['lane']);counts[key]=counts.get(key,0)+1
        assert group['system'] in ['inspection','routing'] and 0<=group['lane']<6
    assert len(counts)==12 and all(v>0 for v in counts.values())
    for mid,material in data['materials'].items():
        if 'image' in material:
            name=mid+'.png';(output/name).write_bytes(base64.b64decode(material.pop('image').split(',',1)[1]));material['texture']=name
    data.update(schema='brickflow.source-service-enclosures.v1',referenceSha256=source_sha,counts=counts,
                provenance='Exact source inspectionCovers and routingCovers meshes; no inferred enclosure geometry',geometryChecks=check_geometry(data))
    target=output/'enclosures.json';target.write_text(json.dumps(data,separators=(',',':'))+'\n')
    return dict(file=target.name,sha256=hashlib.sha256(target.read_bytes()).hexdigest(),counts=counts,instances=len(data['instances']))

def main():
    from playwright.sync_api import sync_playwright
    p=argparse.ArgumentParser();p.add_argument('--reference',type=Path,required=True);p.add_argument('--sha256',required=True);p.add_argument('--exporter',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    raw=a.reference.read_bytes();assert hashlib.sha256(raw).hexdigest()==a.sha256
    marker='window.CART_DEMO={model,scene,camera,renderer,';text=raw.decode();assert text.count(marker)==1
    text=text.replace(marker,marker+'actorMeshes,sourceBeams,rowCenters,bricks,inspectionCovers,routingCovers,orbit,',1)
    a.output.mkdir(parents=True,exist_ok=True);author=a.output/'enclosure-authoring.html';author.write_text(text)
    with sync_playwright() as pw:
        browser=pw.chromium.launch(headless=True,args=['--use-gl=angle','--use-angle=swiftshader','--enable-unsafe-swiftshader'])
        page=browser.new_page(viewport={'width':1600,'height':900});page.add_init_script('window.requestAnimationFrame=()=>0');page.goto(author.resolve().as_uri(),wait_until='load',timeout=120000)
        page.wait_for_function('window.CART_DEMO || window.CART_ERROR',timeout=600000,polling=500)
        error=page.evaluate('window.CART_ERROR || null');assert not error,error
        page.evaluate('CART_DEMO.seek(0)');result=export(page,a.exporter,a.output,a.sha256);browser.close()
    (a.output/'enclosure-export-status.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result),flush=True)
if __name__=='__main__':main()
