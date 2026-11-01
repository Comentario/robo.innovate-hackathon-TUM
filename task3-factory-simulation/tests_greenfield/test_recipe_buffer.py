import random
import unittest
from collections import Counter
from greenfield.recipe_buffer import Recipe, RecipeBuffer, PalletOrders, SHADES, pallets_per_hour


class RecipeBufferTests(unittest.TestCase):
    def admit(self, b, cell, identity, shade, wanted=None):
        t = b.admit(cell, identity, shade, wanted)
        self.assertIsNotNone(t)
        b.complete(t)
        return t

    def test_full_loop_evicts_then_restores_requested_colour(self):
        b = RecipeBuffer(6, 4, 4)
        for i in range(6):
            self.admit(b, 0, str(i), 'Warm', 'Warm')
        self.admit(b, 0, 'target', 'Copper', 'Copper')
        t = b.plan(0, 'Copper')
        self.assertEqual(t.destination, ('bank', 0, 'Warm'))
        self.assertFalse(b.room(('loop', 0)))  # Source held until ACK.
        b.complete(t)
        t = b.plan(0, 'Copper')
        self.assertEqual(t.identity, 'target')
        self.assertFalse(b.room(('loop', 0)))  # Return slot already reserved.
        b.complete(t)
        self.assertEqual(b.take(0, 'Copper'), 'target')
        self.assertTrue(b.audit())

    def test_missing_colour_and_full_bank_cause_backpressure_not_loss(self):
        b = RecipeBuffer(3, 2, 1)
        self.admit(b, 0, 'bank', 'Warm', 'Copper')
        t = b.plan(0, 'Copper'); b.complete(t)
        for i in range(3):
            self.admit(b, 0, str(i), 'Warm', 'Warm')
        before = b.snapshot()
        self.assertIsNone(b.plan(0, 'Copper'))
        self.assertIsNone(b.admit(0, 'blocked', 'Warm', 'Copper'))
        self.assertEqual(b.snapshot(), before)
        self.assertNotIn('blocked', b.shades)
        self.assertIsNone(b.take(0, 'Copper'))
        b.audit()

    def test_shared_bank_can_supply_another_cell_on_same_line(self):
        b = RecipeBuffer(3, 2, 4)
        self.admit(b, 1, 'copper', 'Copper', 'Warm')
        t = b.plan(1, 'Warm'); b.complete(t)
        self.assertIsNone(b.plan(4, 'Copper'))  # Other line has no Copper.
        t = b.plan(0, 'Copper'); b.complete(t)
        self.assertEqual(b.take(0, 'Copper'), 'copper')

    def test_shared_transport_is_serial_and_cancellation_keeps_source(self):
        b = RecipeBuffer(3, 2, 4)
        for c in [0, 1]:
            self.admit(b, c, str(c), 'Warm')
        t = b.plan(0, 'Copper')
        self.assertIsNone(b.plan(1, 'Copper'))
        b.cancel(t)
        self.assertIn('0', b.queues['loop', 0])
        self.assertIsNotNone(b.plan(1, 'Copper'))
        b.audit()

    def test_external_cancel_releases_capacity_and_allows_retry(self):
        b = RecipeBuffer(3, 2, 4)
        t = b.admit(0, 'new', 'Warm')
        b.cancel(t)
        self.assertEqual(b.snapshot()['accepted'], 0)
        t = self.admit(b, 0, 'new', 'Warm')
        with self.assertRaises(ValueError):
            b.complete(t)
        with self.assertRaises(ValueError):
            b.admit(0, 'new', 'Warm')
        b.audit()

    def test_reservations_prevent_overbooking_before_ack(self):
        b = RecipeBuffer(3, 2, 4)
        jobs = [b.admit(0, str(i), 'Warm', 'Warm') for i in range(3)]
        self.assertFalse(b.room(('loop', 0)))
        extra = b.admit(0, 'extra', 'Warm', 'Warm')
        self.assertEqual(extra.destination, ('bank', 0, 'Warm'))
        b.complete(extra)
        for t in reversed(jobs): b.complete(t)
        b.audit()

    def test_randomized_ownership_capacity_and_recovery_sequences(self):
        rng = random.Random(8)
        b = RecipeBuffer(8, 6, 12)
        for i in range(4000):
            cell = rng.randrange(8); shade = rng.choice(SHADES)
            action = rng.randrange(4)
            if action == 0:
                b.admit(cell, 'R'+str(i), shade, rng.choice(SHADES))
            elif action == 1:
                b.plan(cell, shade)
            elif action == 2:
                b.take(cell, shade)
            elif b.inflight:
                t = rng.choice(list(b.inflight.values()))
                (b.cancel if rng.random() < .2 else b.complete)(t)
            self.assertTrue(b.audit())


class PalletOrderTests(unittest.TestCase):
    def accept_and_stack(self, o, cell, identity, shade):
        layer = o.accept(cell, identity, shade)
        if layer:
            return o.acknowledge_layer(layer['line'], layer['pallet'], layer['layer'])

    def test_change_waits_until_all_fourteen_layers_complete(self):
        o = PalletOrders()
        o.demand(0)  # Locks current work even before first completed layer.
        o.queue(0, Recipe('single', 'Copper'))
        self.assertEqual(o.recipes[0].mode, 'mixed')
        serial = 0
        while not o.completed:
            for cell in range(4):
                shade = o.demand(cell)
                if shade:
                    self.accept_and_stack(o, cell, 'P'+str(serial), shade); serial += 1
        self.assertEqual(len(o.completed[0]['ids']), 560)
        self.assertEqual(o.completed[0]['mode'], 'mixed')
        self.assertEqual(o.recipes[0], Recipe('single', 'Copper'))
        self.assertTrue(all(o.demand(c) == 'Copper' for c in range(4)))
        self.assertEqual(o.recipes[1].mode, 'mixed')

    def test_monochrome_pallet_is_pure_and_invalid_output_is_rejected(self):
        o = PalletOrders([Recipe('single', 'Russet'), Recipe()])
        with self.assertRaises(ValueError): o.accept(0, 'bad', 'Warm')
        for i in range(560):
            self.accept_and_stack(o, 0, str(i), 'Russet')
        self.assertEqual(o.completed[0]['shade'], 'Russet')
        self.assertEqual(len(o.completed[0]['ids']), 560)
        with self.assertRaises(ValueError): o.accept(0, '0', 'Russet')

    def test_formed_layers_do_not_finish_pallet_before_stacker_ack(self):
        o = PalletOrders([Recipe('single', 'Warm'), Recipe()])
        o.queue(0, Recipe('single', 'Copper'))
        ready = []
        for i in range(560):
            layer = o.accept(0, 'S'+str(i), 'Warm')
            if layer: ready.append(layer)
        self.assertFalse(o.completed)
        self.assertIsNone(o.demand(0))
        self.assertEqual(o.recipes[0].shade, 'Warm')
        for layer in ready[:-1]:
            self.assertIsNone(o.acknowledge_layer(0, 0, layer['layer']))
        with self.assertRaises(ValueError): o.acknowledge_layer(0, 0, ready[0]['layer'])
        completed = o.acknowledge_layer(0, 0, ready[-1]['layer'])
        self.assertEqual(len(completed['ids']), 560)
        self.assertEqual(o.demand(0), 'Copper')
        with self.assertRaises(ValueError): o.acknowledge_layer(0, 0, ready[-1]['layer'])

    def test_mixed_pattern_has_no_triples_in_any_axis(self):
        grids = [Recipe().layer(k) for k in range(14)]
        total = Counter(s for grid in grids for s in grid)
        self.assertLessEqual(max(total.values())-min(total.values()), 1)
        for grid in grids:
            self.assertTrue(all(not(grid[r*10+c] == grid[r*10+c+1] == grid[r*10+c+2]) for r in range(4) for c in range(8)))
            self.assertTrue(all(not(grid[r*10+c] == grid[(r+1)*10+c] == grid[(r+2)*10+c]) for r in range(2) for c in range(10)))
        self.assertTrue(all(not(grids[k][s] == grids[k+1][s] == grids[k+2][s]) for k in range(12) for s in range(40)))

    def test_recipe_validation_and_pallet_rate(self):
        for args in [('single', None), ('mixed', 'Warm'), ('single', 'Pale'), ('other', None)]:
            with self.assertRaises(ValueError): Recipe(*args)
        self.assertAlmostEqual(pallets_per_hour(4, 2073.7157979), 6.9440566613)
        with self.assertRaises(ValueError): pallets_per_hour(0, 0)


if __name__ == '__main__': unittest.main()
