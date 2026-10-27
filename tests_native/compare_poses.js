/* Offline comparison against the actual reference JS pose function, not a port. */
const fs=require('node:fs'),zlib=require('node:zlib'),vm=require('node:vm'),assert=require('node:assert/strict');
const path=require('node:path');
const root=path.resolve(__dirname,'..');
global.window={};
vm.runInThisContext(fs.readFileSync(path.join(root,'artifacts/cinematic/reference_30/model.js'),'utf8'));
const results={verified:true,modes:{}};
for(const mode of ['mixed','single']){
  const native=JSON.parse(fs.readFileSync(path.join(root,`artifacts/cinematic/reference_30/native-${mode}.json`)));
  const reference=JSON.parse(zlib.gunzipSync(fs.readFileSync(path.join(root,`artifacts/greenfield_30/${mode}-572c87cac2f8addb.json.gz`))));
  const names=new Set(native.samples.map(s=>s.id)),records=new Map();
  for(const r of reference.records)if(names.has(String(r.id))){
    if(reference.kinds){let previous=r.initial;r.tracks=r.tracks.map(v=>{
      const s={t0:v[0],t1:v[1],a:previous,b:v.slice(2,6),kind:reference.kinds[v[6]],linear:!!v[7]};
      if(v[8])s.path=v[8];if(v[9])s.rigid=v[9];previous=s.b;return s;
    });}
    records.set(String(r.id),r);
  }
  let maximum=0;
  for(const sample of native.samples){
    const record=records.get(sample.id);assert(record,`${mode}: missing ${sample.id}`);
    const expected=window.CartFactory.pose(record,sample.t);
    const error=Math.max(...expected.map((x,i)=>Math.abs(x-sample.pose[i])));maximum=Math.max(maximum,error);
    assert(error<1e-7,`${mode}: pose mismatch ${sample.id} at ${sample.t}: ${error}`);
  }
  results.modes[mode]={samples:native.samples.length,maxPoseComponentError:maximum};
}
fs.writeFileSync(path.join(root,'artifacts/cinematic/reference_30/pose-comparison.json'),JSON.stringify(results,null,2));
console.log(JSON.stringify(results,null,2));
