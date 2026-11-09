// Self-contained, deterministic sample readings. Never connects to real IoT APIs.
(() => {
  const stations=['DEMO-STATION-A','DEMO-STATION-B'];
  const readings=Object.fromEntries(stations.map((station,index)=>[station,Array.from({length:360},(_,i)=>{
    const month=8+Math.floor(i/120),day=1+Math.floor((i%120)/4),hour=[0,6,12,15][i%4];
    return {received_at:new Date(Date.UTC(2026,month,day,hour)).toISOString(),temperature:Number((27+index+3*Math.sin(i/18)).toFixed(1)),humidity:Number((66-index*4+10*Math.cos(i/15)).toFixed(1)),pm25:Number((18+index*7+7*Math.sin(i/12)).toFixed(1))};
  })]));
  window.fetch=async input=>{
    const url=new URL(typeof input==='string'?input:input.url,location.href),json=(value,status=200)=>new Response(JSON.stringify(value),{status,headers:{'Content-Type':'application/json'}});
    if(url.pathname==='/api/stations')return json(stations);
    const match=url.pathname.match(/^\/api\/stations\/([^/]+)\/(months|latest|history)$/);if(!match)return json({error:'Unavailable in demo'},404);
    const data=readings[decodeURIComponent(match[1])];if(!data)return json({error:'Unknown demo station'},404);
    const month=url.searchParams.get('month'),filtered=month?data.filter(x=>x.received_at.startsWith(month)):data;
    if(match[2]==='months')return json([...new Set(data.map(x=>x.received_at.slice(0,7)))]);
    if(match[2]==='latest')return filtered.length?json({...filtered.at(-1),status:'SIMULATED'}):json({error:'No data'},404);
    const limit=Number(url.searchParams.get('limit')||100);return json(filtered.slice(-Math.max(0,limit)));
  };
})();
