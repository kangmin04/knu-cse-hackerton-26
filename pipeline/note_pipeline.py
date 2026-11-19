"""수업 사진 한 장에서 필기를 덩어리별 스티커 카드로 뽑아낸다.

순서
  1. OpenCV: 사진에서 프로젝터 화면을 찾아 반듯하게 잘라낸다 (칠판은 크기만 줄임)
  2. OpenCV: 펜 종류에 맞게 필기만 남긴 마스크를 만든다
  3. Gemini: 필기를 의미 단위 덩어리로 나누고, 덩어리마다 위치·제목·글자(LaTeX)를 받는다
  4. OpenCV: Gemini가 준 대략적인 상자를 필기 경계에 맞게 다듬는다
     숫자 정렬 블록(세로셈·나눗셈·진리표 등)은 원본 해상도로 잘라 Gemini에 줄 단위로 다시 읽히고,
     가로 작대기는 OpenCV로 찾아 판서 모양(열 위치) 그대로 다시 그린다. 연산 종류는 판단하지 않는다.
  5. 덩어리마다 원본 조각, 투명 배경 필기 이미지, 결과 json, 확인용 html을 저장한다

실행
  python3 pipeline/note_pipeline.py samples/screen2.jpg --pen black
  python3 pipeline/note_pipeline.py samples/screen1.jpg --pen red
  python3 pipeline/note_pipeline.py samples/board1.jpg --pen board
  python3 pipeline/note_pipeline.py samples/screen_binary-calculate.jpeg --pen red

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
# 기본은 빠르고 한도가 넉넉한 flash-lite. 정확도가 더 필요하면 .env에 GEMINI_MODEL=gemini-3.5-flash
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


def straighten(img, pen, margin=0.12):
    """화면을 찾아 원본 해상도 그대로 펴서 돌려준다. 칠판이거나 못 찾으면 원본을 돌려준다.

    찾은 사각형이 화면 전체가 아니라 슬라이드 안쪽 상자일 수 있고, 판서가 그 밖으로
    삐져나오기도 하므로 사방에 margin 비율만큼 여백을 두고 자른다.
    """
    corners = find_screen(img) if pen != "board" else None
    if corners is None:
        return img, None
    tl, tr, br, bl = corners
    w = int(max(np.linalg.norm(tr - tl), np.linalg.norm(br - bl)))
    h = int(max(np.linalg.norm(bl - tl), np.linalg.norm(br - tr)))
    mx, my = int(w * margin), int(h * margin)
    dst = np.float32([[mx, my], [mx + w, my], [mx + w, my + h], [mx, my + h]])
    out = cv2.warpPerspective(
        img,
        cv2.getPerspectiveTransform(corners, dst),
        (w + 2 * mx, h + 2 * my),
        borderMode=cv2.BORDER_REPLICATE,  # 사진 밖으로 나간 부분은 검은색 대신 가장자리로 채움
    )
    return out, corners


def shrink(img, max_side):
    """긴 변이 max_side보다 크면 줄인다."""
    k = max_side / max(img.shape[:2])
    if k >= 1:
        return img
    return cv2.resize(img, None, fx=k, fy=k, interpolation=cv2.INTER_AREA)


def crop_slide(img, pen, max_side=1600):
    """화면을 찾아 펴고 긴 변을 max_side로 줄여 돌려준다."""
    out, corners = straighten(img, pen)
    return shrink(out, max_side), corners


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
    kind: str = Field(
        description=(
            "aligned: 숫자가 여러 줄로 열을 맞춰 쌓인 블록 (세로셈·나눗셈·진리표 등). "
            "text: 그 밖의 필기"
        )
    )
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

[있는 그대로 옮기기]
6. 필기를 '추출'하는 게 목적이야. 계산이 틀려 보여도 고치거나 다시 계산하지 말고 쓰인 그대로 옮겨.
7. 빨강·검정·노랑·파랑 등 펜 색이 달라도 모두 필기야.
   다른 색으로 덧쓴 값, 동그라미 친 값도 빠뜨리지 마.

[숫자 정렬 블록]
8. 세로셈·나눗셈·진리표처럼 숫자가 여러 줄로 열을 맞춰 쌓인 필기는 kind를 "aligned", 그 밖은 "text".
   어떤 연산인지는 따지지 말고, 위에 쓴 결과·중간 줄·맨 아래 값·다른 색으로 쓴 값까지
   그 풀이 전체를 한 덩어리로 묶어.
   lines에는 줄마다 숫자·부호만 공백 없이 옮기고 $ 로 감싸지 마. 점선·화살표는 빼.
"""


def load_api_key():
    """저장소 최상위 .env 파일에서 GEMINI_API_KEY와 GEMINI_MODEL을 읽는다.

    이미 환경 변수로 준 값이 있으면 그 값을 쓴다 (.env보다 우선).
    """
    global MODEL
    env_file = ROOT / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            name, _, value = line.partition("=")
            name, value = name.strip(), value.strip().strip('"')
            if name in ("GEMINI_API_KEY", "GEMINI_MODEL") and value:
                os.environ.setdefault(name, value)
    MODEL = os.environ.get("GEMINI_MODEL", MODEL)
    if not os.environ.get("GEMINI_API_KEY"):
        sys.exit(f"API 키가 없어요. {env_file} 에 GEMINI_API_KEY=발급받은키 한 줄을 넣어 주세요.")


class GeminiError(RuntimeError):
    """Gemini에 요청했지만 끝내 답을 받지 못함."""


RPM_LIMIT = 12  # 무료 등급 한도는 분당 15회. 여유를 두고 12회까지만 보낸다 (다시 시도 포함)
RETRY_WAITS = (3, 6, 12)  # 다시 시도하기 전에 쉬는 초. 최대 3번 다시 시도
RETRY_CODES = {408, 500, 502, 503, 504}  # 일시 오류(시간 초과·서버 오류)만 다시 시도한다
# 요청 한 번을 기다리는 최대 초. 라이브러리의 시간 제한은 연결·받기 단계마다 따로 걸려서
# 요청 전체를 막지 못한다 (실제로 312초 걸린 적 있음). 그래서 전체 시간을 직접 잰다.
REQUEST_TIMEOUT = 60  # flash는 정상일 때도 한 번에 10~20초 걸려서 30초면 빠듯하다

_calls = deque()  # 최근 60초 동안 보낸 요청 시각
_calls_lock = threading.Lock()  # 서버에서 여러 요청이 동시에 들어와도 한도를 지키도록
_client = None


def get_client():
    """Gemini 연결을 한 번만 만들어 다시 쓴다."""
    global _client
    if _client is None:
        # 단계별 시간 제한도 REQUEST_TIMEOUT으로 맞춘다. generate()가 시간 초과로 버린 요청이
        # 뒤에서 오래 살아 있으면 다시 시도할 때마다 요청이 겹쳐 쌓이고 분당 한도도 잡아먹는다.
        _client = genai.Client(http_options=types.HttpOptions(timeout=REQUEST_TIMEOUT * 1000))
    return _client


def generate(contents, config):
    """Gemini 요청을 한 번 보내고 REQUEST_TIMEOUT초까지만 기다린다. 넘으면 TimeoutError.

    요청은 별도 스레드에서 보내고, 시간이 넘으면 기다리지 않고 버린다 (뒤에서 끝나도 결과는 안 씀).
    """
    box = {}

    def work():
        try:
            box["response"] = get_client().models.generate_content(
                model=MODEL, contents=contents, config=config
            )
        except Exception as error:  # 오류는 부른 쪽에서 다시 던진다
            box["error"] = error

    worker = threading.Thread(target=work, daemon=True)
    worker.start()
    worker.join(REQUEST_TIMEOUT)
    if worker.is_alive():
        raise TimeoutError(f"{REQUEST_TIMEOUT}초 안에 답이 없음")
    if "error" in box:
        raise box["error"]
    return box["response"]


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
    한계: 진짜 줄바꿈 바로 뒤에 영어 글자가 붙으면(\\nThen) LaTeX 명령으로 보고 글자 그대로 남긴다.
    LaTeX 명령(\\frac, \\theta, \\nabla …)이 훨씬 자주 나와서 이쪽을 택했다.
    """
    return parse_json(text, NoteRegions).regions


def parse_json(text, schema):
    """Gemini 답(JSON 글자)을 schema로 바꾼다. 끊기거나 깨진 답이면 ValueError."""
    if not text:
        raise ValueError("빈 답")
    fixed = re.sub(r'\\(\\|"|/|u[0-9a-fA-F]{4}|[a-zA-Z]+|.)', _fix_escape, text)
    return schema.model_validate(json.loads(fixed, strict=False))


def empty_reason(response):
    """빈 답이 온 이유를 짧게 (차단 이유나 생성이 끝난 이유)."""
    feedback = getattr(response, "prompt_feedback", None)
    if feedback and feedback.block_reason:
        return f"차단: {feedback.block_reason}"
    if response.candidates:
        return f"끝난 이유: {response.candidates[0].finish_reason}"
    return "답 후보 없음"


def ask_regions(img):
    """Gemini에 덩어리를 물어본다. 돌려주는 값과 실패 처리는 ask_gemini와 같다."""
    image = Image.fromarray(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))
    result, info = ask_gemini([image, PROMPT], NoteRegions)
    return result.regions, info


def ask_gemini(contents, schema, temperature=0.1):
    """Gemini에 요청하고 답을 schema로 받는다.

    돌려주는 값: (schema 객체, 정보). 정보는 seconds(성공한 요청의 응답 시간),
    retries(다시 시도한 횟수), waited(한도·다시 시도로 기다린 초)
    다시 시도: 일시 오류(408·500·502·503·504), 연결 끊김, REQUEST_TIMEOUT초 넘게 답이 없음,
    답이 끊기거나 깨짐
    바로 멈춤: 사용 한도 초과(429), 빈 답(안전 차단 등),
    키·모델 이름 문제처럼 다시 해도 안 되는 오류
    끝내 실패하면 GeminiError를 던진다 (프로그램을 끝내지 않아서 서버에서도 쓸 수 있음).
    """
    config = types.GenerateContentConfig(
        response_mime_type="application/json", response_schema=schema, temperature=temperature
    )
    waited = 0.0
    for attempt in range(len(RETRY_WAITS) + 1):
        waited += wait_for_slot()
        start = time.time()
        try:
            response = generate(contents, config)
            if not response.text:  # 안전 차단 등으로 빈 답이면 다시 해도 같으므로 바로 멈춘다
                raise GeminiError(f"Gemini가 빈 답을 보냈어요({empty_reason(response)}).")
            parsed = parse_json(response.text, schema)
            info = {"seconds": time.time() - start, "retries": attempt, "waited": waited}
            return parsed, info
        except errors.APIError as error:
            if error.code == 429:
                message = "Gemini 사용 한도를 넘었어요(429). 잠시 뒤 다시 시도해 주세요."
                raise GeminiError(message) from error
            if error.code not in RETRY_CODES:
                raise GeminiError(f"Gemini 요청 실패({error.code}): {error.message}") from error
            reason = f"서버 오류 {error.code}"
        except httpx.TransportError:
            reason = "연결 끊김"
        except TimeoutError:  # OSError의 한 종류라 OSError보다 먼저 잡는다
            reason = f"{REQUEST_TIMEOUT}초 안에 답이 없음"
        except OSError:  # httpx 밖에서 나는 연결 오류 (연결 재설정, SSL 오류 등)
            reason = "연결 끊김"
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
# 4-1. 숫자 정렬 블록을 판서 모양 그대로 읽기
# ─────────────────────────────────────────────


class GridRow(BaseModel):
    kind: str = Field(description="digits: 숫자·부호가 적힌 줄 / rule: 가로로 그은 작대기")
    text: str = Field(
        description=(
            "digits면 보이는 문자를 왼쪽부터 공백 없이 그대로 (숫자, + - × ÷ ⊕ = 같은 부호, "
            "나눗셈 괄호 ')' 포함). rule이면 빈 문자열"
        )
    )
    box_2d: list[int] = Field(
        description="이 줄을 감싸는 상자 [ymin, xmin, ymax, xmax]. 이 이미지를 0~1000으로 본 좌표"
    )
    circled: bool = Field(description="동그라미나 네모로 감싼 값이면 true")
    color: str = Field(description="펜 색. red, black, blue, green, yellow, white 중 하나")


class Grid(BaseModel):
    rows: list[GridRow]


GRID_PROMPT = """
이 이미지는 판서 사진에서 '숫자 정렬 블록'(세로셈·나눗셈·진리표처럼 숫자가 줄과 열을 맞춰
쌓인 손글씨) 부분만 확대한 거야. 판서 모양을 그대로 다시 그릴 수 있게,
위에서 아래로 모든 줄을 rows에 옮겨 줘.

1. 계산하거나 고치지 마. 틀려 보여도 쓰인 그대로. 어떤 연산인지도 따지지 마.
2. digits 줄: 같은 높이에 쓰인 숫자·부호를 왼쪽부터 공백 없이 한 줄로.
   - 나눗셈 모양이면 제수, 괄호 ')', 피제수를 한 줄로. 예: "1011)1001000"
   - 줄 앞에 쓴 부호(+, -, ×, ⊕ 등)도 그 줄 text 맨 앞에 넣어.
   - 세로 막대 모양은 1, 동그라미 모양은 0. 숫자를 하나하나 세어 자릿수를 정확히.
   - 숫자끼리 붙어 있어도 하나씩 따로 세. 예: 붙어 쓴 "10"은 1과 0 두 글자.
   - 휘거나 기울어진 세로 획도 1이야. 괄호 ')'는 제수와 피제수 사이에 있을 때만 괄호로 적어.
3. rule 줄: 숫자 줄 사이에 가로로 그은 작대기 (빼기 결과 위의 줄, 나눗셈 괄호 위의 가로선).
4. box_2d는 그 줄의 왼쪽 끝부터 오른쪽 끝까지 꼭 맞게. 열 맞춤에 쓰이니 x 좌표를 특히 정확히.
5. 점선, 화살표(↓), 물결 밑줄, 안내선은 옮기지 마.
6. 펜 색이 달라도 모두 옮겨. 동그라미 친 값은 circled를 true로.
7. 이미지 가장자리에 잘려 들어온 다른 필기는 무시해.
"""

GRID_MAX_SIDE = 2000  # 2차 요청에 보내는 확대 조각의 최대 크기


def read_grid(full, scale, box, pad=0.06):
    """숫자 정렬 블록을 원본 해상도로 잘라 Gemini에 줄 단위로 다시 읽힌다.

    full: 원본 해상도로 편 사진, scale: full과 작업용 사진의 배율, box: 작업용 사진 기준 상자
    돌려주는 값: (줄 목록, 정보). 줄의 좌표는 작업용 사진 기준 픽셀 (x0, y0, x1, y1)
    """
    x0, y0, x1, y1 = box
    px, py = int((x1 - x0) * pad) + 4, int((y1 - y0) * pad) + 4
    h, w = full.shape[0] / scale, full.shape[1] / scale
    cx0, cy0 = max(0, x0 - px), max(0, y0 - py)
    cx1, cy1 = min(w, x1 + px), min(h, y1 + py)
    crop = full[int(cy0 * scale) : int(cy1 * scale), int(cx0 * scale) : int(cx1 * scale)]
    image = Image.fromarray(cv2.cvtColor(shrink(crop, GRID_MAX_SIDE), cv2.COLOR_BGR2RGB))
    grid, info = ask_gemini([image, GRID_PROMPT], Grid, temperature=0)

    rows = []
    for r in grid.rows:
        if len(r.box_2d) != 4:
            continue
        ymin, xmin, ymax, xmax = r.box_2d
        rows.append(
            {
                "kind": "rule" if r.kind == "rule" else "digits",
                "text": r.text.replace(" ", ""),
                "circled": r.circled,
                "color": r.color,
                "x0": cx0 + min(xmin, xmax) / 1000 * (cx1 - cx0),
                "x1": cx0 + max(xmin, xmax) / 1000 * (cx1 - cx0),
                "y0": cy0 + min(ymin, ymax) / 1000 * (cy1 - cy0),
                "y1": cy0 + max(ymin, ymax) / 1000 * (cy1 - cy0),
            }
        )
    return rows, info


class RowChar(BaseModel):
    char: str = Field(description="글자 하나 (숫자 또는 부호)")
    x_range: list[int] = Field(
        description="이 글자의 [xmin, xmax]. 이미지 가로를 0~1000으로 본 좌표"
    )


class RowRead(BaseModel):
    chars: list[RowChar]


ROW_PROMPT = """
이 이미지는 판서에서 숫자 한 줄을 크게 잘라낸 거야.
가운데 있는 한 줄만, 왼쪽부터 글자를 하나씩 짚어 가며 chars에 옮겨 줘.

1. 계산하거나 고치지 말고 쓰인 그대로.
2. 숫자끼리 붙어 있어도 하나씩 따로 세. 예: 붙어 쓴 "10"은 1과 0 두 글자.
3. 휘거나 기울어진 세로 획도 1이야. 동그라미 모양은 0.
4. 괄호 ')'는 제수와 피제수 사이에 있을 때만 괄호로 적어.
5. 위아래 줄에서 잘려 들어온 글자, 가로선, 점선, 화살표는 빼.
"""

COUNT_TOLERANCE = 0.75  # 줄 너비로 어림한 칸 수와 읽은 글자 수가 이만큼 넘게 다르면 다시 읽는다
MAX_REREAD_ROWS = 6  # 블록 하나에서 다시 읽을 줄의 최대 개수 (분당 호출 한도 보호)


def recheck_rows(full, scale, rows, char_w, char_h):
    """글자 수가 줄 너비와 맞지 않는 숫자 줄을 그 줄만 크게 잘라 다시 읽는다.

    붙어 쓴 1과 0, 휘어진 1처럼 블록 전체에서는 뭉개지는 글자를 줄 단위로 크게 보여 준다.
    어림한 칸 수는 다시 읽을 줄을 고르고, 두 결과 중 어느 쪽을 쓸지 정하는 데만 쓴다
    (글자 자체를 고치지는 않는다). 끝까지 칸 수와 안 맞으면 uncertain으로 표시한다.
    돌려주는 값: 다시 읽는 데 걸린 초
    """
    h, w = full.shape[0] / scale, full.shape[1] / scale
    seconds = 0.0
    suspects = []
    for r in rows:
        if r["kind"] != "digits" or not r["text"]:
            continue
        r["expected"] = round((r["x1"] - r["x0"]) / char_w, 1)
        if abs(r["expected"] - len(r["text"])) >= COUNT_TOLERANCE:
            suspects.append(r)
    for r in suspects[:MAX_REREAD_ROWS]:
        cx0, cx1 = max(0, r["x0"] - char_w), min(w, r["x1"] + char_w)
        cy0, cy1 = max(0, r["y0"] - char_h * 0.35), min(h, r["y1"] + char_h * 0.35)
        crop = full[int(cy0 * scale) : int(cy1 * scale), int(cx0 * scale) : int(cx1 * scale)]
        image = Image.fromarray(cv2.cvtColor(crop, cv2.COLOR_BGR2RGB))
        try:
            read, info = ask_gemini([image, ROW_PROMPT], RowRead, temperature=0)
        except GeminiError as error:
            print(f"   줄 다시 읽기 실패: {error}", flush=True)
            continue
        seconds += info["seconds"]
        chars = [c for c in read.chars if c.char.strip()]
        text = "".join(c.char.strip() for c in chars)
        r["first_read"] = r["text"]
        if text and abs(len(text) - r["expected"]) <= abs(len(r["text"]) - r["expected"]):
            r["text"] = text
            boxes = [c.x_range for c in chars if len(c.x_range) == 2]
            if boxes:  # 글자 단위 위치로 줄의 양 끝을 바로잡는다 (열 맞춤이 정확해짐)
                r["x0"] = cx0 + min(min(b) for b in boxes) / 1000 * (cx1 - cx0)
                r["x1"] = cx0 + max(max(b) for b in boxes) / 1000 * (cx1 - cx0)
        print(f"   줄 다시 읽기: {r['first_read']} → {r['text']}", flush=True)
    for r in rows:
        if "expected" in r:
            r["uncertain"] = abs(r["expected"] - len(r["text"])) >= COUNT_TOLERANCE
    return seconds


def find_rules(mask, box, char_w, char_h, min_chars=2):
    """상자 안에서 가로 작대기를 픽셀로 찾는다. 글자 min_chars개보다 긴 수평선만 본다.

    점선·화살표·글자의 짧은 가로획은 끊겨 있거나 짧아서 걸러진다.
    손으로 그은 선은 살짝 기울어 여러 조각으로 잡히므로, 높이가 비슷하고
    가로로 이어지는 조각은 하나로 합친다.
    """
    x0, y0, x1, y1 = (int(v) for v in box)
    k = max(5, int(char_w * min_chars))
    lines = cv2.morphologyEx(mask[y0:y1, x0:x1], cv2.MORPH_OPEN, np.ones((1, k), np.uint8))
    count, _, stats, _ = cv2.connectedComponentsWithStats(lines, connectivity=8)
    pieces = sorted(
        [x0 + x, x0 + x + w, y0 + y, y0 + y + h]
        for x, y, w, h, _ in stats[1:count]
        if w >= k and w > 4 * h
    )
    merged = []
    for piece in pieces:  # 왼쪽부터 보며 앞 선과 이어지면 합친다
        for m in merged:
            near_y = abs((m[2] + m[3]) / 2 - (piece[2] + piece[3]) / 2) < char_h * 0.6
            if near_y and piece[0] - m[1] < char_w:
                m[:] = [
                    min(m[0], piece[0]),
                    max(m[1], piece[1]),
                    min(m[2], piece[2]),
                    max(m[3], piece[3]),
                ]
                break
        else:
            merged.append(list(piece))
    return [{"x0": a, "x1": b, "y0": c, "y1": d} for a, b, c, d in merged]


def snap_rules(rules, lines, char_h):
    """Gemini가 준 작대기마다 가까운 OpenCV 선을 찾아 양 끝을 픽셀 기준으로 맞춘다.

    작대기가 있는지와 줄 순서(높이)는 Gemini를 따르고, 가로 범위만 OpenCV로 바로잡는다.
    짝이 없는 Gemini 작대기는 그대로 둔다.
    돌려주는 값: (바로잡은 작대기 목록, 짝을 못 찾은 OpenCV 선 목록)
    """
    unused = list(lines)
    snapped = []
    for r in rules:
        ry = (r["y0"] + r["y1"]) / 2

        near = [
            line
            for line in unused
            if overlap(line, r) >= 0.5 and abs((line["y0"] + line["y1"]) / 2 - ry) < char_h
        ]
        if near:
            best = min(near, key=lambda line: abs((line["y0"] + line["y1"]) / 2 - ry))
            unused.remove(best)
            r = {**r, "x0": best["x0"], "x1": best["x1"]}
        snapped.append(r)
    return snapped, unused


def overlap(a, b):
    """두 가로 범위가 겹치는 정도 (짧은 쪽 길이 대비)."""
    inter = min(a["x1"], b["x1"]) - max(a["x0"], b["x0"])
    return inter / max(1.0, min(a["x1"] - a["x0"], b["x1"] - b["x0"]))


def missing_rules(digits, rules, lines):
    """Gemini가 빠뜨린 작대기를 OpenCV 선으로 채운다.

    작대기가 없는 이웃한 두 숫자 줄 사이 높이에 있고, 위아래 두 줄과 모두 가로로 겹치는 선만
    작대기로 본다. 빼기 결과 위의 작대기는 위아래 숫자 줄에 걸쳐 그어지기 때문이다.
    물결 밑줄처럼 한쪽 줄에만 걸친 선은 걸러진다.
    """

    def mid(r):
        return (r["y0"] + r["y1"]) / 2

    found = []
    ordered = sorted(digits, key=mid)
    for k in range(len(ordered) - 1):
        above, below = ordered[k], ordered[k + 1]
        if any(mid(above) < mid(r) < mid(below) for r in rules + found):
            continue
        between = [
            line
            for line in lines
            if mid(above) < mid(line) < mid(below)
            and overlap(line, above) >= 0.5
            and overlap(line, below) >= 0.5
        ]
        if between:
            line = max(between, key=lambda line: line["x1"] - line["x0"])
            lines.remove(line)
            found.append({"kind": "rule", **line})
    return found


def layout_grid(rows, lines):
    """줄 목록을 열 위치가 있는 격자로 바꾼다. 숫자 한 칸의 폭을 기준으로 열을 센다.

    lines: OpenCV로 찾은 가로선. 작대기의 가로 범위를 바로잡는 데 쓴다.
    돌려주는 값: 위에서 아래 순서의 격자 줄 목록. 줄마다 col(시작 열)과
    digits면 text·circled·color, rule이면 length(칸 수)
    """
    digits = [r for r in rows if r["kind"] == "digits" and r["text"]]
    if not digits:
        return []
    char_w, char_h = char_size(digits)
    rules, unused = snap_rules([r for r in rows if r["kind"] == "rule"], lines, char_h)
    rules += missing_rules(digits, rules, unused)
    origin = min(r["x0"] for r in digits + rules)

    grid = []
    for r in digits + rules:
        item = {"kind": r["kind"], "col": round((r["x0"] - origin) / char_w)}
        if r["kind"] == "digits":
            item.update(
                text=r["text"],
                circled=r["circled"],
                color=r["color"],
                uncertain=r.get("uncertain", False),
            )
        else:
            item["length"] = max(1, round((r["x1"] - r["x0"]) / char_w))
        grid.append(((r["y0"] + r["y1"]) / 2, item))
    return [item for _, item in sorted(grid, key=lambda g: g[0])]


def char_size(digits):
    """숫자 줄들로 글자 한 칸의 폭과 높이(픽셀)를 어림한다."""
    long_rows = [r for r in digits if len(r["text"]) >= 2] or digits
    char_w = float(np.median([(r["x1"] - r["x0"]) / len(r["text"]) for r in long_rows]))
    char_h = float(np.median([r["y1"] - r["y0"] for r in digits]))
    return max(char_w, 1.0), max(char_h, 1.0)


def grid_text(grid):
    """격자를 고정폭 글꼴용 줄 문자열로 그린다."""
    return [
        " " * g["col"] + (g["text"] if g["kind"] == "digits" else "─" * g["length"]) for g in grid
    ]


def read_aligned(full, scale, mask, card):
    """숫자 정렬 블록 카드를 다시 읽어 격자를 붙인다. 실패하면 1차 결과를 그대로 둔다."""
    try:
        rows, info = read_grid(full, scale, card["box"])
    except GeminiError as error:
        print(f"   카드 {card['no']} 다시 읽기 실패 → 1차 결과 사용: {error}", flush=True)
        return 0.0
    digits = [r for r in rows if r["kind"] == "digits" and r["text"]]
    if digits:
        seconds = info["seconds"] + recheck_rows(full, scale, rows, *char_size(digits))
        lines = find_rules(mask, card["box"], *char_size(digits))
        card["grid"] = layout_grid(rows, lines)
        card["layout"] = grid_text(card["grid"])
        card["lines"] = [r["text"] for r in sorted(digits, key=lambda r: r["y0"])]
        return seconds
    return info["seconds"]


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
.grid {{ margin: 0; font: 15px/1.35 ui-monospace, Menlo, monospace; overflow-x: auto; }}
.grid .uncertain {{ text-decoration: underline dotted #b3402f; }}
.grid .circled {{ border: 1.5px solid currentColor; border-radius: 999px; padding: 0 2px; }}
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


PEN_COLORS = {"red": "#c8372d", "blue": "#2a5db0", "green": "#2f7a4d", "yellow": "#b58900"}


def grid_html(grid):
    """격자를 판서 모양 그대로 보이는 html로 만든다 (펜 색과 동그라미 포함)."""
    rows = []
    for g in grid:
        pad = " " * g["col"]
        if g["kind"] == "rule":
            rows.append(pad + "─" * g["length"])
            continue
        color = PEN_COLORS.get(g["color"])
        style = f' style="color:{color}"' if color else ""
        names = [n for n in ("circled", "uncertain") if g.get(n)]
        cls = f' class="{" ".join(names)}"' if names else ""
        if g.get("uncertain"):
            cls += ' title="글자 수가 줄 너비와 맞지 않아요. 원본을 확인하세요"'

        rows.append(f"{pad}<span{cls}{style}>{html.escape(g['text'])}</span>")
    return f'<pre class="grid">{chr(10).join(rows)}</pre>'


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
        if c.get("grid"):
            lines = grid_html(c["grid"])
        else:
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
    waited(한도·다시 시도로 기다린 초), grid_seconds(숫자 정렬 블록 다시 읽기에 걸린 초)
    """
    full, corners = straighten(original, pen)
    img = shrink(full, 1600)
    scale = full.shape[1] / img.shape[1]
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
                "kind": "aligned" if region.kind == "aligned" else "text",
                "lines": region.lines,
                "box_gemini": list(rough),
                "box": list(refine_box(clean, rough)),
            }
        )
    print(f"4. 상자 다듬기 {len(cards)}개", flush=True)

    aligned = [c for c in cards if c["kind"] == "aligned"]
    grid_seconds = sum(read_aligned(full, scale, mask, c) for c in aligned)
    if aligned:
        print(f"4-1. 숫자 정렬 블록 {len(aligned)}개 다시 읽기 {grid_seconds:.1f}초", flush=True)
    result = {"img": img, "corners": corners, "mask": mask, "cards": cards, **info}
    result["grid_seconds"] = grid_seconds
    return result


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
