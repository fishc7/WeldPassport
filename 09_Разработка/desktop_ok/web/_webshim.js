"use strict";
/*
 * Шим pywebview для запуска web/app.js в обычном браузере (вне десктопа).
 *
 * В десктопе мост window.pywebview.api.<метод>(...) даёт pywebview. В браузере
 * его нет — здесь те же вызовы маршрутизируются на HTTP-эндпоинты server.py:
 *   • данные        → POST /api/call/<метод> {args:[...]} → конверт {ok,data/error}
 *   • выбор файлов   → нативных диалогов нет: pick_tabel_files / pick_1c_file
 *                      открывают браузерный <input type=file>, грузят файлы на
 *                      /api/upload и возвращают серверные пути — как ждёт app.js.
 *
 * Файл подключается ТОЛЬКО в веб-режиме (server.py подмешивает его перед app.js).
 * Десктопный index.html его не грузит, поэтому настоящий мост pywebview не
 * затрагивается. На всякий случай ничего не делаем, если мост уже есть.
 */
(function () {
  if (window.pywebview && window.pywebview.api) return; // десктоп — мост уже есть

  async function rpc(method, args) {
    let r;
    try {
      r = await fetch("/api/call/" + method, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ args }),
      });
    } catch (e) {
      // сервер ОК не запущен / недоступен
      return { ok: false, error: "Нет связи с сервером ОК (запущен ли server.py?)" };
    }
    if (!r.ok) {
      let msg = "HTTP " + r.status;
      try { const j = await r.json(); if (j && j.detail) msg = j.detail; } catch (_) {}
      return { ok: false, error: msg };
    }
    return r.json(); // уже {ok, data/error}
  }

  // Открыть браузерный диалог выбора файлов. Вызывается синхронно в рамках
  // пользовательского клика (иначе браузер заблокирует открытие диалога).
  function browsePickFiles(multiple) {
    return new Promise((resolve) => {
      const input = document.createElement("input");
      input.type = "file";
      input.accept = ".xlsx,.xls";
      input.multiple = !!multiple;
      input.style.display = "none";
      input.addEventListener("change", () => {
        const files = Array.from(input.files || []);
        input.remove();
        resolve(files);
      });
      document.body.appendChild(input);
      input.click();
    });
  }

  async function uploadFiles(files) {
    if (!files.length) return [];
    const fd = new FormData();
    files.forEach((f) => fd.append("files", f, f.name));
    const r = await fetch("/api/upload", { method: "POST", body: fd });
    const j = await r.json();
    if (!j || j.ok !== true) throw new Error((j && j.error) || "Не удалось загрузить файлы");
    return j.data; // серверные пути
  }

  // Спец-обработка методов выбора файлов (нативных диалогов в браузере нет).
  const overrides = {
    async pick_tabel_files() {
      const files = await browsePickFiles(true);
      if (!files.length) return { ok: true, data: [] };
      try {
        return { ok: true, data: await uploadFiles(files) };
      } catch (e) {
        return { ok: false, error: e.message };
      }
    },
    async pick_1c_file() {
      const files = await browsePickFiles(false);
      if (!files.length) return { ok: true, data: null };
      try {
        const paths = await uploadFiles(files);
        return { ok: true, data: paths[0] || null };
      } catch (e) {
        return { ok: false, error: e.message };
      }
    },
  };

  // Любой метод, кроме перечисленных выше, уходит RPC-вызовом на backend.
  const api = new Proxy(overrides, {
    get(target, prop) {
      if (typeof prop === "string" && prop in target) return target[prop];
      return (...args) => rpc(prop, args);
    },
  });

  window.pywebview = { api };

  // app.js на старте слушает pywebviewready и/или сразу зовёт loadAll(), если
  // мост уже есть. Мост мы поставили синхронно выше, так что событие нужно лишь
  // на случай, если app.js уже успел навесить слушатель.
  window.dispatchEvent(new Event("pywebviewready"));
})();
