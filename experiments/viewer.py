"""사진을 올리면 OpenCV로 원근 보정한 뒤 LLM에 보내 결과를 보여주는 테스트 페이지.

실행: python viewer.py  →  브라우저에서 http://localhost:8000
"""
import base64
import io
import json
import re
import threading
import time
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

import cv2
import numpy as np
from google.genai import errors
from PIL import Image, ImageOps

import step6
from layout import extract_layout
from perspective import correct
from step6 import load_api_key

# 3.8 Flash는 응답이 1~4분 걸려서, 한도가 넉넉하고 빠른 Flash-Lite로 바꿔 씀 (step6 원본은 그대로 둠)
MODEL = step6.MODEL = "gemini-3.5-flash-lite"
RUNS = 10   # 사진 1장당 LLM 호출 횟수 (차례로 보냄)

PAGE = """<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>판서 처리 테스트</title>
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/katex@0.16.9/dist/katex.min.css">
<script src="https://cdn.jsdelivr.net/npm/katex@0.16.9/dist/katex.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/katex@0.16.9/dist/contrib/auto-render.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/html-to-image@1.11.11/dist/html-to-image.js"></script>
<style>
  body { margin: 0; padding: 20px; font-family: -apple-system, "Apple SD Gothic Neo", sans-serif; background: #f3f4f6; }
  .top { display: flex; gap: 12px; align-items: center; flex-wrap: wrap; margin-bottom: 16px; }
  button { font-size: 15px; padding: 8px 16px; border: 0; border-radius: 8px; background: #0b7a55; color: #fff; }
  button:disabled { background: #999; }
  .panel { background: #fff; border-radius: 12px; padding: 14px; min-width: 0; }
  #save { background: #455a64; }
  #save:disabled { background: #999; }
  /* 왼쪽: 요약·회차 목록(스크롤해도 고정), 오른쪽: 선택한 회차 상세 */
  .layout { display: grid; grid-template-columns: 330px minmax(0, 1fr); gap: 16px; align-items: start; }
  .side { position: sticky; top: 12px; max-height: calc(100vh - 24px); overflow-y: auto; box-sizing: border-box; }
  .stats { font-size: 13px; margin: 4px 0 10px; line-height: 1.7; }
  .stats b { color: #0b7a55; }
  table { border-collapse: collapse; width: 100%; font-size: 13px; }
  th, td { padding: 6px 6px; border-bottom: 1px solid #eee; text-align: right; white-space: nowrap; }
  th:first-child, td:first-child { text-align: left; }
  th { font-size: 12px; color: #666; }
  tbody tr { cursor: pointer; }
  tbody tr:hover { background: #f5f9f7; }
  tbody tr.on { background: #0b7a55; color: #fff; }
  tbody tr.on td { color: #fff; }
  .st-wait { color: #999; } .st-run { color: #1e88e5; font-weight: 600; } .st-ok { color: #0b7a55; } .st-err { color: #c62828; font-weight: 600; }
  #all { width: 100%; margin-top: 10px; background: #fff; color: #0b7a55; border: 1px solid #0b7a55; }
  #all.on { background: #0b7a55; color: #fff; }
  #all:disabled { color: #bbb; border-color: #e3e3e3; background: #f7f7f7; }
  .keys { font-size: 12px; color: #888; margin-top: 8px; }
  kbd { border: 1px solid #ccc; border-radius: 3px; padding: 0 4px; font-size: 11px; background: #fafafa; }
  .empty { color: #999; font-size: 14px; padding: 40px 0; text-align: center; }
  .head { display: flex; gap: 10px; align-items: baseline; flex-wrap: wrap; margin-bottom: 8px; }
  .head h2 { margin: 0; }
  .head .status { margin: 0; }
  /* 상세: 왼쪽 사진(스크롤해도 고정), 오른쪽 인식 텍스트 */
  .split { display: grid; grid-template-columns: minmax(0, 1.15fr) minmax(0, 1fr); gap: 16px; align-items: start; }
  .split > .stage { position: sticky; top: 12px; }
  .split .block:first-child h3 { margin-top: 0; }
  .offstage { position: absolute; left: -20000px; top: 0; width: 1000px; }   /* 숨김 상태에서도 수식 PNG를 찍을 수 있게 화면 밖에 둠 */
  .cmp { display: grid; grid-template-columns: repeat(auto-fill, minmax(300px, 1fr)); gap: 10px; }
  .cmp > div { border: 1px solid #eee; border-radius: 8px; padding: 8px 10px; min-width: 0; overflow-x: auto; cursor: pointer; }
  .cmp > div:hover { border-color: #0b7a55; }
  .cmp h4 { margin: 0 0 4px; font-size: 13px; }
  .cmp .line { font-size: 14px; }
  @media (max-width: 900px) {
    .layout, .split { grid-template-columns: 1fr; }
    .side, .split > .stage { position: static; max-height: none; }
  }
  .panel h2 { margin: 0 0 4px; font-size: 16px; }
  .status { font-size: 15px; font-weight: 600; margin: 6px 0 10px; color: #0b7a55; min-height: 20px; }
  .status.err { color: #c62828; }
  .panel img { max-width: 100%; border-radius: 6px; display: block; margin-bottom: 10px; }
  .note { font-size: 12px; color: #777; margin-bottom: 8px; }
  .block h3 { margin: 10px 0 4px; font-size: 13px; color: #666; }
  .line { margin: 4px 0; font-size: 16px; line-height: 1.6; }
  pre { background: #f6f6f6; padding: 10px; border-radius: 8px; white-space: pre-wrap; font-size: 11px; }
  .inkbox { border-radius: 6px; padding: 6px; margin-bottom: 4px; }
  .section { margin: 14px 0 6px; font-size: 13px; font-weight: 700; color: #333; border-top: 1px solid #eee; padding-top: 10px; }
  .sticker { display: inline-block; padding: 10px 14px; color: #111; font-size: 20px; line-height: 1.7; max-width: 900px; }
  .sticker .line { font-size: 20px; margin: 2px 0; }
  .dl { font-size: 12px; margin: 0 0 10px; display: inline-block; }
  .stage { position: relative; margin-bottom: 10px; }
  .stage img { margin: 0; }
  .box { position: absolute; border: 2px solid; box-sizing: border-box; border-radius: 3px; }
  .box span { position: absolute; top: 0; left: 0; color: #fff; font-size: 12px; font-weight: 700; padding: 0 4px; }
  .tag { display: inline-block; color: #fff; font-size: 12px; font-weight: 700; padding: 0 6px; border-radius: 4px; margin-right: 6px; }
  .bg-checker { background: repeating-conic-gradient(#ddd 0% 25%, #fff 0% 50%) 0 0 / 20px 20px; }
  .bg-white { background: #fff; outline: 1px solid #ddd; }
  .bg-black { background: #222; }
</style>
</head>
<body>
<div class="top">
  <input type="file" id="file" accept="image/*">
  <button id="go" disabled>처리하기</button>
  <span class="note">모델: __MODEL__ · OpenCV 원근 보정 → LLM · 사진 1장당 __RUNS__회 차례로 호출 (분당 12회 제한)</span>
  <button id="save" disabled>결과 JSON 저장</button>
  <span class="note">PNG 뒤 배경:
    <label><input type="radio" name="bg" value="checker" checked> 체크무늬(투명 확인)</label>
    <label><input type="radio" name="bg" value="white"> 흰색(굿노트)</label>
    <label><input type="radio" name="bg" value="black"> 검정</label>
  </span>
</div>
<div class="layout">
  <aside class="panel side">
    <h2>요약</h2>
    <div class="stats" id="stats">사진을 고르고 처리하기를 누르세요.</div>
    <table><thead><tr><th>회차</th><th>상태</th><th>LLM</th><th>블록</th><th>줄</th></tr></thead><tbody id="rows"></tbody></table>
    <button id="all" disabled>전체 비교</button>
    <div class="keys"><kbd>←</kbd> <kbd>→</kbd> 이전·다음 회차 · <kbd>A</kbd> 전체 비교 · 회차를 바꿔도 스크롤 위치는 그대로</div>
  </aside>
  <main class="panel">
    <div id="detail" style="position: relative;"><div class="empty">회차를 고르면 여기에 결과가 나와요</div></div>
  </main>
</div>
<script>
const $ = id => document.getElementById(id);
let file = null;
$("file").onchange = () => { file = $("file").files[0]; $("go").disabled = !file; };
const bgNow = () => document.querySelector("input[name=bg]:checked").value;
document.querySelectorAll("input[name=bg]").forEach(r => r.onchange = () => {
  document.querySelectorAll(".inkbox").forEach(box => box.className = "inkbox bg-" + r.value);
});

// 재시도·대기가 있었으면 상태 줄 뒤에 붙임
function extra(d) {
  const parts = [];
  if (d.retries) parts.push(`503으로 재시도 ${d.retries}회`);
  if (d.waited) parts.push(`대기 ${d.waited.toFixed(0)}초`);
  if (d.input_tokens) parts.push(`입력 ${d.input_tokens}토큰`);
  return parts.length ? ` (${parts.join(", ")})` : "";
}

function el(tag, cls, text) { const e = document.createElement(tag); if (cls) e.className = cls; if (text) e.textContent = text; return e; }

function mathLine(text) {
  const row = el("div", "line", text);
  renderMathInElement(row, { delimiters: [{ left: "$", right: "$", display: false }], throwOnError: false });
  return row;
}

// 이미지(PNG) 하나를 배경 상자에 담고 내려받기 링크를 붙임
function pngBox(url, name) {
  const wrap = el("div");
  const box = el("div", "inkbox bg-" + bgNow());
  const img = el("img"); img.src = url; box.appendChild(img); wrap.appendChild(box);
  const a = el("a", "dl", "PNG 내려받기"); a.href = url; a.download = name; wrap.appendChild(a);
  return wrap;
}

// 블록 순서·이어짐 표시
const COLORS = ["#e53935", "#43a047", "#1e88e5", "#fb8c00", "#8e24aa", "#00acc1", "#6d4c41", "#3949ab", "#c0ca33", "#d81b60"];
const ordered = result => [...result.blocks].sort((a, b) => a.order - b.order);
const color = block => COLORS[(block.order - 1) % COLORS.length];
function label(block, result) {
  const from = result.blocks.find(b => b.id === block.continues_from);
  return from ? `${block.order} ← ${from.order}에서 이어짐` : `${block.order}`;
}
function tag(block, result) {
  const t = el("span", "tag", label(block, result)); t.style.background = color(block); return t;
}

// 사진 위에 LLM이 준 블록 박스를 번호와 함께 겹쳐 그림 (box_2d = [ymin, xmin, ymax, xmax], 0~1000)
function stage(src, result) {
  const s = el("div", "stage");
  const img = el("img"); img.src = src; s.appendChild(img);
  for (const block of ordered(result)) {
    const [y1, x1, y2, x2] = block.box_2d || [];
    if (y2 === undefined) continue;
    const box = el("div", "box");
    Object.assign(box.style, { left: x1 / 10 + "%", top: y1 / 10 + "%", width: (x2 - x1) / 10 + "%",
                               height: (y2 - y1) / 10 + "%", borderColor: color(block) });
    const t = el("span", "", label(block, result).replace("에서 이어짐", "")); t.style.background = color(block);
    box.appendChild(t); box.title = block.category; s.appendChild(box);
  }
  return s;
}

// LLM 결과를 블록마다 깔끔한 수식 이미지(투명 PNG)로 바꿈 (팀원 step7의 스티커 방식)
async function renderStickers(target, result, prefix) {
  target.appendChild(el("div", "section", "정리된 수식 이미지 (굿노트용, 투명 PNG, 읽는 순서대로)"));
  await document.fonts.ready;                       // KaTeX 글꼴이 다 불러와진 뒤에 찍어야 깨지지 않음
  for (const [i, block] of ordered(result).entries()) {
    const head = el("div"); head.appendChild(tag(block, result)); target.appendChild(head);
    const card = el("div", "sticker");
    block.lines.forEach(line => card.appendChild(mathLine(line)));
    target.appendChild(card);                        // 화면에 붙어 있어야 이미지로 찍을 수 있음
    try {
      const url = await htmlToImage.toPng(card, { pixelRatio: 2 });
      card.replaceWith(pngBox(url, `${prefix}formula_${i + 1}.png`));
    } catch (e) {
      card.after(el("div", "note", "이미지 변환 실패: " + e.message));
    }
  }
}

function renderText(target, result) {
  for (const block of ordered(result)) {
    const b = el("div", "block");
    const h = el("h3"); h.appendChild(tag(block, result)); h.appendChild(document.createTextNode(block.category));
    b.appendChild(h);
    block.lines.forEach(line => b.appendChild(mathLine(line)));
    target.appendChild(b);
  }
}

// ---------- 같은 사진을 RUNS번 차례로 보내고 회차별로 비교 ----------
const RUNS = __RUNS__;
let runs = [];          // 회차마다 { state: wait/run/ok/err, data, error, total, el }
let current = null;     // 지금 보고 있는 탭: 회차 번호(0부터) 또는 "all"

const sec = v => v === undefined ? "" : `${v.toFixed(1)}초`;
const lineCount = r => r.blocks.reduce((n, b) => n + b.lines.length, 0);
const STATE = { wait: "대기", run: "처리 중", ok: "완료", err: "실패" };

function stats(values) {
  const v = [...values].sort((a, b) => a - b);
  const mid = v.length % 2 ? v[(v.length - 1) / 2] : (v[v.length / 2 - 1] + v[v.length / 2]) / 2;
  return { avg: v.reduce((a, b) => a + b, 0) / v.length, min: v[0], max: v[v.length - 1], mid };
}

function renderStats() {
  const ok = runs.filter(r => r.state === "ok");
  const done = runs.filter(r => r.state === "ok" || r.state === "err").length;
  if (!ok.length) { $("stats").textContent = `진행 ${done}/${RUNS} · 아직 성공한 회차 없음`; return; }
  const llm = stats(ok.map(r => r.data.seconds)), total = stats(ok.map(r => r.total));
  const blocks = stats(ok.map(r => r.data.result.blocks.length));
  const retries = ok.reduce((n, r) => n + (r.data.retries || 0), 0);
  const waited = ok.reduce((n, r) => n + (r.data.waited || 0), 0);
  $("stats").innerHTML =
    `진행 <b>${done}/${RUNS}</b> · 성공 <b>${ok.length}</b> · 실패 <b>${runs.filter(r => r.state === "err").length}</b><br>` +
    `LLM 응답: 평균 <b>${sec(llm.avg)}</b> · 중앙값 ${sec(llm.mid)} · 최소 ${sec(llm.min)} · 최대 ${sec(llm.max)}<br>` +
    `전체(브라우저 기준): 평균 <b>${sec(total.avg)}</b> · 최소 ${sec(total.min)} · 최대 ${sec(total.max)}<br>` +
    `블록 수: ${blocks.min === blocks.max ? blocks.min : `${blocks.min}~${blocks.max}`}개 (평균 ${blocks.avg.toFixed(1)})` +
    ` · 503 재시도 ${retries}회 · 한도 대기 ${waited.toFixed(0)}초`;
}

function renderTable() {
  const rows = $("rows"); rows.innerHTML = "";
  runs.forEach((r, i) => {
    const d = r.data, tr = el("tr");
    const status = r.state === "run" ? `처리 중 ${sec((performance.now() - r.t0) / 1000)}`
      : STATE[r.state] + (d && d.retries ? ` (재시도${d.retries})` : "");
    const cells = [`${i + 1}`, status, d ? sec(d.seconds) : "", d ? d.result.blocks.length : "", d ? lineCount(d.result) : ""];
    cells.forEach((c, k) => tr.appendChild(el("td", k === 1 ? "st-" + r.state : "", String(c))));
    if (r.state === "err") tr.title = r.error;
    if (current === i) tr.className = "on";
    if (r.el) tr.onclick = () => show(i);
    rows.appendChild(tr);
  });
}

function renderAllButton() {
  $("all").disabled = !runs.some(r => r.state === "ok");
  $("all").className = current === "all" ? "on" : "";
}
$("all").onclick = () => show("all");

function refresh() { renderStats(); renderTable(); renderAllButton(); }

// 처리 중 회차의 경과 시간만 갱신 (표를 통째로 다시 그리면 클릭이 씹혀서)
function tick() {
  const r = runs.find(r => r.state === "run"), td = document.querySelector("td.st-run");
  if (r && td) td.textContent = `처리 중 ${sec((performance.now() - r.t0) / 1000)}`;
}

// 회차 상세: 보정 사진 + 박스, 텍스트, 수식 PNG. 화면 밖(offstage)에 먼저 붙여서 PNG를 찍어 둠
function buildDetail(i) {
  const r = runs[i], box = el("div", "offstage");
  $("detail").appendChild(box);
  r.el = box;
  const head = el("div", "head"); head.appendChild(el("h2", "", `${i + 1}회차`)); box.appendChild(head);
  if (r.state === "err") { head.appendChild(el("div", "status err", `실패: ${r.error}`)); return; }
  const d = r.data;
  head.appendChild(el("div", "status", `LLM ${sec(d.seconds)} + 보정 ${(d.prep_seconds * 1000).toFixed(0)}ms · 전체 ${sec(r.total)}` + extra(d)));
  head.appendChild(el("span", "note", `블록 ${d.result.blocks.length}개 · ${lineCount(d.result)}줄`));
  if (!d.corrected) box.appendChild(el("div", "note", "화면 사각형을 못 찾아서 원본을 그대로 보냈어요 (칠판이 사진을 꽉 채운 경우 등)"));
  const split = el("div", "split");
  split.appendChild(stage(d.image, d.result));
  const text = el("div"); renderText(text, d.result); split.appendChild(text);
  box.appendChild(split);
  const stickers = el("div"); box.appendChild(stickers);
  const json = el("details"); json.appendChild(el("summary", "", "원본 JSON"));
  json.appendChild(el("pre", "", JSON.stringify(d.result, null, 2))); box.appendChild(json);
  renderStickers(stickers, d.result, `run${i + 1}_`);
}

// 전체 비교: 성공한 회차의 인식 텍스트를 나란히
function buildCompare() {
  const wrap = el("div", "cmp");
  runs.forEach((r, i) => {
    if (r.state !== "ok") return;
    const card = el("div");
    card.onclick = () => show(i); card.title = "눌러서 이 회차 자세히 보기";
    card.appendChild(el("h4", "", `${i + 1}회차 · 블록 ${r.data.result.blocks.length}개 · ${sec(r.data.seconds)}`));
    for (const block of ordered(r.data.result)) {
      const h = el("div", "note"); h.appendChild(tag(block, r.data.result)); h.appendChild(document.createTextNode(block.category));
      card.appendChild(h);
      block.lines.forEach(line => card.appendChild(mathLine(line)));
    }
    wrap.appendChild(card);
  });
  return wrap;
}

let compareEl = null;
function show(which) {
  current = which;
  runs.forEach(r => r.el && (r.el.className = "offstage"));
  if (compareEl) { compareEl.remove(); compareEl = null; }
  const empty = $("detail").querySelector(".empty"); if (empty) empty.remove();
  if (which === "all") { compareEl = buildCompare(); $("detail").appendChild(compareEl); }
  else runs[which].el.className = "";
  refresh();
}

async function runOnce(i) {
  const r = runs[i];
  r.state = "run"; r.t0 = performance.now();
  try {
    const res = await fetch("/llm", { method: "POST", body: file });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error);
    r.data = data; r.state = "ok";
  } catch (e) {
    r.error = e.message; r.state = "err";
  }
  r.total = (performance.now() - r.t0) / 1000;
  buildDetail(i);
  if (current === null || (current === "all")) show(current ?? i);   // 처음 끝난 회차를 바로 보여줌
}

$("go").onclick = async () => {
  $("go").disabled = $("save").disabled = true;
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

// 회차별 결과를 JSON으로 저장 (사진 data URL은 빼고)
$("save").onclick = () => {
  const out = { file: file?.name, model: "__MODEL__", runs: runs.map((r, i) => ({
    run: i + 1, state: r.state, total_seconds: r.total, error: r.error,
    ...(r.data ? { seconds: r.data.seconds, prep_seconds: r.data.prep_seconds, corrected: r.data.corrected,
                   retries: r.data.retries, waited: r.data.waited, input_tokens: r.data.input_tokens,
                   result: r.data.result } : {}),
  })) };
  const a = el("a"); a.download = `runs_${(file?.name || "photo").replace(/\.[^.]+$/, "")}.json`;
  a.href = URL.createObjectURL(new Blob([JSON.stringify(out, null, 2)], { type: "application/json" }));
  a.click();
};
</script>
</body>
</html>
""".replace("__MODEL__", MODEL).replace("__RUNS__", str(RUNS))


def _escape_fix(m):
    s = m.group(0)
    valid = s in ('\\\\', '\\"', '\\/') or re.fullmatch(r"\\u[0-9a-fA-F]{4}", s) or (len(s) == 2 and s[1] in "bfnrt")
    return s if valid else "\\" + s


def load_json(raw):
    # 모델이 LaTeX를 역슬래시 하나로 보낼 때가 있음: \lim 은 JSON 오류, \frac·\times 는 \f(폼피드)·\t(탭)으로 깨짐
    # → JSON에서 올바른 이스케이프(\\ \" \/ \uXXXX, 뒤에 글자가 안 붙은 \n \t 등)만 두고 나머지 역슬래시는 두 개로 고침
    return json.loads(re.sub(r'\\(\\|"|/|u[0-9a-fA-F]{4}|[a-zA-Z]+|.)', _escape_fix, raw), strict=False)


def decode(data):
    """업로드 바이트 → OpenCV 이미지 (아이폰 사진 회전 정보 반영)."""
    img = ImageOps.exif_transpose(Image.open(io.BytesIO(data))).convert("RGB")
    return cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)


def encode(bgr_or_bgra, ext, max_side=None):
    if max_side and max(bgr_or_bgra.shape[:2]) > max_side:
        s = max_side / max(bgr_or_bgra.shape[:2])
        bgr_or_bgra = cv2.resize(bgr_or_bgra, None, fx=s, fy=s, interpolation=cv2.INTER_AREA)
    ok, buf = cv2.imencode(ext, bgr_or_bgra, [cv2.IMWRITE_JPEG_QUALITY, 95] if ext == ".jpg" else [])
    return buf.tobytes()


def data_url(raw, mime):
    return f"data:{mime};base64,{base64.b64encode(raw).decode()}"


RPM_GUARD = 12                 # 모델 한도는 분당 15회. 여유 두고 12회까지만 보냄 (재시도 포함)
RETRY_WAITS = [3, 6]           # 503이면 3초, 6초 쉬고 다시 (최대 2번)
_calls, _lock = deque(), threading.Lock()


def wait_for_slot():
    """최근 60초 안에 보낸 호출이 12회면 자리가 날 때까지 기다린다. 기다린 초를 돌려준다."""
    waited = 0.0
    while True:
        with _lock:
            now = time.time()
            while _calls and now - _calls[0] > 60:
                _calls.popleft()
            if len(_calls) < RPM_GUARD:
                _calls.append(now)
                return waited
            pause = 60 - (now - _calls[0]) + 0.1
        print(f"  분당 {RPM_GUARD}회 도달 → {pause:.0f}초 대기")
        time.sleep(pause)
        waited += pause


def ask_llm(jpegs):
    """503(서버 혼잡)만 재시도. 429(한도 초과)는 재시도하지 않고 바로 알림."""
    waited = 0.0
    for attempt in range(len(RETRY_WAITS) + 1):
        waited += wait_for_slot()
        start = time.time()
        try:
            # 필기 + 블록 위치·읽는 순서·이어짐 (호출 1회)
            text, tokens = extract_layout(jpegs)
            return {"seconds": time.time() - start, "waited": waited, "retries": attempt,
                    "input_tokens": tokens, "result": load_json(text)}
        except errors.APIError as e:
            if e.code == 429:
                raise RuntimeError("Gemini 사용 한도 초과(429). 잠시 후 다시 시도하세요.") from e
            if e.code != 503 or attempt == len(RETRY_WAITS):
                raise
            print(f"  503 서버 혼잡 → {RETRY_WAITS[attempt]}초 후 재시도 ({attempt + 1}/{len(RETRY_WAITS)})")
            time.sleep(RETRY_WAITS[attempt])
            waited += RETRY_WAITS[attempt]


def handle_llm(bgr):
    """OpenCV로 원근 보정한 사진을 LLM에 보냄. 화면 사각형을 못 찾으면 원본으로 대신함."""
    start = time.time()
    fixed = correct(bgr)
    prep = time.time() - start
    src = fixed if fixed is not None else bgr
    out = ask_llm([encode(src, ".jpg")])
    return {**out, "prep_seconds": prep, "corrected": fixed is not None,
            "image": data_url(encode(src, ".jpg", 1200), "image/jpeg")}


class Handler(BaseHTTPRequestHandler):
    def send(self, code, body, content_type):
        data = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        self.send(200, PAGE, "text/html; charset=utf-8")

    def do_POST(self):
        url = urlparse(self.path)
        data = self.rfile.read(int(self.headers["Content-Length"]))
        start = time.time()
        try:
            body = handle_llm(decode(data))
            print(f"{url.path} {len(data) / 1024:.0f}KB → {time.time() - start:.1f}초")
            self.send(200, json.dumps(body, ensure_ascii=False), "application/json")
        except Exception as error:
            print(f"{url.path} {len(data) / 1024:.0f}KB → 실패 ({time.time() - start:.1f}초): "
                  f"{type(error).__name__}: {error}")
            self.send(500, json.dumps({"error": f"{type(error).__name__}: {str(error)[:300]}"}, ensure_ascii=False),
                      "application/json")

    def log_message(self, *args):   # 기본 접속 로그는 끔 (위에서 직접 찍음)
        pass


if __name__ == "__main__":
    load_api_key()
    print("http://localhost:8000 에서 열기 (종료: Ctrl+C)")
    ThreadingHTTPServer(("127.0.0.1", 8000), Handler).serve_forever()
