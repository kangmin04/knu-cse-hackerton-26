import cv2
import numpy as np
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "experiments/out"

WEAK = 18      # 이 값보다 어두우면 "필기 후보"
STRONG = 45    # 이 값보다 어두운 점이 하나라도 있어야 "진짜 필기"
AREA = 101     # 주변 배경을 보는 범위 (홀수)

img = cv2.imread(str(ROOT / "samples/screen2.jpg"))
img = img[560:1370, 80:1070]                                   # 화면 부분만 (세로, 가로)
img = cv2.resize(img, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)   # 2배 확대

gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
gray = cv2.bilateralFilter(gray, 7, 30, 5)                     # 선은 살리고 잡티만 줄이기
bg = cv2.medianBlur(gray, AREA)                                # 주변 배경의 밝기
diff = bg.astype(np.int16) - gray.astype(np.int16)             # 주변보다 얼마나 어두운가

# 약한 선이라도 진한 선과 이어져 있으면 살린다
weak = (diff > WEAK).astype(np.uint8)
strong = diff > STRONG
count, labels = cv2.connectedComponents(weak, connectivity=8)
keep = np.zeros(count, bool)
keep[np.unique(labels[strong])] = True
keep[0] = False
ink = keep[labels]

# 가장자리를 부드럽게 (0~1 사이 값)
alpha = np.clip((diff - 15) / 30.0, 0, 1) * ink

cv2.imwrite(str(OUT / "5_preview.png"), (255 - alpha * 255).astype(np.uint8))   # 흰 배경 미리보기

h, w = alpha.shape
rgba = np.zeros((h, w, 4), np.uint8)                           # 검은 글씨
rgba[..., 3] = (alpha * 255).astype(np.uint8)                  # 필기 부분만 불투명
cv2.imwrite(str(OUT / "5_ink.png"), rgba)                      # 투명 배경
