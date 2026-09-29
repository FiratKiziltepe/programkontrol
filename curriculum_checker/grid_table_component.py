"""Sistem Excel'i ↔ PDF Excel'i yan yana karşılaştırma tablosu (Streamlit components v2, yalnızca görüntüleme).

Veri grid_compare.grid_payload() biçimindedir. Hiçbir metin üretilmez; tablo yalnızca iki kaynağın
değerlerini ve deterministik durumlarını gösterir.
"""
from __future__ import annotations

import streamlit as st

HTML = """
<div class="gx">
  <div class="gx-bar">
    <div class="gx-view" role="group" aria-label="Görünüm">
      <button type="button" data-v="h" title="Her satır bir süreç bileşeni; alanlar sütun sütun">Yatay tablo</button>
      <button type="button" data-v="v" title="Her tema bir blok; alanlar alt alta, Sistem | PDF yan yana; öğrenme çıktıları ve süreç bileşenleri tek hücrede">Dikey (alan alan)</button>
    </div>
    <label class="gx-check gx-vonly"><input type="checkbox"> Yalnızca farklı alanlar</label>
    <span class="gx-sp"></span>
    <button type="button" class="gx-btn gx-full" title="Tam ekran (Esc ile çıkılır)">⛶ Tam ekran</button>
    <button type="button" class="gx-btn gx-dl" data-img="0" title="Geçerli görünüm ve filtrelerle, çevrimdışı açılabilen HTML dosyası (PDF sayfaları olmadan)">⤓ HTML indir (resimsiz)</button>
    <button type="button" class="gx-btn gx-dl" data-img="1" title="Ayrıca PDF sayfaları gömülür: dosyada “PDF s.” bağlantısına tıklayınca sayfa, yer sarı işaretli açılır (dosya büyür)">⤓ HTML indir (resimli)</button>
  </div>
  <div class="gx-toolbar">
    <div class="gx-seg"></div>
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
    <span class="gx-hint"></span>
  </div>
  <div class="gx-scroll" tabindex="0"><table class="gx-table"><thead></thead><tbody></tbody></table><div class="gx-vert"></div></div>
  <div class="gx-pager"></div>
  <div class="gx-pv" hidden>
    <div class="gx-pvd" role="dialog" aria-modal="true">
      <header class="gx-mhead">
        <div><div class="gx-mtitle gx-pvt"></div><div class="gx-msub gx-pvs"></div></div>
        <div class="gx-mnav"><button class="gx-pvx" type="button" title="Kapat (Esc)">✕</button></div>
      </header>
      <div class="gx-pvb"></div>
    </div>
  </div>
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
.gx-seg { display: flex; flex-direction: column; gap: .4rem; flex: 1 1 100%; }
.gx-seg .fg { display: flex; flex-wrap: wrap; gap: .3rem; align-items: center; }
.gx-seg .fl { font-size: 12px; font-weight: 600; opacity: .7; min-width: 3rem; }
.gx-seg .chip { border: 1px solid var(--bd); background: var(--bg); color: inherit; border-radius: 999px; padding: .25rem .7rem; cursor: pointer; font: inherit; }
.gx-seg .chip[aria-pressed="true"] { background: var(--st-primary-color); border-color: var(--st-primary-color); color: #fff; }
.gx-seg .chip.c-FARKLI[aria-pressed="true"] { background: #cf222e; border-color: #cf222e; }
.gx-seg .chip.c-YALNIZCA_SİSTEM[aria-pressed="true"], .gx-seg .chip.c-YALNIZCA_PDF[aria-pressed="true"] { background: #bf8700; border-color: #bf8700; }
.gx-seg .chip.c-BİÇİM[aria-pressed="true"] { background: #0969da; border-color: #0969da; }
.gx-seg .chip.c-AYNI[aria-pressed="true"] { background: #1a7f37; border-color: #1a7f37; }
.gx-seg .chip.c-BOŞ[aria-pressed="true"] { background: #6e7781; border-color: #6e7781; }
.gx-seg .ct { opacity: .8; margin-left: .35rem; font-variant-numeric: tabular-nums; }
.gx-seg .quick { display: inline-flex; gap: .25rem; margin-left: .5rem; }
.gx-seg .mini { border: 0; background: none; color: var(--st-primary-color); cursor: pointer; font: inherit; font-size: 12px; text-decoration: underline; padding: 0 .2rem; }
.gx-seg details.fields { margin-left: .25rem; }
.gx-seg details.fields summary { cursor: pointer; font-size: 12px; opacity: .85; }
.gx-seg details.fields .fg { margin-top: .35rem; }
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
/* görünüm seçimi, tam ekran, indirme */
.gx-bar { display: flex; gap: .5rem; flex-wrap: wrap; align-items: center; margin-bottom: .5rem; }
.gx-sp { flex: 1 1 auto; }
.gx-view { display: inline-flex; border: 1px solid var(--bd); border-radius: .5rem; overflow: hidden; }
.gx-view button { border: 0; background: var(--bg); color: inherit; font: inherit; padding: .35rem .8rem; cursor: pointer; }
.gx-view button + button { border-left: 1px solid var(--bd); }
.gx-view button[aria-pressed="true"] { background: var(--st-primary-color); color: #fff; }
.gx-btn { border: 1px solid var(--bd); background: var(--bg); color: inherit; font: inherit; border-radius: .5rem; padding: .35rem .8rem; cursor: pointer; white-space: nowrap; }
.gx-btn:hover, .gx-view button:not([aria-pressed="true"]):hover { background: var(--bg2); }
.gx-vonly[hidden] { display: none; }
.gx.is-full { position: fixed; inset: 0; z-index: 1000000; background: var(--bg); padding: 1rem; display: flex; flex-direction: column; overflow: auto; box-sizing: border-box; }
.gx.is-full .gx-scroll { max-height: none; flex: 1 0 24rem; min-height: 0; }
.gx.is-full .gx-cols, .gx.is-full .gx-legend, .gx.is-full .gx-pager { flex: 0 0 auto; }
.gx-btn:disabled { opacity: .6; cursor: progress; }
.gx-btn[hidden] { display: none; }
a.pg { color: var(--st-primary-color); text-decoration: underline; cursor: pointer; }
/* PDF sayfa görüntüleyici (resimli HTML): sarı işaret, uygulamadaki diyalogla aynı renk */
.gx-pv { position: fixed; inset: 0; background: rgba(0,0,0,.5); z-index: 1000002; display: flex; align-items: center; justify-content: center; padding: 1rem; }
.gx-pv[hidden] { display: none; }
.gx-pvd { background: var(--bg); color: var(--st-text-color); width: min(1000px, 100%); max-height: 94vh; border-radius: .8rem; display: flex; flex-direction: column; box-shadow: 0 20px 60px rgba(0,0,0,.3); }
.gx-pvb { overflow: auto; padding: .5rem 1.25rem 1.25rem; }
.gx-pvb .pv-n { background: rgba(245,166,35,.15); border-radius: .4rem; padding: .5rem .75rem; margin: .5rem 0; }
.gx-pvb .pv-h { font-weight: 600; margin: .75rem 0 .35rem; }
.pv-w { position: relative; border: 1px solid var(--bd); }
.pv-w img { display: block; width: 100%; height: auto; }
.pv-w i { position: absolute; background: rgba(255,224,26,.42); outline: 1px solid rgb(230,158,0); }
/* dikey görünüm: her öğrenme çıktısı bir blok; alanlar alt alta, Sistem | PDF yan yana */
.gx-scroll.v .gx-table, .gx-scroll:not(.v) .gx-vert { display: none; }
.gx-vert { padding: .6rem; display: flex; flex-direction: column; gap: .8rem; --vcols: minmax(9rem, 14rem) minmax(0, 1fr) minmax(0, 1fr); }
.vb { border: 1px solid var(--bd); border-radius: .6rem; overflow: clip; }
.vb-h, .vr { display: grid; grid-template-columns: var(--vcols); }
.vb-h { position: sticky; top: 0; z-index: 1; background: var(--bg2); border-bottom: 1px solid var(--bd); font-weight: 600; }
.vb-h > div { padding: .5rem .75rem; }
.vb-h > div + div { border-left: 1px solid var(--bd); }
.vb-h .vb-id { display: flex; flex-direction: column; gap: .2rem; }
.vb-h .vb-t { font-weight: 400; font-size: 12px; opacity: .8; }
.vb-h .vb-tools { display: flex; gap: .4rem; align-items: center; flex-wrap: wrap; font-weight: 400; }
.vb-h .sys { color: #0969da; } .vb-h .pdf { color: #8250df; }
.vr + .vr { border-top: 1px solid var(--bd); }
.vr > div { padding: .5rem .75rem; min-width: 0; }
.vr > .vs { border-left: 1px solid var(--bd); white-space: pre-wrap; word-break: break-word; line-height: 1.45; }
.vr .vf { font-weight: 600; font-size: 12px; }
.vr .vf .vfm { margin-top: .3rem; display: flex; flex-wrap: wrap; gap: .2rem; align-items: center; }
.vr .vf .meta { margin-top: .25rem; font-weight: 400; opacity: .7; font-size: 11px; }
.vr .vs .lab { display: none; }
.vr.st-FARKLI > .vs { background: var(--diff); } .vr.st-YALNIZCA_SİSTEM > .vs, .vr.st-YALNIZCA_PDF > .vs { background: var(--only); }
.vr.st-BİÇİM > .vs { background: var(--fmt); }
.vr.st-FARKLI > .vf { box-shadow: inset 3px 0 0 #cf222e; } .vr.st-YALNIZCA_SİSTEM > .vf, .vr.st-YALNIZCA_PDF > .vf { box-shadow: inset 3px 0 0 #bf8700; }
.vr > .vn { grid-column: 1 / -1; border-top: 1px dashed var(--bd); font-size: 12px; opacity: .9; white-space: pre-wrap; }
.vr > .vn.g { background: rgba(245,166,35,.12); opacity: 1; }
@media (max-width: 720px) {
  .gx-vert { --vcols: 1fr; padding: .4rem; }
  .vb-h > div.sys, .vb-h > div.pdf { display: none; }
  .vr > .vs { border-left: 0; border-top: 1px solid var(--bd); }
  .vr .vs .lab { display: block; }
}
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
  if (A.length * B.length > 1500000) return null;  // çok uzun metinde vurgulama yapılmaz
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
  // D.init: indirilen HTML dosyası, indirme anındaki görünüm ve filtrelerle açılır
  const I = D.init || {};
  const S = root.__gx || (root.__gx = {
    sel: new Set(I.sel || DIFF), flags: new Set(I.flags || []), fields: new Set(I.fields || []), q: I.q || "",
    fmt: I.fmt ?? true, hidden: new Set(I.hidden || []), page: 0, open: -1, onlyDiff: false, view: I.view || "h", vOnly: !!I.vOnly,
  });
  const headers = D.headers || [];
  const levels = D.levels || {};
  const doc = root.ownerDocument;

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
  // Çoklu seçimli filtre: satır, seçili durumlardan en az birine sahip bir hücre içeriyorsa gösterilir.
  // Alan filtresi seçiliyse yalnızca o alanların hücrelerine bakılır; ek filtreler (tamamlanan, Gemini?) VE ile uygulanır.
  const STATUS_ORDER = ["FARKLI", "YALNIZCA_SİSTEM", "YALNIZCA_PDF", "BİÇİM", "AYNI", "BOŞ"];
  const FLAGS = [
    ["done", "Tamamlananlar", (c) => c.src !== "çıkarım"],
    ["gq", "Gemini doğrulanamadı", (c) => !!c.g],
  ];
  const fieldCells = (r) => Object.entries(cellsOf(r, false)).filter(([h]) => !S.fields.size || S.fields.has(h)).map(([, c]) => c);
  const rowHas = (r, st) => fieldCells(r).some((c) => eff(c.st) === st);
  const flagOk = (r) => [...S.flags].every((k) => fieldCells(r).some(FLAGS.find((f) => f[0] === k)[2]));
  const statusOk = (r) => S.sel.size === 0 || fieldCells(r).some((c) => S.sel.has(eff(c.st)));

  function matches(r) {
    if (!S.q) return true;
    const q = S.q.toLocaleLowerCase("tr");
    if ((r.lo + " " + r.tl + " " + r.c).toLocaleLowerCase("tr").includes(q)) return true;
    return Object.values(cellsOf(r, false)).some((c) => (c.s + " " + c.p).toLocaleLowerCase("tr").includes(q));
  }
  const visibleRows = () => (D.rows || []).filter((r) => statusOk(r) && flagOk(r) && matches(r));

  // araç çubuğu: filtre çipleri
  const seg = root.querySelector(".gx-seg");
  // Dikey görünüm hücreleri: tema başına tema düzeyindeki alanlar + birleştirilmiş alanlar (D.tm), her biri bir kez.
  // Bu görünümde sayılar tekil hücredir: temadaki bir hata her öğrenme çıktısında tekrar sayılmaz.
  const MERGED_LO = D.merged_lo || "Öğrenme Çıktısı ve Süreç Bileşenleri";
  const vHeadersOf = (h) => (h === MERGED_LO ? ["Öğrenme Çıktısı", "Süreç Bileşeni"] : [h]);  // alan filtresi / sütun gizleme
  const vFieldOk = (h) => !S.fields.size || vHeadersOf(h).some((x) => S.fields.has(x));
  const vCells = (t) => [...Object.entries((D.theme || {})[t] || {}), ...Object.entries((D.tm || {})[t] || {})];
  const THEMES = [...new Set((D.rows || []).map((r) => r.t))];
  function renderFilters() {
    const rows = D.rows || [];
    const statuses = STATUS_ORDER.filter((s) => !(S.fmt && s === "BİÇİM"));
    const vcells = S.view === "v" ? THEMES.flatMap((t) => vCells(t)).filter(([h]) => vFieldOk(h)).map(([, c]) => c) : [];
    const nStatus = (s) => (S.view === "v" ? vcells.filter((c) => eff(c.st) === s).length : rows.filter((r) => rowHas(r, s)).length);
    const nFlag = (f) => (S.view === "v" ? vcells.filter(f).length : rows.filter((r) => fieldCells(r).some(f)).length);
    const chip = (kind, key, label, n, extra = "") =>
      `<button type="button" class="chip ${extra}" data-k="${kind}" data-v="${esc(key)}" aria-pressed="${kind === "s" ? S.sel.has(key) : kind === "f" ? S.flags.has(key) : S.fields.has(key)}">${esc(label)}${n === null ? "" : `<span class="ct">${n}</span>`}</button>`;
    seg.innerHTML =
      `<div class="fg"><span class="fl">Durum</span>` +
      statuses.map((s) => chip("s", s, LABEL[s], nStatus(s), `c-${s}`)).join("") +
      `<span class="quick"><button type="button" class="mini" data-q="diff">Farklar</button><button type="button" class="mini" data-q="all">Tümü</button><button type="button" class="mini" data-q="none">Temizle</button></span></div>` +
      `<div class="fg"><span class="fl">Ek</span>` + FLAGS.map(([k, t, f]) => chip("f", k, t, nFlag(f))).join("") +
      `<details class="fields"${S.fields.size ? " open" : ""}><summary>Alan filtresi${S.fields.size ? ` (${S.fields.size} seçili)` : " (tüm alanlar)"}</summary><div class="fg">` +
      headers.map((h) => chip("h", h, h, null)).join("") + `</div></details></div>`;
    seg.querySelectorAll("button.chip").forEach((b) => (b.onclick = () => {
      const set = b.dataset.k === "s" ? S.sel : b.dataset.k === "f" ? S.flags : S.fields;
      set.has(b.dataset.v) ? set.delete(b.dataset.v) : set.add(b.dataset.v);
      S.page = 0; render();
    }));
    seg.querySelectorAll("button.mini").forEach((b) => (b.onclick = () => {
      S.sel = b.dataset.q === "diff" ? new Set(DIFF) : b.dataset.q === "all" ? new Set(STATUS_ORDER) : new Set();
      S.page = 0; render();
    }));
  }
  const search = root.querySelector(".gx-search");
  search.value = S.q;
  search.oninput = () => { S.q = search.value.trim(); S.page = 0; render(false); };
  const fmt = root.querySelector(".gx-fmt");
  fmt.checked = S.fmt;
  fmt.onchange = () => { S.fmt = fmt.checked; render(); };
  const chips = root.querySelector(".gx-colchips");
  chips.innerHTML = headers.map((h, i) => `<label><input type="checkbox" data-i="${i}" ${S.hidden.has(h) ? "" : "checked"}> ${esc(h)}</label>`).join("");
  chips.querySelectorAll("input").forEach((x) => (x.onchange = () => { const h = headers[+x.dataset.i]; x.checked ? S.hidden.delete(h) : S.hidden.add(h); render(false); }));

  // görünüm seçimi (yatay tablo / dikey)
  const vonly = root.querySelector(".gx-vonly");
  const vonlyBox = vonly.querySelector("input");
  vonlyBox.checked = S.vOnly;
  vonlyBox.onchange = () => { S.vOnly = vonlyBox.checked; render(false); };
  root.querySelectorAll(".gx-view button").forEach((b) => (b.onclick = () => { if (S.view !== b.dataset.v) { S.view = b.dataset.v; S.page = 0; render(); } }));
  function applyView() {
    root.querySelectorAll(".gx-view button").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.v === S.view)));
    root.querySelector(".gx-scroll").classList.toggle("v", S.view === "v");
    vonly.hidden = S.view !== "v";
    root.querySelector(".gx-hint").textContent = S.view === "v"
      ? "Her tema bir blok · öğrenme çıktıları ve kodlar temada tek hücrede · sayılar tekil hücre sayısıdır"
      : "Satıra tıklayınca tüm alanlar açılır · tabloyu yatay kaydırın";
  }

  // tam ekran: Fullscreen API varsa gerçek tam ekran, yoksa pencereyi kaplayan katman
  const fullBtn = root.querySelector(".gx-full");
  const rootNode = root.getRootNode();
  const realFull = () => rootNode.fullscreenElement === root;
  function setFull(on) {
    root.classList.toggle("is-full", on);
    fullBtn.textContent = on ? "✕ Tam ekrandan çık" : "⛶ Tam ekran";
    if (on && root.requestFullscreen && !realFull()) root.requestFullscreen().catch(() => {});
    if (!on && realFull()) doc.exitFullscreen().catch(() => {});
  }
  fullBtn.textContent = root.classList.contains("is-full") ? "✕ Tam ekrandan çık" : "⛶ Tam ekran";
  fullBtn.onclick = () => setFull(!root.classList.contains("is-full"));
  if (!root.__gxFull) {
    root.__gxFull = true;
    doc.addEventListener("fullscreenchange", () => { if (!realFull() && root.classList.contains("is-full")) setFull(false); });
  }

  // HTML indir: bu bileşenin kendisi + veri + geçerli görünüm/filtreler tek, çevrimdışı açılan dosyada.
  // Resimli: PDF sayfaları (bir kez) ve hücrelerin sarı işaret kutuları Python'dan istenir, gelince dosyaya gömülür.
  const X = D.export;
  const { setTriggerValue } = component;
  function download(pdf) {
    const { export: _x, init: _i, pdf_export: _p, ...data } = D;
    if (pdf) data.pdf = { pages: pdf.pages, locs: pdf.locs };
    data.init = { sel: [...S.sel], flags: [...S.flags], fields: [...S.fields], q: S.q, fmt: S.fmt, hidden: [...S.hidden], view: S.view, vOnly: S.vOnly };
    const json = JSON.stringify(data).replace(/</g, "\\u003c");
    const html = `<!doctype html><html lang="tr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">` +
      `<title>${esc(X.title)}</title><style>${X.page_css}\n${X.css}</style></head><body>` +
      `<h1 class="gx-doc-h">${esc(X.title)}</h1><p class="gx-doc-s">${esc(X.subtitle)} · ${esc(new Date().toLocaleString("tr-TR"))}` +
      `${pdf ? " · “PDF s.” bağlantıları sayfayı sarı işaretli açar" : ""}</p>` +
      `${X.html}<script type="application/json" id="gx-data">${json}<\/script>` +
      `<script type="module">${X.js}\ngxMain({ data: JSON.parse(document.getElementById("gx-data").textContent), parentElement: document.body });<\/script></body></html>`;
    const a = doc.createElement("a");
    a.href = URL.createObjectURL(new Blob([html], { type: "text/html;charset=utf-8" }));
    a.download = `${X.file_name}${pdf ? "_resimli" : ""}.html`;
    doc.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(a.href), 5000);
  }
  const IMG_LABEL = "⤓ HTML indir (resimli)", IMG_BUSY = "⏳ Sayfalar hazırlanıyor…";
  root.querySelectorAll(".gx-dl").forEach((b) => {
    b.hidden = !X;
    const img = b.dataset.img === "1";
    if (img) { b.disabled = !!S.pendingExport; b.textContent = S.pendingExport ? IMG_BUSY : IMG_LABEL; }
    if (X) b.onclick = () => {
      if (!img) return download(null);
      S.pendingExport = Math.random().toString(36).slice(2);
      b.disabled = true;
      b.textContent = IMG_BUSY;
      setTriggerValue("export_images", { token: S.pendingExport });
    };
  });
  if (X && D.pdf_export && S.pendingExport && D.pdf_export.token === S.pendingExport) {
    S.pendingExport = null;
    download(D.pdf_export);
    root.querySelectorAll('.gx-dl[data-img="1"]').forEach((b) => { b.disabled = false; b.textContent = IMG_LABEL; });
  }

  // "PDF s.X": uygulamada Python diyaloğu (sayfa + sarı işaret); resimli HTML'de gömülü sayfa görüntüleyici
  const inApp = typeof setTriggerValue === "function" && !!X;
  const PDF = D.pdf || null;
  function pageRef(c) {
    if (!c.pg || !c.pg.length) return "";
    const txt = `PDF s.${c.pg.join(", ")}`;
    const can = c.k && (inApp || (PDF && PDF.locs && PDF.locs[c.k]));
    return can ? `<a class="pg" href="#" data-k="${esc(c.k)}" title="PDF'de göster (sarı işaretli)">${txt}</a>` : txt;
  }
  const pv = root.querySelector(".gx-pv");
  const closePv = () => { pv.hidden = true; };
  root.querySelector(".gx-pvx").onclick = closePv;
  pv.onclick = (e) => { if (e.target === pv) closePv(); };
  function openPv(k) {
    const L = PDF.locs[k];
    root.querySelector(".gx-pvt").textContent = L.t || "PDF";
    root.querySelector(".gx-pvs").textContent = L.pg.map((p) => `s.${p}` + ((L.r[p] || []).length ? ` (${L.r[p].length} işaret)` : "")).join(" · ");
    const body = root.querySelector(".gx-pvb");
    body.innerHTML = (L.n ? `<div class="pv-n">${esc(L.n)}</div>` : "") + L.pg.map((p) =>
      `<div class="pv-h">Sayfa ${p}${(L.r[p] || []).length ? "" : " · işaret yok"}</div><div class="pv-w"><img alt="Sayfa ${p}" src="data:image/jpeg;base64,${PDF.pages[p] || ""}">` +
      (L.r[p] || []).map((r) => `<i style="left:${r[0] * 100}%;top:${r[1] * 100}%;width:${(r[2] - r[0]) * 100}%;height:${(r[3] - r[1]) * 100}%"></i>`).join("") + `</div>`).join("");
    pv.hidden = false;
    body.scrollTop = 0;
    const first = body.querySelector(".pv-w i");
    if (first) {
      const img = first.parentElement.querySelector("img");
      const go = () => first.scrollIntoView({ block: "center" });
      img.complete ? go() : (img.onload = go);
    }
    root.querySelector(".gx-pvx").focus();
  }
  root.__gxCtx = { inApp, PDF, setTriggerValue, openPv };
  if (!root.__gxPg) {
    root.__gxPg = true;
    root.addEventListener("click", (e) => {
      const a = e.target.closest && e.target.closest("a.pg");
      if (!a) return;
      e.preventDefault();
      e.stopPropagation();
      const ctx = root.__gxCtx;
      if (ctx.PDF && ctx.PDF.locs[a.dataset.k]) ctx.openPv(a.dataset.k);
      else if (ctx.inApp) ctx.setTriggerValue("open_pdf", { k: a.dataset.k, n: Date.now() });
    });
  }

  function badges(c) {
    let b = "";
    if (c.src === "PDF metin katmanı") b += `<b class="bd bd-tl" title="Çıkarımda eksikti; PDF metin katmanında bulundu">PDF✓</b>`;
    if (c.src && c.src.startsWith("Gemini")) b += `<b class="bd bd-gm" title="Gemini sayfada buldu; PDF metin katmanında doğrulandı">Gemini✓</b>`;
    if (c.g) b += `<b class="bd bd-gu" title="Gemini önerisi PDF metin katmanında bulunamadı">Gemini?</b>`;
    return b;
  }

  const STATUS_RANK = ["FARKLI", "YALNIZCA_SİSTEM", "YALNIZCA_PDF", "BİÇİM", "AYNI"];
  const worst = (sts) => STATUS_RANK.find((s) => sts.has(s)) || "BOŞ";
  const cellMeta = (c) => [c.a ? `Excel ${esc(c.a)}` : "", pageRef(c), c.src && c.src !== "çıkarım" ? esc(c.src) : ""].filter(Boolean);
  const diffPair = (c, e) => {
    const d = DIFF.has(e) && c.s && c.p ? wordDiff(c.s, c.p) : null;
    return d || [esc(c.s), esc(c.p)];
  };

  function renderPager(n, unit, perPage) {
    const pages = Math.max(1, Math.ceil(n / perPage));
    const pager = root.querySelector(".gx-pager");
    pager.innerHTML = `<span>${n} ${unit} · sayfa ${S.page + 1}/${pages}</span><button type="button" class="pp" ${S.page === 0 ? "disabled" : ""}>‹ Önceki</button><button type="button" class="pn" ${S.page >= pages - 1 ? "disabled" : ""}>Sonraki ›</button>`;
    pager.querySelector(".pp").onclick = () => { S.page--; render(false); };
    pager.querySelector(".pn").onclick = () => { S.page++; render(false); };
  }

  // Dikey görünüm: her TEMA bir blok; alanlar sistem Excel'i sütun sırasıyla alt alta, Sistem | PDF yan yana.
  // Tema düzeyindeki alanlar ve temanın birleştirilmiş alanları (öğrenme çıktıları + süreç bileşenleri tek hücrede,
  // ÖÇ düzeyindeki kod sütunları temada tek listede; Python: grid_compare.merged_theme_cells) birer kez gösterilir.
  const VPAGE = 10;
  const notes = (c) => (c.n ? `<div class="vn">${esc(c.n)}</div>` : "") +
    (c.x ? `<div class="vn">Tamamlamadan önceki çıkarım: ${esc(c.x) || "(boş)"}</div>` : "") +
    (c.g ? `<div class="vn g"><b>Gemini önerisi — PDF metin katmanında doğrulanamadı, tabloya alınmadı:</b>\n${esc(c.g)}</div>` : "");
  function vField(label, c) {
    const e = eff(c.st);
    const [sv, pv] = diffPair(c, e);
    const meta = cellMeta(c).join(" · ");
    return `<div class="vr st-${e}"><div class="vf">${esc(label)}<div class="vfm"><span class="pill p-${c.st}">${LABEL[c.st]}</span>${badges(c)}</div>` +
      (meta ? `<div class="meta">${meta}</div>` : "") + `</div>` +
      `<div class="vs"><span class="lab sys">SİSTEM</span>${sv || '<span class="rep">(boş)</span>'}</div>` +
      `<div class="vs"><span class="lab pdf">PDF</span>${pv || '<span class="rep">(boş)</span>'}</div>` + notes(c) + `</div>`;
  }
  function themeVisible(t) {
    const cs = vCells(t).filter(([h]) => vFieldOk(h)).map(([, c]) => c);
    if (S.sel.size && !cs.some((c) => S.sel.has(eff(c.st)))) return false;
    if (![...S.flags].every((k) => cs.some(FLAGS.find((f) => f[0] === k)[2]))) return false;
    if (!S.q) return true;
    const q = S.q.toLocaleLowerCase("tr");
    return (D.rows || []).some((r) => r.t === t && (r.lo + " " + r.tl + " " + r.c).toLocaleLowerCase("tr").includes(q)) ||
      vCells(t).some(([, c]) => (c.s + " " + c.p).toLocaleLowerCase("tr").includes(q));
  }
  function renderVert() {
    const themes = THEMES.filter(themeVisible);
    const pages = Math.max(1, Math.ceil(themes.length / VPAGE));
    S.page = Math.min(S.page, pages - 1);
    const html = themes.slice(S.page * VPAGE, (S.page + 1) * VPAGE).map((t) => {
      const trs = (D.rows || []).filter((r) => r.t === t);
      const tc = (D.theme || {})[t] || {}, mc = (D.tm || {})[t] || {};
      const items = [];
      for (const h of headers) {
        if (h === "Süreç Bileşeni") continue;  // öğrenme çıktılarıyla birlikte tek hücrede
        const key = h === "Öğrenme Çıktısı" ? MERGED_LO : h;
        if (vHeadersOf(key).every((x) => S.hidden.has(x))) continue;
        const c = tc[key] || mc[key];
        if (c) items.push([key, c]);
      }
      const bst = worst(new Set(items.map(([, c]) => eff(c.st))));
      const body = items.map(([h, c]) => (S.vOnly && !DIFF.has(eff(c.st)) ? "" : vField(h, c))).join("");
      const nLo = new Set(trs.filter((r) => r.l !== null && r.l !== undefined).map((r) => r.l)).size;
      return `<section class="vb"><div class="vb-h"><div class="vb-id"><span>${esc(trs[0] ? trs[0].tl : "") || "(tema yok)"}</span>` +
        `<span class="vb-t">${nLo} öğrenme çıktısı · ${trs.filter((r) => (D.comp || {})[r.id]).length} süreç bileşeni</span>` +
        `<span class="vb-tools"><span class="pill p-${bst}">${LABEL[bst]}</span></span></div>` +
        `<div class="sys">Sistem</div><div class="pdf">PDF</div></div>${body || '<div class="gx-empty">Farklı alan yok.</div>'}</section>`;
    }).join("");
    root.querySelector(".gx-vert").innerHTML = html || `<div class="gx-empty">Bu filtreye uyan tema yok.</div>`;
    renderPager(themes.length, "tema", VPAGE);
  }

  function render(rebuildHead = true) {
    applyView();
    if (S.view === "v") { renderVert(); renderFilters(); return; }
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
    renderPager(rows.length, "satır", PAGE);
    renderFilters();
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
      const meta = cellMeta(c).join(" · ");
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
      if (!pv.hidden) { if (e.key === "Escape") closePv(); return; }
      if (modal.hidden) {
        if (e.key === "Escape" && root.classList.contains("is-full") && !realFull()) setFull(false);
        return;
      }
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

# İndirilen HTML: aynı bileşen (HTML/CSS/JS) Streamlit dışında çalışır; Streamlit tema değişkenleri burada verilir.
_EXPORT_JS = JS.replace("export default function (component)", "function gxMain(component)")
assert _EXPORT_JS != JS
_EXPORT_PAGE_CSS = """
:root { --st-font: system-ui, -apple-system, "Segoe UI", Roboto, sans-serif; --st-text-color: #1f2328;
  --st-primary-color: #ff4b4b; --st-background-color: #fff; --st-secondary-background-color: #f5f6f8;
  --st-border-color: rgba(128,128,128,.25); }
body { margin: 0; padding: 16px; background: #fff; color: #1f2328; font-family: var(--st-font); }
.gx-doc-h { font-size: 1.2rem; margin: 0 0 .25rem; } .gx-doc-s { margin: 0 0 1rem; opacity: .7; font-size: 13px; }
"""


def grid_table(payload: dict, key: str = "grid_table", title: str = "", subtitle: str = "", file_name: str = "karsilastirma",
               pdf_export: dict | None = None):
    """file_name uzantısız verilir (".html" / "_resimli.html" eklenir). pdf_export yalnızca resimli indirme
    istendiğinde bir kez verilir: {"token", "pages": {sayfa: jpeg base64}, "locs": {hücre: konum}}."""
    export = {"css": CSS, "js": _EXPORT_JS, "html": HTML, "page_css": _EXPORT_PAGE_CSS,
              "title": title, "subtitle": subtitle, "file_name": file_name}
    data = {**payload, "export": export}
    if pdf_export:
        data["pdf_export"] = pdf_export
    return _component(data=data, key=key, on_open_pdf_change=lambda: None, on_export_images_change=lambda: None)
