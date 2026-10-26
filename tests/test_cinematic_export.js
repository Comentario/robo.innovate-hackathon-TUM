/* Run with node tests/test_cinematic_export.js /tmp/brickflow-export.json.gz. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const zlib = require('node:zlib');
const crypto = require('node:crypto');
const path = require('node:path');
const root = path.resolve(__dirname, '..');
const context = {console};
context.window = context;
context.document = {getElementById: () => ({value: '42'})};
vm.createContext(context);
vm.runInContext(fs.readFileSync(path.join(root, 'third_party/three/three.min.js'), 'utf8'), context);
vm.runInContext(`
const scene = new THREE.Scene();
const camera = new THREE.PerspectiveCamera(43, 16/9, .1, 100);
camera.position.set(0, 2, 6); camera.lookAt(0, 0, 0); camera.updateMatrixWorld();
const instances = new THREE.InstancedMesh(new THREE.BoxGeometry(1,1,1),
  new THREE.MeshLambertMaterial({color: 0xffffff}), 3);
instances.position.x = .5;
instances.setMatrixAt(0, new THREE.Matrix4().makeTranslation(-1, 0, 0));
instances.setMatrixAt(1, new THREE.Matrix4().makeTranslation(1, 0, 0));
instances.setMatrixAt(2, new THREE.Matrix4().makeScale(0,0,0));
instances.setColorAt(0, new THREE.Color(.6,.2,.05));
instances.setColorAt(1, new THREE.Color(.15,.5,.3));
scene.add(instances);
const proxy = new THREE.Mesh(new THREE.BoxGeometry(), new THREE.MeshBasicMaterial({visible:false}));
scene.add(proxy);
window.CART_DEMO = {scene, camera, seek: () => {}, model: {total:100, inspected:3, delivered:0, bph:0, pph:0}};
`, context);
vm.runInContext(fs.readFileSync(path.join(root, 'cinematic/export_scene.js'), 'utf8'), context);
const data = vm.runInContext('exportFactoryScene()', context);
assert.equal(data.objects.length, 2, 'Exclude invisible proxy and hidden zero-scale instance');
assert.equal(Object.keys(data.geometries).length, 1, 'Share instanced geometry');
assert.equal(data.objects[0].matrix[12], -.5, 'Compose instance and world transforms');
assert.equal(data.objects[1].matrix[12], 1.5);
assert.equal(data.objects[0].color[0], Math.fround(.6));
assert.equal(data.evidence.simulationTime, 42);
assert.equal(data.camera.fov, 43);
assert.equal(Object.values(data.geometries)[0].normals.length, 72);
const changes = vm.runInContext(`instances.setMatrixAt(0,new THREE.Matrix4().makeTranslation(-.5,0,0)); sampleFactoryMotion(43)`,context);
assert.equal(changes.length,1);
assert.equal(changes[0].index,0);
assert.equal(changes[0].matrix[12],0);
assert.equal(vm.runInContext('sampleFactoryMotion(44).length',context),0,'Skip unchanged transforms');
if (process.argv[2]) {
  const snapshot=zlib.gzipSync(JSON.stringify(data));
  fs.writeFileSync(process.argv[2], snapshot);
  if(process.argv[3]) fs.writeFileSync(process.argv[3],zlib.gzipSync(JSON.stringify({
    schema:'brickflow.render-motion.v1',fps:24,rate:1,start:42,
    snapshotSha256:crypto.createHash('sha256').update(snapshot).digest('hex'),
    frames:[{frame:2,changes},{frame:3,changes:[]},{frame:4,changes:[]}]
  })));
}
console.log('Cinematic export: instancing, world transforms, colors, visibility and evidence passed.');
