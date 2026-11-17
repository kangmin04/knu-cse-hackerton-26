"""판서를 블록으로 나누고, 블록마다 위치·읽는 순서·이어짐을 함께 받아오는 LLM 요청.

판서는 위→아래로 쓰다가 공간이 부족하면 오른쪽 위로 올라가 이어 쓰는 경우가 많아서,
단순히 위치 순서로 읽으면 순서가 꼬인다. 그래서 LLM에게 순서와 '어디서 이어지는지'를 같이 묻는다.
"""
import io
from typing import List, Optional

from google import genai
from google.genai import types
from PIL import Image
from pydantic import BaseModel, Field

import step6


class LayoutBlock(BaseModel):
    id: int = Field(description="블록 번호. 1부터")
    box_2d: List[int] = Field(description="이 블록의 손글씨 전체를 감싸는 사각형 [ymin, xmin, ymax, xmax]. "
                                          "이미지 높이·너비를 0~1000으로 정규화한 값")
    order: int = Field(description="교수가 쓴 순서(읽는 순서). 1부터")
    continues_from: Optional[int] = Field(description="공간이 부족해 다른 자리(보통 오른쪽 위)로 옮겨 이어 쓴 블록이면 "
                                                      "이어지는 이전 블록의 id. 새로 시작한 내용이면 null")
    category: str = Field(description="블록 내용 요약 (예: 쿨롱 법칙, Example 4 풀이). 짧게")
    lines: List[str] = Field(description="손으로 쓴 내용을 쓰인 순서대로 한 줄씩. 수식 부분만 $...$ 로 감싼 LaTeX")


class Layout(BaseModel):
    blocks: List[LayoutBlock]


PROMPT = step6.PROMPT + """
[블록 나누기]
7. 판서를 의미 단위 블록(한 흐름의 풀이, 한 정의, 한 그림 등)으로 나눠.
8. 블록마다 box_2d에 그 블록 손글씨 전체를 감싸는 사각형을 [ymin, xmin, ymax, xmax] (0~1000 정규화)로 적어.
9. order에는 교수가 쓴 순서를 적어. 판서는 위에서 아래로 쓰다가 공간이 부족하면 오른쪽 위로 올라가
   이어 쓰는 경우가 많으니, 위치만 보지 말고 화살표·수식 흐름·내용 연결을 보고 판단해.
10. 다른 블록에서 이어지는 내용이면 continues_from에 그 블록의 id를, 아니면 null을 적어.
"""

_client = None


def extract_layout(jpegs, model=None):
    """JPEG 바이트 목록 → (모델 응답 JSON 문자열, 입력 토큰 수)."""
    global _client
    if _client is None:
        _client = genai.Client()   # 키는 step6.load_api_key()가 환경변수에 넣어 둠
    config = dict(response_mime_type="application/json", response_schema=Layout, temperature=0.1)
    response = _client.models.generate_content(
        model=model or step6.MODEL,
        contents=[*(Image.open(io.BytesIO(j)) for j in jpegs), PROMPT],
        config=types.GenerateContentConfig(**config),
    )
    return response.text, response.usage_metadata.prompt_token_count
