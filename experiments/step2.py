import cv2
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "experiments/out"

img = cv2.imread(str(ROOT / "samples/screen1.jpg"))
img = cv2.resize(img, None, fx=0.5, fy=0.5)          # 절반 크기로

gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)         # 흑백으로
cv2.imwrite(str(OUT / "2_gray.jpg"), gray)

for t in (90, 100, 110, 120, 130, 140):                              # 기준값 세 개를 한 번에 비교
    _, mask = cv2.threshold(gray, t, 255, cv2.THRESH_BINARY_INV)
    cv2.imwrite(str(OUT / f"2_dark_{t}.png"), mask)