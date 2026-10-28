"""Check imported Unreal snapshot transforms against source matrices and A/B invariants."""
import argparse
import base64
import hashlib
import json
import struct
from pathlib import Path


def apply(matrix, point):
    return [sum(matrix[row + column * 4] * point[column] for column in range(4)) for row in range(4)]


def verify(manifest_path, evidence_path, compare_path=None):
    manifest = json.loads(manifest_path.read_text())
    asset_path = manifest_path.parent / manifest["geometry"]
    raw = asset_path.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == manifest["geometrySha256"]
    geometry, evidence = json.loads(raw), json.loads(evidence_path.read_text())
    assert manifest["snapshotOnly"] and geometry["snapshotOnly"] and evidence["snapshotOnly"]
    assert not manifest["nativeSimulationPorted"] and not evidence["nativeSimulationPorted"]
    assert evidence["referenceSha256"] == manifest["referenceSha256"] == geometry["referenceSha256"]
    assert evidence["geometrySha256"] == manifest["geometrySha256"]
    assert evidence["snapshotTime"] == manifest["snapshotTime"]
    expected_count = len(geometry["instances"]) + sum(b["count"] for b in geometry["instanceBatches"])
    assert evidence["meshInstances"] == expected_count
    camera = next(c for c in manifest["cameras"] if c["view"] == evidence["camera"])
    assert all(abs(x) < 1e7 for x in camera["unrealPositionCm"])
    maximum = 0
    decoded = {}
    seen = set()
    for sample in evidence["matrixSamples"]:
        batch_index, instance_index = sample["batch"], sample["instance"]
        batch = geometry["instanceBatches"][batch_index]
        if batch_index not in decoded:
            decoded[batch_index] = base64.b64decode(batch["matrices"], validate=True)
        matrix = struct.unpack_from("<16f", decoded[batch_index], instance_index * 64)
        for point, actual in zip([(0, 0, 0, 1), (1, 0, 0, 1), (0, 1, 0, 1), (0, 0, 1, 1)], sample["unrealBasisPointsCm"]):
            world = apply(batch["parentMatrix"], apply(matrix, point))
            expected = [world[i] * 100 for i in (0, 2, 1)]
            maximum = max(maximum, max(abs(a - b) for a, b in zip(expected, actual)))
        seen.add(batch_index)
    assert len(seen) == len(geometry["instanceBatches"]), "Missing packed-batch samples"
    assert maximum < 0.02, f"Import transform differs by {maximum} cm"
    if compare_path:
        compare = json.loads(compare_path.read_text())
        for key in ["meshInstances", "snapshotTime", "camera", "cameraPosition", "geometrySha256", "referenceSha256", "matrixSamples"]:
            assert compare[key] == evidence[key], f"A/B changed {key}"
        assert {compare["lightingVariant"], evidence["lightingVariant"]} == {"baseline", "candidate"}
    return {"importTransformsVerified": True, "snapshotOnly": True, "nativeSimulationPorted": False,
            "meshInstances": expected_count, "packedBatchesChecked": len(seen), "basisSamples": len(evidence["matrixSamples"]),
            "maximumBasisErrorCm": maximum, "abInvariantsVerified": compare_path is not None,
            "referenceSha256": manifest["referenceSha256"], "validationStatus": "unvalidated"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--compare", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = verify(args.manifest, args.evidence, args.compare)
    text = json.dumps(result, indent=2)
    if args.output:
        args.output.write_text(text + "\n")
    print(text)


if __name__ == "__main__":
    main()
