"""Render manually specified reference polygons; never reads detector outputs.

Strip corners/seam fractions below were placed by visual inspection of original
1280x720 images. Bilinear interpolation is only a drawing convenience for the
individually inspected regular four-stud groups, not an automatic detector.
Uncertain counts/layer assignments are explicitly excluded.
"""
import hashlib,json,math
from pathlib import Path
from PIL import Image,ImageDraw
ROOT=Path(__file__).resolve().parents[3]
HERE=Path(__file__).resolve().parent
SOURCE=ROOT/'resources/realsense_d435i_lego'
# Quads ordered TL,TR,BR,BL. Strips run vertically except 7 and 10.
SPECS={
1:dict(group='A',orientation='vertical',spacing=22.5,notes='Near overhead; cool color cast and left shadow; rightmost strip partly disassembled.', strips=[
 [[378,137],[423,137],[422,585],[377,585]],
 [[469,137],[515,137],[513,586],[468,585]],
 [[558,137],[603,136],[601,586],[556,586]],
 [[647,136],[692,136],[692,586],[647,586]],
 [[738,136],[783,136],[784,586],[739,586]],
 [[829,136],[874,136],[873,588],[828,587]],
],ambiguous={(5,1):'No full long-oriented top face; lower perpendicular surfaces appear in this cell.',(5,3):'No full long-oriented top face; lower perpendicular surfaces appear in this cell.'},lower=[[[516,140],[555,140],[555,180],[516,180]],[[603,229],[645,229],[645,269],[603,269]],[[693,319],[735,319],[735,358],[693,358]],[[784,409],[825,409],[825,447],[784,447]]],studs=[(394,151,'c0r0'),(414,151,'c0r0'),(394,174,'c0r0'),(414,174,'c0r0'),(839,331,'c5r2'),(861,331,'c5r2'),(839,354,'c5r2'),(861,354,'c5r2')]),
3:dict(group='A',orientation='vertical',spacing=20.5,notes='Same visible arrangement as A; rotated view and perspective; darker shadow.',strips=[
 [[375,212],[416,205],[464,606],[423,614]],
 [[456,199],[497,193],[547,596],[505,603]],
 [[533,187],[574,180],[625,584],[584,591]],
 [[614,174],[655,168],[704,576],[664,582]],
 [[695,162],[736,155],[786,565],[745,571]],
 [[778,149],[823,142],[878,566],[834,572]],
],ambiguous={(5,1):'Partially disassembled edge; no complete top face.',(5,3):'Partially disassembled edge; no complete top face.'},lower=[[[418,210],[455,204],[462,239],[424,245]],[[579,254],[616,248],[622,281],[584,287]],[[746,397],[784,391],[789,424],[752,430]]],studs=[(391,222,'c0r0'),(411,219,'c0r0'),(394,242,'c0r0'),(414,239,'c0r0'),(792,160,'c5r0'),(812,157,'c5r0'),(795,181,'c5r0'),(815,178,'c5r0')]),
7:dict(group='B',orientation='horizontal',spacing=21.0,notes='Approximately 90-degree layer orientation change; several exposed edge surfaces and visible deeper studs.',strips=[
 [[554,98],[986,96],[985,140],[552,142]],
 [[552,184],[987,183],[986,225],[551,226]],
 [[550,270],[986,268],[986,310],[549,311]],
 [[549,355],[987,355],[986,398],[548,398]],
 [[547,442],[986,443],[985,485],[546,484]],
 [[544,528],[986,534],[985,577],[543,568]],
],ambiguous={(5,1):'Gap/partial lower surfaces rather than a full horizontal top-layer brick.',(5,3):'Gap/partial lower surfaces rather than a full horizontal top-layer brick.'},lower=[[[540,144],[580,144],[580,179],[539,179]],[[623,144],[662,144],[662,179],[623,179]],[[789,229],[827,229],[827,265],[789,265]],[[872,402],[910,402],[910,438],[872,438]]],studs=[(569,109,'c0r0'),(590,109,'c0r0'),(569,129,'c0r0'),(590,129,'c0r0'),(829,195,'c1r3'),(850,195,'c1r3'),(829,215,'c1r3'),(850,215,'c1r3')]),
10:dict(group='C',orientation='horizontal',spacing=22.0,notes='Horizontal strip arrangement; long same-color runs and lower-layer studs in openings.',strips=[
 [[409,124],[876,122],[877,168],[410,170]],
 [[411,191],[877,190],[877,236],[411,237]],
 [[413,279],[877,280],[878,326],[413,325]],
 [[414,369],[878,369],[879,415],[414,415]],
 [[414,460],[879,460],[880,506],[414,506]],
 [[415,549],[880,550],[881,595],[415,594]],
],ambiguous={(0,2):'Same-color seam poorly resolved in dark top strip; nominal four-stud grouping only.',(0,3):'Same-color seam poorly resolved in dark top strip; nominal four-stud grouping only.'},lower=[[[414,242],[453,242],[453,275],[414,275]],[[582,243],[619,243],[619,276],[582,276]],[[839,242],[875,242],[875,276],[839,276]],[[669,331],[705,331],[705,364],[669,364]]],studs=[(429,383,'c3r0'),(451,383,'c3r0'),(429,405,'c3r0'),(451,405,'c3r0'),(615,383,'c3r2'),(638,383,'c3r2'),(615,405,'c3r2'),(638,405,'c3r2')]),
13:dict(group='D',orientation='vertical',spacing=23.0,notes='Vertical same-color columns, five visible complete 2x4 groups per strip; image does not show a full 6x6 top layer.',strips=[
 [[434,83],[480,83],[482,550],[435,550]],
 [[510,83],[557,82],[565,556],[518,557]],
 [[606,81],[653,80],[654,559],[607,560]],
 [[704,80],[751,79],[750,559],[703,560]],
 [[803,79],[850,78],[846,557],[799,558]],
 [[900,78],[945,77],[942,553],[896,555]],
],ambiguous={(0,0):'Dark same-color seam/side boundary less certain; excluded conservatively.',(0,1):'Dark same-color seam less certain; excluded conservatively.'},lower=[[[560,88],[598,88],[598,130],[560,130]],[[656,156],[695,156],[695,196],[656,196]],[[755,252],[792,252],[792,291],[755,291]],[[852,441],[891,441],[891,480],[852,480]]],studs=[(720,94,'c3r0'),(743,94,'c3r0'),(720,117,'c3r0'),(743,117,'c3r0'),(913,94,'c5r0'),(936,94,'c5r0'),(913,117,'c5r0'),(936,117,'c5r0')]),
16:dict(group='D',orientation='vertical',spacing=22.0,notes='Oblique rotated view of D with strong specular highlight and cast shadow; glare exclusions explicit.',strips=[
 [[553,146],[602,155],[549,594],[502,587]],
 [[630,158],[679,166],[625,603],[579,596]],
 [[721,175],[769,182],[703,615],[657,608]],
 [[809,188],[856,196],[799,625],[752,619]],
 [[888,201],[938,208],[886,637],[841,630]],
 [[965,213],[1014,219],[957,638],[912,632]],
],ambiguous={(4,1):'Specular highlight obscures a same-color seam.',(4,2):'Specular highlight obscures a same-color seam.',(5,1):'Strong specular highlight; individual seam/extent uncertain.',(5,2):'Strong specular highlight; individual seam/extent uncertain.'},lower=[[[600,159],[641,166],[636,204],[595,197]],[[752,258],[791,264],[786,300],[747,293]],[[724,498],[760,504],[755,542],[720,535]],[[880,514],[915,520],[910,556],[875,550]]],studs=[(822,202,'c3r0'),(845,205,'c3r0'),(819,224,'c3r0'),(842,227,'c3r0'),(813,247,'c3r0'),(835,251,'c3r0'),(810,269,'c3r0'),(832,272,'c3r0')]),
}

def lerp(a,b,t):return [round(a[0]+(b[0]-a[0])*t,1),round(a[1]+(b[1]-a[1])*t,1)]

def portion(q,start,end,vertical):
 tl,tr,br,bl=q
 if vertical:return [lerp(tl,bl,start),lerp(tr,br,start),lerp(tr,br,end),lerp(tl,bl,end)]
 return [lerp(tl,tr,start),lerp(tl,tr,end),lerp(bl,br,end),lerp(bl,br,start)]

images=[]
for n,s in SPECS.items():
 instances=[];vertical=s['orientation']=='vertical'
 for c,q in enumerate(s['strips']):
  for r in range(5):
   poly=portion(q,r/5,(r+1)/5,vertical)
   p0,p1=(lerp(poly[0],poly[1],.5),lerp(poly[3],poly[2],.5)) if vertical else (lerp(poly[0],poly[3],.5),lerp(poly[1],poly[2],.5))
   angle=math.degrees(math.atan2(p1[1]-p0[1],p1[0]-p0[0]))%180
   reason=s['ambiguous'].get((c,r));role='ambiguous' if reason else 'exposed_top'
   instances.append(dict(id=f'c{c}r{r}',polygon=poly,orientation_deg=round(angle,2),role=role,ambiguous_reason=reason,orientation_reference_usable=not bool(reason),physical_gripper_accessibility='not_assessed'))
 for i,poly in enumerate(s['lower']):instances.append(dict(id=f'lower_{i}',polygon=poly,orientation_deg=None,role='visible_lower',annotation_extent='visible_fragment_only',physical_gripper_accessibility='not_assessed'))
 # Manual outer footprint, covering visible stack, not loose bricks/background.
 coords=[p for q in s['strips'] for p in q]
 minx=min(p[0] for p in coords)-20;maxx=max(p[0] for p in coords)+5
 miny=min(p[1] for p in coords)-15;maxy=max(p[1] for p in coords)+25
 record=dict(file=f'img_{n}.jpg',width=1280,height=720,correlation_group=s['group'],selection_reason=s['notes'],manual_stud_spacing_px=s['spacing'],annotation_boundary_uncertainty_px=3,stack_roi_polygon=[[minx,miny],[maxx,miny],[maxx,maxy],[minx,maxy]],instances=instances,studs=[dict(x=x,y=y,instance_id=i,uncertainty_px=2) for x,y,i in s['studs']])
 images.append(record)
 out=Image.open(SOURCE/record['file']).convert('RGB');d=ImageDraw.Draw(out)
 colors={'exposed_top':(0,255,80),'visible_lower':(30,150,255),'ambiguous':(255,170,0)}
 for inst in instances:
  pts=[tuple(p) for p in inst['polygon']];color=colors[inst['role']];d.line(pts+[pts[0]],fill=color,width=2)
  x=sum(p[0] for p in pts)/4;y=sum(p[1] for p in pts)/4
  d.text((x-15,y-5),inst['id'],fill=color,stroke_fill='black',stroke_width=1)
 for stud in record['studs']:
  x,y=stud['x'],stud['y'];d.ellipse((x-3,y-3,x+3,y+3),outline=(255,0,255),width=2)
 d.text((8,8),'MANUAL REFERENCE green=exposed visual top | orange=ambiguous/excluded | blue=lower fragment | magenta=stud',fill='white',stroke_width=2,stroke_fill='black')
 out.save(HERE/f'img_{n}_reference.png')
annotation=dict(schema='manual-brick-reference-v1',coordinate_convention='pixels; image x right, y down; polygons TL/TR/BR/BL; undirected long-axis angle modulo 180 degrees',annotator='independent visual inspection before detector overlays',source_geometry_note='User corrected full stack to 10 layers of 6x6=360 bricks and confirmed layers removed between views. References describe visible surfaces, not forced full-layer counts. Five complete brick-length groups per visible strip were visually counted in selected views.',scope='Only individual exposed visual top faces are positive targets. This is not proof of mechanical gripper accessibility or robot-frame pose.',ambiguity_policy='Orange regions excluded from positive scoring and ignored for spurious detections on overlap. Lower-layer regions are a non-exhaustive set of visible fragments; conservative false-target checks only.',correlation_policy='A:img1-6; B:img7-9; C:img10-12; D:img13-18. Repeated views are correlated; no random train/test split or independent-generalization claim.',images=images)
(HERE/'annotations.json').write_text(json.dumps(annotation,indent=2)+'\n')
inventory=[]
for p in sorted(SOURCE.glob('*.jpg'),key=lambda p:int(p.stem.split('_')[-1])):
 n=int(p.stem.split('_')[-1]);im=Image.open(p)
 group='A' if n<=6 else 'B' if n<=9 else 'C' if n<=12 else 'D'
 inventory.append(dict(file=p.name,width=im.width,height=im.height,sha256=hashlib.sha256(p.read_bytes()).hexdigest(),correlation_group=group,reference_selected=n in SPECS,exif=dict(im.getexif()),capture_intrinsics='unavailable',optical_extrinsics='unavailable'))
(HERE/'inventory.json').write_text(json.dumps(inventory,indent=2)+'\n')
summary={im['file']:{r:sum(i['role']==r for i in im['instances']) for r in ['exposed_top','ambiguous','visible_lower']} for im in images}
(HERE/'counts.json').write_text(json.dumps(summary,indent=2)+'\n');print(json.dumps(summary,indent=2))
