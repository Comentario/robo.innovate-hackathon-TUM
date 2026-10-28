"""Pin the final prepared reference and export its authoritative event tracks for C++ playback.

No process is replanned here. This is a source-replay export, not independent
physical validation or an independently ported production planner.
"""
import argparse
import base64
import hashlib
import json
import math
import struct
from pathlib import Path

from inspect_reference_cloud import unreal_camera, check_geometry
from export_source_enclosures import export as export_enclosures


def save(path, data):
    path.write_text(json.dumps(data, separators=(",", ":")) + "\n")


def string16(value):
    data = value.encode()
    assert len(data) < 65536
    return struct.pack("<H", len(data)) + data


def main():
    from playwright.sync_api import sync_playwright
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference", type=Path, required=True)
    parser.add_argument("--sha256", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--exporter", type=Path, required=True)
    args = parser.parse_args()
    raw = args.reference.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == args.sha256, "Final reference changed"
    args.output.mkdir(parents=True, exist_ok=True)
    boundary = "window.CART_DEMO={model,scene,camera,renderer,"
    html = raw.decode();assert html.count(boundary) == 1
    html = html.replace(boundary, boundary + "actorMeshes,sourceBeams,rowCenters,bricks,inspectionCovers,routingCovers,orbit,", 1)
    page_path = args.output / "authoring.html";page_path.write_text(html)
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader"])
        page = browser.new_page(viewport={"width": 1600, "height": 900})
        page.add_init_script("window.requestAnimationFrame=()=>0")
        page.goto(page_path.resolve().as_uri(), wait_until="load", timeout=120000)
        page.wait_for_function("window.CART_DEMO || window.CART_ERROR", polling=500, timeout=600000)
        error = page.evaluate("window.CART_ERROR || null")
        if error:raise RuntimeError(error)
        facts = page.evaluate("""() => {
          const m=CART_DEMO.model,records=[...m.records.values()],kinds=[...new Set(records.flatMap(r=>r.trackKinds||r.tracks.map(s=>s.kind)))];
          window.EXPORT_RECORDS=records;window.EXPORT_KINDS=kinds;window.EXPORT_KIND_MAP=new Map(kinds.map((s,i)=>[s,i]));
          const candidates=[];
          for(const p of m.pallets)if(p.shippedAt)for(const id of p.ids){const r=m.rec(id);
            if(r.cart===1&&r.layer===19&&r.j===5&&r.c%2===1&&r.good){
              const tracks=r.tracks.map((s,i)=>Array.isArray(s)?{t0:s[0],t1:s[1],a:i?r.tracks[i-1].slice(2,6):r.initial,b:s.slice(2,6),kind:r.trackKinds[s[6]]}:s);
              candidates.push({id:r.id,cart:r.cart,c:r.c,j:r.j,layer:r.layer,row:r.row,col:r.col,shade:r.shade,pallet:p,
                tracks:tracks.map(s=>({kind:s.kind,start:s.t0,end:s.t1,from:s.a,to:s.b}))});break;
            }}
          candidates.sort((a,b)=>a.pallet.shippedAt-b.pallet.shippedAt);
          const cart=m.rec('input-cart-1');const delivery=cart.tracks.find(s=>s.kind==='cart-delivery');
          return {referenceSha256:HASH,ownerDeclaredFinal:true,backend:'source-event-timeline',independentNativePlanner:false,
            total:m.total,totalInput:m.totalInput,inspected:m.inspected,rejected:m.rejected,produced:m.produced,stored:m.stored,loaded:m.loaded,shipped:m.shipped,
            completeInput:m.completeInput,records:records.length,kinds,cart2Delivery:{start:delivery.t0,end:delivery.t1},
            candidates:candidates.slice(0,24),history:m.history,lanes:m.lanes.map(l=>({id:l.id,z:l.z,group:l.group,side:l.side})),
            pallets:m.pallets,orders:m.orders||[],fleet:m.fleet||[],truckRecords:records.filter(r=>r.kind==='truck').map(r=>({id:r.id,visible:r.visible,hiddenAt:r.hiddenAt}))};
        }""".replace("HASH", json.dumps(args.sha256)))
        assert facts["completeInput"] and facts["inspected"] == 57600
        assert facts["candidates"], "No second-cart top-layer shipped subject matches the profile camera"
        save(args.output / "facts.json", facts)
        print(json.dumps({"stage": "facts", "records": facts["records"], "candidates": len(facts["candidates"]), "cart2Delivery": facts["cart2Delivery"]}), flush=True)
        binary = args.output / "replay.bin"
        with binary.open("wb") as output:
            output.write(b"BFR37V1\0");output.write(struct.pack("<II", facts["records"], len(facts["kinds"])))
            for kind in facts["kinds"]:output.write(string16(kind))
            for offset in range(0, facts["records"], 384):
                encoded = page.evaluate("""offset=>{
                  const rows=EXPORT_RECORDS.slice(offset,offset+384),encoded=new TextEncoder();let size=0;
                  for(const r of rows){size+=2+encoded.encode(String(r.id)).length+2+encoded.encode(r.kind).length+32+16+28+4+8+2+encoded.encode(r.producerGroup||'').length+4;
                    for(const s of r.tracks){const path=Array.isArray(s)?s[8]:s.path,rigid=Array.isArray(s)?s[9]:s.rigid;size+=56+(path?path.length*24:0)+(rigid?96:0)}}
                  const buffer=new ArrayBuffer(size),v=new DataView(buffer);let n=0;
                  const u8=x=>{v.setUint8(n,x);n++},u16=x=>{v.setUint16(n,x,true);n+=2},u32=x=>{v.setUint32(n,x,true);n+=4},i32=x=>{v.setInt32(n,x,true);n+=4},f64=x=>{v.setFloat64(n,x,true);n+=8},str=x=>{const a=encoded.encode(String(x));u16(a.length);new Uint8Array(buffer,n,a.length).set(a);n+=a.length};
                  for(const r of rows){str(r.id);str(r.kind);r.initial.forEach(f64);f64(r.visible||0);f64(r.hiddenAt??1e100);
                    for(const key of ['cart','c','j','layer','row','col','shade'])i32(r[key]??-1);
                    u8(r.good===false?0:1);u8(r.extreme?1:0);u16(0);f64(r.producerScore??NaN);str(r.producerGroup||'');u32(r.tracks.length);
                    for(const s of r.tracks){const a=Array.isArray(s),path=a?s[8]:s.path,rigid=a?s[9]:s.rigid,linear=a?s[7]:s.linear,kind=a?r.trackKinds[s[6]]:s.kind;
                      f64(a?s[0]:s.t0);f64(a?s[1]:s.t1);(a?s.slice(2,6):s.b).forEach(f64);u16(EXPORT_KIND_MAP.get(kind));u16((linear?1:0)|(path?2:0)|(rigid?4:0));u16(path?.length||0);u16(0);
                      if(path)for(const point of path)point.forEach(f64);
                      if(rigid)for(const values of [rigid.from,rigid.to,rigid.local,[rigid.yaw]])values.forEach(f64);
                    }}
                  if(n!==size)throw Error('Replay binary size mismatch '+n+' '+size);
                  const bytes=new Uint8Array(buffer),pieces=[];for(let i=0;i<bytes.length;i+=32768)pieces.push(String.fromCharCode(...bytes.subarray(i,i+32768)));
                  return btoa(pieces.join(''));
                }""", offset)
                output.write(base64.b64decode(encoded))
                if offset % 3840 == 0:print(json.dumps({"stage": "tracks", "records": offset}), flush=True)
        # Independent source samples include path/rigid midpoints, visibility boundaries and all actor types.
        samples = page.evaluate("""() => {
          const list=[],records=EXPORT_RECORDS,subject=CART_DEMO.model.rec(ID);
          for(let i=0;i<records.length;i++){const r=records[i];if(r.kind==='brick'&&i%79&&r!==subject)continue;
            const tracks=r.tracks,indices=[0,Math.floor(tracks.length/3),Math.floor(tracks.length*2/3),tracks.length-1];
            const times=[0,r.visible];if(r.hiddenAt)times.push(r.hiddenAt-.01,r.hiddenAt);
            for(const k of indices)if(tracks[k]){const s=tracks[k],a=Array.isArray(s)?s[0]:s.t0,b=Array.isArray(s)?s[1]:s.t1;times.push(a,(a+b)/2,b)}
            for(const t of times){const pose=CartFactory.pose(r,t);list.push({id:String(r.id),t,pose:pose.length>=7?pose:pose.concat([0,1,0]),visible:t>=(r.visible||0)&&t<(r.hiddenAt??1e100)});}}
          return list;
        }""".replace("ID", json.dumps(facts["candidates"][0]["id"])))
        with (args.output / "pose-samples.csv").open("w") as f:
            for s in samples:
                assert all(math.isfinite(v) for v in s["pose"])
                f.write(",".join([s["id"], str(s["t"]), *map(str, s["pose"]), str(int(s["visible"]))]) + "\n")
        page.evaluate('CART_DEMO.seek(0)')
        enclosures=export_enclosures(page,args.exporter,args.output,args.sha256)
        page.evaluate("""()=>{for(const c of CART_DEMO.routingCovers)c.visible=false;for(const c of CART_DEMO.inspectionCovers)c.visible=false;CART_DEMO.scene.updateMatrixWorld(true)}""")
        page.add_script_tag(path=str(args.exporter.resolve()))
        geometry = page.evaluate("exportNativeFactory({compactInstances:true,reviewLod:true,replayBindings:true})")
        parts = [i for i in geometry["instances"] if "binding" in i]
        geometry["instances"] = [i for i in geometry["instances"] if "binding" not in i]
        assert not any("binding" in b for b in geometry["instanceBatches"])
        types = sorted({p["binding"]["type"] for p in parts})
        geometry.update(snapshotOnly=True, snapshotTime=0, nativeSimulationPorted=False, referenceSha256=args.sha256,
                        purpose="Static scene for native C++ playback of the final source event timeline", serviceCutaways="Separate source enclosures with reversible camera-dependent reveal")
        checks = check_geometry(geometry)
        for material_id, m in geometry["materials"].items():
            if "image" in m:
                name = material_id + ".png";(args.output / name).write_bytes(base64.b64decode(m.pop("image").split(",", 1)[1]));m["texture"] = name
        save(args.output / "geometry.json", geometry);save(args.output / "parts.json", {"parts": parts, "types": types, "brick": geometry["brick"]})
        # Camera presets are an authoring aid; film camera paths are event-driven.
        cameras = []
        for view in ["input", "rows", "inspection", "formation", "output", "warehouse", "shipping", "overview"]:
            page.evaluate("view=>CART_DEMO.view(view)", view)
            camera = page.evaluate("view=>({view,target:CART_DEMO.orbit.target.toArray(),position:CART_DEMO.camera.position.toArray(),quaternion:CART_DEMO.camera.quaternion.toArray(),verticalFov:CART_DEMO.camera.fov})", view)
            cameras.append(unreal_camera(camera))
        save(args.output / "scene.json", {"schema": "brickflow.unreal-lighting-scene.v1", "referenceSha256": args.sha256,
            "snapshotOnly": True, "nativeSimulationPorted": False, "snapshotName": "final37-source-replay-static", "snapshotTime": 0,
            "geometry": "geometry.json", "geometrySha256": hashlib.sha256((args.output / "geometry.json").read_bytes()).hexdigest(),
            "enclosures":"enclosures.json","enclosuresSha256":enclosures['sha256'],"defaultCamera": "overview", "cameras": cameras})
        save(args.output / "export-status.json", {"complete": True, "sourceSha256": args.sha256, "replaySha256": hashlib.sha256(binary.read_bytes()).hexdigest(),
            "replayBytes": binary.stat().st_size, "dynamicParts": len(parts), "bindingTypes": types, "sourcePoseSamples": len(samples), "geometryChecks": checks,
            "runtime": "native C++ source-event replay in Unreal", "independentNativePlanner": False})
        browser.close()
    print(json.dumps({"complete": True, "output": str(args.output), "dynamicParts": len(parts), "bindingTypes": types}), flush=True)


if __name__ == "__main__":main()
