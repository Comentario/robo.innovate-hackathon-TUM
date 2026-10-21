'use strict';
const data=JSON.parse(document.getElementById('review-data').textContent);
const $=id=>document.getElementById(id);
const NS='http://www.w3.org/2000/svg';
const colors={planned:'#5de2b1',available:'#79b9f3',excluded:'#f39685'};
const reasons={below_score_threshold:'Below the chosen score threshold',unknown_color:'Color is unknown',ineligible_geometry:'Partial, merged or ineligible geometry'};
let scenario=data.scenarios.find(s=>s.threshold===data.default_threshold),selected=null;
const bricks=new Map(data.bricks.map(b=>[b.id,b]));
function el(tag,text,className){const node=document.createElement(tag);if(text!==undefined)node.textContent=text;if(className)node.className=className;return node;}
function svg(tag,attrs={}){const node=document.createElementNS(NS,tag);for(const [k,v] of Object.entries(attrs))node.setAttribute(k,v);return node;}
function placements(){return scenario.plan?scenario.plan.placements:[];}
function placement(id){return placements().find(p=>p.brick_id===id);}
function state(id){return placement(id)?'planned':scenario.accepted_ids.includes(id)?'available':'excluded';}
function stateLabel(id){return {planned:'Planned',available:'Accepted, not selected',excluded:'Excluded'}[state(id)];}
function target(p){return p?`L${p.layer+1} · R${p.row+1} · C${p.column+1}`:'—';}
function selectBrick(id,focus=false){selected=id;render();if(focus)document.querySelector(`[data-brick="${CSS.escape(id)}"]`)?.focus({preventScroll:true});}
for(const s of data.scenarios){const option=el('option',s.threshold.toFixed(2));option.value=s.threshold;$('threshold').append(option);}
$('threshold').value=scenario.threshold;
$('threshold').addEventListener('change',()=>{scenario=data.scenarios.find(s=>s.threshold===Number($('threshold').value));render();});
$('filter').addEventListener('change',render);
$('next').addEventListener('click',()=>{const list=placements();if(!list.length)return;const i=list.findIndex(p=>p.brick_id===selected);selectBrick(list[(i+1)%list.length].brick_id);});
$('recipe').textContent='Provisional recipe: '+Object.entries(data.config.target_ratios).map(([g,n])=>`${g}: ${n}`).join(' / ');
$('attribution').textContent=data.attribution;
$('provenance').textContent=`Image: ${data.image_id}. Inventory SHA-256: ${data.inventory_sha256}. Image SHA-256: ${data.image_sha256}.`;
function render(){
  if(!selected)selected=placements()[0]?.brick_id||data.bricks[0].id;
  const list=placements();
  $('metrics').replaceChildren(...[[data.bricks.length,'Detected in source'],[scenario.accepted_ids.length,'Accepted by filter'],[scenario.excluded.length,'Excluded by filter'],[`${list.length}/${data.config.rows*data.config.columns*data.config.layers}`,'Planned positions']].map(([n,label])=>{const node=el('div',undefined,'metric');node.append(el('strong',String(n)),el('span',label));return node;}));
  const source=$('source');source.replaceChildren();source.setAttribute('viewBox',`0 0 ${data.image_size_px.width} ${data.image_size_px.height}`);
  source.append(svg('image',{href:SOURCE_IMAGE,width:data.image_size_px.width,height:data.image_size_px.height}));
  for(const b of data.bricks){
    const status=state(b.id),box=b.bbox_px,dim=$('filter').value!=='all'&&$('filter').value!==status&&b.id!==selected;
    const group=svg('g',{opacity:dim?0.12:1});
    const rect=svg('rect',{x:box.x,y:box.y,width:box.width,height:box.height,fill:b.id===selected?'#ffffff22':'transparent',stroke:b.id===selected?'white':colors[status],'stroke-width':b.id===selected?4:2,'stroke-dasharray':status==='excluded'?'5 3':'none',tabindex:dim?-1:0,role:'button','aria-label':`${b.id}, ${stateLabel(b.id)}, score ${b.color_score}`,'data-brick':b.id});
    rect.append(svg('title'));rect.firstChild.textContent=`${b.id} · ${b.color_group} · ${b.color_score.toFixed(3)} · ${stateLabel(b.id)}`;
    rect.addEventListener('click',()=>selectBrick(b.id));
    rect.addEventListener('keydown',event=>{if(event.key==='Enter'||event.key===' '){event.preventDefault();selectBrick(b.id,true);}});
    const text=svg('text',{x:box.x+3,y:box.y+13});text.textContent=b.id.replace('brick_','');group.append(rect,text);source.append(group);
  }
  const status=$('plan-status');status.className=scenario.plan?'ok':'blocked';
  status.textContent=scenario.plan?`Complete plan · ${list.length} unique IDs · No movement dispatched`:`Plan blocked: ${scenario.error}. No previous plan is retained.`;
  $('next').disabled=!list.length;
  $('layers').replaceChildren();
  if(scenario.plan){
    for(let layer=0;layer<data.config.layers;layer++){
      const section=el('section');section.append(el('h3',`LAYER ${layer+1} · ${layer===0?'Bottom':'Upper'}`));
      const slots=el('div',undefined,'slots');slots.style.gridTemplateColumns=`repeat(${data.config.columns},minmax(0,1fr))`;
      for(const p of list.filter(p=>p.layer===layer).sort((a,b)=>a.row-b.row||a.column-b.column)){
        const button=el('button',undefined,'slot'+(p.brick_id===selected?' selected':''));button.type='button';button.dataset.target=p.brick_id;
        button.append(el('small',`#${p.step} · Row ${p.row+1}, Col ${p.column+1}`),el('strong',p.brick_id),el('small',p.color_group));
        button.addEventListener('click',()=>selectBrick(p.brick_id));slots.append(button);
      }section.append(slots);$('layers').append(section);
    }
  }
  $('groups').replaceChildren();
  const centers=data.color_estimation.group_centers_lab;
  centers.forEach((lab,index)=>{
    const name=centers.length===1?'uniform':`color_group_${index+1}`;
    const accepted=scenario.accepted_ids.filter(id=>bricks.get(id).color_group===name).length;
    const planned=list.filter(p=>p.color_group===name).length;
    $('groups').append(el('div',`${name} · Lab [${lab.join(', ')}] · accepted ${accepted} · planned ${planned}`, 'group-row'));
  });
  const b=bricks.get(selected),p=placement(selected),box=b.bbox_px;
  const crop=$('crop');crop.replaceChildren();crop.setAttribute('viewBox',`${box.x} ${box.y} ${box.width} ${box.height}`);crop.append(svg('image',{href:SOURCE_IMAGE,width:data.image_size_px.width,height:data.image_size_px.height}));
  const details=$('details');details.replaceChildren(el('h3',b.id));
  const exclusion=scenario.excluded.find(row=>row.id===b.id);
  const why=exclusion?exclusion.reasons.map(reason=>reasons[reason]||reason).join('; '):p?'Passed filter and selected by the mixing planner':'Passed filter; not needed for this 12-position pallet';
  $('selection-summary').textContent=`${b.id} · ${stateLabel(b.id)} · ${p?'Target '+target(p):why}`;
  const dl=el('dl');
  for(const [label,value] of [['Decision',stateLabel(b.id)],['Reason',why],['Relative group',b.color_group],['Heuristic score',`${b.color_score.toFixed(3)} · chosen minimum ${scenario.threshold.toFixed(2)}`],['Target',target(p)],['Source box',`x ${box.x}, y ${box.y}, width ${box.width}, height ${box.height} px`],['Observed face','Identity unavailable; no other faces inferred']])dl.append(el('dt',label),el('dd',value));
  details.append(dl);
  const scroll=$('inventory').closest('.table-wrap').scrollTop;
  $('inventory').replaceChildren();
  for(const row of data.bricks){
    const tr=el('tr',undefined,row.id===selected?'selected':'');tr.dataset.inventoryId=row.id;
    const first=el('td'),button=el('button',row.id);button.type='button';button.addEventListener('click',()=>selectBrick(row.id));first.append(button);tr.append(first);
    for(const value of [row.color_group,row.color_score.toFixed(3),stateLabel(row.id),target(placement(row.id))])tr.append(el('td',value));
    $('inventory').append(tr);
  }
  $('inventory').closest('.table-wrap').scrollTop=scroll;
}
render();
