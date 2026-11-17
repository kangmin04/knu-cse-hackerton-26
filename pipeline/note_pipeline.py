"""수업 사진 한 장에서 필기를 덩어리별 스티커 카드로 뽑아낸다.

순서
  1. OpenCV: 사진에서 프로젝터 화면을 찾아 반듯하게 잘라낸다 (칠판은 크기만 줄임)
  2. OpenCV: 펜 종류에 맞게 필기만 남긴 마스크를 만든다
  3. Gemini: 필기를 의미 단위 덩어리로 나누고, 덩어리마다 위치·제목·글자(LaTeX)를 받는다
  4. OpenCV: Gemini가 준 대략적인 상자를 필기 경계에 맞게 다듬는다
  5. 덩어리마다 원본 조각, 투명 배경 필기 이미지, 결과 json, 확인용 html을 저장한다

실행
  python3 pipeline/note_pipeline.py samples/screen2.jpg --pen black
  python3 pipeline/note_pipeline.py samples/screen1.jpg --pen red
  python3 pipeline/note_pipeline.py samples/board1.jpg --pen board

필요한 것
  pip install -r pipeline/requirements.txt
  저장소 최상위 .env 파일에 GEMINI_API_KEY=발급받은키
"""

import argparse
import html
import json
import os
import re
import sys
import threading
import time
from collections import deque
from pathlib import Path

import cv2
import httpx
import numpy as np
from google import genai
from google.genai import errors, types
from PIL import Image
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parent.parent
MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.5-flash-lite")


# ─────────────────────────────────────────────
# 1. 화면 찾아 잘라내기
# ─────────────────────────────────────────────


def order_corners(pts):
    """네 점을 좌상, 우상, 우하, 좌하 순서로 정렬한다."""
    pts = pts.reshape(4, 2).astype(np.float32)
    s = pts.sum(axis=1)
    d = np.diff(pts, axis=1).ravel()
    return np.float32([pts[s.argmin()], pts[d.argmin()], pts[s.argmax()], pts[d.argmax()]])


def looks_like_screen(quad, img_area):
    """화면다운 사각형인지: 충분히 크고, 가로가 더 길고, 많이 기울지 않음."""
    tl, tr, br, bl = quad
    width = (np.linalg.norm(tr - tl) + np.linalg.norm(br - bl)) / 2
    height = (np.linalg.norm(bl - tl) + np.linalg.norm(br - tr)) / 2
    top_angle = abs(np.degrees(np.arctan2(tr[1] - tl[1], tr[0] - tl[0])))
    return (
        cv2.contourArea(quad) > 0.15 * img_area
        and 1.0 < width / max(height, 1) < 2.4
        and top_angle < 20
    )


def find_screen(img):
    """밝은 큰 사각형(화면)의 네 모서리를 찾는다. 못 찾으면 None."""
    scale = 800 / max(img.shape[:2])
    small = cv2.resize(img, None, fx=scale, fy=scale)
    gray = cv2.GaussianBlur(cv2.cvtColor(small, cv2.COLOR_BGR2GRAY), (5, 5), 0)
    img_area = gray.shape[0] * gray.shape[1]

    otsu, _ = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    top = np.percentile(gray, 97)
    best, best_fill = None, 0
    for t in np.linspace(otsu, (otsu + top) / 2, 4):  # 밝기 기준을 바꿔 가며 시도
        bright = (gray > t).astype(np.uint8) * 255
        bright = cv2.morphologyEx(bright, cv2.MORPH_CLOSE, np.ones((15, 15), np.uint8))
        bright = cv2.morphologyEx(bright, cv2.MORPH_OPEN, np.ones((9, 9), np.uint8))
        contours, _ = cv2.findContours(bright, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if not contours:
            continue
        c = max(contours, key=cv2.contourArea)
        hull = cv2.convexHull(c)
        quad = cv2.approxPolyDP(hull, 0.02 * cv2.arcLength(hull, True), True)
        if len(quad) != 4:
            continue
        quad = order_corners(np.array(quad, np.float32))
        if not looks_like_screen(quad, img_area):
            continue
        fill = cv2.contourArea(c) / cv2.contourArea(quad)  # 사각형을 얼마나 꽉 채우는가
        if fill > best_fill:
            best, best_fill = quad, fill
    return None if best is None else best / scale


def crop_slide(img, pen, max_side=1600):
    """화면을 찾아 펴서 돌려준다. 칠판이거나 못 찾으면 크기만 줄여서 돌려준다."""
    corners = find_screen(img) if pen != "board" else None
    out = img
    if corners is not None:
        tl, tr, br, bl = corners
        w = int(max(np.linalg.norm(tr - tl), np.linalg.norm(br - bl)))
        h = int(max(np.linalg.norm(bl - tl), np.linalg.norm(br - tr)))
        dst = np.float32([[0, 0], [w, 0], [w, h], [0, h]])
        out = cv2.warpPerspective(img, cv2.getPerspectiveTransform(corners, dst), (w, h))
    k = max_side / max(out.shape[:2])
    if k < 1:
        out = cv2.resize(out, None, fx=k, fy=k, interpolation=cv2.INTER_AREA)
    return out, corners


# ─────────────────────────────────────────────
# 2. 필기 마스크
# ─────────────────────────────────────────────


def ink_mask(img, pen):
    """필기 부분만 255인 마스크. 펜마다 '주변 배경과 얼마나 다른가'를 다르게 본다."""
    b, g, r = [c.astype(np.int16) for c in cv2.split(img)]
    if pen == "red":  # 주변보다 붉은 것 (빨강 - 초록)
        rg = np.clip(r - g + 128, 0, 255).astype(np.uint8)
        diff = rg.astype(np.int16) - cv2.medianBlur(rg, 51).astype(np.int16)
        weak, strong = diff > 6, diff > 14
    else:
        gray = cv2.bilateralFilter(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY), 7, 30, 5)
        bg = cv2.medianBlur(gray, 51).astype(np.int16)
        diff = gray.astype(np.int16) - bg if pen == "board" else bg - gray.astype(np.int16)
        weak, strong = diff > 18, diff > 40  # 칠판은 밝은 것, 검은 펜은 어두운 것

    # 약한 선이라도 진한 선과 이어져 있으면 살린다
    count, labels = cv2.connectedComponents(weak.astype(np.uint8), connectivity=8)
    keep = np.zeros(count, bool)
    keep[np.unique(labels[strong])] = True
    keep[0] = False
    return keep[labels].astype(np.uint8) * 255


def remove_long_lines(mask):
    """표 테두리처럼 길게 뻗은 직선을 지운다 (상자를 다듬을 때 멀리 끌려가지 않게)."""
    h, w = mask.shape
    horizontal = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((1, max(1, w // 4)), np.uint8))
    vertical = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((max(1, h // 4), 1), np.uint8))
    lines = cv2.dilate(horizontal | vertical, np.ones((5, 5), np.uint8))
    return cv2.bitwise_and(mask, cv2.bitwise_not(lines))


# ─────────────────────────────────────────────
# 3. Gemini로 덩어리 나누기 + 글자 읽기
# ─────────────────────────────────────────────


class NoteRegion(BaseModel):
    box_2d: list[int] = Field(
        description="덩어리를 감싸는 상자 [ymin, xmin, ymax, xmax]. 이미지를 0~1000으로 본 좌표"
    )
    title: str = Field(description="이 덩어리가 무엇인지 짧게 (예: f'(x) 부호 확인, 로피탈 계산)")
    lines: list[str] = Field(
        description="덩어리 안의 손글씨를 쓰인 순서대로 한 줄씩. 수식 부분만 $...$ 로 감싼 LaTeX"
    )


class NoteRegions(BaseModel):
    regions: list[NoteRegion]


PROMPT = """
이 이미지는 강의 화면(또는 칠판) 사진이야. 손으로 쓴 필기를 '의미 단위 덩어리'로 나눠 줘.

[규칙]
1. 한 덩어리 = 한 가지 내용 (하나의 풀이 과정, 하나의 메모, 하나의 강조 표시 묶음).
   같은 풀이의 여러 줄은 한 덩어리로 묶고, 서로 다른 내용은 나눠.
   →, = 로 시작하는 줄은 바로 위 줄과 같은 풀이이므로 반드시 같은 덩어리에 넣어.
2. 프로젝터 화면이라면 슬라이드에 원래 인쇄된 글자와 수식은 덩어리에 넣지 마.
   인쇄된 글자 위에 친 동그라미·밑줄만 있는 곳은 덩어리로 만들지 마.
3. box_2d는 그 덩어리의 손글씨를 빠짐없이 감싸되 최대한 꼭 맞게.
4. lines에는 쓰여 있는 내용만 옮겨. 해설을 덧붙이지 말고, 읽을 수 없으면 [?].
5. 덩어리는 위에서 아래, 왼쪽에서 오른쪽 순서로.
"""


def load_api_key():
    """저장소 최상위 .env 파일에서 GEMINI_API_KEY를 읽는다."""
    env_file = ROOT / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            if line.startswith("GEMINI_API_KEY="):
                os.environ["GEMINI_API_KEY"] = line.split("=", 1)[1].strip().strip('"')
    if not os.environ.get("GEMINI_API_KEY"):
        sys.exit(f"API 키가 없어요. {env_file} 에 GEMINI_API_KEY=발급받은키 한 줄을 넣어 주세요.")


class GeminiError(RuntimeError):
    """Gemini에 요청했지만 끝내 답을 받지 못함."""


RPM_LIMIT = 12  # 무료 등급 한도는 분당 15회. 여유를 두고 12회까지만 보낸다 (다시 시도 포함)
RETRY_WAITS = (3, 6, 12)  # 다시 시도하기 전에 쉬는 초. 최대 3번 다시 시도
RETRY_CODES = {500, 503, 504}  # 서버 쪽 일시 오류만 다시 시도한다

_calls = deque()  # 최근 60초 동안 보낸 요청 시각
_calls_lock = threading.Lock()  # 서버에서 여러 요청이 동시에 들어와도 한도를 지키도록
_client = None


def get_client():
    """Gemini 연결을 한 번만 만들어 다시 쓴다."""
    global _client
    if _client is None:
        _client = genai.Client(http_options=types.HttpOptions(timeout=40_000))
    return _client


def wait_for_slot():
    """최근 60초 동안 보낸 요청이 RPM_LIMIT개면 자리가 날 때까지 기다린다. 기다린 초를 돌려준다."""
    waited = 0.0
    while True:
        with _calls_lock:
            now = time.time()
            while _calls and now - _calls[0] > 60:
                _calls.popleft()
            if len(_calls) < RPM_LIMIT:
                _calls.append(now)
                return waited
            pause = 60 - (now - _calls[0]) + 0.1
        print(f"  분당 {RPM_LIMIT}회 도달 → {pause:.0f}초 대기", flush=True)
        time.sleep(pause)
        waited += pause


def _fix_escape(match):
    """JSON에서 올바른 이스케이프만 두고, 나머지 역슬래시는 두 개로 바꾼다."""
    s = match.group(0)
    valid = (
        s in ("\\\\", '\\"', "\\/")
        or re.fullmatch(r"\\u[0-9a-fA-F]{4}", s)
        or (len(s) == 2 and s[1] in "bfnrt")
    )
    return s if valid else "\\" + s


def parse_regions(text):
    """Gemini 답(JSON 글자)을 덩어리 목록으로 바꾼다. 끊기거나 깨진 답이면 ValueError.

    모델이 LaTeX 역슬래시를 하나만 보낼 때가 있다. \\lim 은 JSON 오류가 나고,
    \\frac·\\times 는 \\f(폼피드)·\\t(탭)으로 바뀌어 수식이 깨지므로 먼저 고친다.
    """
    if not text:
        raise ValueError("빈 답")
    fixed = re.sub(r'\\(\\|"|/|u[0-9a-fA-F]{4}|[a-zA-Z]+|.)', _fix_escape, text)
    return NoteRegions.model_validate(json.loads(fixed, strict=False)).regions


def ask_regions(img):
    """Gemini에 덩어리를 물어본다.

    돌려주는 값: (덩어리 목록, 정보). 정보는 seconds(성공한 요청의 응답 시간),
    retries(다시 시도한 횟수), waited(한도·다시 시도로 기다린 초)
    다시 시도: 서버 일시 오류(500·503·504), 연결 끊김·시간 초과, 답이 끊기거나 깨짐
    바로 멈춤: 사용 한도 초과(429), 키·모델 이름 문제처럼 다시 해도 안 되는 오류
    끝내 실패하면 GeminiError를 던진다 (프로그램을 끝내지 않아서 서버에서도 쓸 수 있음).
    """
    image = Image.fromarray(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))
    config = types.GenerateContentConfig(
        response_mime_type="application/json", response_schema=NoteRegions, temperature=0.1
    )
    waited = 0.0
    for attempt in range(len(RETRY_WAITS) + 1):
        waited += wait_for_slot()
        start = time.time()
        try:
            response = get_client().models.generate_content(
                model=MODEL, contents=[image, PROMPT], config=config
            )
            regions = parse_regions(response.text)
            info = {"seconds": time.time() - start, "retries": attempt, "waited": waited}
            return regions, info
        except errors.APIError as error:
            if error.code == 429:
                message = "Gemini 사용 한도를 넘었어요(429). 잠시 뒤 다시 시도해 주세요."
                raise GeminiError(message) from error
            if error.code not in RETRY_CODES:
                raise GeminiError(f"Gemini 요청 실패({error.code}): {error.message}") from error
            reason = f"서버 오류 {error.code}"
        except httpx.TransportError:
            reason = "연결 끊김·시간 초과"
        except ValueError:  # JSON 오류와 형식 검사(pydantic) 오류가 모두 ValueError
            reason = "답이 끊기거나 깨짐"
        if attempt == len(RETRY_WAITS):
            break
        pause = RETRY_WAITS[attempt]
        print(
            f"  Gemini 실패: {reason} → {pause}초 뒤 다시 시도 ({attempt + 1}/{len(RETRY_WAITS)})",
            flush=True,
        )
        time.sleep(pause)
        waited += pause
    raise GeminiError(
        f"Gemini에 {len(RETRY_WAITS) + 1}번 요청했지만 실패했어요({reason}). "
        "잠시 뒤 다시 실행해 주세요."
    )


# ─────────────────────────────────────────────
# 4. 상자 다듬기
# ─────────────────────────────────────────────


def to_pixels(box, w, h):
    """Gemini의 0~1000 좌표를 픽셀 (x0, y0, x1, y1)로 바꾼다."""
    ymin, xmin, ymax, xmax = box
    x0, x1 = sorted((int(xmin / 1000 * w), int(xmax / 1000 * w)))
    y0, y1 = sorted((int(ymin / 1000 * h), int(ymax / 1000 * h)))
    return max(0, x0), max(0, y0), min(w, x1), min(h, y1)


def refine_box(mask, box, link=0.006, max_grow=0.3, belong=0.4, pad=6):
    """상자에 걸친 필기 덩어리를 끝까지 포함하도록 넓히고, 빈 테두리는 좁힌다.

    link: 이 거리(사진 가로 대비)보다 가까운 선은 같은 글자로 보고 이어 붙인다
    max_grow: 한쪽으로 원래 크기의 이 비율까지만 넓힌다
    belong: 덩어리의 이 비율 이상이 상자 안에 있을 때만 이 상자의 필기로 본다
    """
    h, w = mask.shape
    x0, y0, x1, y1 = box
    bw, bh = x1 - x0, y1 - y0

    # 출발점: 상자 안 필기에 딱 맞게 좁힌 상자
    ys, xs = np.nonzero(mask[y0:y1, x0:x1])
    if len(xs) == 0:
        return box
    nx0, ny0, nx1, ny1 = x0 + xs.min(), y0 + ys.min(), x0 + xs.max(), y0 + ys.max()

    # 경계에 걸친 덩어리 중 이 상자의 것은 끝까지 포함
    k = max(3, int(w * link))
    linked = cv2.dilate(mask, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, max(3, k // 2))))
    _, labels, stats, _ = cv2.connectedComponentsWithStats(linked, connectivity=8)
    lx0, ly0 = max(0, int(x0 - bw * max_grow)), max(0, int(y0 - bh * max_grow))
    lx1, ly1 = min(w, int(x1 + bw * max_grow)), min(h, int(y1 + bh * max_grow))
    for i in np.unique(labels[y0:y1, x0:x1]):
        if i == 0:
            continue
        cx, cy, cw, ch, area = stats[i]
        if (labels[y0:y1, x0:x1] == i).sum() < belong * area:
            continue
        nx0, ny0 = min(nx0, max(cx, lx0)), min(ny0, max(cy, ly0))
        nx1, ny1 = max(nx1, min(cx + cw, lx1)), max(ny1, min(cy + ch, ly1))

    # 이어 붙이느라 부풀린 만큼 실제 필기 경계로 좁힌다
    ys, xs = np.nonzero(mask[ny0:ny1, nx0:nx1])
    if len(xs):
        nx0, nx1 = nx0 + xs.min(), nx0 + xs.max()
        ny0, ny1 = ny0 + ys.min(), ny0 + ys.max()
    return (
        int(max(0, nx0 - pad)),
        int(max(0, ny0 - pad)),
        int(min(w, nx1 + pad)),
        int(min(h, ny1 + pad)),
    )


# ─────────────────────────────────────────────
# 5. 저장
# ─────────────────────────────────────────────

PAGE = """<!doctype html>
<html lang="ko"><head><meta charset="utf-8"><title>{title}</title>
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/katex@0.16.9/dist/katex.min.css">
<script src="https://cdn.jsdelivr.net/npm/katex@0.16.9/dist/katex.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/katex@0.16.9/dist/contrib/auto-render.min.js"></script>
<style>
body {{ margin: 0; padding: 24px; background: #e8ece8; color: #1f2623;
       font-family: -apple-system, "Apple SD Gothic Neo", sans-serif; }}
h1 {{ font-size: 18px; margin: 0 0 4px; }}
.meta {{ color: #6b746f; font-size: 13px; margin-bottom: 16px; }}
.top {{ display: flex; gap: 20px; flex-wrap: wrap; margin-bottom: 24px; }}
.top img {{ max-width: 520px; width: 100%; border: 1px solid #c9d0cb; }}
.cards {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(320px, 1fr)); gap: 18px; }}
.card {{ background: #fff; border: 2px solid #fff; border-radius: 10px;
        box-shadow: 0 2px 0 #c9d0cb; padding: 12px; display: grid; gap: 10px; }}
.card h2 {{ font-size: 14px; margin: 0; }}
.ink {{ background: repeating-conic-gradient(#f1f3f1 0 25%, #fff 0 50%) 0 0 / 14px 14px;
       border-radius: 6px; padding: 6px; }}
.ink img {{ max-width: 100%; display: block; }}
.line {{ font-size: 15px; line-height: 1.7; }}
</style></head><body>
<h1>{title}</h1>
<div class="meta">{meta}</div>
<div class="top"><img src="boxes.jpg" alt="덩어리 위치"></div>
<div class="cards">{cards}</div>
<script>
document.querySelectorAll(".line").forEach(el => renderMathInElement(el, {{
  delimiters: [{{ left: "$", right: "$", display: false }}], throwOnError: false }}));
</script>
</body></html>
"""


def card_ink(img, mask, box):
    """카드 상자 부분을 잘라 필기만 보이는 투명 배경 이미지(BGRA)로 만든다."""
    x0, y0, x1, y1 = box
    ink = np.zeros((y1 - y0, x1 - x0, 4), np.uint8)
    ink[..., :3] = img[y0:y1, x0:x1]
    ink[..., 3] = mask[y0:y1, x0:x1]  # 필기만 보이게
    return ink


def save(out_dir, name, img, mask, cards, seconds, corners):
    out_dir.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(out_dir / "cropped.jpg"), img)
    preview = img.copy()
    html_cards = []
    for c in cards:
        x0, y0, x1, y1 = c["box"]
        cv2.imwrite(str(out_dir / f"card_{c['no']:02d}.jpg"), img[y0:y1, x0:x1])
        cv2.imwrite(str(out_dir / f"card_{c['no']:02d}_ink.png"), card_ink(img, mask, c["box"]))

        cv2.rectangle(preview, (x0, y0), (x1, y1), (76, 90, 47), 2)
        cv2.putText(
            preview, str(c["no"]), (x0 + 3, y0 + 20), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (76, 90, 47), 2
        )
        lines = "".join(f'<div class="line">{html.escape(t)}</div>' for t in c["lines"])
        html_cards.append(
            f'<div class="card"><h2>{c["no"]}. {html.escape(c["title"])}</h2>'
            f'<div class="ink"><img src="card_{c["no"]:02d}_ink.png" alt=""></div>{lines}</div>'
        )

    cv2.imwrite(str(out_dir / "boxes.jpg"), preview)
    result = {
        "source": name,
        "model": MODEL,
        "seconds": round(seconds, 1),
        "screen_found": corners is not None,
        "size": [img.shape[1], img.shape[0]],
        "cards": cards,
    }
    (out_dir / "result.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    found = "찾음" if corners is not None else "자르지 않음"
    meta = f"{MODEL} · {seconds:.1f}초 · 카드 {len(cards)}개 · 화면 {found}"
    (out_dir / "index.html").write_text(
        PAGE.format(title=html.escape(name), meta=html.escape(meta), cards="".join(html_cards)),
        encoding="utf-8",
    )


def process(original, pen):
    """사진(BGR 배열) 한 장을 처리해 결과를 돌려준다. 파일은 만들지 않는다.

    돌려주는 값: img(잘라낸 사진), corners(화면 모서리, 못 찾으면 None), mask(필기 마스크),
    cards(덩어리 카드 목록), seconds(Gemini 응답 시간), retries(Gemini 다시 시도 횟수),
    waited(한도·다시 시도로 기다린 초)
    """
    img, corners = crop_slide(original, pen)
    print(
        f"1. 화면 {'찾아서 잘라냄' if corners is not None else '자르지 않음'} "
        f"→ {img.shape[1]}x{img.shape[0]}",
        flush=True,
    )

    mask = ink_mask(img, pen)
    print(f"2. 필기 마스크 ({pen})", flush=True)

    regions, info = ask_regions(img)
    print(f"3. Gemini {info['seconds']:.1f}초, 덩어리 {len(regions)}개", flush=True)

    h, w = mask.shape
    clean = remove_long_lines(mask)
    cards = []
    for region in regions:
        if len(region.box_2d) != 4:
            continue
        rough = to_pixels(region.box_2d, w, h)
        if rough[2] - rough[0] < 10 or rough[3] - rough[1] < 10:
            continue
        cards.append(
            {
                "no": len(cards) + 1,
                "title": region.title,
                "lines": region.lines,
                "box_gemini": list(rough),
                "box": list(refine_box(clean, rough)),
            }
        )
    print(f"4. 상자 다듬기 {len(cards)}개", flush=True)
    return {"img": img, "corners": corners, "mask": mask, "cards": cards, **info}


def run(photo_path, pen, out_root):
    """사진 파일을 처리해 결과 폴더에 저장한다 (명령줄 실행용)."""
    photo_path = Path(photo_path)
    original = cv2.imread(str(photo_path))
    if original is None:
        sys.exit(f"사진을 읽지 못했어요: {photo_path}")

    try:
        result = process(original, pen)
    except GeminiError as error:
        sys.exit(str(error))

    out_dir = Path(out_root) / photo_path.stem
    save(
        out_dir,
        photo_path.name,
        result["img"],
        result["mask"],
        result["cards"],
        result["seconds"],
        result["corners"],
    )
    print(f"5. 저장: {out_dir}/index.html", flush=True)
    return out_dir


def main():
    parser = argparse.ArgumentParser(
        description="수업 사진에서 필기를 덩어리별 스티커 카드로 뽑아낸다"
    )
    parser.add_argument("photo", help="사진 경로")
    parser.add_argument(
        "--pen",
        choices=["red", "black", "board"],
        default="black",
        help="red: 빨간 펜(프로젝터) / black: 검은 펜(프로젝터) / board: 칠판",
    )
    parser.add_argument("--out", default=str(ROOT / "pipeline/out"), help="결과 폴더")
    args = parser.parse_args()
    load_api_key()
    run(args.photo, args.pen, args.out)


if __name__ == "__main__":
    main()
