// Run with Node and the exact Three.js script extracted from the pinned reference.
const fs=require('fs'),vm=require('vm'),assert=require('assert');
const context={console,btoa:value=>Buffer.from(value,'binary').toString('base64')};context.window=context;context.self=context;
vm.createContext(context);
vm.runInContext(fs.readFileSync(process.argv[2],'utf8'),context);
vm.runInContext(fs.readFileSync(process.argv[3],'utf8'),context);
vm.runInContext(`
const T=THREE,scene=new T.Scene(),material=new T.MeshLambertMaterial({color:0xffffff}),geometry=new T.BoxGeometry(1,1,1);
const visible=new T.Mesh(geometry,material);scene.add(visible);
const hidden=new T.Group();hidden.visible=false;hidden.add(new T.Mesh(geometry,material));scene.add(hidden);
const lod=new T.LOD(),near=new T.InstancedMesh(geometry,material,3),far=new T.Mesh(geometry,material),matrix=new T.Matrix4();
near.setMatrixAt(0,matrix.makeTranslation(1,2,3));near.setMatrixAt(1,matrix.makeScale(0,0,0));near.setMatrixAt(2,matrix.makeTranslation(4,5,6));
near.setColorAt(0,new T.Color(1,0,0));near.setColorAt(1,new T.Color(0,1,0));near.setColorAt(2,new T.Color(0,0,1));
lod.addLevel(near,0);lod.addLevel(far,6);near.visible=false;far.visible=true;scene.add(lod);
const bricks=new T.InstancedMesh(geometry,[material],2);bricks.setMatrixAt(0,matrix.makeTranslation(7,8,9));bricks.setMatrixAt(1,matrix.makeScale(0,0,0));scene.add(bricks);
window.CART_DEMO={scene,actorMeshes:new Map(),sourceBeams:[],rowCenters:[],bricks};
window.legacy=exportNativeFactory();window.snapshot=exportNativeFactory({compactInstances:true,snapshotWorld:true});
`,context);
assert.equal(context.legacy.schema,'brickflow.native-geometry.v1');
assert.equal(context.legacy.instances.length,6,'Legacy authoring includes animation/LOD states and excludes the brick pool');
assert.equal(context.snapshot.instances.length,1,'Hidden ancestors and far LOD must not leak into a frozen state');
assert.equal(context.snapshot.instanceBatches.length,2,'Nearest LOD and the brick pool are both retained');
assert.deepEqual(Array.from(context.snapshot.instanceBatches,b=>b.count),[2,1],'Zero-scale hidden instances are removed');
const batch=context.snapshot.instanceBatches[0],colors=Buffer.from(batch.colors,'base64'),matrices=Buffer.from(batch.matrices,'base64');
assert.equal(colors.length,2*12);assert.equal(matrices.length,2*64);
assert.equal(matrices.readFloatLE(12*4),1);assert.equal(matrices.readFloatLE((16+12)*4),4);
assert.equal(colors.readFloatLE(0),1);assert.equal(colors.readFloatLE(5*4),1);
console.log(JSON.stringify({legacyPreserved:true,hiddenAncestorsExcluded:true,nearestLodOnly:true,visibleBrickPoolIncluded:true,colorsRemainAligned:true}));
