"""Manually registered, image-space 2x4 face evidence with layer hypotheses.

This module never imports detector outputs, labels, simulation state or shade
classes. Its supplied observed window is not a reconstruction of the original
360-brick stack. Nominal intrinsics only support an approximate lower-plane
counter-hypothesis; no robot-frame pose is returned.
"""

import math

import cv2
import numpy as np


def project(points, homography):
    """Project N planar points through a homography, retaining pixel units."""
    return cv2.perspectiveTransform(np.asarray(points, np.float32)[None], homography)[0]


class Evidence:
    """Scale-relative circular-gradient and edge evidence on a rectified plane."""

    def __init__(self, gray, config):
        self.gray = gray.astype(np.float32)
        self.config = config
        self.feature_model = config.get("feature_model", "whole_patch_radial_v0")
        if self.feature_model not in ("whole_patch_radial_v0", "ring_coherence_v1"):
            raise ValueError(f"Unsupported explicit feature model: {self.feature_model}")
        self.pitch = config["pixels_per_stud"]
        smooth = cv2.GaussianBlur(self.gray, (0, 0), 0.7)
        self.gx = cv2.Sobel(smooth, cv2.CV_32F, 1, 0, ksize=3) / 8.0
        self.gy = cv2.Sobel(smooth, cv2.CV_32F, 0, 1, ksize=3) / 8.0
        self.mag = np.hypot(self.gx, self.gy)
        theta = np.arange(32, dtype=np.float32) * (2*np.pi/32)
        self.rays = np.stack((np.cos(theta), np.sin(theta)), axis=1)

    def stud(self, point, search=True):
        """Score a stud cap at a supplied location; return bounded local maximum.

        Score uses radial edge concentration versus local gradient noise and
        angular coverage. Contrast supplies an observability term; blank input
        cannot become positive merely because a layout was supplied.
        """
        x, y = point
        margin = int(math.ceil(self.pitch * .60))
        xi, yi = round(float(x)), round(float(y))
        if xi < margin or yi < margin or xi >= self.gray.shape[1]-margin or yi >= self.gray.shape[0]-margin:
            return dict(expected_xy=[float(x), float(y)], refined_xy=[float(x), float(y)], score=0., observability=0., boundary=True)
        patch = self.gray[yi-margin:yi+margin+1, xi-margin:xi+margin+1]
        contrast = float(np.percentile(patch, 90)-np.percentile(patch, 10))
        observable = float(np.clip(contrast/self.config["contrast_range_for_observability"], 0, 1))
        # The mean of this patch is dominated by adjacent brick seams/shadows.
        # A median estimates quiet local gradient noise without that bias.
        gradients = self.mag[yi-margin:yi+margin+1, xi-margin:xi+margin+1]
        noise = float(gradients.mean() if self.feature_model == "whole_patch_radial_v0" else np.median(gradients))
        radius = round(self.pitch*self.config["stud_search_fraction"]) if search else 0
        shifts = np.asarray([(dx,dy) for dy in range(-radius,radius+1) for dx in range(-radius,radius+1)], np.float32)
        centers = shifts + np.array([x,y],np.float32)
        best = (-1., np.array([x,y]), 0.)
        for fraction in self.config["stud_radius_fractions"]:
            samples = centers[:,None,:] + self.pitch*fraction*self.rays[None,:,:]
            mx, my = samples[:,:,0].astype(np.float32), samples[:,:,1].astype(np.float32)
            gx = cv2.remap(self.gx,mx,my,cv2.INTER_LINEAR,borderMode=cv2.BORDER_CONSTANT)
            gy = cv2.remap(self.gy,mx,my,cv2.INTER_LINEAR,borderMode=cv2.BORDER_CONSTANT)
            radial = np.abs(gx*self.rays[None,:,0] + gy*self.rays[None,:,1])
            if self.feature_model == "whole_patch_radial_v0":
                concentration = np.clip((radial.mean(axis=1)/(noise+2.0)-1.0)/1.2,0,1)
                coverage = (radial > max(noise*.5,2.)).mean(axis=1)
            else:
                magnitude = np.hypot(gx,gy)
                coherence = radial.sum(axis=1)/(magnitude.sum(axis=1)+1e-6)
                # Isotropic directions have E[abs(cos(theta))] = 2/pi.
                isotropic_null = 2/np.pi
                concentration = np.clip((coherence-isotropic_null)/(1-isotropic_null),0,1)
                # A fixed half-gray-level floor excludes very weak gradients.
                coverage = (radial > max(noise,.5)).mean(axis=1)
            scores = concentration * coverage * math.sqrt(observable)
            index = int(np.argmax(scores))
            if float(scores[index]) > best[0]:
                best = (float(scores[index]), centers[index], fraction)
        return dict(expected_xy=[float(x),float(y)], refined_xy=[float(v) for v in best[1]],
                    score=best[0], observability=observable, radius_fraction=best[2], boundary=False)

    def edges(self, polygon):
        """Weak independent boundary evidence; do not require same-color seams."""
        points = np.asarray(polygon,np.float32)
        center = points.mean(axis=0)
        margin = self.pitch*.20
        x0,y0 = np.floor(points.min(axis=0)-margin).astype(int)
        x1,y1 = np.ceil(points.max(axis=0)+margin).astype(int)
        x0,y0=max(0,x0),max(0,y0)
        x1,y1=min(self.mag.shape[1],x1),min(self.mag.shape[0],y1)
        noise = float(self.mag[y0:y1,x0:x1].mean()) if x1>x0 and y1>y0 else 0.
        scores=[]
        for i in range(4):
            a,b=points[i],points[(i+1)%4]
            along=np.linspace(.1,.9,32)[:,None]
            line=a[None]+along*(b-a)[None]
            tangent=b-a
            normal=np.array([-tangent[1],tangent[0]],np.float32)
            normal/=max(float(np.linalg.norm(normal)),1e-6)
            strength=[]
            for offset in (-1.5,0.,1.5):
                samples=line+offset*normal
                mx,my=samples[:,0:1].astype(np.float32),samples[:,1:2].astype(np.float32)
                gx=cv2.remap(self.gx,mx,my,cv2.INTER_LINEAR)
                gy=cv2.remap(self.gy,mx,my,cv2.INTER_LINEAR)
                strength.append(np.abs(gx*normal[0]+gy*normal[1]).ravel())
            value=float(np.max(strength,axis=0).mean())
            scores.append(float(np.clip((value/(noise+2.0)-.5)/1.5,0,1)))
        # Canonical vertical 2x4 faces: sides 1/3 are the long gap-facing edges.
        return float(.1*scores[0]+.4*scores[1]+.1*scores[2]+.4*scores[3]),scores


def nominal_lower_projection(quad, layout, registration, config, canonical_to_image):
    """Fit approximate planar camera and return lower-pattern projection helper.

    A single nominal intrinsic matrix and manual quad do not establish metric
    calibration. This approximation is rejected if it cannot reproduce the
    supplied reference plane closely enough. No hidden stack offsets are used.
    """
    u_extent=(layout["strips"]-1)*layout["strip_pitch_studs"]+2
    v_extent=layout["groups_along_strip"]*4
    pitch=config["stud_pitch_m"]
    objects=np.array([[0,0,0],[u_extent*pitch,0,0],[u_extent*pitch,v_extent*pitch,0],[0,v_extent*pitch,0]],np.float64)
    calibration=registration.get("calibration",{})
    nominal=config["nominal_intrinsics"]
    fx,fy,cx,cy=[float(calibration.get(k,d)) for k,d in zip(("fx","fy","cx","cy"),nominal)]
    intr=np.array([[fx,0,cx],[0,fy,cy],[0,0,1]],np.float64)
    ok,rvec,tvec=cv2.solvePnP(objects,np.asarray(quad,np.float64),intr,None,flags=cv2.SOLVEPNP_IPPE)
    if not ok:
        return None,dict(status="nominal_plane_fit_failed",reprojection_error_px=None)
    fitted,_=cv2.projectPoints(objects,rvec,tvec,intr,None)
    error=float(np.linalg.norm(fitted.reshape(-1,2)-quad,axis=1).mean())
    if not np.isfinite(error) or error > config["maximum_nominal_pose_reprojection_px"]:
        return None,dict(status="nominal_plane_fit_unreliable",reprojection_error_px=error)
    rotation,_=cv2.Rodrigues(rvec)
    # Choose the normal direction that moves points farther from the camera.
    deeper_sign=1. if rotation[2,2]>=0 else -1.
    image_to_canonical=np.linalg.inv(canonical_to_image)

    def lower_points(points_studs, depth_layers):
        xy=np.asarray(points_studs,np.float64)*pitch
        xyz=np.column_stack((xy,np.full(len(xy),deeper_sign*depth_layers*config["brick_height_m"])))
        pixels,_=cv2.projectPoints(xyz,rvec,tvec,intr,None)
        return project(pixels.reshape(-1,2),image_to_canonical)

    return lower_points,dict(status="nominal_not_calibrated",reprojection_error_px=error,
                             relative_lower_depths_m=[config["brick_height_m"],2*config["brick_height_m"]])


def analyze(image, registration, config):
    """Return one evidence-driven decision per supplied observed-window cell."""
    layout=registration.get("supplied_layout",{})
    layout={"strips":6,"groups_along_strip":5,"strip_pitch_studs":4,**layout}
    pitch=config["pixels_per_stud"]
    u_extent=(layout["strips"]-1)*layout["strip_pitch_studs"]+2
    v_extent=layout["groups_along_strip"]*4
    corners=np.array([[0,0],[u_extent*pitch,0],[u_extent*pitch,v_extent*pitch],[0,v_extent*pitch]],np.float32)
    quad=np.asarray(registration["canonical_quad_xy"],np.float32)
    if quad.shape!=(4,2) or not np.isfinite(quad).all():
        raise ValueError("canonical_quad_xy must contain four finite global registration anchors")
    canonical_to_image=cv2.getPerspectiveTransform(corners,quad)
    gray=cv2.cvtColor(image,cv2.COLOR_BGR2GRAY) if image.ndim==3 else image
    # Padding supports stud responses and lower-pattern samples at outer edges.
    pad=round(pitch*.75)
    shift=np.array([[1,0,pad],[0,1,pad],[0,0,1]],np.float64)
    rectified=cv2.warpPerspective(gray,shift@np.linalg.inv(canonical_to_image),
        (round(u_extent*pitch)+2*pad,round(v_extent*pitch)+2*pad),flags=cv2.INTER_LINEAR,borderMode=cv2.BORDER_CONSTANT)
    evidence=Evidence(rectified,config)
    top_grid=[]
    for c in range(layout["strips"]):
        for r in range(layout["groups_along_strip"]):
            top_grid += [[(4*c+u)*pitch+pad,(4*r+v)*pitch+pad] for v in (.5,1.5,2.5,3.5) for u in (.5,1.5)]
    coarse=[evidence.stud(p) for p in top_grid]
    good=[f for f in coarse if f["score"]>=config["stud_confirm_score"]]
    correction=np.zeros(2,np.float32)
    inliers=0
    if len(good)>=config["registration_min_studs"]:
        offsets=np.array([np.array(f["refined_xy"])-f["expected_xy"] for f in good])
        median=np.median(offsets,axis=0)
        mask=np.linalg.norm(offsets-median,axis=1)<=pitch*config["registration_inlier_radius_studs"]
        inliers=int(mask.sum())
        if inliers>=config["registration_min_studs"]:
            proposed=np.median(offsets[mask],axis=0)
            if np.linalg.norm(proposed)<=pitch*config["registration_max_shift_studs"]:
                correction=proposed.astype(np.float32)
    refined_quad=project(corners+correction,canonical_to_image)
    lower_project,plane_info=nominal_lower_projection(refined_quad,layout,registration,config,canonical_to_image)
    candidates=[]
    for c in range(layout["strips"]):
        for r in range(layout["groups_along_strip"]):
            uv=np.array([[4*c,4*r],[4*c+2,4*r],[4*c+2,4*r+4],[4*c,4*r+4]],np.float32)
            poly_canonical=uv*pitch+correction
            top_points=np.array([[(4*c+u)*pitch,(4*r+v)*pitch] for v in (.5,1.5,2.5,3.5) for u in (.5,1.5)],np.float32)+correction
            features=[evidence.stud(p+pad) for p in top_points]
            stud_scores=np.array([f["score"] for f in features])
            confirmed=stud_scores>=config["stud_confirm_score"]
            top_score=float(stud_scores.mean())
            observable=float(np.mean([f["observability"] for f in features]))
            edge,edge_parts=evidence.edges(poly_canonical+pad)
            lower_scores=[]
            if lower_project is not None:
                # Orthogonal 2x4 local counter-pattern, not a reconstructed lower layer.
                lower_uv=[[4*c+u,4*r+v] for v in (1.5,2.5) for u in (-.5,.5,1.5,2.5)]
                for depth in (1,2):
                    lower_canonical=lower_project(lower_uv,depth)
                    lower_scores.append(float(np.mean([evidence.stud(p+pad)["score"] for p in lower_canonical])))
            lower_score=max(lower_scores) if lower_scores else None
            ends=bool(confirmed[:2].any() and confirmed[-2:].any())
            reasons=["manual_global_registration","supplied_observed_window","current_top_height_unverified"]
            if observable<config["minimum_observability"]:
                decision,layer="uncertain","ambiguous"
                reasons.append("insufficient_local_contrast")
            elif (int(confirmed.sum())>=config["present_min_studs"] and ends
                  and top_score>=config["present_min_mean_stud_score"] and edge>=config["present_min_edge_score"]
                  and (lower_score is None or top_score-lower_score>=config["present_top_lower_margin"])):
                decision,layer="present","top_compatible"
                reasons.append("distributed_top_stud_and_edge_evidence")
            elif (int(confirmed.sum())<=config["missing_max_studs"] and lower_score is not None
                  and lower_score>=config["missing_min_lower_score"] and lower_score-top_score>=config["missing_lower_top_margin"]):
                decision,layer="missing","lower_compatible"
                reasons.append("orthogonal_lower_pattern_dominates")
            else:
                decision,layer="uncertain","ambiguous"
                reasons.append("incomplete_or_conflicting_geometric_evidence")
            poly=project(poly_canonical,canonical_to_image)
            long_axis=poly[2:].mean(axis=0)-poly[:2].mean(axis=0)
            orientation=float(math.degrees(math.atan2(long_axis[1],long_axis[0]))%180)
            studs=[]
            for f in features:
                expected=project(np.array([f["expected_xy"]])-pad,canonical_to_image)[0]
                refined=project(np.array([f["refined_xy"]])-pad,canonical_to_image)[0]
                studs.append(dict(expected_xy=expected.tolist(),refined_xy=refined.tolist(),score=f["score"],
                                  confirmed=f["score"]>=config["stud_confirm_score"],observability=f["observability"]))
            candidates.append(dict(id=f"c{c}r{r}",polygon=poly.tolist(),orientation_deg=orientation,
                decision=decision,layer_hypothesis=layer,layer_verified=False,
                scores=dict(top_stud=top_score,confirmed_studs=int(confirmed.sum()),edge=edge,edge_components=edge_parts,
                            lower=lower_score,lower_per_depth=lower_scores,observability=observable,
                            combined=float(.8*top_score+.2*edge)),studs=studs,reason_flags=reasons))
    initial_center=project(corners.mean(axis=0)[None],canonical_to_image)[0]
    refined_center=project((corners.mean(axis=0)+correction)[None],canonical_to_image)[0]
    return dict(schema="known-layout-evidence-v0",file=registration.get("file"),
        feature_model=config.get("feature_model", "whole_patch_radial_v0"),
        registration=dict(initial_quad_xy=quad.tolist(),refined_quad_xy=refined_quad.tolist(),
            correction_px=(refined_center-initial_center).tolist(),correction_rectified_px=correction.tolist(),
            consensus_studs=inliers,registration_score=inliers/max(len(top_grid),1),manual_assisted=True,
            reference="supplied observed-window plane, not a measured baseplate frame",calibration_status="nominal_not_measured",lower_projection=plane_info),
        supplied_layout=layout,candidates=candidates,
        limitations=["image-space visual presence, not robot-frame pose or gripper accessibility",
                     "supplied current plane and nominal intrinsics do not verify absolute layer height",
                     "original 360-brick hidden geometry is not inferred or used"])


def overlay(image, result):
    """Draw decision and evidence without hiding missing/uncertain cells."""
    canvas=image.copy()
    colors={"present":(30,220,30),"missing":(40,40,240),"uncertain":(0,190,255)}
    for candidate in result["candidates"]:
        color=colors[candidate["decision"]]
        poly=np.rint(candidate["polygon"]).astype(np.int32)
        cv2.polylines(canvas,[poly],True,color,2)
        center=np.rint(poly.mean(axis=0)).astype(int)
        label=f"{candidate['id']} {candidate['decision'][0].upper()} s={candidate['scores']['confirmed_studs']}"
        cv2.putText(canvas,label,tuple(center),cv2.FONT_HERSHEY_SIMPLEX,.34,(0,0,0),2)
        cv2.putText(canvas,label,tuple(center),cv2.FONT_HERSHEY_SIMPLEX,.34,color,1)
        for stud in candidate["studs"]:
            cv2.circle(canvas,tuple(np.rint(stud["refined_xy"]).astype(int)),2,(255,0,255) if stud["confirmed"] else (130,130,130),1)
    cv2.putText(canvas,"MANUAL GLOBAL REGISTRATION | nominal calibration | visual presence only",(8,20),cv2.FONT_HERSHEY_SIMPLEX,.52,(0,0,0),3)
    cv2.putText(canvas,"MANUAL GLOBAL REGISTRATION | nominal calibration | visual presence only",(8,20),cv2.FONT_HERSHEY_SIMPLEX,.52,(255,255,255),1)
    return canvas
