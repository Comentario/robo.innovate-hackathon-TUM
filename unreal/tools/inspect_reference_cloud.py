"""Read an explicitly pinned, unvalidated reference and stage migration evidence.

Authoring inspection only: this does not install geometry into the native app,
port simulation code, validate the plant, or capture a movie.
"""
import argparse
import base64
import hashlib
import json
import math
import struct
from pathlib import Path


def unreal_camera(camera):
    result = dict(camera)
    x, y, z, w = camera['quaternion']
    forward = [-2*(x*z+w*y), -2*(y*z-w*x), -(1-2*(x*x+y*y))]
    ue = [forward[0], forward[2], forward[1]]
    assert abs(sum(v*v for v in ue)-1) < 1e-6
    result.update(unrealPositionCm=[camera['position'][i]*100 for i in (0, 2, 1)],
                  unrealForward=ue,
                  unrealPitchYawDegrees=[math.degrees(math.atan2(ue[2], math.hypot(*ue[:2]))), math.degrees(math.atan2(ue[1], ue[0]))],
                  unrealHorizontalFov=math.degrees(2*math.atan(math.tan(math.radians(camera['verticalFov'])/2)*16/9)))
    return result


def check_geometry(geometry):
    assert geometry['schema'] == 'brickflow.authoring-geometry.v2'
    matrices = 0
    for item in geometry['instances'] + geometry.get('instanceBatches', []):
        assert item['geometry'] in geometry['geometries']
        assert all(m in geometry['materials'] for m in item['materials'])
        if 'matrices' in item:
            data = base64.b64decode(item['matrices'], validate=True)
            assert len(data) == item['count']*64
            assert all(math.isfinite(v[0]) for v in struct.iter_unpack('<f', data))
            assert len(item['parentMatrix']) == 16 and all(map(math.isfinite, item['parentMatrix']))
            if 'colors' in item:
                assert len(base64.b64decode(item['colors'], validate=True)) == item['count']*12
            matrices += item['count']
        if 'lod' in item:
            lod = item['lod']
            assert lod['minDistance'] >= 0
            assert lod['maxDistance'] is None or lod['maxDistance'] > lod['minDistance']
    return {'verifiedAssetStructure': True, 'packedInstanceMatricesChecked': matrices,
            'unvalidatedPlant': True, 'nativePortComplete': False}


def main():
    from playwright.sync_api import sync_playwright
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reference', type=Path, required=True)
    parser.add_argument('--sha256', required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--exporter', type=Path, required=True)
    parser.add_argument('--build', action='store_true', help='Explicitly run the source model if its prepared replay is absent')
    args = parser.parse_args()
    data = args.reference.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    if digest != args.sha256:
        raise ValueError('Reference changed; pin and review its new digest explicitly')
    needle = 'window.CART_DEMO={model,scene,camera,renderer,'
    html = data.decode()
    if html.count(needle) != 1:
        raise ValueError('Unknown reference instrumentation boundary')
    html = html.replace(needle, needle + 'actorMeshes,sourceBeams,rowCenters,bricks,', 1)
    args.output.mkdir(parents=True, exist_ok=True)
    authoring = args.output / 'authoring.html'
    authoring.write_text(html)
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=[
            '--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'])
        page = browser.new_page(viewport={'width': 1280, 'height': 720})
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.add_init_script('window.requestAnimationFrame=()=>0')
        page.goto(authoring.resolve().as_uri() + ('?build' if args.build else ''), wait_until='load', timeout=120000)
        page.wait_for_function('window.CART_DEMO || window.CART_ERROR', timeout=900000, polling=500)
        failure = page.evaluate('window.CART_ERROR || null')
        if failure or errors:
            (args.output / 'runtime-error.json').write_text(json.dumps({'sourceError': failure, 'pageErrors': errors}, indent=2))
            raise RuntimeError(failure or errors)
        summary = page.evaluate('''() => {
            const m=CART_DEMO.model,kinds={},tracks={},actors=[];
            for(const r of m.records.values()) {
                kinds[r.kind]=(kinds[r.kind]||0)+1;
                for(const s of r.tracks) {
                    const a=tracks[s.kind]||(tracks[s.kind]={count:0,first:s.t0,last:s.t1});
                    a.count++;a.first=Math.min(a.first,s.t0);a.last=Math.max(a.last,s.t1);
                }
                if(r.kind!=='brick') actors.push({id:r.id,kind:r.kind,initial:r.initial,
                    visible:r.visible,hiddenAt:r.hiddenAt,trackKinds:[...new Set(r.tracks.map(s=>s.kind))]});
            }
            const first=(key)=>m.history.find(h=>h[key]>0)?.t??null;
            return {total:m.total,totalInput:m.totalInput,inspected:m.inspected,rejected:m.rejected,
                produced:m.produced,delivered:m.delivered,stored:m.stored,loaded:m.loaded,shipped:m.shipped,
                completeInput:m.completeInput,actorKinds:kinds,actors,trackKinds:tracks,
                storage:m.storage.map(s=>({id:s.id,category:s.category,x:s.x,z:s.z,state:s.state})),
                fleet:m.fleet.map(v=>({id:v.id,home:v.home,actor:v.actor,fork:v.fork})),
                docks:m.docks.map(d=>({category:d.category,z:d.z})),
                orders:m.orders.map(o=>({id:o.id,category:o.category,capacity:o.capacity,loaded:o.loaded,status:o.status})),
                fleetReservations:m.fleetPlans.length,moduleControl:m.moduleControl,
                milestones:{firstProduced:first('produced'),firstDelivered:first('delivered'),
                    firstStored:first('stored'),firstLoaded:first('loaded'),firstShipped:first('shipped')}};
        }''')
        summary.update(reference='greenfield_37', referenceSha256=digest, validationStatus='unvalidated',
                       evidenceKind='source-model observations, not independent validation')
        (args.output / 'source-inventory.json').write_text(json.dumps(summary, indent=2))
        cameras = []
        for view in ['input', 'rows', 'inspection', 'formation', 'output', 'warehouse', 'shipping', 'overview']:
            time = summary['milestones']['firstLoaded'] if view == 'shipping' else summary['milestones']['firstStored']
            time = min(summary['total'], (time or 0) + 10)
            page.evaluate('''({view,time})=>{CART_DEMO.seek(time);CART_DEMO.view(view);
                CART_DEMO.renderer.setPixelRatio(1);CART_DEMO.renderer.setSize(1280,720);
                CART_DEMO.camera.aspect=1280/720;CART_DEMO.camera.updateProjectionMatrix();}''', {'view': view, 'time': time})
            cameras.append(page.evaluate('''({view,time})=>({view,time,position:CART_DEMO.camera.position.toArray(),
                quaternion:CART_DEMO.camera.quaternion.toArray(),verticalFov:CART_DEMO.camera.fov})''', {'view': view, 'time': time}))
            if view in ['overview', 'warehouse', 'shipping']:
                png = page.evaluate("""()=>{CART_DEMO.renderer.render(CART_DEMO.scene,CART_DEMO.camera);
                    return CART_DEMO.renderer.domElement.toDataURL('image/png')}""")
                (args.output / f'webgl-{view}.png').write_bytes(base64.b64decode(png.split(',', 1)[1]))
        (args.output / 'camera-bookmarks.json').write_text(json.dumps({'reference': 'greenfield_37',
            'validationStatus': 'unvalidated', 'coordinateSystem': 'Three.js metres, Y-up', 'views': cameras}, indent=2))
        (args.output / 'camera-bookmarks-unreal.json').write_text(json.dumps({'reference': 'greenfield_37',
            'validationStatus': 'unvalidated', 'views': [unreal_camera(c) for c in cameras]}, indent=2))
        page.evaluate('CART_DEMO.seek(0); CART_DEMO.scene.updateMatrixWorld(true)')
        page.add_script_tag(path=str(args.exporter.resolve()))
        geometry = page.evaluate('exportNativeFactory({reviewLod:true,compactInstances:true})')
        geometry.update(reference='greenfield_37', referenceSha256=digest, validationStatus='unvalidated',
                        nativeSimulationPorted=False, purpose='Isolated authoring candidate; do not replace validated factory.json')
        items = geometry['instances'] + geometry.get('instanceBatches', [])
        geometry['lodGroupCount'] = len({i['lod']['group'] for i in items if 'lod' in i})
        geometry['meshInstanceCount'] = len(geometry['instances']) + sum(b['count'] for b in geometry.get('instanceBatches', []))
        checks = check_geometry(geometry)
        checks.update(sourceShaMatchesPinnedInput=True, cameraBookmarksChecked=len(cameras))
        (args.output / 'preparation-checks.json').write_text(json.dumps(checks, indent=2))
        for name, material in geometry['materials'].items():
            if 'image' in material:
                filename = name + '.png'
                (args.output / filename).write_bytes(base64.b64decode(material.pop('image').split(',', 1)[1]))
                material['texture'] = filename
        (args.output / 'factory-candidate.json').write_text(json.dumps(geometry, separators=(',', ':')))
        browser.close()
    print(json.dumps({'referenceSha256': digest, 'validationStatus': 'unvalidated',
                      'instances': len(geometry['instances']), 'actorKinds': summary['actorKinds'],
                      'totalInput': summary['totalInput'], 'completeInputObserved': summary['completeInput'],
                      'output': str(args.output)}, indent=2))


if __name__ == '__main__':
    main()
