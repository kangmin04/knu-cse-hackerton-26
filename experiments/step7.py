import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "experiments/out"
OUT.mkdir(exist_ok=True)                 # 결과 폴더가 없으면 만든다

data = json.loads((OUT / "6_gemini.json").read_text(encoding="utf-8"))

HTML = """<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<title>필기 스티커</title>
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/katex@0.16.9/dist/katex.min.css">
<script src="https://cdn.jsdelivr.net/npm/katex@0.16.9/dist/katex.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/katex@0.16.9/dist/contrib/auto-render.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/html-to-image@1.11.11/dist/html-to-image.js"></script>
<style>
  body { margin: 0; padding: 24px; background: #e9ecf0; font-family: -apple-system, "Apple SD Gothic Neo", sans-serif; }
  button { font-size: 15px; padding: 10px 16px; border: 0; border-radius: 8px; background: #0b7a55; color: #fff; }
  #list { display: flex; flex-wrap: wrap; gap: 20px; align-items: flex-start; margin-top: 20px; }
  .sticker { background: #fffbe6; border: 1.5px solid #e6d98a; border-radius: 12px; padding: 16px 20px; max-width: 640px; }
  .sticker h2 { margin: 0 0 6px; font-size: 15px; color: #7a6400; }
  .sticker p { margin: 0 0 10px; font-size: 13px; line-height: 1.5; color: #555; }
  .eq { margin: 8px 0; font-size: 17px; color: #1a1a1a; }
  .line { margin: 8px 0; font-size: 17px; line-height: 1.7; color: #1a1a1a; }
  img.sticker-img { max-width: 640px; cursor: grab; }
</style>
</head>
<body>
<button id="toImage">이미지로 바꾸기 (끌어다 놓기 가능)</button>
<div id="list"></div>
<script>
const blocks = __DATA__;
const list = document.getElementById("list");

for (const block of blocks) {
  const card = document.createElement("div");
  card.className = "sticker";

  const title = document.createElement("h2");
  title.textContent = block.category;
  card.appendChild(title);

  if (block.lines) {
    // 새 형식: 글자와 수식이 섞인 줄. $...$ 부분만 수식으로 그린다.
    for (const line of block.lines) {
      const row = document.createElement("div");
      row.className = "line";
      row.textContent = line;
      renderMathInElement(row, {
        delimiters: [{ left: "$", right: "$", display: false }],
        throwOnError: false,
      });
      card.appendChild(row);
    }
  } else {
    // 예전 형식: 설명 + 수식 목록
    const text = document.createElement("p");
    text.textContent = block.text_content;
    card.appendChild(text);
    for (const latex of block.latex_equations) {
      const eq = document.createElement("div");
      eq.className = "eq";
      katex.render(latex, eq, { displayMode: true, throwOnError: false });
      card.appendChild(eq);
    }
  }
  list.appendChild(card);
}

// 카드를 PNG 이미지로 바꾼다. <img>가 되어야 굿노트로 끌어다 놓을 수 있다.
document.getElementById("toImage").onclick = async () => {
  for (const card of [...document.querySelectorAll(".sticker")]) {
    const url = await htmlToImage.toPng(card, { pixelRatio: 2 });
    const img = document.createElement("img");
    img.className = "sticker-img";
    img.src = url;
    card.replaceWith(img);
  }
};
</script>
</body>
</html>
"""

page = HTML.replace("__DATA__", json.dumps(data["blocks"], ensure_ascii=False))
(OUT / "7_stickers.html").write_text(page, encoding="utf-8")
print(f"저장: {OUT / '7_stickers.html'}")
