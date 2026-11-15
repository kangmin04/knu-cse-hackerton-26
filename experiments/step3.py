import cv2
import numpy as np
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "experiments/out"

img = cv2.imread(str(ROOT / "samples/screen1.jpg"))
b, g, r = [c.astype(np.int16) for c in cv2.split(img)]

rb = np.clip(r - b + 128, 0, 255).astype(np.uint8)     # 붉은 정도 (빨강 - 파랑)
bg = cv2.medianBlur(rb, 49)                            # 주변 배경의 붉은 정도
diff = rb.astype(np.int16) - bg.astype(np.int16)       # 주변보다 얼마나 붉은가

for t in (8, 9, 10, 11, 12):
    mask = (diff > t).astype(np.uint8) * 255
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((2, 2), np.uint8))   # 잡티 제거
    cv2.imwrite(str(OUT / f"3_red_{t}.png"), mask)

    # 투명 배경 + 빨간 글씨
    h, w = mask.shape
    rgba = np.zeros((h, w, 4), np.uint8)
    rgba[..., 2] = 220          # R
    rgba[..., 0] = rgba[..., 1] = 40
    rgba[..., 3] = mask         # 필기 부분만 불투명
    cv2.imwrite(str(OUT / f"3_ink_{t}.png"), rgba)