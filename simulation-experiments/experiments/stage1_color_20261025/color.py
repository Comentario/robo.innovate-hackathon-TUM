"""Local reference-based LEGO color evidence; no detector rerun or routing truth."""
import cv2
import numpy as np


def _lab(rgb_bgr):
    image=np.asarray(rgb_bgr)
    if image.ndim!=3 or image.shape[2]!=3:raise ValueError('Expected HxWx3 BGR image')
    if image.dtype==np.uint8:scaled=image.astype(np.float32)/255.
    elif np.issubdtype(image.dtype,np.floating) and np.isfinite(image).all() and image.min()>=0 and image.max()<=1:scaled=image.astype(np.float32,copy=True)
    else:raise ValueError('BGR pixels must be uint8 or finite floating point in [0,1]')
    return cv2.cvtColor(scaled,cv2.COLOR_BGR2LAB)


def _color_valid(lab,settings):
    low,high=settings['lightness_range']
    return np.isfinite(lab).all(axis=-1)&(lab[...,0]>=low)&(lab[...,0]<=high)&(np.linalg.norm(lab[...,1:],axis=-1)>=settings['minimum_chroma'])


def build_prototypes(rgb_bgr,patches,settings):
    """Human-labelled reference rectangles only; bounds are upper-exclusive."""
    lab=_lab(rgb_bgr);height,width=lab.shape[:2];labels={}
    for patch in patches:
        label=patch['label'];box=patch['pixel_xyxy']
        if not isinstance(label,str) or not label or label in labels:raise ValueError('Reference labels must be unique nonempty strings')
        if len(box)!=4 or any(int(v)!=v for v in box):raise ValueError('Reference pixel_xyxy must contain four integer coordinates')
        x0,y0,x1,y1=map(int,box)
        if not(0<=x0<x1<=width and 0<=y0<y1<=height):raise ValueError('Reference rectangle outside image')
        crop=lab[y0:y1,x0:x1];valid=_color_valid(crop,settings);count=int(valid.sum());total=int(valid.size)
        enough=count>=settings['prototype_minimum_pixels']
        labels[label]={'median_lab':np.median(crop[valid],axis=0).astype(float).tolist() if enough else None,
            'interior_pixels':total,'valid_pixels':count,'valid_fraction':float(count/total),
            'valid':bool(enough),'reasons':[] if enough else ['insufficient_prototype_pixels']}
    return {'space':'OpenCV_float_BGR_to_Lab','labels':labels,'ready':bool(len(labels)>=2 and all(row['valid'] for row in labels.values()))}


def classify(rgb_bgr,depth,cal,candidate,frame_id,prototypes,settings):
    """Score a supported interior color region and abstain on weak evidence."""
    evidence={'interior_pixels':0,'valid_pixels':0,'valid_fraction':0.,'nearest_label':None,
        'distances':{},'margin':None,'pixel_agreement':None,'median_lab':None}
    result={'frame_id':frame_id,'candidate_id':candidate.get('candidate_id'),
        'source_decision':candidate.get('decision'),'label':None,'decision':'unknown',
        'reasons':[],'evidence':evidence,'region_polygon':[]}
    if candidate.get('decision')!='present':result['reasons']=['candidate_not_present'];return result
    if not frame_id or not candidate.get('candidate_id'):result['reasons']=['missing_frame_or_candidate_id'];return result
    lab=_lab(rgb_bgr);depth=np.asarray(depth)
    if depth.shape!=lab.shape[:2]:raise ValueError('Depth and RGB shapes differ')
    polygon=np.asarray(candidate['image_polygon'],np.float64)
    if polygon.ndim!=2 or polygon.shape[1]!=2 or len(polygon)<3 or not np.isfinite(polygon).all():result['reasons']=['invalid_region_polygon'];return result
    moments=cv2.moments(polygon.astype(np.float32))
    if abs(moments['m00'])<1e-12:result['reasons']=['degenerate_region_polygon'];return result
    center=np.array([moments['m10']/moments['m00'],moments['m01']/moments['m00']])
    region=center+settings['interior_scale']*(polygon-center);result['region_polygon']=region.tolist()
    mask=np.zeros(depth.shape,np.uint8);cv2.fillPoly(mask,[np.rint(region).astype(np.int32)],1);interior=mask.astype(bool)
    total=int(interior.sum());evidence['interior_pixels']=total
    finite=interior&np.isfinite(depth)&(depth>0);rows,columns=np.nonzero(finite)
    K,R,t=np.asarray(cal['K'],float),np.asarray(cal['R'],float),np.asarray(cal['t'],float)
    if K.shape!=(3,3) or R.shape!=(3,3) or t.shape!=(3,) or not all(np.isfinite(v).all() for v in (K,R,t)) or K[0,0]<=0 or K[1,1]<=0:raise ValueError('Invalid configured optical calibration')
    rays=np.column_stack(((columns-K[0,2])/K[0,0],(rows-K[1,2])/K[1,1],np.ones(len(rows))))
    world=(depth[rows,columns,None]*rays-t)@R
    surface=float(candidate['estimated_body_top_from_selected_band_m']);lo,hi=settings['depth_height_offsets_m']
    supported=np.isfinite(world).all(axis=1)&(world[:,2]>=surface+lo)&(world[:,2]<=surface+hi)
    valid=np.zeros(depth.shape,bool);valid[rows[supported],columns[supported]]=True;valid&=_color_valid(lab,settings)
    count=int(valid.sum());fraction=float(count/total) if total else 0.;evidence.update(valid_pixels=count,valid_fraction=fraction)
    if count<settings['minimum_valid_pixels']:result['reasons'].append('insufficient_valid_pixels')
    if fraction<settings['minimum_valid_fraction']:result['reasons'].append('insufficient_valid_fraction')
    reference=prototypes.get('labels',{})
    if not prototypes.get('ready') or len(reference)<2 or any(row.get('median_lab') is None for row in reference.values()):result['reasons'].append('prototypes_unavailable');return result
    if count==0:return result
    labels=sorted(reference);medians=np.asarray([reference[label]['median_lab'] for label in labels],float)
    if medians.shape!=(len(labels),3) or not np.isfinite(medians).all():raise ValueError('Invalid reference medians')
    values=lab[valid];median=np.median(values,axis=0);distances=np.linalg.norm(medians-median,axis=1);order=np.argsort(distances,kind='stable');best=int(order[0]);margin=float(distances[order[1]]-distances[best])
    assignment=np.argmin(np.linalg.norm(values[:,None,:]-medians[None,:,:],axis=2),axis=1);agreement=float(np.mean(assignment==best))
    evidence.update(nearest_label=labels[best],distances={label:float(d) for label,d in zip(labels,distances)},margin=margin,pixel_agreement=agreement,median_lab=median.astype(float).tolist())
    if distances[best]>settings['maximum_delta_e']:result['reasons'].append('outside_reference_distance')
    if margin<settings['minimum_runner_up_gap']:result['reasons'].append('ambiguous_reference_margin')
    if agreement<settings['minimum_pixel_agreement']:result['reasons'].append('mixed_or_inconsistent_pixels')
    if not result['reasons']:result.update(label=labels[best],decision='known')
    return result
