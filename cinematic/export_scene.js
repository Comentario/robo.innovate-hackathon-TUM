/* Read-only snapshot of the actual Three.js replay, including instanced meshes. */
window.exportFactoryScene = function () {
  const demo = window.CART_DEMO;
  if (!demo) throw Error('Full-cart replay is not ready');
  const T = window.THREE, geometries = {}, materials = {}, objects = [];
  demo.scene.updateMatrixWorld(true);
  function material(m) {
    if (!materials[m.uuid]) {
      const item = {color: m.color ? m.color.toArray() : [1, 1, 1],
        opacity: m.opacity, roughness: m.roughness ?? .48, metalness: m.metalness ?? 0};
      if (m.map) {
        const image = m.map.image;
        if (!image || !image.width) throw Error('Texture is not loaded');
        const canvas = document.createElement('canvas');
        canvas.width = image.width; canvas.height = image.height;
        canvas.getContext('2d').drawImage(image, 0, 0);
        item.texture = canvas.toDataURL('image/png');
      }
      materials[m.uuid] = item;
    }
    return m.uuid;
  }
  demo.scene.traverseVisible(o => {
    if (!o.isMesh) return;
    const mats = Array.isArray(o.material) ? o.material : [o.material];
    if (mats.every(m => !m.visible || m.opacity === 0)) return;
    if (mats.some(m => !m.visible)) throw Error('Partially invisible material is unsupported');
    const g = o.geometry;
    if (!geometries[g.uuid]) geometries[g.uuid] = {
      positions: Array.from(g.attributes.position.array),
      normals: g.attributes.normal ? Array.from(g.attributes.normal.array) : null,
      uv: g.attributes.uv ? Array.from(g.attributes.uv.array) : null,
      indices: g.index ? Array.from(g.index.array) : null,
      groups: g.groups,
    };
    const ids = mats.map(material), matrix = new T.Matrix4(), color = new T.Color();
    for (let i = 0; i < (o.isInstancedMesh ? o.count : 1); i++) {
      if (o.isInstancedMesh) { o.getMatrixAt(i, matrix); matrix.premultiply(o.matrixWorld); }
      else matrix.copy(o.matrixWorld);
      if (Math.abs(matrix.determinant()) < 1e-15) continue;
      const item = {geometry: g.uuid, materials: ids, matrix: matrix.toArray()};
      if (o.instanceColor) { o.getColorAt(i, color); item.color = color.toArray(); }
      objects.push(item);
    }
  });
  return {schema: 'brickflow.render-snapshot.v1', geometries, materials, objects,
    camera: {matrix: demo.camera.matrixWorld.toArray(), fov: demo.camera.fov},
    evidence: {type: 'synthetic engineering replay',
      simulationTime: Number(document.getElementById('time').value),
      total: demo.model.total, inspected: demo.model.inspected,
      delivered: demo.model.delivered, bph: demo.model.bph, pph: demo.model.pph}};
};
