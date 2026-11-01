import unittest,sys,math
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'collector'))
from collector import validate_payload
class ValidationTests(unittest.TestCase):
 def sample(self):return dict(station_id='station01',temperature=28,humidity=65,pm25=12)
 def test_valid(self):self.assertTrue(validate_payload(self.sample())[0])
 def test_reject_invalid(self):
  for field,values in {'temperature':[-41,81,True,math.inf,math.nan], 'humidity':[-1,101], 'pm25':[-1,1001], 'pm10':[math.inf,-1], 'station_id':['','bad/id','<script>'], 'timestamp':['bad','2999-01-01T00:00:00Z']}.items():
   for value in values:
    with self.subTest(field=field,value=value):
     d=self.sample();d[field]=value;self.assertFalse(validate_payload(d)[0])
 def test_reject_non_objects(self):
  for d in [[],None,'text',{}]:self.assertFalse(validate_payload(d)[0])
 def test_boundaries(self):
  for low,high in [(-40,80)]:
   for temp in [low,high]:
    d=self.sample();d['temperature']=temp;self.assertTrue(validate_payload(d)[0])
