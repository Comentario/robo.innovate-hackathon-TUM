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
    if(options.replayBindings&&g.userData.reachSleeves) {
      g.userData.reachSleeves.forEach((root,i)=>roots.set(root,{type:'forkSleeve',record:String(r.id),root,sign:i?1:-1,parentTransform:transform(root.matrix)}));
      g.userData.reachPosts.forEach((root,i)=>roots.set(root,{type:'forkPost',record:String(r.id),root,sign:i?1:-1,parentTransform:transform(root.matrix)}));
      for(const root of g.children)if(root.isMesh&&root.scale.x===1&&root.scale.y===.05)
        roots.set(root,{type:'forkTop',record:String(r.id),root,sign:root.position.z<0?-1:1,parentTransform:transform(root.matrix)});
    }
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
    if(!o.isMesh||(o===d.bricks&&!options.snapshotWorld))return;
    if(options.snapshotWorld) {
      // A frozen authoring state, including current visibility and brick matrices.
      // Use nearest LOD consistently; never render both levels over one another.
      for(let p=o;p;p=p.parent) {
        if(p.parent?.isLOD) {
          if(p!==p.parent.levels[0].object)return;
        } else if(!p.visible)return;
      }
    }
    const mats=Array.isArray(o.material)?o.material:[o.material];
    if(mats.every(m=>!m.visible||m.opacity===0))return;
    let binding=null;
    if(!options.snapshotWorld)for(let p=o;p;p=p.parent)if(roots.has(p)){binding=roots.get(p);break;}
    // One reusable native pallet prefab instead of one instance per cached pallet.
    if(binding&&binding.record.startsWith('wood-')&&binding.record!=='wood-0'&&!options.replayBindings)return;
    if(options.replayBindings) {
      for(let p=o;p;p=p.parent) {
        if(p.parent?.isLOD){if(p!==p.parent.levels[0].object)return;}
        else if(!binding&&!p.visible)return;
      }
    }
    const inverse=binding?binding.root.matrixWorld.clone().invert():null;
    if(options.compactInstances&&o.isInstancedMesh&&!(options.replayBindings&&binding)) {
      const parent=o.matrixWorld.clone();if(inverse)parent.premultiply(inverse);
      let matrices=o.instanceMatrix.array.subarray(0,o.count*16),colors=o.instanceColor?.array.subarray(0,o.count*3),count=o.count;
      if(options.snapshotWorld) {
        const kept=[],tints=[];
        for(let i=0;i<o.count;i++) {
          const values=matrices.subarray(i*16,i*16+16);
          if(Math.hypot(values[0],values[1],values[2])<1e-8)continue;
          kept.push(...values);if(colors)tints.push(...colors.subarray(i*3,i*3+3));
        }
        count=kept.length/16;if(!count)return;
        matrices=new Float32Array(kept);if(colors)colors=new Float32Array(tints);
      }
      const batch={geometry:geometry(o.geometry),materials:mats.map(mat),count,
        parentMatrix:parent.toArray(),matrixEncoding:'base64-float32-little-endian-column-major',
        matrices:encodeFloat32(matrices)};
      if(binding)batch.binding={...binding,root:undefined,base:transform(binding.root.matrixWorld)};
      const lod=lodFor(o);if(lod)batch.lod=lod;
      if(colors)batch.colors=encodeFloat32(colors);
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
