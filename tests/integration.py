import os,json,time,subprocess,urllib.request,urllib.error
from pathlib import Path
base=os.getenv('BASE_URL','http://127.0.0.1:18001');results=[]
def get(path):
 try:
  with urllib.request.urlopen(base+path,timeout=10) as r:return r.status,json.loads(r.read())
 except urllib.error.HTTPError as e:return e.code,e.read().decode()
def check(name,ok,detail=''):results.append({'test':name,'pass':bool(ok),'detail':detail});print(name,ok,detail)
def pub(payload,station='qa-weather'):
 subprocess.run(['docker','exec',os.getenv('MQTT_CONTAINER','weather-iot-mqtt-1'),'mosquitto_pub','-t',f'weather/{station}/data','-m',payload,'-q','1'],check=True,capture_output=True)
code,stations=get('/api/stations');check('stations API',code==200,stations)
raw=urllib.request.urlopen(base+'/').read();check('dashboard HTTP',b'<html' in raw.lower())
check('chart asset HTTP',urllib.request.urlopen(base+'/static/vendor/chart.umd.min.js').status==200)
pub(json.dumps({'station_id':'qa-weather','temperature':29.5,'humidity':65,'pm25':17.2}));time.sleep(1)
code,d=get('/api/stations/qa-weather/latest');check('MQTT to MongoDB to latest API',code==200 and d.get('temperature')==29.5 and d.get('status')=='ONLINE',d)
code,d=get('/api/stations/qa-weather/history');check('history API',code==200 and len(d)==1)
for payload in ['{bad-json','[]',json.dumps({'station_id':'qa-weather'}),json.dumps({'station_id':'qa-weather','temperature':True,'humidity':65,'pm25':17})]:pub(payload)
time.sleep(1);code,d=get('/api/stations/qa-weather/history');check('invalid payloads rejected / collector survives',len(d)==1)
pub(json.dumps({'station_id':'qa-weather','temperature':25,'humidity':70,'pm25':10,'timestamp':'2026-09-30T23:59:59+07:00'}));pub(json.dumps({'station_id':'qa-weather','temperature':26,'humidity':71,'pm25':11,'timestamp':'2026-10-01T00:00:00+07:00'}));time.sleep(1)
code,d=get('/api/stations/qa-weather/history?month=2026-09');check('Thai month boundary',code==200 and len(d)==1 and d[0]['temperature']==25,d)
check('invalid month rejected',get('/api/stations/qa-weather/history?month=2026-13')[0]==422)
check('missing station 404',get('/api/stations/does-not-exist/latest')[0]==404)
pub(json.dumps({'station_id':'qa-range','temperature':999,'humidity':150,'pm25':-5}),'qa-range');time.sleep(1);code,d=get('/api/stations/qa-range/latest');check('out-of-range sensor values rejected',code==404,{'status':code,'response':d})
Path(__file__).with_name('integration-results.json').write_text(json.dumps(results,ensure_ascii=False,indent=2))
