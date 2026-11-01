"""Export the current full-cart Three.js scene; requires Playwright + Chromium."""
import argparse
import base64
import gzip
import hashlib
import json
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--demo', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--time', type=float, default=1200)
    parser.add_argument('--duration', type=float, default=0, help='Video duration in seconds')
    parser.add_argument('--fps', type=int, default=24)
    parser.add_argument('--rate', type=float, default=1, help='Simulation seconds per video second')
    parser.add_argument('--view', choices=['overview', 'input', 'rows', 'inspection',
                                         'formation', 'output'], default='overview')
    args = parser.parse_args()
    if args.duration < 0 or args.fps < 1 or args.rate <= 0:
        parser.error('Duration must be nonnegative; fps and rate must be positive')
    html = args.demo.resolve()
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=[
            '--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'])
        page = browser.new_page(viewport={'width': 1920, 'height': 1080})
        errors = []
        page.on('pageerror', lambda e: errors.append(str(e)))
        page.goto(html.as_uri(), wait_until='load', timeout=120000)
        page.wait_for_function('window.CART_DEMO || window.CART_ERROR', timeout=900000)
        failure = page.evaluate('window.CART_ERROR || null')
        if failure or errors:
            raise RuntimeError(failure or errors)
        page.evaluate('''({time, view}) => {
            window.requestAnimationFrame = () => 0;
            const play = document.getElementById('play');
            if (play.textContent === 'Pause') play.click();
            CART_DEMO.seek(time); CART_DEMO.view(view);
            CART_DEMO.renderer.render(CART_DEMO.scene, CART_DEMO.camera);
        }''', {'time': args.time, 'view': args.view})
        page.add_script_tag(path=str(ROOT / 'cinematic/export_scene.js'))
        data = page.evaluate('(includeHidden) => exportFactoryScene({includeHidden})', args.duration > 0)
        data['evidence']['demoSha256'] = hashlib.sha256(html.read_bytes()).hexdigest()
        data['evidence']['view'] = args.view
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_bytes(gzip.compress(json.dumps(data).encode()))
        if args.duration:
            end = args.time + args.duration*args.rate
            if end > data['evidence']['total']:
                raise ValueError('Requested clip extends beyond the recorded replay')
            motion = page.evaluate('''({start,duration,fps,rate}) => {
                const frames=[];
                for(let i=1;i<Math.round(duration*fps);i++)
                    frames.push({frame:i+1,changes:sampleFactoryMotion(start+i/fps*rate)});
                return {schema:'brickflow.render-motion.v1',fps,rate,start,frames};
            }''', {'start':args.time,'duration':args.duration,'fps':args.fps,'rate':args.rate})
            motion['snapshotSha256'] = hashlib.sha256(args.output.read_bytes()).hexdigest()
            args.output.with_suffix('.motion.json.gz').write_bytes(gzip.compress(json.dumps(motion).encode()))
        # Read the actual WebGL buffer instead of waiting on Chromium's compositor
        # while the large scene is redrawn by software rasterization.
        png = page.evaluate("CART_DEMO.renderer.domElement.toDataURL('image/png')")
        args.output.with_suffix('.reference.png').write_bytes(base64.b64decode(png.split(',', 1)[1]))
        browser.close()
    print(json.dumps({'output': str(args.output), 'objects': len(data['objects']),
                      'evidence': data['evidence']}, indent=2))


if __name__ == '__main__':
    main()
