import cv2
import numpy as np
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "experiments/out"

img = cv2.imread(str(ROOT / "samples/screen2.jpg"))
img = img[560:1370, 80:1070]                        # 화면 부분만 대충 잘라내기 (세로, 가로)

gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
bg = cv2.medianBlur(gray, 51)                       # 주변 배경의 밝기
diff = bg.astype(np.int16) - gray.astype(np.int16)  # 주변보다 얼마나 어두운가

for t in (25, 35, 50):
    mask = (diff > t).astype(np.uint8) * 255

    h, w = mask.shape
    rgba = np.zeros((h, w, 4), np.uint8)            # 검은 글씨
    rgba[..., 3] = mask                             # 필기 부분만 불투명
    cv2.imwrite(str(OUT / f"4_ink_{t}.png"), rgba)