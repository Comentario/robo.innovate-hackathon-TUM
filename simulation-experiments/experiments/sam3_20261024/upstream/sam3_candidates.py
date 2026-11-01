"""A1 image-only SAM 3 adapter and deterministic mask mechanics (no labels)."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
from importlib.metadata import distribution
import json
from pathlib import Path
import time

import cv2
import numpy as np

SOURCE_REVISION = '660a5e9e1b8b4c02c0ad97229b88a09a6e4ff5b7'
CONFIDENCE = 0.5
DEDUP_IOU = 0.80


def file_hash(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def checked_mask(mask, size):
    mask = np.asarray(mask)
    if mask.dtype != np.bool_ or mask.shape != (size[1], size[0]):
        raise ValueError('mask must be binary and original-resolution')
    return mask


def interior_point(mask):
    """Largest 8-connected component, precise L2 maximum, row-major ties."""
    if mask.ndim != 2 or mask.dtype != np.bool_ or not mask.any():
        raise ValueError('empty or invalid mask')
    count, labels, stats, _ = cv2.connectedComponentsWithStats(mask.astype(np.uint8), connectivity=8)
    component = min(range(1, count), key=lambda i: (
        -int(stats[i, cv2.CC_STAT_AREA]), int(stats[i, cv2.CC_STAT_TOP]),
        int(stats[i, cv2.CC_STAT_LEFT])))
    padded = np.pad((labels == component).astype(np.uint8), 1)
    distance = cv2.distanceTransform(padded, cv2.DIST_L2, cv2.DIST_MASK_PRECISE)
    v, u = np.unravel_index(distance.argmax(), distance.shape)
    point = [int(u - 1), int(v - 1)]
    assert mask[point[1], point[0]]
    return point, float(distance[v, u])


@dataclass(frozen=True)
class Candidate:
    id: str
    mask: np.ndarray
    bbox_xyxy: tuple
    interior_pixel: tuple
    clearance_px: float
    score: float
    mask_hash: str
    sources: tuple

    def metadata(self):
        return {name: getattr(self, name) for name in (
            'id', 'bbox_xyxy', 'interior_pixel', 'clearance_px', 'score',
            'mask_hash', 'sources')}


def candidates_from_raw(raw, size):
    """Greedy score-ranked IoU suppression; never union or repair masks."""
    ordered = []
    for item in raw:
        mask = checked_mask(item['mask'], size)
        score = float(item['score'])
        if not np.isfinite(score) or not 0 <= score <= 1:
            raise ValueError('invalid candidate score')
        if not mask.any() or score <= CONFIDENCE:
            continue
        digest = hashlib.sha256(mask.tobytes()).hexdigest()
        ordered.append(dict(item, mask_hash=digest, sources=[{
            'concept': item['concept'], 'raw_id': item['raw_id']}]))
    ordered.sort(key=lambda c: (-c['score'], c['concept'], c['mask_hash'], c['raw_id']))
    kept = []
    for item in ordered:
        duplicate = None
        for other in kept:
            intersection = np.count_nonzero(item['mask'] & other['mask'])
            union = np.count_nonzero(item['mask'] | other['mask'])
            if intersection / union >= DEDUP_IOU:
                duplicate = other
                break
        if duplicate is None:
            v, u = np.nonzero(item['mask'])
            item['bbox'] = (int(u.min()), int(v.min()), int(u.max()), int(v.max()))
            kept.append(item)
        else:
            duplicate['sources'].extend(item['sources'])
    kept.sort(key=lambda c: (*c['bbox'], c['mask_hash']))
    result = []
    for i, item in enumerate(kept, 1):
        point, clearance = interior_point(item['mask'])
        mask = item['mask'].copy()
        mask.setflags(write=False)
        result.append(Candidate(f'o{i:03d}', mask, item['bbox'], tuple(point),
                                clearance, float(item['score']), item['mask_hash'],
                                tuple(sorted(item['sources'], key=lambda s: (s['concept'], s['raw_id'])))))
    return tuple(result)


def annotate(rgb, candidates, max_side=1024, selected=None):
    """Draw on the resized RGB, keeping contours thin and IDs readable."""
    h, w = rgb.shape[:2]
    scale = min(1, max_side / max(h, w))
    size = (round(w * scale), round(h * scale))
    canvas = cv2.resize(rgb, size, interpolation=cv2.INTER_AREA) if scale < 1 else rgb.copy()
    occupied = []
    for i, c in enumerate(candidates):
        if selected is not None and c.id != selected:
            continue
        color = tuple(int(x) for x in cv2.cvtColor(
            np.uint8([[[i * 47 % 180, 210, 255]]]), cv2.COLOR_HSV2RGB)[0, 0])
        small = cv2.resize(c.mask.astype(np.uint8), size, interpolation=cv2.INTER_NEAREST)
        contours, _ = cv2.findContours(small, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
        cv2.drawContours(canvas, contours, -1, color, 1, cv2.LINE_AA)
        u, v = [round(p * scale) for p in c.interior_pixel]
        # Offset colliding labels without moving or changing any masks.
        label_w, label_h = cv2.getTextSize(c.id, cv2.FONT_HERSHEY_SIMPLEX, .45, 1)[0]
        x = max(0, min(u, size[0] - label_w - 4))
        y = max(label_h + 4, min(v, size[1] - 2))
        for offset in range(0, size[1], label_h + 6):
            trial = (y + offset - label_h - 4) % max(1, size[1] - label_h - 4) + label_h + 4
            rect = (x, trial - label_h - 3, x + label_w + 3, trial + 2)
            if all(rect[2] < r[0] or r[2] < rect[0] or rect[3] < r[1] or r[3] < rect[1] for r in occupied):
                y = trial
                break
        occupied.append((x, y - label_h - 3, x + label_w + 3, y + 2))
        cv2.line(canvas, (u, v), (x, y), color, 1, cv2.LINE_AA)
        cv2.rectangle(canvas, (x, y - label_h - 3), (x + label_w + 3, y + 2), (0, 0, 0), -1)
        cv2.putText(canvas, c.id, (x + 1, y), cv2.FONT_HERSHEY_SIMPLEX, .45, color, 1, cv2.LINE_AA)
        if selected is not None:
            cv2.drawMarker(canvas, (u, v), (255, 255, 255), cv2.MARKER_CROSS, 13, 2)
    return canvas


class Sam3Candidates:
    def __init__(self, checkpoint, model_revision):
        import torch
        from sam3.model_builder import build_sam3_image_model
        from sam3.model.sam3_image_processor import Sam3Processor

        checkpoint = Path(checkpoint)
        if not checkpoint.is_file():
            raise ValueError('local SAM checkpoint is missing')
        if not torch.cuda.is_available() or not torch.cuda.is_bf16_supported():
            raise RuntimeError('CUDA with BF16 is required; no CPU fallback')
        direct = json.loads(distribution('sam3').read_text('direct_url.json') or '{}')
        if direct.get('vcs_info', {}).get('commit_id') != SOURCE_REVISION:
            raise ValueError('SAM installation does not match the pinned source revision')
        torch.cuda.reset_peak_memory_stats()
        started = time.monotonic()
        self.model = build_sam3_image_model(
            checkpoint_path=str(checkpoint), load_from_HF=False, device='cuda',
            eval_mode=True, enable_inst_interactivity=False, compile=False)
        self.processor = Sam3Processor(self.model, resolution=1008, device='cuda',
                                       confidence_threshold=CONFIDENCE)
        torch.cuda.synchronize()
        self.provenance = {
            'source_revision': SOURCE_REVISION, 'model_repository': 'facebook/sam3',
            'model_revision': model_revision, 'checkpoint_sha256': file_hash(checkpoint),
            'checkpoint_name': checkpoint.name, 'gpu': torch.cuda.get_device_name(),
            'gpu_total_bytes': torch.cuda.get_device_properties(0).total_memory,
            'torch': torch.__version__, 'cuda': torch.version.cuda, 'precision': 'CUDA BF16 autocast',
            'resolution': 1008, 'confidence_threshold': CONFIDENCE, 'dedup_iou': DEDUP_IOU,
            'compile': False, 'interactive': False, 'model_load_seconds': time.monotonic() - started,
            **self.memory()}

    @staticmethod
    def memory():
        import torch
        return {'peak_allocated_bytes': torch.cuda.max_memory_allocated(),
                'peak_reserved_bytes': torch.cuda.max_memory_reserved()}

    def segment(self, rgb, concepts, folder):
        """Write each query's raw output immediately, including empty masks."""
        import torch
        from PIL import Image
        from b0 import write_json

        folder.mkdir(exist_ok=True)
        raw, manifest, timings = [], [], []
        torch.cuda.reset_peak_memory_stats()
        torch.cuda.synchronize()
        started = time.monotonic()
        with torch.inference_mode(), torch.autocast('cuda', dtype=torch.bfloat16):
            state = self.processor.set_image(Image.fromarray(rgb).convert('RGB'))
            torch.cuda.synchronize()
            encoder_seconds = time.monotonic() - started
            for query_index, concept in enumerate(concepts):
                self.processor.reset_all_prompts(state)
                query_start = time.monotonic()
                output = self.processor.set_text_prompt(state=state, prompt=concept)
                masks = output['masks'].detach().cpu().numpy()[:, 0].astype(bool)
                boxes = output['boxes'].detach().float().cpu().numpy()
                scores = output['scores'].detach().float().cpu().numpy()
                torch.cuda.synchronize()
                timings.append({'concept': concept, 'seconds': time.monotonic() - query_start})
                for index, (mask, box, score) in enumerate(zip(masks, boxes, scores, strict=True)):
                    raw_id = f'q{query_index:02d}_{index:03d}'
                    path = folder / f'{raw_id}.png'
                    if not cv2.imwrite(str(path), mask.astype(np.uint8) * 255):
                        raise OSError('mask artifact write failed')
                    record = {'raw_id': raw_id, 'concept': concept, 'score': float(score),
                              'sam_bbox_xyxy': box.tolist(), 'mask': path.name}
                    manifest.append(record)
                    raw.append(dict(record, mask=mask))
                write_json(folder / 'raw.json', {'candidates': manifest, 'queries': timings,
                           'encoder_seconds': encoder_seconds, **self.memory()})
                # reset drops full-resolution logits before the next query
                self.processor.reset_all_prompts(state)
            del state
        return raw, {'segmentation_seconds': time.monotonic() - started,
                     'encoder_seconds': encoder_seconds, 'queries': timings, **self.memory()}
