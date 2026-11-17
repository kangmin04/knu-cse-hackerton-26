"""사진을 올리면 판서 파이프라인(pipeline/note_pipeline.py)을 10회 차례로 돌려 회차별 결과를 비교하는 테스트 페이지.

같은 사진·같은 코드로 여러 번 돌려 Gemini 응답 속도와 결과 흔들림을 잰다.
실행: python experiments/viewer.py  →  브라우저에서 http://localhost:8000
"""
import base64
import io
import json
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import cv2
import numpy as np
from PIL import Image, ImageOps

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))
import note_pipeline as pipeline  # noqa: E402

RUNS = 10  # 사진 1장당 파이프라인 실행 횟수 (차례로 보냄)
PENS = {"black": "검은 펜(프로젝터)", "red": "빨간 펜(프로젝터)", "board": "칠판"}

PAGE = r"""<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>판서 파이프라인 테스트</title>
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/katex@0.16.9/dist/katex.min.css">
<script src="https://cdn.jsdelivr.net/npm/katex@0.16.9/dist/katex.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/katex@0.16.9/dist/contrib/auto-render.min.js"></script>
<style>
  body { margin: 0; padding: 20px; font-family: -apple-system, "Apple SD Gothic Neo", sans-serif; background: #f3f4f6; }
  .top { display: flex; gap: 12px; align-items: center; flex-wrap: wrap; margin-bottom: 16px; }
  button { font-size: 15px; padding: 8px 16px; border: 0; border-radius: 8px; background: #0b7a55; color: #fff; cursor: pointer; }
  button:disabled { background: #999; cursor: default; }
  #save { background: #455a64; }
  #save:disabled { background: #999; }
  .opts { font-size: 13px; color: #555; }
  .note { font-size: 12px; color: #777; }
  .panel { background: #fff; border-radius: 12px; padding: 14px; min-width: 0; }
  .panel h2 { margin: 0 0 4px; font-size: 16px; }
  /* 왼쪽: 요약·회차 목록(스크롤해도 고정), 오른쪽: 선택한 회차 상세 */
  .layout { display: grid; grid-template-columns: 330px minmax(0, 1fr); gap: 16px; align-items: start; }
  .side { position: sticky; top: 12px; max-height: calc(100vh - 24px); overflow-y: auto; box-sizing: border-box; }
  .stats { font-size: 13px; margin: 4px 0 10px; line-height: 1.7; }
  .stats b { color: #0b7a55; }
  table { border-collapse: collapse; width: 100%; font-size: 13px; }
  th, td { padding: 6px; border-bottom: 1px solid #eee; text-align: right; white-space: nowrap; }
  th:first-child, td:first-child { text-align: left; }
  th { font-size: 12px; color: #666; }
  tbody tr { cursor: pointer; }
  tbody tr:hover { background: #f5f9f7; }
  tbody tr.on, tbody tr.on td { background: #0b7a55; color: #fff; }
  .st-wait { color: #999; } .st-run { color: #1e88e5; font-weight: 600; } .st-ok { color: #0b7a55; } .st-err { color: #c62828; font-weight: 600; }
  #all { width: 100%; margin-top: 10px; background: #fff; color: #0b7a55; border: 1px solid #0b7a55; }
  #all.on { background: #0b7a55; color: #fff; }
  #all:disabled { color: #bbb; border-color: #e3e3e3; background: #f7f7f7; }
  .keys { font-size: 12px; color: #888; margin-top: 8px; }
  kbd { border: 1px solid #ccc; border-radius: 3px; padding: 0 4px; font-size: 11px; background: #fafafa; }
  .empty { color: #999; font-size: 14px; padding: 40px 0; text-align: center; }
  .head { display: flex; gap: 10px; align-items: baseline; flex-wrap: wrap; margin-bottom: 8px; }
  .head h2 { margin: 0; }
  .status { font-size: 15px; font-weight: 600; color: #0b7a55; }
  .status.err { color: #c62828; }
  /* 상세: 왼쪽 사진(스크롤해도 고정), 오른쪽 카드 목록 */
  .split { display: grid; grid-template-columns: minmax(0, 1.15fr) minmax(0, 1fr); gap: 16px; align-items: start; }
  .stage { position: sticky; top: 12px; }
  .stage img { width: 100%; display: block; border-radius: 6px; }
  .box { position: absolute; border: 2px solid; box-sizing: border-box; border-radius: 3px; }
  .box span { position: absolute; top: 0; left: 0; color: #fff; font-size: 12px; font-weight: 700; padding: 0 4px; }
  .box.rough { border: 1px dashed #555; display: none; }
  body.show-rough .box.rough { display: block; }
  .card { border: 1px solid #eee; border-left: 4px solid; border-radius: 8px; padding: 8px 10px; margin-bottom: 10px; }
  .card h3 { margin: 0 0 6px; font-size: 14px; }
  .tag { display: inline-block; color: #fff; font-size: 12px; font-weight: 700; padding: 0 6px; border-radius: 4px; margin-right: 6px; }
  .inkbox { border-radius: 6px; padding: 6px; display: inline-block; max-width: 100%; box-sizing: border-box; }
  .inkbox img { max-width: 100%; display: block; }
  .bg-checker { background: repeating-conic-gradient(#ddd 0% 25%, #fff 0% 50%) 0 0 / 20px 20px; }
  .bg-white { background: #fff; outline: 1px solid #ddd; }
  .bg-black { background: #222; }
  .dl { font-size: 12px; margin-left: 8px; }
  .line { margin: 4px 0; font-size: 15px; line-height: 1.6; }
  pre { background: #f6f6f6; padding: 10px; border-radius: 8px; white-space: pre-wrap; font-size: 11px; }
  .cmp { display: grid; grid-template-columns: repeat(auto-fill, minmax(300px, 1fr)); gap: 10px; }
  .cmp > div { border: 1px solid #eee; border-radius: 8px; padding: 8px 10px; min-width: 0; overflow-x: auto; cursor: pointer; }
  .cmp > div:hover { border-color: #0b7a55; }
  .cmp h4 { margin: 0 0 4px; font-size: 13px; }
  .cmp .line { font-size: 14px; }
  @media (max-width: 900px) {
    .layout, .split { grid-template-columns: 1fr; }
    .side, .stage { position: static; max-height: none; }
  }
</style>
</head>
<body>
<div class="top">
  <input type="file" id="file" accept="image/*">
  <span class="opts">펜: __PEN_RADIOS__</span>
  <button id="go" disabled>처리하기</button>
  <button id="save" disabled>결과 JSON 저장</button>
  <span class="opts">PNG 뒤 배경:
    <label><input type="radio" name="bg" value="checker" checked> 체크무늬</label>
    <label><input type="radio" name="bg" value="white"> 흰색(굿노트)</label>
    <label><input type="radio" name="bg" value="black"> 검정</label>
  </span>
  <label class="opts"><input type="checkbox" id="rough"> Gemini 원래 상자(점선)도 보기</label>
  <span class="note">모델: __MODEL__ · 사진 1장당 __RUNS__회 차례로 실행</span>
</div>
<div class="layout">
  <aside class="panel side">
    <h2>요약</h2>
    <div class="stats" id="stats">사진과 펜을 고르고 처리하기를 누르세요.</div>
    <table><thead><tr><th>회차</th><th>상태</th><th>LLM</th><th>카드</th><th>줄</th></tr></thead><tbody id="rows"></tbody></table>
    <button id="all" disabled>전체 비교</button>
    <div class="keys"><kbd>←</kbd> <kbd>→</kbd> 이전·다음 회차 · <kbd>A</kbd> 전체 비교 · 회차를 바꿔도 스크롤 위치는 그대로</div>
  </aside>
  <main class="panel">
    <div id="detail"><div class="empty">회차를 고르면 여기에 결과가 나와요</div></div>
  </main>
</div>
<script>
const $ = id => document.getElementById(id);
const RUNS = __RUNS__;
const PEN_NAMES = __PEN_NAMES__;
let file = null;
let runs = [];          // 회차마다 { state: wait/run/ok/err, data, error, total, el }
let current = null;     // 지금 보고 있는 것: 회차 번호(0부터) 또는 "all"
let pen = null;         // 이번 처리에 쓴 펜 (처리 중에 바꿔도 영향 없게 시작할 때 고정)

$("file").onchange = () => { file = $("file").files[0]; $("go").disabled = !file; };
const bgNow = () => document.querySelector("input[name=bg]:checked").value;
document.querySelectorAll("input[name=bg]").forEach(r => r.onchange = () => {
  document.querySelectorAll(".inkbox").forEach(box => box.className = "inkbox bg-" + r.value);
});
$("rough").onchange = () => document.body.classList.toggle("show-rough", $("rough").checked);

function el(tag, cls, text) { const e = document.createElement(tag); if (cls) e.className = cls; if (text !== undefined) e.textContent = text; return e; }
function mathLine(text) {
  const row = el("div", "line", text);
  renderMathInElement(row, { delimiters: [{ left: "$", right: "$", display: false }], throwOnError: false });
  return row;
}

const COLORS = ["#e53935", "#43a047", "#1e88e5", "#fb8c00", "#8e24aa", "#00acc1", "#6d4c41", "#3949ab", "#c0ca33", "#d81b60"];
const color = card => COLORS[(card.no - 1) % COLORS.length];
function tag(card) { const t = el("span", "tag", String(card.no)); t.style.background = color(card); return t; }
const sec = v => v === undefined ? "" : `${v.toFixed(1)}초`;
const lineCount = d => d.cards.reduce((n, c) => n + c.lines.length, 0);
const STATE = { wait: "대기", run: "처리 중", ok: "완료", err: "실패" };

// 잘라낸 사진 위에 카드 상자를 그림. 실선 = 다듬은 상자, 점선 = Gemini가 준 원래 상자
function stage(d) {
  const s = el("div", "stage");
  const img = el("img"); img.src = d.image; s.appendChild(img);
  const [w, h] = d.size;
  const place = (box, [x0, y0, x1, y1]) => Object.assign(box.style, {
    left: x0 / w * 100 + "%", top: y0 / h * 100 + "%", width: (x1 - x0) / w * 100 + "%", height: (y1 - y0) / h * 100 + "%" });
  for (const card of d.cards) {
    const rough = el("div", "box rough"); place(rough, card.box_gemini); s.appendChild(rough);
    const box = el("div", "box"); place(box, card.box); box.style.borderColor = color(card); box.title = card.title;
    const t = el("span", "", String(card.no)); t.style.background = color(card); box.appendChild(t);
    s.appendChild(box);
  }
  return s;
}

// 카드 하나: 번호·제목, 손글씨 PNG, 인식된 글자
function cardView(card, run) {
  const c = el("div", "card"); c.style.borderLeftColor = color(card);
  const h = el("h3"); h.appendChild(tag(card)); h.appendChild(document.createTextNode(card.title)); c.appendChild(h);
  const box = el("div", "inkbox bg-" + bgNow());
  const img = el("img"); img.src = card.ink; box.appendChild(img); c.appendChild(box);
  const a = el("a", "dl", "PNG 내려받기"); a.href = card.ink; a.download = `run${run + 1}_card_${String(card.no).padStart(2, "0")}.png`; c.appendChild(a);
  card.lines.forEach(line => c.appendChild(mathLine(line)));
  return c;
}

function stats(values) {
  const v = [...values].sort((a, b) => a - b);
  const mid = v.length % 2 ? v[(v.length - 1) / 2] : (v[v.length / 2 - 1] + v[v.length / 2]) / 2;
  return { avg: v.reduce((a, b) => a + b, 0) / v.length, min: v[0], max: v[v.length - 1], mid };
}

function renderStats() {
  const ok = runs.filter(r => r.state === "ok");
  const done = runs.filter(r => r.state === "ok" || r.state === "err").length;
  const head = `${PEN_NAMES[pen]} · 진행 <b>${done}/${RUNS}</b> · 성공 <b>${ok.length}</b> · 실패 <b>${runs.filter(r => r.state === "err").length}</b>`;
  if (!ok.length) { $("stats").innerHTML = head; return; }
  const llm = stats(ok.map(r => r.data.seconds)), total = stats(ok.map(r => r.total));
  const cards = stats(ok.map(r => r.data.cards.length));
  const retries = ok.reduce((n, r) => n + r.data.retries, 0);
  const waited = ok.reduce((n, r) => n + r.data.waited, 0);
  $("stats").innerHTML = head + "<br>" +
    `LLM 응답: 평균 <b>${sec(llm.avg)}</b> · 중앙값 ${sec(llm.mid)} · 최소 ${sec(llm.min)} · 최대 ${sec(llm.max)}<br>` +
    `전체(브라우저 기준): 평균 <b>${sec(total.avg)}</b> · 최소 ${sec(total.min)} · 최대 ${sec(total.max)}<br>` +
    `카드 수: ${cards.min === cards.max ? cards.min : `${cards.min}~${cards.max}`}개 (평균 ${cards.avg.toFixed(1)})` +
    ` · 다시 시도 ${retries}회 · 대기 ${waited.toFixed(0)}초`;
}

function renderTable() {
  const rows = $("rows"); rows.innerHTML = "";
  runs.forEach((r, i) => {
    const d = r.data, tr = el("tr");
    const status = r.state === "run" ? `처리 중 ${sec((performance.now() - r.t0) / 1000)}`
      : STATE[r.state] + (d && d.retries ? ` (재시도${d.retries})` : "");
    const cells = [`${i + 1}`, status, d ? sec(d.seconds) : "", d ? d.cards.length : "", d ? lineCount(d) : ""];
    cells.forEach((c, k) => tr.appendChild(el("td", k === 1 ? "st-" + r.state : "", String(c))));
    if (r.state === "err") tr.title = r.error;
    if (current === i) tr.className = "on";
    if (r.el) tr.onclick = () => show(i);
    rows.appendChild(tr);
  });
}

function refresh() {
  renderStats(); renderTable();
  $("all").disabled = !runs.some(r => r.state === "ok");
  $("all").className = current === "all" ? "on" : "";
}
$("all").onclick = () => show("all");

// 처리 중 회차의 경과 시간만 갱신 (표를 통째로 다시 그리면 클릭이 씹혀서)
function tick() {
  const r = runs.find(r => r.state === "run"), td = document.querySelector("td.st-run");
  if (r && td) td.textContent = `처리 중 ${sec((performance.now() - r.t0) / 1000)}`;
}

// 회차 상세: 잘라낸 사진 + 상자 | 카드 목록, 그 아래 원본 JSON
function buildDetail(i) {
  const r = runs[i], box = el("div");
  box.hidden = true;
  $("detail").appendChild(box);
  r.el = box;
  const head = el("div", "head"); head.appendChild(el("h2", "", `${i + 1}회차`)); box.appendChild(head);
  if (r.state === "err") { head.appendChild(el("div", "status err", `실패: ${r.error}`)); return; }
  const d = r.data;
  const extra = [d.retries ? `다시 시도 ${d.retries}회` : "", d.waited ? `대기 ${d.waited.toFixed(0)}초` : ""].filter(Boolean).join(", ");
  head.appendChild(el("div", "status", `LLM ${sec(d.seconds)} · 서버 전체 ${sec(d.server_seconds)} · 브라우저 전체 ${sec(r.total)}` + (extra ? ` (${extra})` : "")));
  head.appendChild(el("span", "note", `카드 ${d.cards.length}개 · ${lineCount(d)}줄 · 화면 ${d.screen_found ? "찾아서 잘라냄" : "자르지 않음"} · ${PEN_NAMES[pen]}`));
  const split = el("div", "split");
  split.appendChild(stage(d));
  const list = el("div"); d.cards.forEach(card => list.appendChild(cardView(card, i))); split.appendChild(list);
  box.appendChild(split);
  const json = el("details"); json.appendChild(el("summary", "", "원본 JSON (카드 이미지 제외)"));
  json.appendChild(el("pre", "", JSON.stringify(strip(d), null, 2))); box.appendChild(json);
}

// 결과에서 이미지 data URL을 뺀 것 (JSON 보기·저장용)
function strip(d) {
  const { image, cards, ...rest } = d;
  return { ...rest, cards: cards.map(({ ink, ...c }) => c) };
}

// 전체 비교: 성공한 회차의 카드 제목·글자를 나란히
function buildCompare() {
  const wrap = el("div", "cmp");
  runs.forEach((r, i) => {
    if (r.state !== "ok") return;
    const card = el("div");
    card.onclick = () => show(i); card.title = "눌러서 이 회차 자세히 보기";
    card.appendChild(el("h4", "", `${i + 1}회차 · 카드 ${r.data.cards.length}개 · ${sec(r.data.seconds)}`));
    for (const c of r.data.cards) {
      const h = el("div", "note"); h.appendChild(tag(c)); h.appendChild(document.createTextNode(c.title)); card.appendChild(h);
      c.lines.forEach(line => card.appendChild(mathLine(line)));
    }
    wrap.appendChild(card);
  });
  return wrap;
}

let compareEl = null;
function show(which) {
  current = which;
  runs.forEach(r => r.el && (r.el.hidden = true));
  if (compareEl) { compareEl.remove(); compareEl = null; }
  const empty = $("detail").querySelector(".empty"); if (empty) empty.remove();
  if (which === "all") { compareEl = buildCompare(); $("detail").appendChild(compareEl); }
  else runs[which].el.hidden = false;
  refresh();
}

async function runOnce(i) {
  const r = runs[i];
  r.state = "run"; r.t0 = performance.now();
  try {
    const res = await fetch(`/run?pen=${pen}`, { method: "POST", body: file });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error);
    r.data = data; r.state = "ok";
  } catch (e) {
    r.error = e.message; r.state = "err";
  }
  r.total = (performance.now() - r.t0) / 1000;
  buildDetail(i);
  if (current === null || current === "all") show(current ?? i);   // 처음 끝난 회차를 바로 보여줌
}

$("go").onclick = async () => {
  $("go").disabled = $("save").disabled = true;
  pen = document.querySelector("input[name=pen]:checked").value;
  $("detail").innerHTML = ""; compareEl = null; current = null;
  runs = Array.from({ length: RUNS }, () => ({ state: "wait" }));
  refresh();
  const ticker = setInterval(tick, 200);
  for (let i = 0; i < RUNS; i++) {
    await runOnce(i);
    refresh();
  }
  clearInterval(ticker);
  refresh();
  $("go").disabled = $("save").disabled = false;
};

document.addEventListener("keydown", e => {
  if (e.target.tagName === "INPUT" || e.metaKey || e.ctrlKey || e.altKey) return;
  const ready = runs.map((r, i) => r.el ? i : null).filter(i => i !== null);
  if (e.key.toLowerCase() === "a" && !$("all").disabled) { show("all"); return; }
  if ((e.key !== "ArrowLeft" && e.key !== "ArrowRight") || !ready.length) return;
  e.preventDefault();
  const pos = typeof current === "number" ? ready.indexOf(current) : -1;
  const next = e.key === "ArrowRight" ? Math.min(pos + 1, ready.length - 1) : Math.max(pos - 1, 0);
  show(ready[pos === -1 ? 0 : next]);
});

// 회차별 결과를 JSON으로 저장 (이미지는 빼고)
$("save").onclick = () => {
  const out = { file: file?.name, model: "__MODEL__", pen, runs: runs.map((r, i) => ({
    run: i + 1, state: r.state, total_seconds: r.total, error: r.error, ...(r.data ? strip(r.data) : {}) })) };
  const a = el("a"); a.download = `runs_${(file?.name || "photo").replace(/\.[^.]+$/, "")}_${pen}.json`;
  a.href = URL.createObjectURL(new Blob([JSON.stringify(out, null, 2)], { type: "application/json" }));
  a.click();
};
</script>
</body>
</html>
"""


def page():
    radios = " ".join(
        f'<label><input type="radio" name="pen" value="{key}"{" checked" if key == "black" else ""}> {name}</label>'
        for key, name in PENS.items()
    )
    return (PAGE.replace("__PEN_RADIOS__", radios)
            .replace("__PEN_NAMES__", json.dumps(PENS, ensure_ascii=False))
            .replace("__MODEL__", pipeline.MODEL)
            .replace("__RUNS__", str(RUNS)))


def decode(data):
    """업로드 바이트 → OpenCV 이미지 (아이폰 사진 회전 정보 반영)."""
    img = ImageOps.exif_transpose(Image.open(io.BytesIO(data))).convert("RGB")
    return cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)


def data_url(img, ext, max_side=None):
    """OpenCV 이미지 → 브라우저에 바로 넣을 수 있는 data URL. max_side를 주면 그 크기로 줄임."""
    if max_side and max(img.shape[:2]) > max_side:
        s = max_side / max(img.shape[:2])
        img = cv2.resize(img, None, fx=s, fy=s, interpolation=cv2.INTER_AREA)
    params = [cv2.IMWRITE_JPEG_QUALITY, 90] if ext == ".jpg" else []
    _, buf = cv2.imencode(ext, img, params)
    mime = "image/jpeg" if ext == ".jpg" else "image/png"
    return f"data:{mime};base64,{base64.b64encode(buf.tobytes()).decode()}"


def handle_run(bgr, pen):
    """파이프라인을 한 번 돌리고, 화면에 보여줄 값(잘라낸 사진, 카드별 손글씨 PNG 등)을 만든다."""
    start = time.time()
    result = pipeline.process(bgr, pen)
    img, mask = result["img"], result["mask"]
    cards = [
        {**card, "ink": data_url(pipeline.card_ink(img, mask, card["box"]), ".png")}
        for card in result["cards"]
    ]
    return {
        "seconds": result["seconds"],
        "retries": result["retries"],
        "waited": result["waited"],
        "server_seconds": time.time() - start,
        "screen_found": result["corners"] is not None,
        "size": [img.shape[1], img.shape[0]],     # 상자 좌표 기준 크기 (화면용 사진은 줄여서 보냄)
        "image": data_url(img, ".jpg", 1200),
        "cards": cards,
    }


class Handler(BaseHTTPRequestHandler):
    def send(self, code, body, content_type):
        data = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        self.send(200, page(), "text/html; charset=utf-8")

    def do_POST(self):
        url = urlparse(self.path)
        pen = parse_qs(url.query).get("pen", ["black"])[0]
        data = self.rfile.read(int(self.headers["Content-Length"]))
        start = time.time()
        try:
            if url.path != "/run" or pen not in PENS:
                raise ValueError(f"잘못된 요청: {self.path}")
            body = handle_run(decode(data), pen)
            print(f"/run pen={pen} {len(data) / 1024:.0f}KB → {time.time() - start:.1f}초", flush=True)
            self.send(200, json.dumps(body, ensure_ascii=False), "application/json")
        except Exception as error:
            message = str(error) if isinstance(error, pipeline.GeminiError) else f"{type(error).__name__}: {error}"
            print(f"/run pen={pen} → 실패 ({time.time() - start:.1f}초): {message}", flush=True)
            self.send(500, json.dumps({"error": message[:300]}, ensure_ascii=False), "application/json")

    def log_message(self, *args):   # 기본 접속 로그는 끔 (위에서 직접 찍음)
        pass


if __name__ == "__main__":
    pipeline.load_api_key()
    print("http://localhost:8000 에서 열기 (종료: Ctrl+C)", flush=True)
    ThreadingHTTPServer(("127.0.0.1", 8000), Handler).serve_forever()
