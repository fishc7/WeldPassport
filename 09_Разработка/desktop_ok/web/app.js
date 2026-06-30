"use strict";

// ── Состояние ──────────────────────────────────────────────────────────────
let workers = [];
let dolzhnosti = [];

let tabelPaths = [];          // выбранные пути к файлам
let fuzzyDecisions = {};      // {fio_new: "add"|"skip"}
let fuzzyTotal = 0;           // кол-во нечётких — нужно решить все
let colFilters = {};          // {колонка: значение фильтра}

// ── DOM ──────────────────────────────────────────────────────────────────
const $ = (sel) => document.querySelector(sel);
const rowsEl       = $("#rows");
const emptyEl      = $("#empty");
const statusEl     = $("#status");
const searchEl     = $("#search");
const overlayEl    = $("#overlay");
const panelEl      = $("#panel");
const panelTitleEl = $("#panel-title");
const panelBodyEl  = $("#panel-body");

// ── Утилиты ───────────────────────────────────────────────────────────────
async function call(method, ...args) {
  const res = await window.pywebview.api[method](...args);
  if (!res || res.ok !== true) throw new Error((res && res.error) || "Неизвестная ошибка");
  return res.data;
}

function setStatus(text, isError = false) {
  statusEl.textContent = text || "";
  statusEl.classList.toggle("error", isError);
}

// Всегда видимая строка статуса для импорта со спиннером/иконкой
function setFeedback(el, text, kind = "") {
  el.classList.remove("busy", "ok", "err");
  if (!text) { el.innerHTML = ""; return; }
  if (kind) el.classList.add(kind);
  let icon = "";
  if (kind === "busy") icon = '<span class="spinner"></span>';
  else if (kind === "ok") icon = '<span class="fb-dot">✓</span>';
  else if (kind === "err") icon = '<span class="fb-dot">✕</span>';
  el.innerHTML = icon + `<span>${esc(text)}</span>`;
}

const esc = (v) =>
  v == null ? "" : String(v).replace(/[&<>"]/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

const dash = (v) => (v == null || v === "" ? "—" : esc(v));

function statusBadge(status) {
  if (!status) return '<span class="badge badge-empty" title="Статус не указан">?</span>';
  const s = String(status).toLowerCase();
  let cls = "badge-muted";
  if (s.includes("актив")) cls = "badge-ok";
  else if (s.includes("уволен")) cls = "badge-warn";
  return `<span class="badge ${cls}">${esc(status)}</span>`;
}

// ── Вкладки ──────────────────────────────────────────────────────────────
const TAB_IDS = ["workers", "import", "ok1c"];
document.querySelectorAll(".nav-tab").forEach((btn) => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".nav-tab").forEach((b) => b.classList.remove("active"));
    btn.classList.add("active");
    const tab = btn.dataset.tab;
    TAB_IDS.forEach((t) => {
      const pane = $("#tab-" + t);
      if (pane) pane.hidden = t !== tab;
    });
    $("#workers-toolbar").hidden = tab !== "workers";
  });
});

// ── Персонал: загрузка ────────────────────────────────────────────────────
async function loadAll() {
  setStatus("Загрузка…");
  try {
    [workers, dolzhnosti] = await Promise.all([
      call("list_workers"),
      call("list_dolzhnosti"),
    ]);
    fillColumnSelects();
    render();
    setStatus(`Всего работников: ${workers.length}`);
  } catch (e) {
    setStatus("Ошибка загрузки: " + e.message, true);
  }
}

// Наполняет select-фильтры (Должность, Статус) уникальными значениями
function fillColumnSelects() {
  const fill = (col, allLabel) => {
    const sel = document.querySelector(`.col-select[data-col="${col}"]`);
    if (!sel) return;
    const cur = sel.value;
    const vals = [...new Set(workers.map((w) => w[col]).filter(Boolean))]
      .sort((a, b) => a.localeCompare(b, "ru"));
    sel.innerHTML = `<option value="">${allLabel}</option>`
      + vals.map((v) => `<option value="${esc(v)}">${esc(v)}</option>`).join("");
    if (col === "status" && workers.some((w) => !w[col]))
      sel.innerHTML += `<option value="__empty__">⚠ не указан</option>`;
    if (vals.includes(cur) || cur === "__empty__") sel.value = cur;
  };
  fill("dolzhnost", "все");
  fill("status", "все");
}

function filtered() {
  const q = searchEl.value.trim().toLowerCase();
  return workers.filter((w) => {
    // Быстрый поиск по всем полям
    if (q) {
      const hay = [w.fio, w.tabelynyy_nomer, w.dolzhnost, w.organizatsiya,
                   w.status, w.data_priema, w.data_uvolneniya]
        .map((x) => (x == null ? "" : String(x)).toLowerCase()).join(" ");
      if (!hay.includes(q)) return false;
    }
    // Фильтры по столбцам
    for (const [col, val] of Object.entries(colFilters)) {
      if (!val) continue;
      if (col === "is_welder") {
        if (val === "yes" && !w.is_welder) return false;
        if (val === "no" && w.is_welder) return false;
      } else if (col === "dolzhnost" || col === "status") {
        if (col === "status" && val === "__empty__") { if (w[col]) return false; }
        else if ((w[col] || "") !== val) return false;       // set-фильтр (точно)
      } else {
        const cell = (w[col] == null ? "" : String(w[col])).toLowerCase();
        if (!cell.includes(val.toLowerCase())) return false;  // текст (содержит)
      }
    }
    return true;
  });
}

function render() {
  const list = filtered();
  emptyEl.hidden = list.length > 0;
  rowsEl.innerHTML = list.map((w) => `
    <tr data-id="${w.id_rabotnika}">
      <td class="num">${w.id_rabotnika}</td>
      <td>${dash(w.fio)}</td>
      <td>${dash(w.tabelynyy_nomer)}</td>
      <td>${dash(w.dolzhnost)}</td>
      <td>${dash(w.organizatsiya)}</td>
      <td>${dash(w.data_priema)}</td>
      <td>${dash(w.data_uvolneniya)}</td>
      <td>${statusBadge(w.status)}</td>
      <td>${w.is_welder ? '<span class="badge badge-welder">сварщик</span>' : ""}</td>
    </tr>`).join("");
}

// ── Персонал: панель ──────────────────────────────────────────────────────
function openPanel(title) {
  panelTitleEl.textContent = title;
  overlayEl.hidden = false;
  panelEl.hidden = false;
}
function closePanel() {
  overlayEl.hidden = true;
  panelEl.hidden = true;
  panelBodyEl.innerHTML = "";
}

async function showWorker(id) {
  openPanel("Карточка работника");
  panelBodyEl.innerHTML = "Загрузка…";
  try {
    const w = await call("get_worker", id);
    panelBodyEl.innerHTML = renderWorkerCard(w);
    $("#btn-edit").addEventListener("click", () => showForm(w));
  } catch (e) {
    panelBodyEl.innerHTML = `<div class="form-error">${esc(e.message)}</div>`;
  }
}

function field(label, value) {
  return `<div class="field-row">
    <div class="field-label">${label}</div>
    <div class="field-value">${dash(value)}</div>
  </div>`;
}

function renderWorkerCard(w) {
  const dolzhnost = w.dolzhnost_ref
    ? `${esc(w.dolzhnost_ref.nazvanie)} (разряд ${w.dolzhnost_ref.razryad})`
    : dash(w.dolzhnost_stroka);

  let welders = "";
  if (w.svarshchiki && w.svarshchiki.length) {
    welders = '<div class="section-title">Профиль сварщика</div>' +
      w.svarshchiki.map((s) => `
        <div class="welder-card">
          ${field("Клеймо", s.kleymo)}
          ${field("Разряд", s.razryad)}
          ${field("Основной способ", s.osnovnoy_sposob_svarки)}
          ${field("Статус", s.status_svarshchika)}
        </div>`).join("");
  }

  return `
    ${field("ID", w.id_rabotnika)}
    ${field("ФИО", w.fio)}
    ${field("Табельный №", w.tabelynyy_nomer)}
    ${field("Должность", dolzhnost)}
    ${field("Организация", w.organizatsiya)}
    ${field("Дата приёма", w.data_priema)}
    ${field("Статус", w.status)}
    ${welders}
    <div class="panel-actions">
      <button id="btn-edit" class="btn btn-primary">Редактировать</button>
    </div>`;
}

function _suggestStatus(worker) {
  if (worker.status) return worker.status;
  if (worker.data_uvolneniya && worker.data_uvolneniya <= new Date().toISOString().slice(0, 10))
    return "уволен";
  if (worker.data_priema) return "активный";
  return "";
}

function showForm(worker) {
  const isEdit = !!worker;
  openPanel(isEdit ? "Редактирование работника" : "Новый работник");

  const opts = dolzhnosti.map((d) =>
    `<option value="${d.id}" ${isEdit && worker.id_dolzhnosti === d.id ? "selected" : ""}>
      ${esc(d.nazvanie)} (р.${d.razryad})
    </option>`).join("");

  const suggestedStatus = isEdit ? _suggestStatus(worker) : "";
  const statusHint = isEdit && !worker.status && suggestedStatus
    ? ` <span class="form-hint">предложено по дате</span>` : "";

  panelBodyEl.innerHTML = `
    <div class="form-group">
      <label>ФИО *</label>
      <input id="f-fio" value="${isEdit ? esc(worker.fio) : ""}" />
    </div>
    <div class="form-group">
      <label>Табельный №</label>
      <input id="f-tab" value="${isEdit ? esc(worker.tabelynyy_nomer) : ""}" />
    </div>
    <div class="form-group">
      <label>Должность (справочник ЕТКС)</label>
      <select id="f-dolzh"><option value="">— не выбрано —</option>${opts}</select>
    </div>
    <div class="form-group">
      <label>Организация</label>
      <input id="f-org" value="${isEdit ? esc(worker.organizatsiya) : ""}" />
    </div>
    <div class="form-group">
      <label>Дата приёма</label>
      <input id="f-data" type="date" value="${isEdit ? esc(worker.data_priema) : ""}" />
    </div>
    <div class="form-group">
      <label>Статус${statusHint}</label>
      <select id="f-status">
        <option value=""   ${suggestedStatus === ""         ? "selected" : ""}>— требует уточнения —</option>
        <option value="активный" ${suggestedStatus === "активный" ? "selected" : ""}>активный</option>
        <option value="уволен"   ${suggestedStatus === "уволен"   ? "selected" : ""}>уволен</option>
      </select>
    </div>
    <div id="form-error" class="form-error"></div>
    <div class="panel-actions">
      <button id="btn-save" class="btn btn-primary">Сохранить</button>
      <button id="btn-cancel" class="btn">Отмена</button>
    </div>`;

  $("#btn-cancel").addEventListener("click", () =>
    isEdit ? showWorker(worker.id_rabotnika) : closePanel());
  $("#btn-save").addEventListener("click", () => saveForm(worker));
}

async function saveForm(worker) {
  const errEl = $("#form-error");
  errEl.textContent = "";
  const fio = $("#f-fio").value.trim();
  if (!fio) { errEl.textContent = "ФИО обязательно"; return; }
  const payload = {
    fio,
    tabelynyy_nomer: $("#f-tab").value,
    id_dolzhnosti: $("#f-dolzh").value || null,
    organizatsiya: $("#f-org").value,
    data_priema: $("#f-data").value || null,
    status: $("#f-status").value,
  };
  const btn = $("#btn-save");
  btn.disabled = true; btn.textContent = "Сохранение…";
  try {
    const saved = worker
      ? await call("update_worker", worker.id_rabotnika, payload)
      : await call("create_worker", payload);
    await loadAll();
    showWorker(saved.id_rabotnika);
  } catch (e) {
    errEl.textContent = e.message;
    btn.disabled = false; btn.textContent = "Сохранить";
  }
}

// ── Импорт табеля ─────────────────────────────────────────────────────────

const btnPick     = $("#btn-pick");
const pickLabel   = $("#pick-label");
const impOrg      = $("#imp-org");
const btnAnalyze  = $("#btn-analyze");
const impResult   = $("#imp-result");
const btnApply    = $("#btn-apply");
const impStatus   = $("#imp-status");
const impFeedback = $("#imp-feedback");

function updateAnalyzeBtn() {
  btnAnalyze.disabled = tabelPaths.length === 0 || impOrg.value.trim() === "";
}

btnPick.addEventListener("click", async () => {
  btnPick.disabled = true;
  btnPick.textContent = "Открытие диалога…";
  try {
    const paths = await call("pick_tabel_files");
    if (paths && paths.length) {
      tabelPaths = paths;
      const names = paths.map((p) => p.split(/[\\/]/).pop());
      pickLabel.textContent = names.join(", ");
      pickLabel.classList.remove("muted");
    }
  } catch (e) {
    pickLabel.textContent = "Ошибка: " + e.message;
  } finally {
    btnPick.disabled = false;
    btnPick.textContent = "Выбрать файлы…";
    updateAnalyzeBtn();
  }
});

impOrg.addEventListener("input", updateAnalyzeBtn);

btnAnalyze.addEventListener("click", async () => {
  btnAnalyze.disabled = true;
  btnAnalyze.textContent = "Анализ…";
  impResult.hidden = true;
  impStatus.textContent = "";
  fuzzyDecisions = {};
  fuzzyTotal = 0;
  setFeedback(impFeedback, "Анализирую файлы…", "busy");

  try {
    const data = await call("preview_import_tabel", tabelPaths, impOrg.value.trim());
    renderAnalysis(data);
    impResult.hidden = false;
    const errs = (data.errors && data.errors.length)
      ? ` ⚠ ошибки чтения: ${data.errors.length}` : "";
    setFeedback(
      impFeedback,
      `Найдено сварщиков: ${data.unique_count}. `
      + `Новых: ${data.new.length}, уже есть: ${data.exact.length}, `
      + `нечётких: ${data.fuzzy.length}, уволенных в табеле: ${data.dismissed_in_tabel.length}.${errs}`,
      errs ? "err" : "ok",
    );
  } catch (e) {
    setFeedback(impFeedback, "Ошибка: " + e.message, "err");
  } finally {
    btnAnalyze.disabled = false;
    btnAnalyze.textContent = "Анализировать";
  }
});

function renderAnalysis(data) {
  // Уволенные в табеле
  const dismissedEl = $("#imp-dismissed");
  const dismissedList = $("#imp-dismissed-list");
  if (data.dismissed_in_tabel && data.dismissed_in_tabel.length) {
    dismissedList.innerHTML = data.dismissed_in_tabel
      .map((x) => `<li>${esc(x.fio)}</li>`).join("");
    dismissedEl.hidden = false;
  } else {
    dismissedEl.hidden = true;
  }

  // Уже есть в базе
  const exactEl = $("#imp-exact");
  const exactList = $("#imp-exact-list");
  if (data.exact && data.exact.length) {
    exactList.innerHTML = data.exact.map((x) =>
      `<li>${esc(x.fio)}${x.need_svar ? ' <span class="badge badge-welder">создать профиль сварщика</span>' : ""}</li>`
    ).join("");
    exactEl.hidden = false;
  } else {
    exactEl.hidden = true;
  }

  // Нечёткие совпадения
  const fuzzyEl   = $("#imp-fuzzy");
  const fuzzyList = $("#imp-fuzzy-list");
  if (data.fuzzy && data.fuzzy.length) {
    fuzzyTotal = data.fuzzy.length;
    fuzzyList.innerHTML = data.fuzzy.map((x) => `
      <div class="fuzzy-card" data-fio="${esc(x.fio_new)}">
        <div class="fuzzy-row">
          <span class="fuzzy-label">В табеле:</span>
          <strong>${esc(x.fio_new)}</strong>
          <span class="muted">(${esc(x.dolzhnost)})</span>
        </div>
        <div class="fuzzy-row">
          <span class="fuzzy-label">В базе:</span>
          <span>${esc(x.fio_db)}</span>
        </div>
        <div class="fuzzy-btns">
          <button class="btn fuzzy-btn" data-fio="${esc(x.fio_new)}" data-decision="skip">
            Это тот же человек (пропустить)
          </button>
          <button class="btn fuzzy-btn" data-fio="${esc(x.fio_new)}" data-decision="add">
            Добавить как нового
          </button>
        </div>
      </div>`).join("");
    fuzzyEl.hidden = false;

    fuzzyList.querySelectorAll(".fuzzy-btn").forEach((btn) => {
      btn.addEventListener("click", () => {
        const fio = btn.dataset.fio;
        const decision = btn.dataset.decision;
        fuzzyDecisions[fio] = decision;

        // Подсветить выбранный вариант
        const card = btn.closest(".fuzzy-card");
        card.querySelectorAll(".fuzzy-btn").forEach((b) => b.classList.remove("btn-primary"));
        btn.classList.add("btn-primary");

        updateApplyBtn();
      });
    });
  } else {
    fuzzyEl.hidden = true;
  }

  // Новые
  const newEl   = $("#imp-new");
  const newList = $("#imp-new-list");
  if (data.new && data.new.length) {
    newList.innerHTML = data.new
      .map((x) => `<li><strong>${esc(x.fio)}</strong> — ${esc(x.dolzhnost)}</li>`).join("");
    newEl.hidden = false;
  } else {
    newEl.hidden = true;
  }

  const nothingNew = (!data.new || !data.new.length)
    && (!data.fuzzy || !data.fuzzy.length)
    && (!data.exact || !data.exact.some((x) => x.need_svar));
  $("#imp-empty").hidden = !nothingNew;

  updateApplyBtn();
}

function updateApplyBtn() {
  const allFuzzyResolved = Object.keys(fuzzyDecisions).length >= fuzzyTotal;
  btnApply.disabled = !allFuzzyResolved;
  if (fuzzyTotal > 0 && !allFuzzyResolved) {
    impStatus.textContent = `Осталось решений: ${fuzzyTotal - Object.keys(fuzzyDecisions).length}`;
  } else {
    impStatus.textContent = "";
  }
}

btnApply.addEventListener("click", async () => {
  btnApply.disabled = true;
  btnApply.textContent = "Запись…";
  impStatus.textContent = "";
  try {
    const result = await call("apply_import_tabel", fuzzyDecisions);
    const parts = [];
    if (result.inserted)        parts.push(`добавлено: ${result.inserted}`);
    if (result.svar_backfilled) parts.push(`профили сварщика: ${result.svar_backfilled}`);
    if (result.skipped)         parts.push(`пропущено: ${result.skipped}`);
    if (result.archived && result.archived.length)
      parts.push(`в архив: ${result.archived.length}`);
    impStatus.textContent = "✓ Готово. " + (parts.join(", ") || "Изменений нет");
    if (result.archive_errors && result.archive_errors.length)
      impStatus.textContent += " ⚠ Архив: " + result.archive_errors.join("; ");
    impResult.hidden = true;
    tabelPaths = [];
    pickLabel.textContent = "Файлы не выбраны";
    pickLabel.classList.add("muted");
    fuzzyDecisions = {};
    fuzzyTotal = 0;
    await loadAll(); // обновить реестр
  } catch (e) {
    impStatus.textContent = "Ошибка: " + e.message;
  } finally {
    btnApply.disabled = false;
    btnApply.textContent = "Применить импорт";
  }
});

// ── Импорт из 1С ───────────────────────────────────────────────────────────

let ok1cPath = null;

const ok1cPick     = $("#ok1c-pick");
const ok1cPickLbl  = $("#ok1c-pick-label");
const ok1cOrg      = $("#ok1c-org");
const ok1cAnalyze  = $("#ok1c-analyze");
const ok1cResult   = $("#ok1c-result");
const ok1cApply    = $("#ok1c-apply");
const ok1cStatus   = $("#ok1c-status");
const ok1cFeedback = $("#ok1c-feedback");

function updateOk1cAnalyzeBtn() {
  ok1cAnalyze.disabled = !ok1cPath || ok1cOrg.value.trim() === "";
}

ok1cPick.addEventListener("click", async () => {
  ok1cPick.disabled = true;
  ok1cPick.textContent = "Открытие диалога…";
  try {
    const path = await call("pick_1c_file");
    if (path) {
      ok1cPath = path;
      ok1cPickLbl.textContent = path.split(/[\\/]/).pop();
      ok1cPickLbl.classList.remove("muted");
    }
  } catch (e) {
    ok1cPickLbl.textContent = "Ошибка: " + e.message;
  } finally {
    ok1cPick.disabled = false;
    ok1cPick.textContent = "Выбрать файл…";
    updateOk1cAnalyzeBtn();
  }
});

ok1cOrg.addEventListener("input", updateOk1cAnalyzeBtn);

ok1cAnalyze.addEventListener("click", async () => {
  ok1cAnalyze.disabled = true;
  ok1cAnalyze.textContent = "Анализ…";
  ok1cResult.hidden = true;
  ok1cStatus.textContent = "";
  setFeedback(ok1cFeedback, "Анализирую выгрузку…", "busy");
  try {
    const data = await call("preview_import_ok1c", ok1cPath, ok1cOrg.value.trim());
    renderOk1c(data);
    ok1cResult.hidden = false;
    setFeedback(
      ok1cFeedback,
      `В выгрузке 1С: ${data.unique_count}. `
      + `Обновится: ${data.update.length}, добавится: ${data.add.length}, `
      + `активных нет в выгрузке: ${data.missing_from_1c.length}.`,
      "ok",
    );
  } catch (e) {
    setFeedback(ok1cFeedback, "Ошибка: " + e.message, "err");
    ok1cResult.hidden = true;
  } finally {
    ok1cAnalyze.disabled = false;
    ok1cAnalyze.textContent = "Анализировать";
    updateOk1cAnalyzeBtn();
  }
});

function renderOk1c(data) {
  // Будут обновлены
  const updEl = $("#ok1c-update");
  const updList = $("#ok1c-update-list");
  if (data.update && data.update.length) {
    updList.innerHTML = data.update.map((u) => {
      const tag = u.matched === "fuzzy"
        ? ` <span class="badge badge-warn">нечёткое: ${esc(u.fio_ok)}</span>` : "";
      const changes = u.changes
        .map((c) => `${esc(c.field)} → <strong>${dash(c.value)}</strong>`).join(", ");
      return `<li>${esc(u.fio_db)}${tag}<div class="muted">${changes}</div></li>`;
    }).join("");
    updEl.hidden = false;
  } else {
    updEl.hidden = true;
  }

  // Будут добавлены
  const newEl = $("#ok1c-new");
  const newList = $("#ok1c-new-list");
  if (data.add && data.add.length) {
    newList.innerHTML = data.add.map((a) => {
      const raw = a.raw ? ` <span class="muted">(в 1С: ${esc(a.raw)})</span>` : "";
      const uv = a.data_uv ? `, уволен ${esc(a.data_uv)}` : "";
      return `<li><strong>${esc(a.fio)}</strong> — ${dash(a.dolzhnost)}`
        + ` <span class="muted">[${esc(a.status)}; приём ${dash(a.data_priema)}${uv}]</span>${raw}</li>`;
    }).join("");
    newEl.hidden = false;
  } else {
    newEl.hidden = true;
  }

  // Активны в БД, нет в 1С
  const missEl = $("#ok1c-missing");
  const missList = $("#ok1c-missing-list");
  if (data.missing_from_1c && data.missing_from_1c.length) {
    missList.innerHTML = data.missing_from_1c.map((f) => `<li>${esc(f)}</li>`).join("");
    missEl.hidden = false;
  } else {
    missEl.hidden = true;
  }

  const hasChanges = (data.update && data.update.length) || (data.add && data.add.length);
  $("#ok1c-empty").hidden = !!hasChanges
    || (data.missing_from_1c && data.missing_from_1c.length);
  ok1cApply.disabled = !hasChanges;
}

ok1cApply.addEventListener("click", async () => {
  ok1cApply.disabled = true;
  ok1cApply.textContent = "Запись…";
  ok1cStatus.textContent = "";
  try {
    const r = await call("apply_import_ok1c");
    const parts = [];
    if (r.updated)      parts.push(`обновлено: ${r.updated}`);
    if (r.added)        parts.push(`добавлено: ${r.added}`);
    if (r.svar_created) parts.push(`профили сварщика: ${r.svar_created}`);
    ok1cStatus.textContent = "✓ Готово. " + (parts.join(", ") || "Изменений нет");
    ok1cResult.hidden = true;
    ok1cPath = null;
    ok1cPickLbl.textContent = "Файл не выбран";
    ok1cPickLbl.classList.add("muted");
    await loadAll(); // обновить реестр
  } catch (e) {
    ok1cStatus.textContent = "Ошибка: " + e.message;
    ok1cApply.disabled = false;
  } finally {
    ok1cApply.textContent = "Применить обновление";
  }
});

// ── События ────────────────────────────────────────────────────────────────
searchEl.addEventListener("input", render);

// Фильтры по столбцам (текстовые input + select)
document.querySelectorAll(".col-filter").forEach((el) => {
  const col = el.dataset.col;
  const evt = el.tagName === "SELECT" ? "change" : "input";
  el.addEventListener(evt, () => {
    colFilters[col] = el.value;
    render();
  });
});

// Сброс всех фильтров колонок
$("#filters-clear").addEventListener("click", () => {
  colFilters = {};
  document.querySelectorAll(".col-filter").forEach((el) => { el.value = ""; });
  render();
});

$("#btn-add").addEventListener("click", () => showForm(null));
$("#panel-close").addEventListener("click", closePanel);
overlayEl.addEventListener("click", closePanel);
rowsEl.addEventListener("click", (e) => {
  const tr = e.target.closest("tr[data-id]");
  if (tr) showWorker(Number(tr.dataset.id));
});

window.addEventListener("pywebviewready", loadAll);
if (window.pywebview && window.pywebview.api) loadAll();
