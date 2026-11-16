"""사진에서 밝은 화면(프로젝터 스크린/슬라이드) 사각형을 찾아 정면으로 펴는 원근 보정.

못 찾으면 None을 돌려준다 (칠판이 사진을 꽉 채워 테두리가 안 보이는 경우 등).
실행: python perspective.py 사진.jpg  →  out/persp_<이름>.jpg (보정본), out/persp_<이름>_debug.jpg (찾은 사각형)
"""
import sys
from pathlib import Path

import cv2
import numpy as np


def find_quad(img):
    """가장 큰 밝은 영역의 네 꼭짓점(좌상, 우상, 우하, 좌하)을 찾는다."""
    small_scale = 800 / max(img.shape[:2])                       # 계산은 작은 사진으로
    small = cv2.resize(img, None, fx=small_scale, fy=small_scale)
    gray = cv2.GaussianBlur(cv2.cvtColor(small, cv2.COLOR_BGR2GRAY), (5, 5), 0)
    _, mask = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((15, 15), np.uint8))   # 글씨 구멍 메우기
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return None
    hull = cv2.convexHull(max(contours, key=cv2.contourArea))   # 앞사람 머리에 가려진 부분은 볼록 껍질로 메움
    area = cv2.contourArea(hull) / (small.shape[0] * small.shape[1])
    if not 0.15 < area < 0.95:                                  # 너무 작거나 사진 전체면 화면이 아님
        return None
    # 진짜 화면은 바깥보다 확실히 밝다. 칠판 위 조명 반사는 차이가 작아서 여기서 걸러짐
    # (샘플 기준: 화면 87~113, 칠판 반사 37)
    inside = np.zeros_like(gray)
    cv2.drawContours(inside, [hull], -1, 255, -1)
    if gray[inside > 0].mean() - gray[inside == 0].mean() < 60:
        return None
    for eps in np.linspace(0.01, 0.1, 19):                     # 꼭짓점이 4개가 될 때까지 단순화
        approx = cv2.approxPolyDP(hull, eps * cv2.arcLength(hull, True), True)
        if len(approx) == 4:
            return order(approx.reshape(4, 2) / small_scale)
    return None


def order(pts):
    s, d = pts.sum(1), np.diff(pts, axis=1).ravel()
    return np.array([pts[s.argmin()], pts[d.argmin()], pts[s.argmax()], pts[d.argmax()]], np.float32)


def warp(img, quad):
    tl, tr, br, bl = quad
    w = int(max(np.linalg.norm(tr - tl), np.linalg.norm(br - bl)))
    h = int(max(np.linalg.norm(bl - tl), np.linalg.norm(br - tr)))
    dst = np.array([[0, 0], [w - 1, 0], [w - 1, h - 1], [0, h - 1]], np.float32)
    return cv2.warpPerspective(img, cv2.getPerspectiveTransform(quad, dst), (w, h))


def correct(img):
    """보정본을 돌려준다. 화면을 못 찾으면 None."""
    quad = find_quad(img)
    return None if quad is None else warp(img, quad)


if __name__ == "__main__":
    src = Path(sys.argv[1])
    out = Path(__file__).resolve().parent / "out"
    out.mkdir(exist_ok=True)
    img = cv2.imread(str(src))
    quad = find_quad(img)
    if quad is None:
        sys.exit(f"{src.name}: 화면 사각형을 못 찾음")
    cv2.imwrite(str(out / f"persp_{src.stem}.jpg"), warp(img, quad))
    cv2.polylines(img, [quad.astype(int)], True, (0, 0, 255), 8)
    cv2.imwrite(str(out / f"persp_{src.stem}_debug.jpg"), img)
    print(f"{src.name}: 저장 → out/persp_{src.stem}.jpg")
