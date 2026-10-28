"""Freeze source states for native Unreal lighting authoring, not simulation validation."""
import argparse
import base64
import hashlib
import json
from pathlib import Path

from inspect_reference_cloud import check_geometry, unreal_camera


def save_json(path, value):
    path.write_text(json.dumps(value, separators=(",", ":")) + "\n")


def main():
    from playwright.sync_api import sync_playwright
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference", type=Path, required=True)
    parser.add_argument("--sha256", required=True)
    parser.add_argument("--exporter", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    data = args.reference.read_bytes()
    if hashlib.sha256(data).hexdigest() != args.sha256:
        raise ValueError("Input differs from pinned source")
    boundary = "window.CART_DEMO={model,scene,camera,renderer,"
    source = data.decode()
    if source.count(boundary) != 1:
        raise ValueError("Unknown instrumentation boundary")
    source = source.replace(boundary, boundary + "actorMeshes,sourceBeams,rowCenters,bricks,inspectionCovers,routingCovers,orbit,", 1)
    args.output.mkdir(parents=True, exist_ok=True)
    authoring = args.output / "authoring.html"
    authoring.write_text(source)
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader"])
        page = browser.new_page(viewport={"width": 1600, "height": 900})
        page.add_init_script("window.requestAnimationFrame=()=>0")
        page.goto(authoring.resolve().as_uri(), wait_until="load", timeout=120000)
        page.wait_for_function("window.CART_DEMO || window.CART_ERROR", timeout=600000, polling=500)
        failure = page.evaluate("window.CART_ERROR || null")
        if failure:
            raise RuntimeError(failure)
        facts = page.evaluate("""() => {
          const m=CART_DEMO.model,first=k=>m.history.find(h=>h[k]>0)?.t??null;
          const kinds={},tracks={};let reach=null,pick=null;
          for(const r of m.records.values()) {
            kinds[r.kind]=(kinds[r.kind]||0)+1;
            if(r.kind==='brick')continue;
            for(const s of r.tracks) {
              tracks[s.kind]=(tracks[s.kind]||0)+1;
              if(s.kind==='amr-extend-reach-forks'&&(!reach||s.t0<reach.t0))reach={id:r.id,t0:s.t0,t1:s.t1,pose:CartFactory.pose(r,(s.t0+s.t1)/2)};
              if(s.kind==='amr-pallet-confirm'&&(!pick||s.t0<pick.t0))pick={id:r.id,t0:s.t0,t1:s.t1};
            }
          }
          return {total:m.total,totalInput:m.totalInput,completeInput:m.completeInput,inspected:m.inspected,
            rejected:m.rejected,produced:m.produced,stored:m.stored,loaded:m.loaded,shipped:m.shipped,
            actorKinds:kinds,trackKinds:tracks,firstInspected:first('inspected'),firstStored:first('stored'),
            firstLoaded:first('loaded'),firstShipped:first('shipped'),reach,pick,
            lanes:m.lanes.map(l=>({id:l.id,z:l.z})),storage:m.storage.map(s=>({id:s.id,x:s.x,z:s.z})),
            docks:m.docks?.map(d=>({category:d.category,x:d.x,z:d.z}))??[0,1,2,3].map(category=>{
              const r=m.rec('truck-'+category+'-1'),p=r.tracks.find(s=>s.kind==='truck-reverse-to-dock').b;
              return {category,x:p[0],z:p[2]};}),
            trucks:[...m.records.values()].filter(r=>r.kind==='truck').map(r=>({id:r.id,visible:r.visible,hiddenAt:r.hiddenAt}))};
        }""")
        facts.update(referenceSha256=args.sha256, validationStatus="unvalidated", evidenceKind="source replay observations")
        save_json(args.output / "source-facts.json", facts)
        # Presentation-only trial rig, separate from the scene and source process.
        lights = []
        def light(name, position, target, intensity, size, radius, shadows):
            lights.append(dict(id=name, positionCm=position, targetCm=target, intensity=intensity,
                               widthCm=size[0], heightCm=size[1], radiusCm=radius, castShadows=shadows))
        lane_z = facts["lanes"][0]["z"] * 100
        light("input-side-bounce", [-2000,-600,700], [-1300,0,130], 120000, [1400,800], 3000, False)
        light("row-profile-edge", [2100,lane_z-300,500], [2150,lane_z,160], 80000, [900,500], 1800, False)
        light("inspection-housing-key", [2800,lane_z-400,500], [2696,lane_z,175], 65000, [600,400], 1200, True)
        light("inspection-service-fill", [2550,lane_z+300,450], [2696,lane_z,175], 35000, [500,350], 1000, False)
        light("formation-side-fill", [4800,lane_z-400,350], [5000,lane_z,150], 80000, [900,600], 2200, False)
        stock_x = sum(s["x"] for s in facts["storage"]) / len(facts["storage"]) * 100
        light("bridge-stock-side", [stock_x-1200,-800,700], [stock_x,0,150], 300000, [1800,900], 7000, False)
        light("warehouse-overhead", [stock_x,0,1600], [stock_x,0,100], 800000, [3000,3500], 10000, True)
        light("warehouse-face-bounce", [stock_x-200,-1600,500], [stock_x,0,100], 220000, [2600,800], 6000, False)
        dock_x = sum(d["x"] for d in facts["docks"]) / len(facts["docks"]) * 100
        dock_z = sum(d["z"] for d in facts["docks"]) / len(facts["docks"]) * 100
        light("side-loading-overhead", [dock_x,dock_z,1600], [dock_x,dock_z,100], 1200000, [4000,2000], 9000, True)
        light("side-loading-face-bounce", [dock_x+400,dock_z-1000,600], [dock_x,dock_z,100], 400000, [4000,1000], 7000, False)
        save_json(args.output / "lighting-candidate.json", {"schema":"brickflow.review-lights.v1", "status":"trial-not-approved",
                  "referenceSha256":args.sha256,"units":"Unreal centimeters; intensity source values, not measured lux",
                  "lights":lights,"note":"Stationary studio presentation support. No changes to reference actors or motion."})
        reach = facts["reach"]
        if not reach:
            raise ValueError("Prepared source does not contain a side-loading reach event")
        states = [
            ("input", 0, False, "input"),
            ("inspection-closed", (facts["firstInspected"] or 120) + 2, False, "inspection"),
            ("inspection-cutaway", (facts["firstInspected"] or 120) + 2, True, "inspection"),
            ("warehouse", max(0, reach["t0"] - 20), False, "warehouse"),
            ("side-loading", (reach["t0"] + reach["t1"]) / 2, False, "shipping")
        ]
        page.add_script_tag(path=str(args.exporter.resolve()))
        manifests = []
        for name, time, cutaway, default_camera in states:
            page.evaluate("""({time,cutaway})=>{CART_DEMO.seek(time);
              for(const cover of CART_DEMO.inspectionCovers)cover.visible=!cutaway;
              CART_DEMO.scene.updateMatrixWorld(true);} """, {"time": time, "cutaway": cutaway})
            cameras = []
            for view in ["input", "rows", "inspection", "formation", "output", "warehouse", "shipping", "overview"]:
                page.evaluate("view=>CART_DEMO.view(view)", view)
                camera = page.evaluate("""view=>({view,target:CART_DEMO.orbit.target.toArray(),position:CART_DEMO.camera.position.toArray(),
                  quaternion:CART_DEMO.camera.quaternion.toArray(),verticalFov:CART_DEMO.camera.fov})""", view)
                cameras.append(unreal_camera(camera))
            # Additional close views remain review cameras, not actor animation.
            for view, position, target in [
                ("fork-detail", [reach["pose"][0] + 6, 2.7, reach["pose"][2] + 3], [reach["pose"][0], 0.9, reach["pose"][2]]),
                ("stock-detail", [72, 3.7, -8], [66, 0.9, -9])
            ]:
                page.evaluate("""({position,target})=>{const c=CART_DEMO.camera;CART_DEMO.orbit.target.set(...target);c.position.set(...position);c.lookAt(...target);c.updateMatrixWorld(true)}""", {"position": position, "target": target})
                camera = page.evaluate("""view=>({view,target:CART_DEMO.orbit.target.toArray(),position:CART_DEMO.camera.position.toArray(),quaternion:CART_DEMO.camera.quaternion.toArray(),verticalFov:CART_DEMO.camera.fov})""", view)
                cameras.append(unreal_camera(camera))
            geometry = page.evaluate("exportNativeFactory({compactInstances:true,snapshotWorld:true})")
            geometry.update(referenceSha256=args.sha256, validationStatus="unvalidated", nativeSimulationPorted=False,
                            snapshotTime=time, snapshotOnly=True, fixedLod="nearest geometry only", inspectionCutaway=cutaway)
            checks = check_geometry(geometry)
            for material_id, material in geometry["materials"].items():
                if "image" in material:
                    image_name = material_id + ".png"
                    (args.output / image_name).write_bytes(base64.b64decode(material.pop("image").split(",", 1)[1]))
                    material["texture"] = image_name
            asset = args.output / (name + "-geometry.json")
            save_json(asset, geometry)
            manifest = {"schema": "brickflow.unreal-lighting-scene.v1", "referenceSha256": args.sha256,
                        "validationStatus": "unvalidated", "snapshotOnly": True, "nativeSimulationPorted": False,
                        "snapshotTime": time, "snapshotName": name, "inspectionCutaway": cutaway,
                        "geometry": asset.name, "geometrySha256": hashlib.sha256(asset.read_bytes()).hexdigest(),
                        "defaultCamera": default_camera, "cameras": cameras, "checks": checks,
                        "visibleBrickInstances": sum(b["count"] for b in geometry["instanceBatches"] if b["geometry"] == geometry["brick"]["geometry"])}
            save_json(args.output / (name + ".json"), manifest)
            manifests.append(manifest)
            print(json.dumps({"state": name, "time": time, "instances": len(geometry["instances"]),
                              "packed": checks["packedInstanceMatricesChecked"], "assetBytes": asset.stat().st_size}), flush=True)
        save_json(args.output / "review-index.json", {"referenceSha256": args.sha256, "snapshotOnly": True,
                  "nativeSimulationPorted": False, "states": manifests})
        browser.close()


if __name__ == "__main__":
    main()
