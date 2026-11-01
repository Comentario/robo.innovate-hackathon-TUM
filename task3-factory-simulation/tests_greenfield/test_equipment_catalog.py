"""Offline reference integrity and separation of ratings from demo assumptions."""
import hashlib,json,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
class EquipmentCatalogTests(unittest.TestCase):
    def test_references_have_valid_local_images_and_primary_links(self):
        rows=json.loads((ROOT/'greenfield/catalog.json').read_text());self.assertEqual(len(rows),len({r['id'] for r in rows}))
        for row in rows:
            with self.subTest(reference=row['id']):
                self.assertTrue(row['url'].startswith('https://'));self.assertTrue(row['scope']);self.assertTrue(row['image_credit'])
                data=(ROOT/'greenfield/assets'/row['image_asset']).read_bytes();self.assertTrue(data.startswith((b'\xff\xd8',b'\x89PNG')))
                if row.get('image_source'):self.assertEqual(hashlib.sha256(data).hexdigest(),row['image_source']['sha256'])
    def test_published_rating_keys_do_not_include_demo_selections(self):
        for row in json.loads((ROOT/'greenfield/catalog.json').read_text()):
            for key in row['nominal']:
                self.assertFalse(key.lower().startswith(('modeled','selected','our ','zone_pitch','stop_distance')), (row['id'],key))
