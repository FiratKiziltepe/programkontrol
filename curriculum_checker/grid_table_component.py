"""Sistem Excel'i ↔ PDF Excel'i yan yana karşılaştırma tablosu (Streamlit components v2, yalnızca görüntüleme).

Veri grid_compare.grid_payload() biçimindedir. Hiçbir metin üretilmez; tablo yalnızca iki kaynağın
değerlerini ve deterministik durumlarını gösterir.
"""
from __future__ import annotations

import streamlit as st

HTML = """
<div class="gx">
  <div class="gx-toolbar">
    <div class="gx-seg" role="tablist"></div>
    <input class="gx-search" type="search" placeholder="Ara: öğrenme çıktısı kodu, tema veya metin…" aria-label="Ara">
    <label class="gx-check"><input type="checkbox" class="gx-fmt" checked> Biçim farklarını eşleşme say</label>
  </div>
  <details class="gx-cols">
    <summary>Sütunlar</summary>
    <div class="gx-colchips"></div>
  </details>
  <div class="gx-legend">
    <span><i class="lg lg-diff"></i>Farklı</span>
    <span><i class="lg lg-only"></i>Yalnızca bir tarafta</span>
    <span><i class="lg lg-fmt"></i>Biçim farkı</span>
    <span><b class="bd bd-tl">PDF✓</b> PDF metin katmanından tamamlandı</span>
    <span><b class="bd bd-gm">Gemini✓</b> Gemini buldu, PDF'de doğrulandı</span>
    <span><b class="bd bd-gu">Gemini?</b> Gemini önerisi doğrulanamadı</span>
    <span class="gx-hint">Satıra tıklayınca tüm alanlar açılır · tabloyu yatay kaydırın</span>
  </div>
  <div class="gx-scroll" tabindex="0"><table class="gx-table"><thead></thead><tbody></tbody></table></div>
  <div class="gx-pager"></div>
  <div class="gx-modal" hidden>
    <div class="gx-dialog" role="dialog" aria-modal="true">
      <header class="gx-mhead">
        <div><div class="gx-mtitle"></div><div class="gx-msub"></div></div>
        <div class="gx-mnav">
          <button class="gx-prev" type="button" title="Önceki (←)">‹</button>
          <button class="gx-next" type="button" title="Sonraki (→)">›</button>
          <button class="gx-close" type="button" title="Kapat (Esc)">✕</button>
        </div>
      </header>
      <label class="gx-check gx-monly"><input type="checkbox" class="gx-onlydiff"> Yalnızca farklı alanlar</label>
      <div class="gx-mbody"></div>
    </div>
  </div>
</div>
"""

CSS = """
.gx { font-family: var(--st-font); color: var(--st-text-color); font-size: 13px; --bd: var(--st-border-color, rgba(128,128,128,.25));
  --bg: var(--st-background-color, #fff); --bg2: var(--st-secondary-background-color, #f5f6f8);
  --diff: rgba(229, 72, 77, .13); --diffb: rgba(229, 72, 77, .55); --only: rgba(245, 166, 35, .16); --onlyb: rgba(245, 166, 35, .6);
  --fmt: rgba(64, 132, 214, .12); --ok: rgba(46, 160, 67, .10); }
.gx-toolbar { display: flex; gap: .5rem; flex-wrap: wrap; align-items: center; margin-bottom: .5rem; }
.gx-seg { display: flex; flex-wrap: wrap; gap: .25rem; }
.gx-seg button { border: 1px solid var(--bd); background: var(--bg); color: inherit; border-radius: 999px; padding: .3rem .75rem; cursor: pointer; font: inherit; }
.gx-seg button[aria-selected="true"] { background: var(--st-primary-color); border-color: var(--st-primary-color); color: #fff; }
.gx-seg .ct { opacity: .75; margin-left: .25rem; font-variant-numeric: tabular-nums; }
.gx-search { flex: 1 1 14rem; min-width: 10rem; padding: .4rem .6rem; border: 1px solid var(--bd); border-radius: .5rem; background: var(--bg2); color: inherit; font: inherit; }
.gx-check { display: inline-flex; gap: .35rem; align-items: center; white-space: nowrap; cursor: pointer; }
.gx-cols { margin: .25rem 0 .5rem; }
.gx-cols summary { cursor: pointer; opacity: .85; }
.gx-colchips { display: flex; flex-wrap: wrap; gap: .3rem; margin-top: .4rem; }
.gx-colchips label { border: 1px solid var(--bd); border-radius: .4rem; padding: .15rem .5rem; cursor: pointer; display: inline-flex; gap: .3rem; align-items: center; }
.gx-legend { display: flex; flex-wrap: wrap; gap: .35rem 1rem; font-size: 12px; opacity: .9; margin-bottom: .5rem; align-items: center; }
.gx-hint { opacity: .7; margin-left: auto; }
.lg { display: inline-block; width: 12px; height: 12px; border-radius: 3px; margin-right: .3rem; vertical-align: -2px; }
.lg-diff { background: var(--diff); border: 1px solid var(--diffb); } .lg-only { background: var(--only); border: 1px solid var(--onlyb); } .lg-fmt { background: var(--fmt); }
.bd { font-size: 10px; font-weight: 600; border-radius: 4px; padding: 0 .3rem; margin-right: .25rem; white-space: nowrap; }
.bd-tl { background: rgba(46,160,67,.18); color: #1a7f37; } .bd-gm { background: rgba(130,80,223,.18); color: #6639ba; } .bd-gu { background: rgba(245,166,35,.25); color: #9a6700; }
.gx-scroll { overflow: auto; max-height: 70vh; border: 1px solid var(--bd); border-radius: .6rem; background: var(--bg); }
.gx-table { border-collapse: separate; border-spacing: 0; min-width: 100%; }
.gx-table th, .gx-table td { box-sizing: border-box; border-bottom: 1px solid var(--bd); border-right: 1px solid var(--bd); padding: .4rem .5rem; vertical-align: top; text-align: left; background: var(--bg); }
.gx-table thead th { position: sticky; z-index: 2; background: var(--bg2); font-weight: 600; }
.gx-table thead tr:first-child th { top: 0; min-height: 34px; }
.gx-table thead tr:nth-child(2) th { top: 34px; font-weight: 500; font-size: 12px; }
.gx-table thead tr:first-child th[colspan] { max-width: 44rem; }
.gx-table .fix { position: sticky; z-index: 1; }
.gx-table .lead { font-size: 12px; overflow: hidden; }
.gx-table .fixlast { box-shadow: 4px 0 6px -4px rgba(0,0,0,.18); }
.gx-table thead .fix { z-index: 3; }
.gx-table th.sys, .gx-table td.sys { min-width: 13rem; max-width: 22rem; }
.gx-table th.pdf, .gx-table td.pdf { min-width: 13rem; max-width: 22rem; border-right: 2px solid var(--bd); }
.gx-table thead th.sys { color: #0969da; } .gx-table thead th.pdf { color: #8250df; }
.gx-table td.num { color: inherit; opacity: .6; font-variant-numeric: tabular-nums; }
.gx-table tbody tr { cursor: pointer; }
.gx-table tbody tr:hover td { filter: brightness(0.97); }
.gx-table tbody tr.tstart td { border-top: 2px solid var(--st-primary-color); }
.clip { display: -webkit-box; -webkit-line-clamp: 3; -webkit-box-orient: vertical; overflow: hidden; white-space: pre-wrap; word-break: break-word; }
.rep { opacity: .45; font-style: italic; }
td.st-FARKLI { background: var(--diff) !important; } td.st-YALNIZCA_SİSTEM, td.st-YALNIZCA_PDF { background: var(--only) !important; }
td.st-BİÇİM { background: var(--fmt) !important; }
.pill { display: inline-block; border-radius: 999px; padding: .05rem .5rem; font-size: 11px; font-weight: 600; white-space: nowrap; }
.p-FARKLI { background: rgba(229,72,77,.15); color: #cf222e; } .p-YALNIZCA_SİSTEM, .p-YALNIZCA_PDF { background: rgba(245,166,35,.2); color: #9a6700; }
.p-BİÇİM { background: rgba(64,132,214,.15); color: #0969da; } .p-AYNI { background: rgba(46,160,67,.15); color: #1a7f37; } .p-BOŞ { background: var(--bg2); opacity: .8; }
.gx-pager { display: flex; gap: .5rem; align-items: center; justify-content: flex-end; margin-top: .5rem; }
.gx-pager button { border: 1px solid var(--bd); background: var(--bg); color: inherit; border-radius: .4rem; padding: .2rem .6rem; cursor: pointer; }
.gx-pager button:disabled { opacity: .4; cursor: default; }
.gx-empty { padding: 1.5rem; text-align: center; opacity: .7; }
.gx-modal { position: fixed; inset: 0; background: rgba(0,0,0,.45); z-index: 1000001; display: flex; align-items: center; justify-content: center; padding: 1rem; }
.gx-modal[hidden] { display: none; }
.gx-dialog { background: var(--bg); color: var(--st-text-color); width: min(1100px, 100%); max-height: 92vh; border-radius: .8rem; display: flex; flex-direction: column; box-shadow: 0 20px 60px rgba(0,0,0,.3); }
.gx-mhead { display: flex; justify-content: space-between; gap: 1rem; padding: 1rem 1.25rem .5rem; border-bottom: 1px solid var(--bd); }
.gx-mtitle { font-size: 1.1rem; font-weight: 700; } .gx-msub { opacity: .75; margin-top: .15rem; }
.gx-mnav { display: flex; gap: .35rem; align-items: flex-start; }
.gx-mnav button { border: 1px solid var(--bd); background: var(--bg2); color: inherit; border-radius: .4rem; width: 2rem; height: 2rem; cursor: pointer; font-size: 1rem; }
.gx-monly { padding: .5rem 1.25rem 0; }
.gx-mbody { overflow: auto; padding: .5rem 1.25rem 1.25rem; }
.fld { border: 1px solid var(--bd); border-radius: .6rem; margin-top: .75rem; overflow: hidden; }
.fld.st-FARKLI { border-color: var(--diffb); } .fld.st-YALNIZCA_SİSTEM, .fld.st-YALNIZCA_PDF { border-color: var(--onlyb); }
.fld-h { display: flex; gap: .5rem; align-items: center; flex-wrap: wrap; padding: .45rem .75rem; background: var(--bg2); font-weight: 600; }
.fld-h .meta { font-weight: 400; opacity: .7; font-size: 12px; margin-left: auto; }
.fld-b { display: grid; grid-template-columns: 1fr 1fr; }
.fld-b > div { padding: .6rem .75rem; white-space: pre-wrap; word-break: break-word; line-height: 1.45; }
.fld-b > div + div { border-left: 1px solid var(--bd); }
.fld-b .lab { display: block; font-size: 11px; font-weight: 600; margin-bottom: .25rem; }
.lab.sys { color: #0969da; } .lab.pdf { color: #8250df; }
.fld-n { padding: .4rem .75rem; font-size: 12px; border-top: 1px dashed var(--bd); opacity: .9; }
.fld-g { padding: .4rem .75rem; font-size: 12px; background: rgba(245,166,35,.12); border-top: 1px dashed var(--bd); white-space: pre-wrap; }
del { background: rgba(229,72,77,.22); text-decoration: line-through; } ins { background: rgba(46,160,67,.25); text-decoration: none; }
@media (max-width: 720px) {
  .gx-hint { display: none; }
  .gx-dialog { max-height: 100vh; height: 100%; border-radius: 0; }
  .gx-modal { padding: 0; }
  .fld-b { grid-template-columns: 1fr; }
  .fld-b > div + div { border-left: 0; border-top: 1px solid var(--bd); }
  .gx-table th.sys, .gx-table td.sys, .gx-table th.pdf, .gx-table td.pdf { min-width: 10rem; }
}
"""

JS = r"""
const DIFF = new Set(["FARKLI", "YALNIZCA_SİSTEM", "YALNIZCA_PDF"]);
const LABEL = { FARKLI: "Farklı", "YALNIZCA_SİSTEM": "Yalnızca sistemde", "YALNIZCA_PDF": "Yalnızca PDF'de", "BİÇİM": "Biçim farkı", AYNI: "Aynı", "BOŞ": "İki taraf boş" };
const PAGE = 150;
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

function wordDiff(a, b) {
  // Kelime + ardından gelen boşluk bir birimdir; karşılaştırma yalnızca kelimelerle yapılır (boşluk miktarı fark sayılmaz)
  const tok = (t) => ((t || "").match(/\S+\s*/g) || []);
  const A = tok(a), B = tok(b);
  if (A.length * B.length > 250000) return null;  // çok uzun metinde vurgulama yapılmaz
  const W = (x) => x.trim();
  const n = A.length, m = B.length, L = Array.from({ length: n + 1 }, () => new Uint32Array(m + 1));
  for (let i = n - 1; i >= 0; i--) for (let j = m - 1; j >= 0; j--) L[i][j] = W(A[i]) === W(B[j]) ? L[i + 1][j + 1] + 1 : Math.max(L[i + 1][j], L[i][j + 1]);
  const mark = (tag, x) => `<${tag}>${esc(W(x))}</${tag}>${esc(x.slice(W(x).length))}`;
  let i = 0, j = 0, sa = "", sb = "";
  while (i < n && j < m) {
    if (W(A[i]) === W(B[j])) { sa += esc(A[i]); sb += esc(B[j]); i++; j++; }
    else if (L[i + 1][j] >= L[i][j + 1]) { sa += mark("del", A[i]); i++; }
    else { sb += mark("ins", B[j]); j++; }
  }
  while (i < n) { sa += mark("del", A[i]); i++; }
  while (j < m) { sb += mark("ins", B[j]); j++; }
  return [sa, sb];
}

export default function (component) {
  const { data, parentElement } = component;
  const root = parentElement.querySelector(".gx");
  const D = data || { headers: [], rows: [] };
  const S = root.__gx || (root.__gx = { filter: "diff", q: "", fmt: true, hidden: new Set(), page: 0, open: -1, onlyDiff: false });
  const headers = D.headers || [];
  const levels = D.levels || {};

  const cellsOf = (r, all) => {
    const out = {};
    if (all || r.ft) Object.assign(out, (D.theme || {})[r.t] || {});
    if (r.l !== null && r.l !== undefined && (all || r.fl)) Object.assign(out, (D.lo || {})[r.l] || {});
    const c = (D.comp || {})[r.id]; if (c) out["Süreç Bileşeni"] = c;
    return out;
  };
  const eff = (st) => (S.fmt && st === "BİÇİM" ? "AYNI" : st);
  const rowStatus = (r) => {
    const sts = new Set(Object.values(cellsOf(r, false)).map((c) => eff(c.st)));
    for (const s of ["FARKLI", "YALNIZCA_SİSTEM", "YALNIZCA_PDF", "BİÇİM", "AYNI"]) if (sts.has(s)) return s;
    return "BOŞ";
  };
  const rowFlags = (r) => {
    const cs = Object.values(cellsOf(r, false));
    return { completed: cs.some((c) => c.src !== "çıkarım"), unverified: cs.some((c) => c.g) };
  };
  const FILTERS = [
    ["all", "Tümü", () => true],
    ["diff", "Farklar", (r) => DIFF.has(rowStatus(r))],
    ["same", "Eşleşenler", (r) => !DIFF.has(rowStatus(r))],
    ["done", "Tamamlananlar", (r) => rowFlags(r).completed],
    ["gq", "Gemini doğrulanamadı", (r) => rowFlags(r).unverified],
  ];

  function matches(r) {
    if (!S.q) return true;
    const q = S.q.toLocaleLowerCase("tr");
    if ((r.lo + " " + r.tl + " " + r.c).toLocaleLowerCase("tr").includes(q)) return true;
    return Object.values(cellsOf(r, false)).some((c) => (c.s + " " + c.p).toLocaleLowerCase("tr").includes(q));
  }
  const visibleRows = () => {
    const f = FILTERS.find((x) => x[0] === S.filter)[2];
    return (D.rows || []).filter((r) => f(r) && matches(r));
  };

  // araç çubuğu
  const seg = root.querySelector(".gx-seg");
  seg.innerHTML = FILTERS.map(([k, t, f]) => `<button type="button" data-f="${k}" aria-selected="${S.filter === k}">${t}<span class="ct">${(D.rows || []).filter(f).length}</span></button>`).join("");
  seg.querySelectorAll("button").forEach((b) => (b.onclick = () => { S.filter = b.dataset.f; S.page = 0; render(); }));
  const search = root.querySelector(".gx-search");
  search.value = S.q;
  search.oninput = () => { S.q = search.value.trim(); S.page = 0; render(false); };
  const fmt = root.querySelector(".gx-fmt");
  fmt.checked = S.fmt;
  fmt.onchange = () => { S.fmt = fmt.checked; render(); };
  const chips = root.querySelector(".gx-colchips");
  chips.innerHTML = headers.map((h, i) => `<label><input type="checkbox" data-i="${i}" ${S.hidden.has(h) ? "" : "checked"}> ${esc(h)}</label>`).join("");
  chips.querySelectorAll("input").forEach((x) => (x.onchange = () => { const h = headers[+x.dataset.i]; x.checked ? S.hidden.delete(h) : S.hidden.add(h); render(false); }));

  function badges(c) {
    let b = "";
    if (c.src === "PDF metin katmanı") b += `<b class="bd bd-tl" title="Çıkarımda eksikti; PDF metin katmanında bulundu">PDF✓</b>`;
    if (c.src && c.src.startsWith("Gemini")) b += `<b class="bd bd-gm" title="Gemini sayfada buldu; PDF metin katmanında doğrulandı">Gemini✓</b>`;
    if (c.g) b += `<b class="bd bd-gu" title="Gemini önerisi PDF metin katmanında bulunamadı">Gemini?</b>`;
    return b;
  }

  function render(rebuildHead = true) {
    const cols = headers.filter((h) => !S.hidden.has(h));
    const table = root.querySelector(".gx-table");
    // Sol sütunlar: #, ÖÇ, Bileşen, Durum, Tema. Dar ekranda yalnızca ilk üçü sabit kalır.
    const fixW = [44, 104, 62, 112, 170];
    const nFix = root.querySelector(".gx-scroll").clientWidth < 900 ? 3 : 5;
    const left = fixW.map((_, i) => fixW.slice(0, i).reduce((a, b) => a + b, 0));
    const fix = (i) => `class="${i < nFix ? "fix" : ""}${i === nFix - 1 ? " fixlast" : ""} lead" style="${i < nFix ? `left:${left[i]}px;` : ""}width:${fixW[i]}px;min-width:${fixW[i]}px;max-width:${fixW[i]}px"`;
    table.querySelector("thead").innerHTML =
      `<tr><th ${fix(0)} rowspan="2">#</th><th ${fix(1)} rowspan="2">Öğrenme çıktısı</th><th ${fix(2)} rowspan="2">Bileşen</th><th ${fix(3)} rowspan="2">Durum</th><th ${fix(4)} rowspan="2">Tema</th>` +
      cols.map((h) => `<th colspan="2" title="${esc(h)}">${esc(h)}</th>`).join("") + `</tr><tr>` +
      cols.map(() => `<th class="sys">Sistem</th><th class="pdf">PDF</th>`).join("") + `</tr>`;
    const rows = visibleRows();
    const pages = Math.max(1, Math.ceil(rows.length / PAGE));
    S.page = Math.min(S.page, pages - 1);
    const slice = rows.slice(S.page * PAGE, (S.page + 1) * PAGE);
    const body = slice.map((r) => {
      const cs = cellsOf(r, false);
      const st = rowStatus(r);
      const tds = cols.map((h) => {
        const c = cs[h];
        if (!c) {
          const lvl = levels[h];
          const rep = (lvl === "theme" && !r.ft) || (lvl === "lo" && !r.fl);
          return rep ? `<td class="sys"><span class="rep">↑</span></td><td class="pdf"><span class="rep">↑</span></td>` : `<td class="sys"></td><td class="pdf"></td>`;
        }
        const e = eff(c.st);
        return `<td class="sys st-${e}"><div class="clip">${esc(c.s)}</div></td><td class="pdf st-${e}">${badges(c)}<div class="clip">${esc(c.p)}</div></td>`;
      }).join("");
      return `<tr data-id="${r.id}" class="${r.ft ? "tstart" : ""}"><td ${fix(0)}><span class="num">${r.id + 1}</span></td>` +
        `<td ${fix(1)}><b>${esc(r.lo)}</b></td><td ${fix(2)}>${esc(r.c)}</td>` +
        `<td ${fix(3)}><span class="pill p-${st}">${LABEL[st]}</span></td>` +
        `<td ${fix(4)}><div class="clip" title="${esc(r.tl)}">${esc(r.tl)}</div></td>${tds}</tr>`;
    }).join("");
    table.querySelector("tbody").innerHTML = body || `<tr><td colspan="${5 + 2 * cols.length}" class="gx-empty">Bu filtreye uyan satır yok.</td></tr>`;
    table.querySelectorAll("tbody tr[data-id]").forEach((tr) => (tr.onclick = () => openModal(+tr.dataset.id)));
    const pager = root.querySelector(".gx-pager");
    pager.innerHTML = `<span>${rows.length} satır · sayfa ${S.page + 1}/${pages}</span><button type="button" class="pp" ${S.page === 0 ? "disabled" : ""}>‹ Önceki</button><button type="button" class="pn" ${S.page >= pages - 1 ? "disabled" : ""}>Sonraki ›</button>`;
    pager.querySelector(".pp").onclick = () => { S.page--; render(false); };
    pager.querySelector(".pn").onclick = () => { S.page++; render(false); };
    if (rebuildHead) seg.querySelectorAll("button").forEach((b) => b.setAttribute("aria-selected", String(b.dataset.f === S.filter)));
    // Uzun alan başlıkları satır kaydırabilir: ikinci başlık satırı, birincinin gerçek yüksekliğinin altına yapışır
    requestAnimationFrame(() => {
      const r1 = table.querySelector("thead tr:first-child");
      const h = r1 ? r1.getBoundingClientRect().height : 34;
      table.querySelectorAll("thead tr:nth-child(2) th").forEach((th) => (th.style.top = `${h}px`));
    });
  }

  // modal
  const modal = root.querySelector(".gx-modal");
  const onlyDiff = root.querySelector(".gx-onlydiff");
  function openModal(id) {
    const rows = visibleRows();
    const idx = rows.findIndex((r) => r.id === id);
    const r = (D.rows || []).find((x) => x.id === id);
    if (!r) return;
    S.open = id;
    const cs = cellsOf(r, true);
    const st = rowStatus(r);
    root.querySelector(".gx-mtitle").textContent = `${r.lo || "(öğrenme çıktısı yok)"}${r.c ? " • " + r.c : ""}`;
    root.querySelector(".gx-msub").innerHTML = `${esc(r.tl)} · <span class="pill p-${st}">${LABEL[st]}</span>`;
    onlyDiff.checked = S.onlyDiff;
    const body = headers.map((h) => {
      const c = cs[h];
      if (!c) return "";
      const e = eff(c.st);
      if (S.onlyDiff && !DIFF.has(e)) return "";
      const d = DIFF.has(e) && c.s && c.p ? wordDiff(c.s, c.p) : null;
      const sv = d ? d[0] : esc(c.s), pv = d ? d[1] : esc(c.p);
      const meta = [c.a ? `Excel ${esc(c.a)}` : "", c.pg && c.pg.length ? `PDF s.${c.pg.join(", ")}` : "", c.src && c.src !== "çıkarım" ? esc(c.src) : ""].filter(Boolean).join(" · ");
      return `<section class="fld st-${e}"><div class="fld-h">${esc(h)} <span class="pill p-${c.st}">${LABEL[c.st]}</span>${badges(c)}<span class="meta">${meta}</span></div>` +
        `<div class="fld-b"><div><span class="lab sys">SİSTEM</span>${sv || '<span class="rep">(boş)</span>'}</div><div><span class="lab pdf">PDF</span>${pv || '<span class="rep">(boş)</span>'}</div></div>` +
        (c.n ? `<div class="fld-n">${esc(c.n)}</div>` : "") +
        (c.x ? `<div class="fld-n">Tamamlamadan önceki çıkarım: ${esc(c.x) || "(boş)"}</div>` : "") +
        (c.g ? `<div class="fld-g"><b>Gemini önerisi — PDF metin katmanında doğrulanamadı, tabloya alınmadı:</b>\n${esc(c.g)}</div>` : "") +
        `</section>`;
    }).join("");
    root.querySelector(".gx-mbody").innerHTML = body || `<div class="gx-empty">Farklı alan yok.</div>`;
    root.querySelector(".gx-prev").disabled = idx <= 0;
    root.querySelector(".gx-next").disabled = idx < 0 || idx >= rows.length - 1;
    root.querySelector(".gx-prev").onclick = () => idx > 0 && openModal(rows[idx - 1].id);
    root.querySelector(".gx-next").onclick = () => idx >= 0 && idx < rows.length - 1 && openModal(rows[idx + 1].id);
    modal.hidden = false;
    root.querySelector(".gx-close").focus();
  }
  const closeModal = () => { modal.hidden = true; S.open = -1; };
  root.querySelector(".gx-close").onclick = closeModal;
  modal.onclick = (e) => { if (e.target === modal) closeModal(); };
  onlyDiff.onchange = () => { S.onlyDiff = onlyDiff.checked; if (S.open >= 0) openModal(S.open); };
  if (!root.__gxKeys) {
    root.__gxKeys = true;
    root.ownerDocument.addEventListener("keydown", (e) => {
      if (modal.hidden) return;
      if (e.key === "Escape") closeModal();
      if (e.key === "ArrowLeft") root.querySelector(".gx-prev").click();
      if (e.key === "ArrowRight") root.querySelector(".gx-next").click();
    });
  }
  render();
  if (!root.__gxResize) {
    root.__gxResize = true;
    let tmr;
    new ResizeObserver(() => { clearTimeout(tmr); tmr = setTimeout(() => render(false), 150); }).observe(root.querySelector(".gx-scroll"));
  }
}
"""

_component = st.components.v2.component("grid_compare_table", html=HTML, css=CSS, js=JS)


def grid_table(payload: dict, key: str = "grid_table"):
    return _component(data=payload, key=key)
