'use strict';
(() => {
  const data = JSON.parse(document.getElementById('demo-data').textContent);
  const $ = id => document.getElementById(id);
  const modes = ['mixed', 'smooth'];
  let cursor = 0, timer = null;
  const el = (tag, cls, value) => {
    const node = document.createElement(tag);
    if (cls) node.className = cls;
    if (value !== undefined) node.textContent = value;
    return node;
  };
  data.scenarios.forEach((s, i) => {
    const option = el('option', '', s.name); option.value = i; $('scenario').append(option);
  });
  // Start with the face-aware scenario so the new constraint is visible immediately.
  $('scenario').value = '3';
  const scenario = () => data.scenarios[Number($('scenario').value)];
  const report = mode => scenario().results[`${mode}/${$('policy').value}`][$('failure').value === 'none' ? 'normal' : 'failure'];
  const limitFor = r => r.status === 'rejected' ? 0 : r.confirmed_placements.length + (r.status === 'stopped' ? 1 : 0);
  const limit = () => Math.max(...modes.map(m => limitFor(report(m))));
  function stop() { if (timer !== null) clearInterval(timer); timer = null; }
  function phase(r) {
    if (r.status === 'rejected') return 'rejected';
    if (cursor >= limitFor(r)) return r.status;
    return timer !== null ? 'running' : cursor === 0 ? 'ready' : 'paused';
  }
  function renderPanel(mode) {
    const r = report(mode), state = phase(r);
    const box = el('article', `panel ${mode}`); box.dataset.mode = mode; box.dataset.status = state;
    const head = el('div', 'panel-head'), title = el('div', 'panel-title');
    title.append(el('h2', '', mode === 'mixed' ? 'Mixed' : 'Smooth'), el('span', `status ${state}`, state));
    head.append(title, el('p', 'subtitle', mode === 'mixed' ? 'Balance shades across layers and rows' : 'Prioritize small neighboring shade differences'));
    box.append(head);
    if (r.status === 'rejected') {
      box.append(el('p', 'rejection', `Recipe rejected. ${r.reason}. No placements will be simulated.`));
      box.append(el('div', 'event', 'plan_rejected → no picks issued'));
      return box;
    }
    const plan = r.plan, placements = plan.placements;
    const confirmed = Math.min(cursor, r.confirmed_placements.length);
    const stats = el('div', 'stats');
    for (const [value, label] of [[`${confirmed}/${placements.length}`, 'Placed'], [plan.metrics.ratio_l1_error.toFixed(3), 'Final recipe L1 error'], [`${plan.metrics.same_tone_neighbors}/${plan.metrics.neighbor_pairs}`, 'Final matching neighbors']]) {
      const item = el('div'); item.append(el('strong', '', value), el('span', '', label)); stats.append(item);
    }
    head.append(stats);
    const recipe = el('p', 'recipe-counts');
    recipe.append(el('strong', '', 'Final shade counts: '));
    recipe.append(document.createTextNode(Object.entries(plan.blend).map(([g,n]) => `${g} ${n}`).join(' · ')));
    recipe.append(el('span', '', ' | Same quantities, different positions.'));
    head.append(recipe);
    for (let layer = 0; layer < plan.shape.layers; layer++) {
      const section = el('section', 'layer');
      const lh = el('div', 'layer-head'); lh.append(el('span', '', `LAYER ${layer + 1}`), el('span', '', layer === 0 ? 'Bottom layer' : 'Upper layer'));
      const grid = el('div', 'grid'); grid.style.gridTemplateColumns = `repeat(${plan.shape.columns}, minmax(0, 1fr))`;
      for (const p of placements.filter(p => p.layer === layer)) {
        const placed = p.step <= confirmed;
        const failed = state === 'stopped' && p.step === confirmed + 1;
        const next = !placed && !failed && p.step === confirmed + 1 && state !== 'completed';
        let cls = 'brick';
        if (placed) cls += ` placed ${p.color_group}${p.step === confirmed ? " arriving" : ""}`;
        else if ($('ghosts').checked) cls += ` ghost ${p.color_group}`;
        if (next) cls += ' next'; if (failed) cls += ' failed';
        const cell = el('div', cls);
        cell.dataset.step = p.step; cell.dataset.placed = String(placed);
        cell.title = `Step ${p.step}: ${p.brick_id} · ${p.color_group} · ${p.visible_face || 'face not modeled'} · ${p.orientation_id || 'orientation not modeled'}`;
        if (placed || $('ghosts').checked) {
          cell.append(el('strong', '', `#${p.step} ${p.color_group}`), el('small', '', p.visible_face ? `${p.visible_face} · ${p.brick_id}` : p.brick_id));
        } else cell.append(el('span', 'empty', `Position ${p.step}`));
        grid.append(cell);
      }
      const balance = plan.metrics.distribution;
      if (balance) {
        const counts = balance.layers.find(r => r.layer === layer);
        const summary = el('div', 'layer-counts');
        const table = el('table');
        const header = el('tr');
        for (const text of ['Shade', 'Target', 'Planned']) header.append(el('th', '', text));
        table.append(header);
        for (const [shade, n] of Object.entries(counts.counts)) {
          const tr = el('tr');
          for (const text of [shade, counts.target_counts[shade].toFixed(1), String(n)]) tr.append(el('td', '', text));
          table.append(tr);
        }
        summary.append(table);
        const rows = balance.rows.filter(r => r.layer === layer);
        summary.append(el('p', '', 'Row counts (dark / medium / light): ' + rows.map(r => ['dark','medium','light'].map(g => r.counts[g] || 0).join('/')).join(' · ')));
        section.append(lh, grid, summary);
      } else section.append(lh, grid);
      box.append(section);
    }
    const detail = el('section', 'detail');
    const selected = state === 'completed' ? placements[placements.length - 1] : placements[confirmed];
    if (selected) {
      detail.append(el('h3', '', `${state === 'completed' ? 'Last placed' : state === 'stopped' ? 'Failed pick' : 'Next pick'}: ${selected.brick_id}`));
      if (scenario().face_aware) {
        const brick = scenario().inventory.find(b => b.id === selected.brick_id), faces = el('div', 'face-list');
        for (const [name, observation] of Object.entries(brick.faces)) {
          const shade = observation ? observation.color_group : 'unobserved';
          const face = el('span', `face ${name === selected.visible_face ? 'selected' : ''}`);
          face.append(el('i', `face-swatch ${observation ? shade : 'unknown'}`), document.createTextNode(`${name}: ${shade}`));
          faces.append(face);
        }
        detail.append(faces, el('p', '', `Selected: ${selected.visible_face} → ${selected.color_group} | Orientation: ${selected.orientation_id}`));
        detail.append(el('p', '', 'Top face is unobserved. Allowed orientations are synthetic assumptions.'));
      } else detail.append(el('p', '', `Shade: ${selected.color_group}. Face and orientation are not modeled in this inventory.`));
    }
    box.append(detail);
    let event = cursor === 0 ? 'plan_validated → simulated reservation' : `placement_confirmed → step ${confirmed}`;
    if (state === 'completed') event = `run_completed → ${confirmed} placements`;
    if (state === 'stopped') event = `placement_failed → step ${confirmed + 1} · stopped; reconcile before retry`;
    box.append(el('div', 'event', event));
    return box;
  }
  function render() {
    $('description').textContent = scenario().description;
    $('panels').replaceChildren(...modes.map(renderPanel));
    $('progress').textContent = `Step ${cursor} / ${limit()}`;
    $('play').textContent = timer === null ? 'Play' : 'Pause';
    $('play').disabled = cursor >= limit(); $('step').disabled = cursor >= limit();
  }
  function next() { if (cursor < limit()) cursor++; if (cursor >= limit()) stop(); render(); }
  function reset() { stop(); cursor = 0; render(); }
  $('play').onclick = () => {
    if (timer !== null) stop();
    else if (cursor < limit()) timer = setInterval(next, Number($('speed').value));
    render();
  };
  $('step').onclick = () => { stop(); next(); };
  $('reset').onclick = reset;
  for (const id of ['scenario', 'policy', 'failure']) $(id).onchange = reset;
  $('ghosts').onchange = render;
  $('speed').onchange = () => { if (timer !== null) { stop(); timer = setInterval(next, Number($('speed').value)); } render(); };
  document.addEventListener('visibilitychange', () => { if (document.hidden) { stop(); render(); } });
  render();
})();
