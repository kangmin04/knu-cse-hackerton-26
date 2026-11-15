"""같은 사진을 여러 방식으로 Gemini에 보내서 걸리는 시간을 비교한다."""
import time
from pathlib import Path

import cv2
import numpy as np
from google import genai
from google.genai import types
from PIL import Image

from step6 import MODEL, PROMPT, ExtractedHandwriting, load_api_key

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "experiments/out"
SOURCE = ROOT / "samples/screen2.jpg"
CROP = (560, 1370, 80, 1070)          # 화면 부분 (위, 아래, 왼쪽, 오른쪽)


def ink_only(img):
    """step5와 같은 방식으로 필기만 남긴 흰 배경 이미지를 만든다."""
    img = cv2.resize(img, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
    gray = cv2.bilateralFilter(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY), 7, 30, 5)
    diff = cv2.medianBlur(gray, 101).astype(np.int16) - gray.astype(np.int16)
    count, labels = cv2.connectedComponents((diff > 18).astype(np.uint8), connectivity=8)
    keep = np.zeros(count, bool)
    keep[np.unique(labels[diff > 45])] = True
    keep[0] = False
    alpha = np.clip((diff - 15) / 30.0, 0, 1) * keep[labels]
    return (255 - alpha * 255).astype(np.uint8)


def ask(client, image_path, thinking_off):
    config = dict(response_mime_type="application/json", response_schema=ExtractedHandwriting, temperature=0.1)
    if thinking_off:
        config["thinking_config"] = types.ThinkingConfig(thinking_budget=0)
    start = time.time()
    response = client.models.generate_content(
        model=MODEL,
        contents=[Image.open(image_path), PROMPT],
        config=types.GenerateContentConfig(**config),
    )
    return time.time() - start, response


def main():
    load_api_key()
    client = genai.Client()

    # 보낼 사진 세 가지를 만든다
    original = cv2.imread(str(SOURCE))
    top, bottom, left, right = CROP
    cropped = original[top:bottom, left:right]
    cv2.imwrite(str(OUT / "8_cropped.jpg"), cropped)
    cv2.imwrite(str(OUT / "8_ink.png"), ink_only(cropped))

    cases = [
        ("A 원본 그대로", SOURCE, False),
        ("B 화면만 자름", OUT / "8_cropped.jpg", False),
        ("C 필기만 뽑음", OUT / "8_ink.png", False),
        ("D 원본 + 생각 끔", SOURCE, True),
        ("E 필기만 + 생각 끔", OUT / "8_ink.png", True),
    ]

    print(f"모델: {MODEL}\n")
    print(f"{'방식':<16}{'시간':>7}{'입력':>8}{'생각':>8}{'출력':>8}  줄 수")
    for name, path, thinking_off in cases:
        for attempt in range(4):
            try:
                seconds, response = ask(client, path, thinking_off)
                break
            except Exception as error:
                if "503" in str(error) or "429" in str(error):
                    time.sleep(15 * (attempt + 1))        # 서버가 바쁘면 기다렸다 다시
                    continue
                print(f"{name:<16} 실패: {str(error)[:120]}")
                response = None
                break
        else:
            print(f"{name:<16} 실패: 서버가 계속 바쁨")
            continue
        if response is None:
            continue

        usage = response.usage_metadata
        lines = sum(len(block.lines) for block in ExtractedHandwriting.model_validate_json(response.text).blocks)
        print(f"{name:<16}{seconds:>6.1f}초{usage.prompt_token_count or 0:>8}"
              f"{usage.thoughts_token_count or 0:>8}{usage.candidates_token_count or 0:>8}  {lines}")
        (OUT / f"8_result_{name[0]}.json").write_text(response.text, encoding="utf-8")

    print(f"\n결과 파일: {OUT}/8_result_A.json ~ E.json")


if __name__ == "__main__":
    main()
