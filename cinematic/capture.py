"""Export the current full-cart Three.js scene; requires Playwright + Chromium."""
import argparse
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
    parser.add_argument('--view', choices=['overview', 'input', 'rows', 'inspection',
                                         'formation', 'output'], default='overview')
    args = parser.parse_args()
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
            const play = document.getElementById('play');
            if (play.textContent === 'Pause') play.click();
            CART_DEMO.seek(time); CART_DEMO.view(view);
            CART_DEMO.renderer.render(CART_DEMO.scene, CART_DEMO.camera);
        }''', {'time': args.time, 'view': args.view})
        page.add_script_tag(path=str(ROOT / 'cinematic/export_scene.js'))
        data = page.evaluate('exportFactoryScene()')
        data['evidence']['demoSha256'] = hashlib.sha256(html.read_bytes()).hexdigest()
        data['evidence']['view'] = args.view
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_bytes(gzip.compress(json.dumps(data).encode()))
        page.screenshot(path=str(args.output.with_suffix('.reference.png')))
        browser.close()
    print(json.dumps({'output': str(args.output), 'objects': len(data['objects']),
                      'evidence': data['evidence']}, indent=2))


if __name__ == '__main__':
    main()
