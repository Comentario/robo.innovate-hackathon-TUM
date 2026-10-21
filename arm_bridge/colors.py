"""Display existing standard Lab group centers; never classify or cluster bricks."""

def lab_display_colors(centers):
    import cv2
    import numpy as np
    # OpenCV float Lab uses the same standard L*,a*,b* units as the producer export.
    values=np.asarray([list(centers.values())],dtype=np.float32)
    rgb=cv2.cvtColor(values,cv2.COLOR_Lab2RGB)[0]
    return {name:[float(c) for c in color] for name,color in zip(centers,rgb)}
