import cv2
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent   # comkerton 폴더

img = cv2.imread(str(ROOT / "samples/screen1.jpg"))
print(img.shape)
cv2.imwrite(str(ROOT / "experiments/out/1_copy.jpg"), img)
