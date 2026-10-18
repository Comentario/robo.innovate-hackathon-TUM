(async () => {
 const out = document.createElement('pre'); out.id='browser-smoke'; document.body.append(out);
 const check=(yes, message)=>{if(!yes)throw new Error(message);};
 const select=(id,value)=>{const e=document.getElementById(id);e.value=value;e.dispatchEvent(new Event('change'));};
 const count=()=>document.querySelectorAll('[data-placed="true"]').length;
 try {
  check(document.querySelectorAll('.panel').length===2,'two mode panels');
  check(document.getElementById('scenario').value==='3','face scenario defaults');
  document.getElementById('step').click(); check(count()===2,'one placement per mode');
  document.getElementById('reset').click();check(count()===0,'reset clears placement');
  select('failure','5');for(let i=0;i<5;i++)document.getElementById('step').click();
  check(count()===8,'failure confirms exactly four per mode');
  check(document.querySelectorAll('[data-status="stopped"]').length===2,'both stop');
  check(document.getElementById('step').disabled,'no steps after failure');
  select('scenario','4');check(document.querySelectorAll('[data-status="rejected"]').length===2,'locked faces rejected');
  select('policy','redistribute');select('failure','none');
  for(let i=0;i<12;i++)document.getElementById('step').click();
  check(count()===24,'redistributed plan completes');
  check(document.querySelectorAll('[data-status="completed"]').length===2,'completed status');
  select('scenario','3');select('policy','reject');
  document.getElementById('ghosts').click();check(document.querySelectorAll('.ghost').length===0,'hide target pattern');
  document.getElementById('ghosts').click();
  select('speed','400');
  document.getElementById('play').click();
  await new Promise(resolve=>setTimeout(resolve, 550));
  check(count() >= 2,'play advances placements on a timer');
  document.getElementById('play').click();
  check(document.getElementById('play').textContent==='Play','pause stops playback');
  out.textContent='PASS: playback, controls, face constraints, failure stop, redistribution, reset and target visibility';
  out.dataset.result='passed';
 } catch(e){out.textContent='FAIL: '+e.message;out.dataset.result='failed';}
})();
