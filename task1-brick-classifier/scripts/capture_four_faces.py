"""Take one photo of each of the 4 long faces of every brick (base data for YOLO).

Keys in the preview window:
  space  take the photo of the current face (4 per brick)
  g / b  after the 4th photo: label of the brick (good / bad), then next brick
  q      quit

Output: <output>/<session>/brick_NN/face_1.jpg ... face_4.jpg and labels.csv
Usage: capture_four_faces.py [--output Brick_Faces_Dataset] [--camera 0]
"""

import argparse
import csv
import sys
import time
from pathlib import Path

import cv2

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.capture_bricks import HEIGHT, WIDTH, open_camera, read_frame

DEFAULT_OUTPUT = PROJECT_ROOT / "Brick_Faces_Dataset"
FACES = 4


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--camera", type=int, default=0)
    args = parser.parse_args()

    session = args.output / time.strftime("%Y%m%d_%H%M%S")
    session.mkdir(parents=True, exist_ok=True)
    capture = open_camera(args.camera)
    brick, face = 1, 1
    print(f"saving to {session}")
    try:
        while True:
            frame = read_frame(capture)
            text = (f"brick {brick}: label?  g = good, b = bad" if face > FACES
                    else f"brick {brick}  face {face}/{FACES}: space = photo")
            image = cv2.resize(frame, (WIDTH // 2, HEIGHT // 2))
            cv2.putText(image, text, (12, 32), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (255, 255, 255), 5, cv2.LINE_AA)
            cv2.putText(image, text, (12, 32), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 0, 0), 2, cv2.LINE_AA)
            cv2.imshow("four faces", image)
            key = cv2.waitKey(1) & 0xFF
            if key == ord("q"):
                break
            if key == ord(" ") and face <= FACES:
                folder = session / f"brick_{brick:02d}"
                folder.mkdir(exist_ok=True)
                cv2.imwrite(str(folder / f"face_{face}.jpg"), frame)
                print(f"saved brick_{brick:02d}/face_{face}.jpg")
                face += 1
            elif key in (ord("g"), ord("b")) and face > FACES:
                label = "good" if key == ord("g") else "bad"
                with (session / "labels.csv").open("a", newline="", encoding="utf-8") as handle:
                    csv.writer(handle).writerow([f"brick_{brick:02d}", label])
                print(f"brick_{brick:02d}: {label}")
                brick, face = brick + 1, 1
    finally:
        capture.release()
        cv2.destroyAllWindows()
        for _ in range(5):
            cv2.waitKey(1)
    print(f"done: {brick - 1} bricks in {session}")


if __name__ == "__main__":
    main()
