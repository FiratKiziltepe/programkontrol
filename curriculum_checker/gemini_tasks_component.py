"""Tarayıcıda çalışan genel amaçlı Gemini görev bileşeni (Streamlit components v2).

Her görev: isteğe bağlı bir görüntü (JPEG, base64), bir metin istemi ve isteğe bağlı JSON şeması.
API anahtarı yalnızca kullanıcının tarayıcısında kalır (bu sekmenin sessionStorage'ı; "3. Gemini Doğrulama"
sekmesiyle ortak). Python'a yalnızca Gemini yanıtları ve hata mesajları döner; anahtar hiçbir zaman dönmez.
"""
from __future__ import annotations

import streamlit as st

HTML = """
<div class="gt-root">
  <div class="gt-row">
    <label>Gemini API anahtarı
      <input class="gt-key" type="password" autocomplete="off" placeholder="AIza…">
    </label>
    <label>Model
      <input class="gt-model" type="text" autocomplete="off">
    </label>
  </div>
  <p class="gt-note">Anahtar yalnızca bu tarayıcı sekmesinde tutulur (sekme kapanınca silinir); sunucuya gönderilmez.
  İstekler tarayıcınızdan doğrudan Google Gemini API'sine gider.</p>
  <button class="gt-run" type="button"></button>
  <div class="gt-bar"><div class="gt-fill"></div></div>
  <div class="gt-status"></div>
</div>
"""

CSS = """
.gt-root { font-family: var(--st-font); color: var(--st-text-color); }
.gt-row { display: flex; gap: 1rem; flex-wrap: wrap; }
.gt-row label { display: flex; flex-direction: column; gap: .25rem; font-size: .875rem; flex: 1 1 16rem; }
.gt-row input { padding: .5rem .6rem; border: 1px solid var(--st-border-color, #d6d6d9); border-radius: .5rem;
  background: var(--st-secondary-background-color); color: var(--st-text-color); font: inherit; }
.gt-note { font-size: .8rem; opacity: .75; margin: .5rem 0 .75rem; }
.gt-run { padding: .5rem 1rem; border-radius: .5rem; border: 1px solid var(--st-primary-color);
  background: var(--st-primary-color); color: #fff; font: inherit; cursor: pointer; }
.gt-run:disabled { opacity: .5; cursor: default; }
.gt-bar { height: 6px; border-radius: 3px; background: var(--st-secondary-background-color); margin-top: .6rem; overflow: hidden; display: none; }
.gt-fill { height: 100%; width: 0; background: var(--st-primary-color); transition: width .2s; }
.gt-status { margin-top: .5rem; font-size: .875rem; white-space: pre-wrap; }
"""

JS = """
const ENDPOINT = (model) => `https://generativelanguage.googleapis.com/v1beta/models/${encodeURIComponent(model)}:generateContent`;
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function runTask(key, model, task) {
  const parts = [];
  if (task.image) parts.push({ inlineData: { mimeType: "image/jpeg", data: task.image } });
  parts.push({ text: task.text });
  const generationConfig = task.schema
    ? { responseMimeType: "application/json", responseSchema: task.schema }
    : { responseMimeType: "text/plain" };
  const body = { contents: [{ role: "user", parts }], generationConfig };
  if (task.system) body.systemInstruction = { parts: [{ text: task.system }] };
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
    const cand = json && json.candidates && json.candidates[0];
    const ps = cand && cand.content && cand.content.parts;
    const text = ps ? ps.filter((p) => typeof p.text === "string" && !p.thought).map((p) => p.text).join("") : "";
    if (!text) return { error: `Gemini yanıtı boş (${(cand && cand.finishReason) || "boş yanıt"})` };
    return { ok: text };
  }
  return { error: "HTTP 429: hız sınırı aşıldı" };
}

export default function (component) {
  const { data, setStateValue, parentElement } = component;
  const root = parentElement.querySelector(".gt-root");
  const keyInput = root.querySelector(".gt-key");
  const modelInput = root.querySelector(".gt-model");
  const button = root.querySelector(".gt-run");
  const status = root.querySelector(".gt-status");
  const bar = root.querySelector(".gt-bar");
  const fill = root.querySelector(".gt-fill");

  root.__gtData = data || {};
  const d0 = root.__gtData;
  if (!keyInput.value) keyInput.value = sessionStorage.getItem("gv_key") || "";
  if (!modelInput.value) modelInput.value = sessionStorage.getItem("gv_model") || d0.model || "";
  button.textContent = d0.button || "Gemini ile çalıştır";
  const tasks = d0.tasks || [];
  if (!root.__gtRunning) {
    button.disabled = tasks.length === 0;
    status.textContent = tasks.length ? (d0.ready || `${tasks.length} istek hazır.`) : (d0.empty || "Gönderilecek istek yok.");
  }
  keyInput.oninput = () => sessionStorage.setItem("gv_key", keyInput.value.trim());
  modelInput.oninput = () => sessionStorage.setItem("gv_model", modelInput.value.trim());

  button.onclick = async () => {
    const d = root.__gtData;
    const key = keyInput.value.trim();
    const model = modelInput.value.trim();
    if (!key) { status.textContent = "API anahtarı girin."; return; }
    if (!model) { status.textContent = "Model adı girin."; return; }
    root.__gtRunning = true;
    button.disabled = true;
    bar.style.display = "block";
    const results = {};
    const list = d.tasks || [];
    for (let i = 0; i < list.length; i++) {
      const t = list[i];
      status.textContent = `${t.label || t.id} gönderiliyor (${i + 1}/${list.length})…`;
      fill.style.width = `${(100 * i) / list.length}%`;
      results[t.id] = await runTask(key, model, t);
    }
    fill.style.width = "100%";
    const errs = Object.values(results).filter((r) => r.error);
    status.textContent = `Tamamlandı: ${list.length} istek, ${errs.length} hata.` + (errs.length ? `\\nİlk hata: ${errs[0].error}` : "");
    root.__gtRunning = false;
    button.disabled = false;
    // Python'a yalnızca yanıtlar gider; anahtar gönderilmez.
    setStateValue("result", { run_id: d.run_id, model, results });
  };
}
"""

_component = st.components.v2.component("gemini_tasks", html=HTML, css=CSS, js=JS)


def gemini_tasks(payload: dict | None, key: str):
    """payload: {"run_id", "model", "button", "ready", "empty",
                 "tasks": [{"id", "label", "text", "image"?, "schema"?, "system"?}]}
    Dönüş .result -> {"run_id", "model", "results": {görev id: {"ok": metin} | {"error": metin}}}"""
    return _component(data=payload or {}, key=key, on_result_change=lambda: None)
