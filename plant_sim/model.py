"""Finite-buffer SimPy production model with identity/material accounting.

All sensors are virtual acknowledgements of this model, not physical validation.
No direct use of latent brick quality by the operational routing policy.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from copy import deepcopy
from dataclasses import asdict, dataclass
import math
import random
import simpy


class PlantStop(Exception):
    pass


@dataclass
class Brick:
    id: str
    product_id: str
    shade: str
    good: bool  # simulation ground truth; only the inspection generator reads it
    origin: str
    location: str


def validate(config):
    c = deepcopy(config)
    g = c['geometry']
    for k in ('columns', 'rows', 'input_layers', 'output_layers', 'stacks_per_cart'):
        if type(g[k]) is not int or g[k] <= 0:
            raise ValueError(f'geometry.{k} must be a positive integer')
    if g['input_layers'] % 2 or g['output_layers'] % 2:
        raise ValueError('Input and output heights must contain whole two-layer units')
    for k in ('input_stacks', 'inflight_pairs', 'buffer_pairs', 'correction_robots'):
        if type(c[k]) is not int or c[k] < 1:
            raise ValueError(f'{k} must be a positive integer')
    for k in ('replacement_per_shade', 'mixing_budget_per_layer'):
        if type(c[k]) is not int or c[k] < 0:
            raise ValueError(f'{k} must be a nonnegative integer')
    for k in ('defect_rate', 'false_accept_rate', 'false_reject_rate'):
        if not math.isfinite(c[k]) or not 0 <= c[k] <= 1:
            raise ValueError(f'{k} must be in [0, 1]')
    for k in ('arrival_bricks_per_hour', 'sensor_timeout_seconds', 'max_simulation_seconds'):
        if not math.isfinite(c[k]) or c[k] <= 0:
            raise ValueError(f'{k} must be positive and finite')
    expected = {'dock', 'dehack', 'conveyor', 'split', 'inspect', 'reject_pick_place',
                'replacement_pick_place', 'pair', 'restack', 'pallet_exchange'}
    if set(c['seconds']) != expected:
        raise ValueError('seconds must specify exactly the documented operations')
    if any(not math.isfinite(v) or v <= 0 for v in c['seconds'].values()):
        raise ValueError('Operation durations must be positive and finite')
    if len(c['shades']) < 2 or len(set(c['shades'])) != len(c['shades']):
        raise ValueError('At least two unique accepted shades are required')
    if len(c['recipe']) != len(c['shades']) or any(not math.isfinite(x) or x <= 0 for x in c['recipe']):
        raise ValueError('Recipe must contain a positive fraction for each shade')
    if not math.isclose(sum(c['recipe']), 1, abs_tol=1e-8):
        raise ValueError('Recipe fractions must sum to one')
    if c['input_pattern'] not in ('random', 'stratified'):
        raise ValueError('Unknown input pattern')
    if c['fault'] is not None and (set(c['fault']) != {'station', 'pair'} or
            not isinstance(c['fault']['pair'], int) or c['fault']['pair'] < 1 or
            c['fault']['station'] not in ('dock', 'dehacker', 'infeed', 'separator', 'lane_1', 'lane_2', 'robot', 'pairer', 'outfeed', 'stacker')):
        raise ValueError('Fault must identify a known station and positive pair number')
    return c


def mix_metrics(bricks, rows, columns, shades, recipe):
    counts = Counter(b.shade for b in bricks)
    total = len(bricks)
    l1 = sum(abs(counts[s] / total - w) for s, w in zip(shades, recipe)) if total else 0
    mono_rows = sum(len({b.shade for b in bricks[r*columns:(r+1)*columns]}) == 1
                    for r in range(rows)) if total == rows * columns else 0
    mono_cols = sum(len({bricks[r*columns+c].shade for r in range(rows)}) == 1
                    for c in range(columns)) if total == rows * columns else 0
    return {'counts': dict(counts), 'recipe_l1': round(l1, 6),
            'monochrome_rows': mono_rows, 'monochrome_columns': mono_cols}


class Plant:
    def __init__(self, config):
        self.c = validate(config)
        self.env = simpy.Environment()
        # Independent RNGs: changing capacity or speed must not change input/decisions.
        self.rng = random.Random(self.c['seed'])
        self.vision_rng = random.Random(self.c['seed'] + 100000)
        g = self.c['geometry']
        self.n = g['rows'] * g['columns']
        self.pair_size = 2 * self.n
        self.pairs_per_stack = g['input_layers'] // 2
        self.pallet_size = self.n * g['output_layers']
        self.bricks = {}
        self.reserve = defaultdict(list)
        self.pairs = []
        self.events = []
        self.signals = defaultdict(dict)
        self.intervals = []
        self.queue_max = defaultdict(int)
        self.queue_wait = defaultdict(float)
        self.pallets = []
        self.output = []
        self.layer_results = []
        self.observed = {}
        self.stats = Counter()
        self.completed_times = []
        self.status = 'running'
        self.reason = None
        self.done = self.env.event()
        self.tokens = simpy.Container(self.env, capacity=self.c['inflight_pairs'], init=self.c['inflight_pairs'])
        self.raw = simpy.Store(self.env, capacity=self.c['buffer_pairs'])
        self.lanes = [simpy.Store(self.env, capacity=self.c['buffer_pairs']) for _ in range(2)]
        self.corrected = simpy.Store(self.env, capacity=self.c['buffer_pairs'])
        self.paired = simpy.Store(self.env, capacity=self.c['buffer_pairs'])
        self.outfeed = simpy.Store(self.env, capacity=self.c['buffer_pairs'])
        self.robot = simpy.Resource(self.env, capacity=self.c['correction_robots'])
        self.robot_slots = list(range(1, self.c['correction_robots']+1))
        self._create_material()

    def _create_material(self):
        for k in range(self.c['input_stacks'] * self.pairs_per_stack):
            layers = []
            for layer_index in range(2):
                layer = []
                for slot in range(self.n):
                    shade = (self.c['shades'][(2*k+layer_index) % len(self.c['shades'])]
                             if self.c['input_pattern'] == 'stratified' else
                             self.rng.choices(self.c['shades'], weights=self.c['recipe'])[0])
                    good = self.rng.random() >= self.c['defect_rate']
                    b = Brick(f'I-{k+1:04}-{layer_index}-{slot:02}', self.c['product_id'], shade,
                              good, 'input', 'input')
                    self.bricks[b.id] = b
                    layer.append(b)
                layers.append(layer)
            self.pairs.append({'id': k+1, 'layers': layers, 'finished': 0})
        for shade in self.c['shades']:
            for i in range(self.c['replacement_per_shade']):
                b = Brick(f'R-{shade}-{i:04}', self.c['product_id'], shade, True, 'reserve', 'reserve')
                self.bricks[b.id] = b
                self.reserve[shade].append(b)
        self.initial_input = self.pair_size * len(self.pairs)
        self.initial_reserve = len(self.bricks) - self.initial_input

    def emit(self, kind, station='', pair=None, **details):
        self.events.append({'t': round(self.env.now, 6), 'kind': kind, 'station': station,
                            'pair': pair, **details})

    def signal(self, station, name, value, pair):
        self.signals[station][name] = value
        self.emit('signal', station, pair, name=name, value=value)

    def move(self, bricks, location):
        for b in bricks:
            b.location = location

    def motion(self, station, phase, duration, pair):
        # Positive transfer acknowledgment + drive command + end-stop confirmation.
        # These are deliberately modeled virtual signals, not hardware feedback.
        self.signal(station, 'workpiece_present', True, pair)
        if not self.signals[station]['workpiece_present']:
            raise PlantStop(f'{station}: workpiece presence interlock')
        self.signal(station, 'part_clamped', True, pair)
        self.signal(station, 'end_limit', False, pair)
        self.signal(station, 'drive_enabled', True, pair)
        start = self.env.now
        self.emit('operation_start', station, pair, phase=phase, duration=duration)
        fail = self.c['fault'] == {'station': 'robot' if station.startswith('robot_') else station, 'pair': pair}
        yield self.env.timeout(duration)
        if fail:
            self.emit('waiting_sensor', station, pair, sensor='end_limit')
            yield self.env.timeout(self.c['sensor_timeout_seconds'])
            self.signal(station, 'drive_enabled', False, pair)
            self.intervals.append((station, start, self.env.now, 'fault'))
            raise PlantStop(f'{station}: end_limit timeout; explicit reconciliation required')
        self.signal(station, 'end_limit', True, pair)
        self.signal(station, 'drive_enabled', False, pair)
        self.signal(station, 'part_clamped', False, pair)
        self.intervals.append((station, start, self.env.now, phase))
        self.emit('operation_end', station, pair, phase=phase)

    def put(self, store, item, station, pair):
        start = self.env.now
        if len(store.items) == store.capacity:
            self.emit('blocked', station, pair, cause='downstream buffer full')
        yield store.put(item)
        self.queue_wait[station] += self.env.now - start
        self.queue_max[station] = max(self.queue_max[station], len(store.items))
        self.signal(station, 'transfer_confirmed', True, pair)
        self.signal(station, 'workpiece_present', False, pair)
        self.emit('buffer', station, pair, occupancy=len(store.items), capacity=store.capacity)

    def source(self):
        period = self.pair_size / self.c['arrival_bricks_per_hour'] * 3600
        for index, pair in enumerate(self.pairs):
            due = (index + 1) * period
            if self.env.now < due:
                yield self.env.timeout(due - self.env.now)
            yield self.tokens.get(1)
            pair['admitted_at'] = self.env.now
            self.emit('pair_admitted', 'dock', pair['id'])
            pid = pair['id']
            if index % self.pairs_per_stack == 0:
                yield from self.motion('dock', 'Load input stack', self.c['seconds']['dock'], pid)
                self.signal('dock', 'workpiece_present', False, pid)
            self.move(sum(pair['layers'], []), 'dehacker')
            yield from self.motion('dehacker', 'Remove two-layer unit', self.c['seconds']['dehack'], pid)
            self.signal('dehacker', 'workpiece_present', False, pid)
            self.move(sum(pair['layers'], []), 'infeed')
            yield from self.motion('infeed', 'Conveyor transfer', self.c['seconds']['conveyor'], pid)
            self.move(sum(pair['layers'], []), 'raw_buffer')
            yield from self.put(self.raw, pair, 'infeed', pid)
        self.emit('source_finished', 'dock')

    def split(self):
        while True:
            pair = yield self.raw.get()
            pid = pair['id']
            self.move(sum(pair['layers'], []), 'separator')
            yield from self.motion('separator', 'Separate upper and lower layers', self.c['seconds']['split'], pid)
            for lane, layer in enumerate(pair['layers']):
                self.move(layer, f'lane_{lane+1}_buffer')
                yield from self.put(self.lanes[lane], (pair, lane), 'separator', pid)
            self.emit('layers_exposed', 'separator', pid)

    def choose_shade(self, layer, slot):
        # Uses observed accepted shades, never the hidden ground-truth quality flag.
        counts = Counter(b.shade for i, b in enumerate(layer) if i != slot)
        cols = self.c['geometry']['columns']
        neighbor = [i for i in (slot-cols, slot+cols) if 0 <= i < self.n]
        if slot % cols:
            neighbor.append(slot-1)
        if slot % cols < cols-1:
            neighbor.append(slot+1)
        choices = [s for s in self.c['shades'] if self.reserve[s]]
        if not choices:
            raise PlantStop('Replacement supply empty; refill and reconcile before restart')
        def cost(s):
            distribution = sum(abs((counts[t]+(t == s))/self.n-w)
                               for t, w in zip(self.c['shades'], self.c['recipe']))
            adjacency = sum(layer[i].shade == s for i in neighbor) / max(1, len(neighbor))
            return distribution + 0.1 * adjacency, self.c['shades'].index(s)
        return min(choices, key=cost)

    def replace(self, pair, lane, slot, reason):
        layer = pair['layers'][lane]
        pid = pair['id']
        old = layer[slot]
        shade = self.choose_shade(layer, slot)
        # Shared robot ownership covers the complete remove/insert transaction.
        start = self.env.now
        with self.robot.request() as request:
            yield request
            self.stats['robot_wait_seconds'] += self.env.now-start
            robot_station = f'robot_{self.robot_slots.pop(0)}'
            # Re-select after waiting: another lane may have consumed this shade.
            shade = self.choose_shade(layer, slot)
            replacement = self.reserve[shade].pop()
            self.emit('supply_reserved', robot_station, pid, brick=replacement.id, shade=shade)
            self.move([replacement], 'robot_reserved')
            yield from self.motion(robot_station, 'Remove brick' if reason == 'quality' else 'Mix exchange: remove',
                                   self.c['seconds']['reject_pick_place'], pid)
            old.location = 'reject' if reason == 'quality' else 'reuse'
            self.emit('brick_removed', 'robot', pid, brick=old.id, lane=lane, slot=slot, reason=reason)
            yield from self.motion(robot_station, 'Insert approved replacement',
                                   self.c['seconds']['replacement_pick_place'], pid)
            layer[slot] = replacement
            replacement.location = f'lane_{lane+1}'
            self.observed[replacement.id] = 'accepted_supply'
            self.stats['replacements_used'] += 1
            self.stats['quality_replacements' if reason == 'quality' else 'mix_exchanges'] += 1
            self.emit('brick_replaced', 'robot', pid, brick=replacement.id, shade=shade,
                      lane=lane, slot=slot, reason=reason)
            self.signal(robot_station, 'workpiece_present', False, pid)
            self.robot_slots.append(int(robot_station.split('_')[1]))

    def inspect_lane(self, lane):
        station = f'lane_{lane+1}'
        while True:
            pair, _ = yield self.lanes[lane].get()
            layer = pair['layers'][lane]
            pid = pair['id']
            self.move(layer, station)
            yield from self.motion(station, 'Inspect exposed layer', self.c['seconds']['inspect'], pid)
            decisions = []
            # Latent truth is accessed only here to generate synthetic detector outputs.
            for b in layer:
                u = random.Random(f'{self.c["seed"]}:vision:{b.id}').random()
                rejected = (u >= self.c['false_accept_rate']) if not b.good else (u < self.c['false_reject_rate'])
                self.observed[b.id] = 'reject' if rejected else 'accept'
                decisions.append(rejected)
            self.emit('inspection', station, pid, lane=lane, ids=[b.id for b in layer],
                      shades=[b.shade for b in layer], rejected=decisions,
                      source='synthetic detector; exposed layer only')
            for slot, rejected in enumerate(decisions):
                if rejected:
                    yield from self.replace(pair, lane, slot, 'quality')
            # Optional good-brick exchanges address shade stratification at a real time/material cost.
            for _ in range(self.c['mixing_budget_per_layer']):
                counts = Counter(b.shade for b in layer)
                candidates = [i for i, b in enumerate(layer)
                              if counts[b.shade] > self.n*self.c['recipe'][self.c['shades'].index(b.shade)] + 0.5]
                if not candidates:
                    break
                slot = candidates[0]
                shade = self.choose_shade(layer, slot)
                if counts[shade] >= counts[layer[slot].shade]:
                    break
                yield from self.replace(pair, lane, slot, 'mix')
            metrics = mix_metrics(layer, self.c['geometry']['rows'], self.c['geometry']['columns'],
                                  self.c['shades'], self.c['recipe'])
            self.layer_results.append({'pair': pid, 'lane': lane, **metrics})
            self.emit('layer_corrected', station, pid, lane=lane, shades=[b.shade for b in layer], metrics=metrics)
            self.move(layer, 'join_buffer')
            pair['finished'] += 1
            self.signal(station, 'workpiece_present', False, pid)
            if pair['finished'] == 2:
                yield from self.put(self.corrected, pair, station, pid)

    def pair_layers(self):
        while True:
            pair = yield self.corrected.get()
            assert pair['finished'] == 2, 'Both layers must be corrected before pairing'
            pid = pair['id']
            self.move(sum(pair['layers'], []), 'pairer')
            yield from self.motion('pairer', 'Recombine two corrected layers', self.c['seconds']['pair'], pid)
            self.move(sum(pair['layers'], []), 'paired_buffer')
            yield from self.put(self.paired, pair, 'pairer', pid)

    def conveyor_out(self):
        while True:
            pair = yield self.paired.get()
            pid = pair['id']
            self.move(sum(pair['layers'], []), 'outfeed')
            yield from self.motion('outfeed', 'Output conveyor transfer', self.c['seconds']['conveyor'], pid)
            self.move(sum(pair['layers'], []), 'output_buffer')
            yield from self.put(self.outfeed, pair, 'outfeed', pid)

    def stack(self):
        pallet = []
        while True:
            pair = yield self.outfeed.get()
            pid = pair['id']
            bricks = sum(pair['layers'], [])
            self.move(bricks, 'stacker')
            yield from self.motion('stacker', 'Restack two-layer unit', self.c['seconds']['restack'], pid)
            self.move(bricks, 'output')
            self.output.extend(bricks)
            pallet.extend(bricks)
            self.completed_times.append(self.env.now)
            self.stats['completed_pairs'] += 1
            self.emit('pair_completed', 'stacker', pid, output_bricks=len(self.output),
                      pallet_fill=len(pallet), latency=self.env.now-pair['admitted_at'])
            if len(pallet) == self.pallet_size:
                self.pallets.append([b.id for b in pallet])
                self.emit('pallet_completed', 'stacker', pid, pallet=len(self.pallets), size=len(pallet))
                pallet = []
                yield from self.motion('stacker', 'Exchange output pallet', self.c['seconds']['pallet_exchange'], pid)
            self.signal('stacker', 'workpiece_present', False, pid)
            yield self.tokens.put(1)
            if self.stats['completed_pairs'] == len(self.pairs):
                self.partial_pallet = [b.id for b in pallet]
                self.status = 'completed'
                self.done.succeed()
                return

    def guarded(self, generator):
        try:
            yield from generator
        except PlantStop as exc:
            if not self.done.triggered:
                self.status = 'blocked'
                self.reason = str(exc)
                self.emit('alarm', reason=self.reason)
                self.done.succeed()

    def run(self):
        for generator in (self.source(), self.split(), self.inspect_lane(0), self.inspect_lane(1),
                          self.pair_layers(), self.conveyor_out(), self.stack()):
            self.env.process(self.guarded(generator))
        horizon = self.env.timeout(self.c['max_simulation_seconds'])
        self.env.run(until=self.done | horizon)
        if self.status == 'running':
            self.status, self.reason = 'horizon_reached', 'Configured simulation horizon reached; material remains in process'
            self.emit('alarm', reason=self.reason)
        # Global process stop: modeled drives disabled, no further motion is dispatched.
        for station, values in list(self.signals.items()):
            if values.get('drive_enabled'):
                self.signal(station, 'drive_enabled', False, None)
        return self.report()

    def report(self):
        elapsed = self.env.now
        locations = Counter(b.location for b in self.bricks.values())
        output_ids = {b.id for b in self.output}
        assert len(output_ids) == len(self.output)
        assert all(self.bricks[i].location == 'output' for i in output_ids)
        count = sum(locations.values())
        assert count == self.initial_input + self.initial_reserve
        wip = count - locations['output'] - locations['reject'] - locations['reuse'] - locations['reserve']
        busy = defaultdict(float)
        for station, start, end, _ in self.intervals:
            busy[station] += end-start
        # Include operations interrupted by a global stop or horizon.
        starts = {}
        for e in self.events:
            key = (e['station'], e['pair'])
            if e['kind'] == 'operation_start':
                starts[key] = e['t']
            elif e['kind'] == 'operation_end':
                starts.pop(key, None)
        if self.status != 'completed':
            for (station, _), start in starts.items():
                # Fault intervals are already included above.
                if not any(s == station and abs(a-start)<1e-5 and p == 'fault' for s,a,b,p in self.intervals):
                    busy[station] += elapsed-start
        intervals = [b-a for a,b in zip(self.completed_times, self.completed_times[1:])]
        confirmed_bad = sum(not b.good for b in self.output)
        discarded_good = sum(b.good and b.location == 'reject' for b in self.bricks.values())
        layers = self.layer_results
        return {
            'schema_version': '1.0', 'status': self.status, 'reason': self.reason,
            'config': self.c, 'simulated_seconds': round(elapsed, 6),
            'kpis': {
                'input_bricks': self.initial_input, 'initial_reserve': self.initial_reserve,
                'output_bricks': len(self.output), 'conforming_output_bricks': len(self.output)-confirmed_bad,
                'output_bricks_per_hour': round(len(self.output)/elapsed*3600, 3) if elapsed else 0,
                'conforming_bricks_per_hour': round((len(self.output)-confirmed_bad)/elapsed*3600, 3) if elapsed else 0,
                'mean_pair_interval_seconds': round(sum(intervals)/len(intervals), 6) if intervals else None,
                'required_pair_interval_seconds': self.pair_size/self.c['arrival_bricks_per_hour']*3600,
                'full_output_pallets': len(self.pallets),
                'partial_output_pallet_bricks': len(self.output) % self.pallet_size,
                'bad_output_bricks': confirmed_bad, 'good_bricks_rejected': discarded_good,
                'quality_replacements': self.stats['quality_replacements'], 'mix_exchanges': self.stats['mix_exchanges'],
                'reserve_remaining': locations['reserve'], 'reuse_buffer_bricks': locations['reuse'],
                'rejected_bricks': locations['reject'], 'unprocessed_or_inflight_bricks': wip,
                'material_balance_ok': count == self.initial_input+self.initial_reserve,
                'mean_layer_recipe_l1': round(sum(x['recipe_l1'] for x in layers)/len(layers), 6) if layers else None,
                'monochrome_rows': sum(x['monochrome_rows'] for x in layers),
                'monochrome_columns': sum(x['monochrome_columns'] for x in layers),
                'robot_active_fraction': round(sum(v for k,v in busy.items() if k.startswith('robot_'))/elapsed/self.c['correction_robots'], 6) if elapsed else 0,
                'robot_wait_seconds': round(self.stats['robot_wait_seconds'], 6),
            },
            'material_locations': dict(locations), 'busy_seconds': dict(busy),
            'downstream_blocked_seconds': dict(self.queue_wait), 'buffer_max_occupancy': dict(self.queue_max),
            'pallet_mix': [mix_metrics([self.bricks[i] for i in ids], 0, 0, self.c['shades'], self.c['recipe']) for ids in self.pallets],
            'pallets': self.pallets,
            'partial_pallet': [b.id for b in self.output[len(self.pallets)*self.pallet_size:]],
            'output_layers': self.layer_results,
            'material': [asdict(b) for b in self.bricks.values()],
            'events': self.events,
            'limitations': [
                'Process simulation only: no PLC, hardware control, contact, reach or gripping validation.',
                'Virtual presence/end-limit sensors acknowledge modeled motion; they are not independent measurements.',
                'ALL station times, error probabilities, stock levels and shade recipe are unmeasured assumptions.',
                'Single product per run. No unobserved lower-layer classification. Both layers must be exposed.',
                'Mixing is a scored heuristic with optional budgeted exchanges, not a guaranteed pattern.',
                'No automatic restart after timeout or supply shortage; preserve material ledger for reconciliation.',
                'No measured human baseline, so no verified productivity improvement claim.',
                'No brick mass/temperature, thermal cooling, gripping mechanics, downtime distribution or human safety validation.',
                'Reuse buffer is counted but not automatically replenished into approved supply.',
            ],
        }
