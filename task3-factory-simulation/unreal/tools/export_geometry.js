/* Offline authoring only. The shipped application uses native C++ state. */
window.exportNativeFactory = function (options = {}) {
  const d=CART_DEMO,T=THREE,roots=new Map(),geometries={},materials={},instances=[],instanceBatches=[];
  const encodeFloat32 = array => {
    const bytes=new Uint8Array(array.buffer,array.byteOffset,array.byteLength),pieces=[];
    for(let i=0;i<bytes.length;i+=32768)pieces.push(String.fromCharCode(...bytes.subarray(i,i+32768)));
    return btoa(pieces.join(''));
  };
  const lodFor = o => {
    if(!options.reviewLod)return null;
    for(let child=o,parent=o.parent;parent;child=parent,parent=parent.parent)if(parent.isLOD) {
      const level=parent.levels.findIndex(entry=>entry.object===child);
      if(level>=0)return {group:parent.uuid,level,minDistance:parent.levels[level].distance,
        maxDistance:parent.levels[level+1]?.distance??null,origin:transform(parent.matrixWorld)};
      break;
    }
    return null;
  };
  const transform = matrix => {
    const p=new T.Vector3(),q=new T.Quaternion(),s=new T.Vector3();matrix.decompose(p,q,s);
    return {position:p.toArray(),rotation:q.toArray(),scale:s.toArray()};
  };
  for(const {r,g,mast,trolley,beamMesh} of d.actorMeshes.values()) {
    roots.set(g,{type:'actor',record:String(r.id),root:g});
    for(const [type,root] of Object.entries({mast,trolley,beam:beamMesh}))
      if(root) roots.set(root,{type,record:String(r.id),root});
    for(const part of [...(g.userData.jaws||[]),...(g.userData.palletJaws||[])])
      roots.set(part.jaw,{type:g.userData.palletJaws?'palletJaw':'gripperJaw',
        record:String(r.id),root:part.jaw,sign:part.sign,parentTransform:transform(part.jaw.matrix)});
  }
  d.sourceBeams.forEach((root,j)=>roots.set(root,{type:'sourceBeam',record:'head-0-'+j,root}));
  d.rowCenters.forEach(row=>{
    for(const [type,list] of Object.entries({rowPad:row.pads,rowRod:row.rods}))
      list.forEach((root,i)=>roots.set(root,{type,record:'rowpush-'+row.lane+'-'+row.station,
        root,sign:i?1:-1,lane:row.lane,station:row.station}));
  });
  function mat(m) {
    if(materials[m.uuid]) return m.uuid;
    const out={color:m.color?.toArray()||[1,1,1],opacity:m.opacity,doubleSided:m.side===T.DoubleSide};
    if(m.map) {
      const image=m.map.image,canvas=document.createElement('canvas');
      canvas.width=image.width;canvas.height=image.height;canvas.getContext('2d').drawImage(image,0,0);
      out.image=canvas.toDataURL('image/png');
    }
    materials[m.uuid]=out;return m.uuid;
  }
  function geometry(g) {
    if(!geometries[g.uuid]) geometries[g.uuid]={positions:Array.from(g.attributes.position.array),
      normals:g.attributes.normal?Array.from(g.attributes.normal.array):[],
      uv:g.attributes.uv?Array.from(g.attributes.uv.array):[],
      indices:g.index?Array.from(g.index.array):Array.from({length:g.attributes.position.count},(_,i)=>i),groups:g.groups};
    return g.uuid;
  }
  d.scene.updateMatrixWorld(true);
  d.scene.traverse(o=>{
    if(!o.isMesh||o===d.bricks)return;
    const mats=Array.isArray(o.material)?o.material:[o.material];
    if(mats.every(m=>!m.visible||m.opacity===0))return;
    let binding=null;
    for(let p=o;p;p=p.parent)if(roots.has(p)){binding=roots.get(p);break;}
    // One reusable native pallet prefab instead of one instance per cached pallet.
    if(binding&&binding.record.startsWith('wood-')&&binding.record!=='wood-0')return;
    const inverse=binding?binding.root.matrixWorld.clone().invert():null;
    if(options.compactInstances&&o.isInstancedMesh) {
      const parent=o.matrixWorld.clone();if(inverse)parent.premultiply(inverse);
      const batch={geometry:geometry(o.geometry),materials:mats.map(mat),count:o.count,
        parentMatrix:parent.toArray(),matrixEncoding:'base64-float32-little-endian-column-major',
        matrices:encodeFloat32(o.instanceMatrix.array.subarray(0,o.count*16))};
      if(binding)batch.binding={...binding,root:undefined,base:transform(binding.root.matrixWorld)};
      const lod=lodFor(o);if(lod)batch.lod=lod;
      if(o.instanceColor)batch.colors=encodeFloat32(o.instanceColor.array.subarray(0,o.count*3));
      instanceBatches.push(batch);return;
    }
    for(let i=0;i<(o.isInstancedMesh?o.count:1);i++) {
      const matrix=new T.Matrix4();
      if(o.isInstancedMesh){o.getMatrixAt(i,matrix);matrix.premultiply(o.matrixWorld);}else matrix.copy(o.matrixWorld);
      if(inverse)matrix.premultiply(inverse);
      const item={geometry:geometry(o.geometry),materials:mats.map(mat),transform:transform(matrix)};
      const lod=lodFor(o);if(lod)item.lod=lod;
      if(binding) {
        item.binding={...binding,root:undefined,base:transform(binding.root.matrixWorld)};
      }
      if(o.instanceColor){const c=new T.Color();o.getColorAt(i,c);item.color=c.toArray();}
      instances.push(item);
    }
  });
  const brick={geometry:geometry(d.bricks.geometry),materials:d.bricks.material.map(mat)};
  return {schema:options.compactInstances?'brickflow.authoring-geometry.v2':'brickflow.native-geometry.v1',
    geometries,materials,instances,...(options.compactInstances?{instanceBatches}:{}),brick,
    reference:'greenfield_30',units:'metres',coordinates:'Three.js Y-up; runtime converts to UE centimetres'};
};
