/* Offline authoring only. The shipped application uses native C++ state. */
window.exportNativeFactory = function () {
  const d=CART_DEMO,T=THREE,roots=new Map(),geometries={},materials={},instances=[];
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
    for(let i=0;i<(o.isInstancedMesh?o.count:1);i++) {
      const matrix=new T.Matrix4();
      if(o.isInstancedMesh){o.getMatrixAt(i,matrix);matrix.premultiply(o.matrixWorld);}else matrix.copy(o.matrixWorld);
      if(inverse)matrix.premultiply(inverse);
      const item={geometry:geometry(o.geometry),materials:mats.map(mat),transform:transform(matrix)};
      if(binding) {
        item.binding={...binding,root:undefined,base:transform(binding.root.matrixWorld)};
      }
      if(o.instanceColor){const c=new T.Color();o.getColorAt(i,c);item.color=c.toArray();}
      instances.push(item);
    }
  });
  const brick={geometry:geometry(d.bricks.geometry),materials:d.bricks.material.map(mat)};
  return {schema:'brickflow.native-geometry.v1',geometries,materials,instances,brick,
    reference:'greenfield_30',units:'metres',coordinates:'Three.js Y-up; runtime converts to UE centimetres'};
};
