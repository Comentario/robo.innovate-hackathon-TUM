'use strict';
const data=JSON.parse(document.getElementById('review-data').textContent);
const $=id=>document.getElementById(id);
const NS='http://www.w3.org/2000/svg';
const colors={planned:'#5de2b1',available:'#79b9f3',excluded:'#f39685'};
const reasons={below_score_threshold:'Below the chosen score threshold',unknown_color:'Color is unknown',ineligible_geometry:'Partial, merged or ineligible geometry'};
let scenario=data.scenarios.find(s=>s.threshold===data.default_threshold),selected=null;
let hiddenPredictions=new URLSearchParams(location.search).get('review')==='1';
let predictionsSeen=!hiddenPredictions;
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
  document.body.classList.toggle('review-mode',hiddenPredictions);
  $('page-title').textContent=hiddenPredictions?'Review groups against the source image':'From detected brick to planned position';
  $('intro').textContent=hiddenPredictions?'Record your visual judgment without model classes or scores on screen.':'Inspect the same ID in the source image, filtered inventory and proposed pallet.';
  $('source-help').textContent=hiddenPredictions?'Click a box or use Tab and Enter. Neutral borders identify pieces, not predicted groups.':'Click a box or use Tab and Enter. The photo shows the material; borders show planning status.';
  const list=placements();
  $('metrics').replaceChildren(...[[data.bricks.length,'Detected in source'],[scenario.accepted_ids.length,'Accepted by filter'],[scenario.excluded.length,'Excluded by filter'],[`${list.length}/${data.config.rows*data.config.columns*data.config.layers}`,'Planned positions']].map(([n,label])=>{const node=el('div',undefined,'metric');node.append(el('strong',String(n)),el('span',label));return node;}));
  const source=$('source');source.replaceChildren();source.setAttribute('viewBox',`0 0 ${data.image_size_px.width} ${data.image_size_px.height}`);
  source.append(svg('image',{href:SOURCE_IMAGE,width:data.image_size_px.width,height:data.image_size_px.height}));
  for(const b of data.bricks){
    const status=state(b.id),box=b.bbox_px,dim=!hiddenPredictions&&$('filter').value!=='all'&&$('filter').value!==status&&b.id!==selected;
    const group=svg('g',{opacity:dim?0.12:1});
    const rect=svg('rect',{x:box.x,y:box.y,width:box.width,height:box.height,fill:b.id===selected?'#ffffff22':'transparent',stroke:b.id===selected?'white':hiddenPredictions?'#aabdc7':colors[status],'stroke-width':b.id===selected?4:2,'stroke-dasharray':!hiddenPredictions&&status==='excluded'?'5 3':'none',tabindex:dim?-1:0,role:'button','aria-label':hiddenPredictions?b.id:`${b.id}, ${stateLabel(b.id)}, score ${b.color_score}`,'data-brick':b.id});
    rect.append(svg('title'));rect.firstChild.textContent=hiddenPredictions?b.id:`${b.id} · ${b.color_group} · ${b.color_score.toFixed(3)} · ${stateLabel(b.id)}`;
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
  for(const [label,value] of (hiddenPredictions?[['Source box',`x ${box.x}, y ${box.y}, width ${box.width}, height ${box.height} px`],['Review','Use your written group criteria; no model score is shown']]:[['Decision',stateLabel(b.id)],['Reason',why],['Relative group',b.color_group],['Heuristic score',`${b.color_score.toFixed(3)} · chosen minimum ${scenario.threshold.toFixed(2)}`],['Target',target(p)],['Source box',`x ${box.x}, y ${box.y}, width ${box.width}, height ${box.height} px`],['Observed face','Identity unavailable; no other faces inferred']]))dl.append(el('dt',label),el('dd',value));
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
  renderReference();
}

const labels=data.color_estimation.selected_k===1?['uniform']:data.color_estimation.group_centers_lab.map((_,i)=>`color_group_${i+1}`);
const annotations=new Map();
const definitionInputs=new Map();
const draftKey=`munich-reference:${data.image_sha256}:${data.inventory_sha256}`;
for(const name of labels){
  const field=el('label',name+' visual definition','field'),input=el('input');input.type='text';input.placeholder='Describe what belongs in this group';input.id='definition-'+name;field.append(input);$('group-definitions').append(field);definitionInputs.set(name,input);
  input.addEventListener('input',()=>{saveDraft();renderReference();});
  const option=el('option',name);option.value=name;$('reference-label').append(option);
}
const uncertain=el('option','Uncertain / cannot assess');uncertain.value='uncertain';$('reference-label').append(uncertain);
$('hide-predictions').checked=hiddenPredictions;
$('hide-predictions').addEventListener('change',()=>{hiddenPredictions=$('hide-predictions').checked;if(!hiddenPredictions)predictionsSeen=true;saveDraft();render();});
function referenceValue(){return {schema_version:'person1-reference-review-0.1',image_id:data.image_id,image_sha256:data.image_sha256,inventory_sha256:data.inventory_sha256,reference_kind:'operator_image_review',reviewer:$('reviewer').value,group_definitions:Object.fromEntries([...definitionInputs].map(([key,input])=>[key,input.value])),annotations:[...annotations.values()],predictions_visible_during_session:predictionsSeen};}
function criteriaReady(){return $('reviewer').value.trim()&&[...definitionInputs.values()].every(input=>input.value.trim());}
function renderReference(){
  if(!selected)return;
  const row=annotations.get(selected);
  for(const input of definitionInputs.values())input.readOnly=annotations.size>0;
  $('clear-reference').disabled=annotations.size===0;
  $('reference-piece').textContent='Label: '+selected;
  $('reference-label').value=row?row.reference_group:'';
  $('reference-label').disabled=!criteriaReady();
  $('reference-note').value=row?row.note:'';
  $('reference-note').disabled=!row;
  const judged=[...annotations.values()].filter(a=>a.reference_group!=='uncertain').length;
  $('review-progress').textContent=`${judged} classified · ${annotations.size-judged} uncertain · ${data.bricks.length-annotations.size} not reviewed. No threshold validated.`;
  $('export-reference').disabled=!criteriaReady();
}
function saveDraft(){
  try{localStorage.setItem(draftKey,JSON.stringify(referenceValue()));$('review-message').textContent=criteriaReady()?'Draft saved locally. Export a portable copy.':'Enter reviewer and definitions for every group to enable labeling.';}
  catch(error){$('review-message').textContent='Browser draft storage is unavailable. Export a copy to keep annotations.';}
}
function loadReference(value,fromDraft=false){
  if(!value||value.schema_version!=='person1-reference-review-0.1'||value.reference_kind!=='operator_image_review'||value.image_id!==data.image_id||value.image_sha256!==data.image_sha256||value.inventory_sha256!==data.inventory_sha256)throw Error('Annotations belong to a different image or inventory.');
  if(typeof value.reviewer!=='string'||!value.group_definitions||Object.keys(value.group_definitions).sort().join('|')!==[...labels].sort().join('|')||labels.some(label=>typeof value.group_definitions[label]!=='string')||!Array.isArray(value.annotations))throw Error('Invalid review format.');
  if(value.predictions_visible_during_session!==null&&typeof value.predictions_visible_during_session!=='boolean')throw Error('Invalid prediction exposure metadata.');
  const imported=new Map();
  for(const row of value.annotations){if(!row||!bricks.has(row.id)||imported.has(row.id)||![...labels,'uncertain'].includes(row.reference_group)||(row.note!==undefined&&typeof row.note!=='string'))throw Error('Invalid, duplicated or unknown annotation.');imported.set(row.id,{id:row.id,reference_group:row.reference_group,note:row.note||''});}
  if(!fromDraft&&imported.size&&(!value.reviewer.trim()||labels.some(label=>!value.group_definitions[label].trim())))throw Error('Reviewed labels require explicit reviewer and group definitions.');
  // Validate the whole import before changing the current draft.
  $('reviewer').value=value.reviewer;for(const [key,input] of definitionInputs)input.value=value.group_definitions[key];
  annotations.clear();for(const [id,row] of imported)annotations.set(id,row);
  predictionsSeen=predictionsSeen||value.predictions_visible_during_session===true;
}
$('clear-reference').addEventListener('click',()=>{annotations.clear();saveDraft();renderReference();});
$('reviewer').addEventListener('input',()=>{saveDraft();renderReference();});
$('reference-label').addEventListener('change',()=>{const label=$('reference-label').value;if(label)annotations.set(selected,{id:selected,reference_group:label,note:annotations.get(selected)?.note||''});else annotations.delete(selected);saveDraft();renderReference();});
$('reference-note').addEventListener('input',()=>{const row=annotations.get(selected);if(row)row.note=$('reference-note').value;saveDraft();});
$('next-unreviewed').addEventListener('click',()=>{const start=data.bricks.findIndex(b=>b.id===selected);for(let offset=1;offset<=data.bricks.length;offset++){const id=data.bricks[(start+offset)%data.bricks.length].id;if(!annotations.has(id)){selectBrick(id);return;}}$('review-message').textContent='Every piece has a label or an uncertain mark.';});
$('export-reference').addEventListener('click',()=>{
  if(!criteriaReady())return;
  const url=URL.createObjectURL(new Blob([JSON.stringify(referenceValue(),null,2)],{type:'application/json'}));
  const link=el('a');link.href=url;link.download=`${data.image_id}_reference.json`;document.body.append(link);link.click();link.remove();setTimeout(()=>URL.revokeObjectURL(url),1000);
  $('review-message').textContent='Annotation export requested. Keep the downloaded JSON for evaluation.';
});
$('import-reference-trigger').addEventListener('click',()=>$('import-reference').click());
$('import-reference').addEventListener('change',async()=>{try{const file=$('import-reference').files[0];if(!file)return;loadReference(JSON.parse(await file.text()));saveDraft();renderReference();}catch(error){$('review-message').textContent='Import refused: '+error.message;}finally{$('import-reference').value='';}});
try{const saved=localStorage.getItem(draftKey);if(saved)loadReference(JSON.parse(saved),true);}catch(error){$('review-message').textContent='Saved draft could not be restored. Import a previously exported JSON.';}
if(!$('review-message').textContent)$('review-message').textContent='No reference decisions are inferred. Enter reviewer and group criteria to begin.';
render();
