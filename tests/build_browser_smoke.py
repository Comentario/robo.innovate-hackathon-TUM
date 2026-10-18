"""Generate a local browser smoke-test page; not part of the presentation demo."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from demo.browser import build_data, render_page

if __name__ == '__main__':
    page = render_page(build_data(ROOT), ROOT / 'demo/web')
    script = (ROOT / 'tests/browser_smoke.js').read_text(encoding='utf-8')
    page = page.replace('</body>', '<script>' + script + '</script></body>')
    output = ROOT / 'artifacts/brick_demo_smoke.html'
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(page, encoding='utf-8')
    print(f'Open {output}; the result appears at the bottom after one second.')
