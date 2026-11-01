from copy import deepcopy
import json
from pathlib import Path
import unittest
from execution import compile_job, ExecutionSession, SimulatedAdapter, ActionResult
from planning.faces import make_face_plan

ROOT=Path(__file__).resolve().parents[1]


class ExecutionTests(unittest.TestCase):
    def setUp(self):
        self.inventory=json.loads((ROOT/'examples/faces/inventory.json').read_text())
        self.config=json.loads((ROOT/'examples/faces/config.json').read_text())
        self.cell=json.loads((ROOT/'config/cell.json').read_text())
        self.plan=make_face_plan(self.inventory,**self.config)

    def run_session(self,adapter):
        session=ExecutionSession(compile_job(self.plan,self.inventory,self.cell),adapter)
        while session.status not in ('stopped','completed'):session.advance()
        return session

    def test_complete_job_confirms_only_after_place_and_keeps_inputs(self):
        original=deepcopy(self.plan)
        adapter=SimulatedAdapter()
        session=self.run_session(adapter)
        self.assertEqual(len(adapter.calls),96)
        self.assertEqual(len(session.confirmed),12)
        self.assertEqual(session.status,'completed')
        self.assertIsNone(session.held_brick)
        self.assertEqual(session.available,set())
        self.assertEqual(original,self.plan)
        self.assertEqual(len({a['action_id'] for a in adapter.calls}),96)
        self.assertEqual(adapter.calls[3]['object_pose']['orientation_xyzw'],[0.,0.,1.,0.])

    def test_failure_states_do_not_invent_returned_or_confirmed_bricks(self):
        for phase,held,placed in [('pick',False,False),('orient',True,False),('place',True,False),('confirm',False,True)]:
            with self.subTest(phase=phase):
                adapter=SimulatedAdapter(5,phase)
                session=self.run_session(adapter)
                bid=self.plan['placements'][4]['brick_id']
                self.assertEqual(len(session.confirmed),4)
                self.assertEqual(session.held_brick,bid if held else None)
                self.assertEqual(session.placed_unconfirmed,bid if placed else None)
                self.assertEqual(bid in session.available,phase=='pick')
                count=len(adapter.calls)
                self.assertIsNone(session.advance())
                self.assertEqual(len(adapter.calls),count)

    def test_unknown_pick_is_not_reported_as_available(self):
        session=self.run_session(SimulatedAdapter(5,'pick',unknown=True))
        bid=self.plan['placements'][4]['brick_id']
        self.assertEqual(session.uncertain_brick,bid)
        self.assertNotIn(bid,session.available)
        self.assertEqual(len(session.confirmed),4)

    def test_adapter_exception_stops_as_unknown(self):
        class Broken(SimulatedAdapter):
            def perform(self,command):raise TimeoutError('SDK acknowledgement timed out')
        session=self.run_session(Broken())
        self.assertEqual(session.status,'stopped')
        self.assertEqual(session.events[0]['outcome'],'unknown')
        self.assertEqual(session.confirmed,[])

    def test_preflight_rejects_bad_geometry_or_unmapped_orientation(self):
        for mutation in ('outside','overlap','orientation','capacity','pitch'):
            cell=deepcopy(self.cell)
            if mutation=='outside':cell['pallet']['origin_m'][0]=10
            elif mutation=='overlap':cell['pallet']['origin_m']=cell['source']['origin_m'][:]
            elif mutation=='orientation':cell['orientation_quaternions'].pop('back_out')
            elif mutation=='capacity':cell['pallet']['capacity']['columns']=1
            else:cell['pallet']['pitch_m'][2]=.2
            with self.subTest(mutation=mutation),self.assertRaises(ValueError):
                compile_job(self.plan,self.inventory,cell)

    def test_missing_brick_before_pick_stops_without_calling_adapter_for_pick(self):
        adapter=SimulatedAdapter()
        session=ExecutionSession(compile_job(self.plan,self.inventory,self.cell),adapter)
        session.available.remove(self.plan['placements'][0]['brick_id'])
        session.advance()
        event=session.advance()
        self.assertEqual(event['reason'],'brick_no_longer_available')
        self.assertEqual(len(adapter.calls),1)
        self.assertEqual(session.confirmed,[])
