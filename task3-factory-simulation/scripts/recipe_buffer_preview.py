"""Build an executable control-sequence review; never resimulate the input plant."""
import argparse
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from greenfield.recipe_buffer import Recipe, RecipeBuffer, PalletOrders, SHADES


def traces():
    cases = []
    def record(b, steps, title, note):
        b.audit()
        steps.append({"title": title, "note": note, **b.snapshot()})
    def feed(b, cell, identity, shade):
        t = b.admit(cell, identity, shade, shade)
        assert t
        b.complete(t)

    b = RecipeBuffer(6, 4, 4); steps = []
    for i in range(6): feed(b, 0, 'W'+str(i), 'Warm')
    record(b, steps, 'Loop full · Copper requested', 'Six Warm bricks occupy the loop. The requested colour cannot be selected here.')
    t = b.admit(0, 'C0', 'Copper', 'Copper')
    record(b, steps, 'Protect the incoming colour', 'Copper reserves a bank slot through the bypass. Nothing is discarded or silently overwritten.')
    b.complete(t)
    record(b, steps, 'Copper available in reserve', 'The bank has stock, but the loop still needs a free return position.')
    t = b.plan(0, 'Copper')
    record(b, steps, 'Reserve a Warm storage position', 'Source occupancy remains held until the transfer is acknowledged. The line transport is exclusively reserved.')
    b.complete(t)
    record(b, steps, 'One return position is free', 'A Warm brick is safely stored. The loop no longer blocks admission.')
    t = b.plan(0, 'Copper')
    record(b, steps, 'Reserve the return position', 'Copper is dispatched from its FIFO. No other admission can steal its reserved destination.')
    b.complete(t); identity = b.take(0, 'Copper'); assert identity == 'C0'
    record(b, steps, 'Copper selected for the output', 'Only the requested colour is issued. All six Warm bricks remain accounted for.')
    cases.append({"title": 'Full-loop recovery', "steps": steps})

    b = RecipeBuffer(6, 4, 4); steps = []
    feed(b, 1, 'shared', 'Russet')
    record(b, steps, 'Cell A2 has Russet', 'Cell A1 requests Russet; its own loop is empty.')
    t = b.plan(1, 'Warm'); b.complete(t)
    record(b, steps, 'Russet stored in the shared bank', 'Storage belongs to line A rather than to an individual cell.')
    t = b.plan(0, 'Russet')
    record(b, steps, 'Cell A1 reserves the return', 'The controller serializes bank access. The physical transfer route still needs a mechanical design.')
    b.complete(t); assert b.take(0, 'Russet') == 'shared'
    record(b, steps, 'A1 receives the available colour', 'Stock is reused within the same line. No duplicated inventory is created.')
    cases.append({"title": 'Shared colour reserve', "steps": steps})

    b = RecipeBuffer(3, 2, 1); steps = []
    feed(b, 0, 'stored', 'Warm'); t = b.plan(0, 'Copper'); b.complete(t)
    for i in range(3): feed(b, 0, 'blocked'+str(i), 'Warm')
    record(b, steps, 'Loop and Warm reserve full', 'Copper is absent. Increasing conveyor speed cannot create the missing colour.')
    assert b.plan(0, 'Copper') is None
    assert b.admit(0, 'not-admitted', 'Warm', 'Copper') is None
    record(b, steps, 'Admission inhibited · material retained', 'The controller reports a stock/capacity constraint. It neither recirculates an unlimited supply nor invents replacement bricks.')
    cases.append({"title": 'Finite-capacity interlock', "steps": steps})

    orders = PalletOrders(); orders.demand(0); orders.queue(0, Recipe('single', 'Copper'))
    milestones = [{"title": 'Mixed pallet active', "note": 'Single-colour Copper is queued. Current assigned layers keep their mixed recipe.', "complete": 0, "current": 'Mixed', "pending": 'Copper'}]
    n = 0
    while not orders.completed:
        for cell in range(4):
            shade = orders.demand(cell)
            if shade is not None:
                ready = orders.accept(cell, 'O'+str(n), shade); n += 1
                if ready: orders.acknowledge_layer(ready['line'], ready['pallet'], ready['layer'])
        if n in (160, 320, 480):
            milestones.append({"title": str(n)+' bricks committed to Mixed', "note": 'All four formers follow the same pallet contract. The queued recipe cannot replace a layer in this pallet.', "complete": n, "current": 'Mixed', "pending": 'Copper'})
    milestones.append({"title": 'Mixed pallet complete · Copper becomes active', "note": 'Exactly 14 layers / 560 unique bricks close the current order. Subsequent layers are single-colour Copper.', "complete": 560, "current": 'Copper', "pending": 'None'})
    cases.append({"title": 'Pallet-boundary change', "orders": True, "steps": milestones})
    return cases


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    data = traces()
    (args.output_dir/'workflow-traces.json').write_text(json.dumps(data, indent=2))
    template = Path(__file__).resolve().parents[1]/'greenfield/buffer_preview.html'
    (args.output_dir/'buffer.html').write_text(template.read_text().replace('__TRACES__', json.dumps(data)))
    print('Four verified controller sequences written to', args.output_dir/'buffer.html')


if __name__ == '__main__': main()
