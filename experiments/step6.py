import os
import sys
import time
from pathlib import Path

from google import genai
from google.genai import types
from PIL import Image
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "experiments/out"
OUT.mkdir(exist_ok=True)                 # 결과 폴더가 없으면 만든다

IMAGE = ROOT / "samples/screen1.jpg"     # 읽을 사진. 필기만 뽑은 결과로 해 보려면 OUT / "5_preview.png"
MODEL = "gemini-3.8-flash"


def load_api_key():
    """comkerton/.env 파일에서 GEMINI_API_KEY=... 줄을 읽는다."""
    env_file = ROOT / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            if line.startswith("GEMINI_API_KEY="):
                os.environ["GEMINI_API_KEY"] = line.split("=", 1)[1].strip().strip('"')
    if not os.environ.get("GEMINI_API_KEY"):
        sys.exit(f"API 키가 없어요. {env_file} 파일에 GEMINI_API_KEY=발급받은키 한 줄을 넣어 주세요.")


# 앱에서 쓰기 편하도록 출력 구조를 정해 둔다
class NoteBlock(BaseModel):
    category: str = Field(description="필기 영역 구분 (예: 왼쪽 위, Example 4 풀이 등). 짧게")
    lines: list[str] = Field(
        description="손으로 쓴 내용을 쓰인 순서대로 한 줄씩. 글자는 그대로 쓰고, 수식 부분만 $...$ 로 감싼 LaTeX로 쓴다."
    )


class ExtractedHandwriting(BaseModel):
    blocks: list[NoteBlock]


PROMPT = """
너는 강의 사진(프로젝터 화면 또는 칠판)에서 '손으로 쓴 필기'를 그대로 옮겨 적는 AI야.

[엄격한 규칙]
1. 프로젝터 화면이라면, 슬라이드에 원래 인쇄되어 있던 타이핑 텍스트와 수식은 모두 무시해. 칠판이라면 전부 손글씨이므로 모두 옮겨.
2. 글자(한글, 영어)와 수식을 모두 옮겨. 쓰인 순서와 줄 구분을 유지해.
3. 한 줄 안에서 글자는 그대로 쓰고, 수식 부분만 $...$ 로 감싸서 LaTeX로 써.
   예: "자기력 $\\vec{F}_B = q\\vec{v} \\times \\vec{B}$ (오른손 법칙)"
4. 화살표로 이어진 흐름은 → 로 표시해.
5. 읽을 수 없는 부분은 지어내지 말고 [?]로 표시해.
6. 해설이나 요약을 덧붙이지 말고, 쓰여 있는 내용만 옮겨.
"""


def extract_handwriting(image_path: Path) -> str:
    client = genai.Client()
    image = Image.open(image_path)
    response = client.models.generate_content(
        model=MODEL,
        contents=[image, PROMPT],
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=ExtractedHandwriting,
            temperature=0.1,
        ),
    )
    return response.text


if __name__ == "__main__":
    load_api_key()
    print(f"필기 추출 중... ({IMAGE.name})\n")
    for attempt in range(5):
        try:
            result = extract_handwriting(IMAGE)
            break
        except Exception as error:
            if "503" not in str(error) and "429" not in str(error):
                raise                                   # 다른 오류는 그대로 보여줌
            wait = 10 * (attempt + 1)
            print(f"서버가 바빠요. {wait}초 뒤 다시 시도 ({attempt + 1}/5)")
            time.sleep(wait)
    else:
        sys.exit("5번 시도했지만 실패했어요. 잠시 뒤 다시 실행해 주세요.")
    print(result)
    (OUT / "6_gemini.json").write_text(result, encoding="utf-8")
    print(f"\n저장: {OUT / '6_gemini.json'}")
