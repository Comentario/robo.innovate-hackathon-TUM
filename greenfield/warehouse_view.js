/* Scene-native warehouse equipment; dimensions are model settings, not a vendor CAD model. */
'use strict';
window.FactoryWarehouseView=({T,box,rod,beam,support,rollerBed,equipment,label,M,staticRoot,dynamicRoot})=>{
 const colours=[M.green,M.wood,M.orange,M.red],names=['Mixed','Warm','Copper','Russet'];
 function paint(x,z,l,w,colour){box(x,.008,z,l,.012,w,colour)}
 function stand(x,z,stops=true){for(const dz of [-.34,0,.34])box(x,.082,z+dz,1.22,.164,.08,M.steel);if(stops)for(const sign of [-1,1])box(x-.68,.14,z+sign*.5,.075,.28,.075,M.yellow)}
 function sign(text,x,z,colour){const canvas=document.createElement('canvas');canvas.width=512;canvas.height=128;const c=canvas.getContext('2d');c.fillStyle='#102831';c.fillRect(0,0,512,128);c.fillStyle=colour.color.getStyle();c.fillRect(0,0,512,10);c.fillRect(18,42,8,52);c.fillStyle='#edf5f5';c.font='600 34px Segoe UI';c.fillText(text,38,80);const mesh=new T.Mesh(new T.PlaneGeometry(2.6,.65),new T.MeshBasicMaterial({map:new T.CanvasTexture(canvas),side:T.DoubleSide}));mesh.position.set(x,2.35,z);staticRoot.add(mesh);support(x-1.2,z,2.7,.065);box(x,2.7,z,2.6,.12,.08,M.steel)}
 function build(){

  for(let category=0;category<4;category++){
   const x=66+category*6;for(const side of [-1,1])paint(x+side*.92,0,.06,28.2,colours[category]);for(let i=0;i<9;i++){const z=-12+i*3;paint(x,z,1.50,1.30,colours[category]);stand(x,z,false);for(const side of [-1,1]){paint(x,z+side*.66,1.55,.035,M.steel);paint(x+side*.77,z,.035,1.35,M.steel)}}
   for(const z of [-13.5,-4.5,4.5,13.5])support(x-.85,z,2.65,.08);box(x-.85,2.6,0,.08,.12,27.2,M.green);sign(names[category]+' PALLETS',x,-15.1,colours[category]);
   for(const side of [-1,1])paint(x+2.7+side*.95,0,.045,32,M.blue);
   equipment(names[category]+' · warehouse bay','structure','warehouse_bay',[x,.8,0],[2.0,2.0,28.0],'Nine finite pallet locations, assigned by product ID. The yellow overhead bridge deposits directly into a reserved location. Once the bridge clears, autonomous stackers collect pallets for matching truck orders.',[['Product',names[category]],['Capacity','9 complete pallets'],['Location control','Reserved / occupied / picked'],['Handling','Omnidirectional autonomous pallet stackers']]);
  }
  for(const side of [-1,1])paint(80,-17.5+side*.85,39,.04,M.blue);
  for(let i=0;i<4;i++){const x=65+i*5;for(const sign of [-1,1]){paint(x,-21+sign*.85,3.4,.035,M.yellow);paint(x+sign*1.7,-21,.035,1.7,M.yellow)}box(x+.7,.55,-22,.3,1.1,.22,M.dark);ledLocal(x+.7,1.08,-22);}
  for(let category=0;category<4;category++){
   const x=92+category*8,z=32,access=x+5;
   for(const side of [-1,1])paint(access+side*1.35,z,.04,14,M.blue);
   for(let k=0;k<8;k++){const zz=z+(k-3.5)*1.35;paint(x+2.2,zz,.10,.65,colours[category]);}
   sign(names[category]+' ORDERS',x,23,colours[category]);
   equipment(names[category]+' · ground-level side loading','actuator','autonomous_stacker',[x+2.4,.8,z],[3.7,2.0,12.0],'The AMR stays on the ground. Its forks lift the pallet above the trailer deck, a proposed 0.80 m reach attachment places it at the reserved centre position, and the forks withdraw before lowering. The loading side is open; each longitudinal position is accessed directly.',[['Order','8 complete pallets of one product'],['Trailer deck','0.80 m'],['Pallet deposit','0.86 m wood datum'],['Fork lift','0.20 m/s · configured'],['Reach attachment','0.80 m · custom proposed design'],['Interlock','Truck parked + slot reserved + forks withdrawn'],['Rating','Reach-load capacity requires supplier validation']]);
  }
  equipment('Autonomous pallet transport fleet','transport','autonomous_stacker',[77,1.3,-21],[22,2.8,2.4],'Four autonomous pallet stackers collect completed pallets directly from classified stock and deliver them to matching customer orders. Tasks reserve pickup, lift, withdrawal, travel and return together.',[['Forks','0.80 m proposed reach attachment at side loading'],['Fleet','4 vehicles'],['Demo travel speed','1.2 m/s'],['Motion','Sideways / reverse / straight; fixed load orientation'],['Load assumption','560 × 2.2 kg + 30 kg pallet = 1,262 kg']]);
  label('05  CLASSIFIED WAREHOUSE',[75,3.1,0]);label('06  DIRECT SIDE LOADING',[104,3.1,32]);
 }
 function ledLocal(x,y,z,parent=staticRoot){box(x,y,z,.06,.03,.06,M.led,parent)}
 function amr(){const g=new T.Group();dynamicRoot.add(g);box(.1,.49,0,1.35,.54,1.08,M.dark,g);box(.25,.82,0,1.05,.18,1.14,M.green,g);box(.62,.95,0,.2,.18,.3,M.dark,g);box(.65,1.07,0,.22,.06,.32,M.blue,g);box(-.58,.30,0,.42,.17,1.15,M.steel,g);
  for(const [x,z]of [[-.25,-.49],[-.25,.49],[.50,0]]){rod(x,.16,z,.16,.18,M.dark,'z',g);rod(x,.16,z,.075,.184,M.steel,'z',g);box(x,.25,z,.22,.08,.24,M.steel,g)}
  // Low outriggers and load wheels support the pallet in front of the drive body.
  box(-.65,.19,0,.14,.12,1.38,M.steel,g);for(const z of [-.64,.64]){box(-1.25,.18,z,1.30,.12,.10,M.steel,g);rod(-1.85,.10,z,.10,.08,M.dark,'z',g);rod(-1.85,.10,z,.045,.084,M.steel,'z',g)}
  for(const z of [-.43,.43])box(-.72,1.30,z,.10,2.53,.11,M.steel,g);box(-.72,2.54,0,.14,.08,.98,M.green,g);for(const z of [-.30,.30])box(-.73,1.35,z,.02,2.30,.025,M.dark,g);
  box(-.65,.43,0,.16,.12,.26,M.dark,g);ledLocal(-.65,.52,0,g);box(.15,.92,-.53,.12,.06,.12,M.red,g);return g;
 }
 function fork(){const g=new T.Group();dynamicRoot.add(g);g.userData.reachSleeves=[];g.userData.reachPosts=[];for(const z of [-.30,.30]){box(1.20,.18,z,1.0,.05,.06,M.steel,g);const sleeve=box(1.20,.18,z,1.0,.10,.12,M.dark,g),post=box(.65,.4,z,.12,.6,.055,M.steel,g);g.userData.reachSleeves.push(sleeve);g.userData.reachPosts.push(post)}box(.65,.12,0,.10,.22,.88,M.steel,g);for(const z of [-.20,.20]){box(0,-.01,z,1.2,.07,.125,M.steel,g);box(.60,.13,z,.07,.30,.125,M.steel,g)}return g}
 function frame(){const g=new T.Group();dynamicRoot.add(g);box(0,.17,0,1.48,.15,1.14,M.yellow,g);box(0,.30,0,.35,.15,.35,M.dark,g);for(const x of [-.70,.70])for(const z of [-.52,.52])box(x,-.40,z,.08,1.15,.08,M.yellow,g);box(.70,-.97,0,.10,.08,1.12,M.steel,g);for(const z of [-.20,.20])box(.075,-.97,z,1.25,.07,.125,M.steel,g);for(const z of [-.52,.52])box(0,-.12,z,1.45,.12,.08,M.yellow,g);return g}
 function truck(){const g=new T.Group();dynamicRoot.add(g);box(0,.62,0,11.2,.20,2.5,M.dark,g);box(0,.76,0,11.2,.08,2.5,M.steel,g);
  box(0,.92,-1.23,11.3,.12,.06,M.steel,g);box(0,.60,1.23,11.3,.12,.06,M.steel,g);
  box(-7.1,1.25,0,2.7,2.1,2.40,M.green,g);box(-7.75,1.80,0,1.3,.60,2.43,M.blue,g);box(-8.5,.85,0,.12,.24,2.50,M.dark,g);box(-7.1,2.4,0,2.75,.18,2.45,M.green,g);
  for(const x of [-7.0,-4.725,2.025,3.375])for(const z of [-1.05,1.05]){rod(x,.35,z,.35,.22,M.dark,'z',g);rod(x,.35,z,.17,.23,M.steel,'z',g)}return g;
 }

 return{build,amr,fork,frame,truck};
};
