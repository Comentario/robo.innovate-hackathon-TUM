"""Copy verified editorial reviews into the owner's chosen folder without overwriting differing files."""
import argparse
import base64
import hashlib
import json
import shutil
import subprocess
from pathlib import Path


def digest(path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(8 * 1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def copy_verified(source, destination):
    expected = digest(source)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        if digest(destination) != expected:
            raise FileExistsError(f"Preserving an existing different file: {destination}")
    else:
        shutil.copyfile(source, destination)
    if digest(destination) != expected:
        raise RuntimeError(f"Copied file differs: {destination}")
    return expected


def windows_path(path):
    path = path.resolve()
    if str(path).startswith("/mnt/") and len(path.parts[2]) == 1:
        return path.parts[2].upper() + ":\\" + "\\".join(path.parts[3:])
    return "\\\\wsl.localhost\\Ubuntu-22.04" + str(path).replace("/", "\\")


def copy_with_windows(items, output, resume_generated):
    """Use native CopyFile and SHA-256 to avoid slow round trips through drvfs."""
    output.mkdir(parents=True, exist_ok=True)
    manifest = output / "delivery-sources.json"
    manifest.write_text(json.dumps(items, indent=2) + "\n")
    literal = windows_path(manifest).replace("'", "''")
    resume = "$true" if resume_generated else "$false"
    script = r'''
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$reviewItems = Get-Content -LiteralPath 'MANIFEST' -Raw | ConvertFrom-Json
$reviewResumeGenerated = RESUME
foreach ($reviewItem in $reviewItems) {
  $reviewTarget = [string]$reviewItem.windowsDestination
  $reviewExpected = [string]$reviewItem.sha256
  if ([IO.File]::Exists($reviewTarget)) {
    $reviewActual = (Get-FileHash -LiteralPath $reviewTarget -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($reviewActual -eq $reviewExpected) { continue }
    if (-not $reviewResumeGenerated -or (Get-Item -LiteralPath $reviewTarget).Length -ge $reviewItem.bytes) {
      throw "Preserving a different existing file: $reviewTarget"
    }
  }
  [IO.Directory]::CreateDirectory([IO.Path]::GetDirectoryName($reviewTarget)) | Out-Null
  $reviewTemporary = $null
  $reviewPrefix = [IO.Path]::GetFileName($reviewTarget) + '.review-'
  foreach ($reviewCandidate in (Get-ChildItem -LiteralPath ([IO.Path]::GetDirectoryName($reviewTarget)) -File)) {
    if ($reviewCandidate.Name.StartsWith($reviewPrefix) -and $reviewCandidate.Name.EndsWith('.tmp') -and $reviewCandidate.Length -eq $reviewItem.bytes) {
      $reviewCandidateHash = (Get-FileHash -LiteralPath $reviewCandidate.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
      if ($reviewCandidateHash -eq $reviewExpected) { $reviewTemporary = $reviewCandidate.FullName; break }
    }
  }
  if (-not $reviewTemporary) {
    $reviewTemporary = $reviewTarget + '.review-' + [Guid]::NewGuid().ToString('N') + '.tmp'
    [IO.File]::Copy([string]$reviewItem.windowsSource, $reviewTemporary, $false)
  }
  $reviewActual = (Get-FileHash -LiteralPath $reviewTemporary -Algorithm SHA256).Hash.ToLowerInvariant()
  if ($reviewActual -ne $reviewExpected) { throw "Native copied hash mismatch: $reviewTarget" }
  if ([IO.File]::Exists($reviewTarget)) { Move-Item -LiteralPath $reviewTemporary -Destination $reviewTarget -Force }
  else { [IO.File]::Move($reviewTemporary, $reviewTarget) }
  if ($reviewTarget.EndsWith('.mp4')) { Write-Output ('Copied and verified: ' + $reviewItem.file) }
}
'''.replace("MANIFEST", literal).replace("RESUME", resume)
    encoded = base64.b64encode(script.encode("utf-16le")).decode("ascii")
    result = subprocess.run(["/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe", "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded])
    if result.returncode:
        raise RuntimeError("Native Windows copy failed; inspect the PowerShell error above")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--franka", type=Path, required=True)
    parser.add_argument("--inspection", type=Path, required=True)
    parser.add_argument("--index-template", type=Path, required=True)
    parser.add_argument("--base-render", type=Path, help="Include the currently delivered full-factory MP4 files")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--windows-native", action="store_true", help="Copy and hash natively on Windows")
    parser.add_argument("--resume-generated", action="store_true", help="Repair smaller partial files from an interrupted export to this generated folder")
    args = parser.parse_args()
    choices = json.loads((args.franka / "choices.json").read_text())
    assert len(choices["choices"]) == 6 and choices["newVariants"] == 5 and choices["originalPreserved"]
    reports = []
    pending = []
    def export_file(source, target):
        if args.windows_native:
            checksum = digest(source)
            pending.append({"windowsSource": windows_path(source), "windowsDestination": windows_path(target),
                            "file": str(target.relative_to(args.output)), "sha256": checksum, "bytes": source.stat().st_size})
            return checksum
        return copy_verified(source, target)
    # Check all delivered movies against their remote rendering manifests first.
    for choice in choices["choices"]:
        root = args.franka / choice["id"]
        plan = json.loads((root / "edit-plan.json").read_text())
        for item in plan["outputs"]:
            source = root / item["file"]
            assert digest(source) == item["sha256"] and source.stat().st_size == item["bytes"]
    plan = json.loads((args.inspection / "edit-plan.json").read_text())
    assert plan["cameraFeedsShown"] == 1 and not plan["simulationClockModified"]
    for item in plan["outputs"]:
        source = args.inspection / item["file"]
        assert digest(source) == item["sha256"] and source.stat().st_size == item["bytes"]
    for source_root, folder in [(args.franka, "Franka_Variants"), (args.inspection, "Inspection_Overlay_v1")]:
        for source in sorted(source_root.rglob("*")):
            if not source.is_file() or source.suffix.lower() not in {".mp4", ".jpg", ".html", ".json"}:
                continue
            if "baseline-layout-check" in source.parts or source.name == "compare-six-1080p.mp4":
                continue
            target = args.output / folder / source.relative_to(source_root)
            checksum = export_file(source, target)
            reports.append({"file": str(target.relative_to(args.output)), "bytes": source.stat().st_size, "sha256": checksum})
    if args.base_render:
        for name in ["brickflow-continuous-4k.mp4", "brickflow-continuous-1080p.mp4", "edit-plan.json", "verification.json", "packet-verification.json", "insert-points.json"]:
            source = args.base_render / name
            target = args.output / "Base_Render_Current" / name
            checksum = export_file(source, target)
            reports.append({"file": str(target.relative_to(args.output)), "bytes": source.stat().st_size, "sha256": checksum})
    export_file(args.index_template, args.output / "Review_Index.html")
    if args.windows_native:
        copy_with_windows(pending, args.output, args.resume_generated)
    report = {"schema": "brickflow.editorial-review-delivery.v1", "output": str(args.output), "frankaChoices": 6,
              "newFrankaVariants": 5, "inspectionFeeds": 1, "originalV1Preserved": True, "allCopiedHashesMatched": True, "files": reports}
    (args.output / "delivery-manifest.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({key: value for key, value in report.items() if key != "files"}, indent=2))


if __name__ == "__main__":
    main()
