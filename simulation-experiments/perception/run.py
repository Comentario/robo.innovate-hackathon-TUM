"""Evidence-only batch entry point. Use an authorized frozen Pueue snapshot."""

import argparse
import hashlib
import json
import os
from pathlib import Path

import cv2

from .algorithm import analyze, overlay


def main():
    if os.environ.get("ROBO_PUEUE_JOB") != "1":
        raise SystemExit("Batch perception must run from a frozen default-queue Pueue job")
    parser=argparse.ArgumentParser()
    parser.add_argument("--images",type=Path,required=True)
    parser.add_argument("--registrations",type=Path,required=True)
    parser.add_argument("--config",type=Path,required=True)
    parser.add_argument("--output",type=Path,required=True)
    args=parser.parse_args()
    cv2.setNumThreads(2)
    registrations=json.loads(args.registrations.read_text())
    config=json.loads(args.config.read_text())
    args.output.mkdir(parents=True,exist_ok=True)
    (args.output/"overlays").mkdir(exist_ok=True)
    summary=[]
    for registration in registrations["images"]:
        file=registration["file"]
        image=cv2.imread(str(args.images/file))
        if image is None:
            raise ValueError(f"Cannot read {file}")
        result=analyze(image,registration,config)
        (args.output/f"{Path(file).stem}.json").write_text(json.dumps(result,indent=2))
        cv2.imwrite(str(args.output/"overlays"/f"{Path(file).stem}.png"),overlay(image,result))
        counts={key:sum(c["decision"]==key for c in result["candidates"]) for key in ("present","missing","uncertain")}
        summary.append({"file":file,**counts})
        print("PERCEPTION",file,counts,flush=True)
    manifest={"config":config,"config_sha256":hashlib.sha256(args.config.read_bytes()).hexdigest(),
              "registration_sha256":hashlib.sha256(args.registrations.read_bytes()).hexdigest(),
              "opencv":cv2.__version__,"summary":summary}
    (args.output/"run_complete.json").write_text(json.dumps(manifest,indent=2))


if __name__=="__main__":
    main()
