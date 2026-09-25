"""Tarayıcıda çalışan Gemini çağrısı (Streamlit components v2).

API anahtarı yalnızca kullanıcının tarayıcısında kalır: bileşen anahtarı bu sekmenin sessionStorage'ında
tutar (sekme kapanınca silinir) ve istekleri doğrudan generativelanguage.googleapis.com'a gönderir.
Sunucuya (Python'a) yalnızca Gemini'nin JSON yanıtları ve hata mesajları döner; anahtar hiçbir zaman dönmez.
"""
from __future__ import annotations

import streamlit as st

HTML = """
<div class="gv-root">
  <div class="gv-row">
    <label>Gemini API anahtarı
      <input class="gv-key" type="password" autocomplete="off" placeholder="AIza…">
    </label>
    <label>Model
      <input class="gv-model" type="text" autocomplete="off">
    </label>
  </div>
  <p class="gv-note">Anahtar yalnızca bu tarayıcı sekmesinde tutulur (sekme kapanınca silinir); sunucuya gönderilmez.
  Sayfa görüntüleri tarayıcınızdan doğrudan Google Gemini API'sine gönderilir.</p>
  <button class="gv-run" type="button">Gemini ile doğrula</button>
  <div class="gv-status"></div>
</div>
"""

CSS = """
.gv-root { font-family: var(--st-font); color: var(--st-text-color); }
.gv-row { display: flex; gap: 1rem; flex-wrap: wrap; }
.gv-row label { display: flex; flex-direction: column; gap: .25rem; font-size: .875rem; flex: 1 1 16rem; }
.gv-row input { padding: .5rem .6rem; border: 1px solid var(--st-border-color, #d6d6d9); border-radius: .5rem;
  background: var(--st-secondary-background-color); color: var(--st-text-color); font: inherit; }
.gv-note { font-size: .8rem; opacity: .75; margin: .5rem 0 .75rem; }
.gv-run { padding: .5rem 1rem; border-radius: .5rem; border: 1px solid var(--st-primary-color);
  background: var(--st-primary-color); color: #fff; font: inherit; cursor: pointer; }
.gv-run:disabled { opacity: .5; cursor: default; }
.gv-status { margin-top: .6rem; font-size: .875rem; white-space: pre-wrap; }
"""

JS = """
const ENDPOINT = (model) => `https://generativelanguage.googleapis.com/v1beta/models/${encodeURIComponent(model)}:generateContent`;
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function askPage(key, model, page, prompt, schema) {
  const body = {
    contents: [{ role: "user", parts: [{ inlineData: { mimeType: "image/jpeg", data: page.image } }, { text: prompt }] }],
    generationConfig: { responseMimeType: "application/json", responseSchema: schema },
  };
  for (let attempt = 0; attempt < 4; attempt++) {
    let resp;
    try {
      resp = await fetch(ENDPOINT(model), {
        method: "POST",
        headers: { "Content-Type": "application/json", "x-goog-api-key": key },
        body: JSON.stringify(body),
      });
    } catch (e) {
      return { error: `Ağ hatası: ${e.message || e}` };
    }
    if ((resp.status === 429 || resp.status === 503) && attempt < 3) {
      await sleep(4000 * (attempt + 1));  // hız sınırı / geçici yoğunluk: bekleyip yeniden dene
      continue;
    }
    let json = null;
    try { json = await resp.json(); } catch (e) { /* gövde JSON değil */ }
    if (!resp.ok) {
      const msg = (json && json.error && json.error.message) || resp.statusText;
      return { error: `HTTP ${resp.status}: ${msg}` };
    }
    const parts = json && json.candidates && json.candidates[0] && json.candidates[0].content && json.candidates[0].content.parts;
    const text = parts ? parts.filter((p) => typeof p.text === "string" && !p.thought).map((p) => p.text).join("") : "";
    if (!text) {
      const reason = (json && json.candidates && json.candidates[0] && json.candidates[0].finishReason) || "boş yanıt";
      return { error: `Gemini yanıtı boş (${reason})` };
    }
    return { ok: text };
  }
  return { error: "HTTP 429: hız sınırı aşıldı" };
}

export default function (component) {
  const { data, setStateValue, parentElement } = component;
  const root = parentElement.querySelector(".gv-root");
  const keyInput = root.querySelector(".gv-key");
  const modelInput = root.querySelector(".gv-model");
  const button = root.querySelector(".gv-run");
  const status = root.querySelector(".gv-status");

  root.__gvData = data || {};
  if (!keyInput.value) keyInput.value = sessionStorage.getItem("gv_key") || "";
  if (!modelInput.value) modelInput.value = sessionStorage.getItem("gv_model") || root.__gvData.model || "";
  const pages = root.__gvData.pages || [];
  if (!root.__gvRunning) {
    button.disabled = pages.length === 0;
    status.textContent = pages.length ? `${pages.length} sayfa hazır.` : "Önce doğrulanacak temaları seçip sayfaları hazırlayın.";
  }
  keyInput.oninput = () => sessionStorage.setItem("gv_key", keyInput.value.trim());
  modelInput.oninput = () => sessionStorage.setItem("gv_model", modelInput.value.trim());

  button.onclick = async () => {
    const d = root.__gvData;
    const key = keyInput.value.trim();
    const model = modelInput.value.trim();
    if (!key) { status.textContent = "API anahtarı girin."; return; }
    if (!model) { status.textContent = "Model adı girin."; return; }
    root.__gvRunning = true;
    button.disabled = true;
    const results = {};
    for (let i = 0; i < d.pages.length; i++) {
      const page = d.pages[i];
      status.textContent = `Sayfa ${page.page} gönderiliyor (${i + 1}/${d.pages.length})…`;
      results[page.page] = await askPage(key, model, page, d.prompt, d.schema);
    }
    const errors = Object.values(results).filter((r) => r.error).length;
    status.textContent = `Tamamlandı: ${d.pages.length} sayfa, ${errors} hata.` + (errors ? `\\nİlk hata: ${Object.values(results).find((r) => r.error).error}` : "");
    root.__gvRunning = false;
    button.disabled = false;
    // Sunucuya yalnızca yanıtlar gider; anahtar gönderilmez.
    setStateValue("result", { run_id: d.run_id, model, results });
  };
}
"""

_component = st.components.v2.component("gemini_browser_verify", html=HTML, css=CSS, js=JS)


def gemini_browser(payload: dict | None, key: str = "gemini_browser"):
    """payload: {"run_id", "pages": [{"page", "image"}], "prompt", "schema", "model"}.
    Dönüş: bileşen sonucu; .result -> {"run_id", "model", "results": {sayfa: {"ok": json} | {"error": metin}}}"""
    return _component(data=payload or {}, key=key, on_result_change=lambda: None)
