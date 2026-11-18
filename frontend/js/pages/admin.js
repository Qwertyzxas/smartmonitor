import { api } from "../api.js";
import {
  badge, COMMAND_LABEL, confirmDialog, emptyState, esc, fmtAgo, fmtDate, fmtMs, icon, modal, pager,
  PROBLEM_LABEL, toast, withLoading,
} from "../ui.js";
import { showConversation } from "./incident.js";

const TABS = [
  ["services", "Сервисы"], ["settings", "Настройки ИИ"], ["ai", "Логи ИИ-агента"], ["actions", "Действия агента"],
  ["sim", "Симулятор сбоев"], ["users", "Пользователи"],
];

export async function render(ctx) {
  const { main, params } = ctx;
  const tab = TABS.some(([k]) => k === params.tab) ? params.tab : "services";
  main.innerHTML = `
    <div class="page-head"><div><h1>Администрирование</h1><div class="sub">Сервисы, права ИИ-агента, аудит и пользователи</div></div></div>
    <div class="tabs">${TABS.map(([k, l]) => `<button data-tab="${k}" class="${k === tab ? "active" : ""}">${l}</button>`).join("")}</div>
    <div id="tab"></div>`;
  main.querySelector(".tabs").onclick = (e) => {
    const b = e.target.closest("[data-tab]");
    if (b) location.hash = `#/admin/${b.dataset.tab}`;
  };
  const el = main.querySelector("#tab");
  await { services: servicesTab, settings: settingsTab, ai: aiTab, actions: actionsTab, sim: simTab, users: usersTab }[tab](el, ctx);
}

async function servicesTab(el) {
  const load = async () => {
    const services = await api("/services");
    el.innerHTML = `<div class="card">
      <div class="card-head"><h2>Сервисы (${services.length})</h2><button class="btn primary" id="add">${icon("plus")}Добавить</button></div>
      ${services.length ? `<div class="table-wrap"><table>
        <thead><tr><th>Сервис</th><th>Статус</th><th>Интервал</th><th>Порог</th><th>Авто-действия</th><th>Проверка</th><th class="right">Действия</th></tr></thead>
        <tbody>${services.map((s) => `<tr>
          <td><a href="#/services/${s.id}"><b>${esc(s.name)}</b></a><div class="mono faint small ellipsis" style="max-width:320px">${esc(s.url)}</div></td>
          <td>${s.is_active ? badge(s.current_status) : badge("", "Пауза")}</td>
          <td class="mono small">${s.interval_seconds} с</td>
          <td class="mono small">${fmtMs(s.slow_threshold_ms)}</td>
          <td>${s.auto_actions_enabled ? '<span class="badge up">вкл</span>' : '<span class="badge">выкл</span>'}</td>
          <td class="small muted nowrap">${fmtAgo(s.last_checked_at)}</td>
          <td class="right nowrap">
            <button class="btn sm" data-check="${s.id}" title="Проверить">${icon("play")}</button>
            <button class="btn sm" data-edit="${s.id}" title="Редактировать">${icon("edit")}</button>
            <button class="btn sm danger" data-del="${s.id}" title="Удалить">${icon("trash")}</button>
          </td></tr>`).join("")}</tbody></table></div>` : emptyState("Сервисов нет")}
    </div>`;
    el.querySelector("#add").onclick = () => openServiceForm(null, load);
    el.querySelectorAll("[data-edit]").forEach((b) => (b.onclick = () => openServiceForm(services.find((s) => String(s.id) === b.dataset.edit), load)));
    el.querySelectorAll("[data-check]").forEach((b) => (b.onclick = () => withLoading(b, async () => {
      try {
        const r = await api(`/services/${b.dataset.check}/check`, { method: "POST" });
        toast(`${r.check.status} · ${r.check.status_code ?? r.check.error_kind ?? ""} · ${fmtMs(r.check.duration_ms)}`, r.check.status === "up" ? "success" : "error");
        if (r.incident_opened) toast(`Открыт инцидент #${r.incident_opened}`, "error");
        await load();
      } catch (err) { toast(err.message, "error"); }
    })));
    el.querySelectorAll("[data-del]").forEach((b) => (b.onclick = async () => {
      const s = services.find((x) => String(x.id) === b.dataset.del);
      if (!(await confirmDialog(`Удалить сервис «${s.name}» вместе с историей проверок и инцидентов?`, "Удалить"))) return;
      await api(`/services/${s.id}`, { method: "DELETE" });
      toast("Сервис удалён", "success");
      load();
    }));
  };
  await load();
}

export function openServiceForm(service, onSaved) {
  const s = service ?? { name: "", url: "https://", interval_seconds: 60, timeout_seconds: 10, slow_threshold_ms: 2000, is_active: true, auto_actions_enabled: false };
  const m = modal(`
    <h2 style="margin-bottom:18px">${service ? "Редактировать сервис" : "Новый сервис"}</h2>
    <form id="svc-form" class="form-grid">
      <label class="field full">Название<input type="text" name="name" required maxlength="120" value="${esc(s.name)}"></label>
      <label class="field full">URL<input type="url" name="url" required value="${esc(s.url)}" placeholder="https://example.com/health"></label>
      <label class="field">Интервал проверки, с<input type="number" name="interval_seconds" min="10" max="86400" required value="${s.interval_seconds}"></label>
      <label class="field">Таймаут, с<input type="number" name="timeout_seconds" min="1" max="60" step="0.5" required value="${s.timeout_seconds}"></label>
      <label class="field">Порог «медленно», мс<input type="number" name="slow_threshold_ms" min="50" max="60000" required value="${s.slow_threshold_ms}"></label>
      <div></div>
      <label class="switch full"><input type="checkbox" name="is_active" ${s.is_active ? "checked" : ""}><span class="track"></span>
        <span class="txt"><b>Активен</b><span>Планировщик проверяет сервис по интервалу</span></span></label>
      <label class="switch full"><input type="checkbox" name="auto_actions_enabled" ${s.auto_actions_enabled ? "checked" : ""}><span class="track"></span>
        <span class="txt"><b>Разрешить ИИ авто-действия для этого сервиса</b><span>restart / scale_up выполняются без подтверждения (если включено и глобально)</span></span></label>
      <div class="full modal-foot" style="margin-top:6px"><button type="button" class="btn" data-close>Отмена</button><button class="btn primary" type="submit">Сохранить</button></div>
    </form>`);
  const form = m.el.querySelector("#svc-form");
  form.onsubmit = async (e) => {
    e.preventDefault();
    const fd = new FormData(form);
    const body = {
      name: fd.get("name").trim(), url: fd.get("url").trim(),
      interval_seconds: Number(fd.get("interval_seconds")), timeout_seconds: Number(fd.get("timeout_seconds")),
      slow_threshold_ms: Number(fd.get("slow_threshold_ms")),
      is_active: fd.get("is_active") === "on", auto_actions_enabled: fd.get("auto_actions_enabled") === "on",
    };
    const btn = form.querySelector("[type=submit]");
    await withLoading(btn, async () => {
      try {
        await api(service ? `/services/${service.id}` : "/services", { method: service ? "PUT" : "POST", body });
        toast(service ? "Сервис обновлён" : "Сервис добавлен", "success");
        m.close();
        onSaved?.();
      } catch (err) { toast(err.message, "error"); }
    });
  };
}

async function settingsTab(el) {
  const load = async () => {
    const s = await api("/settings");
    el.innerHTML = `<div class="split">
      <div class="card stack">
        <h2>Права ИИ-агента</h2>
        <label class="switch"><input type="checkbox" data-key="auto_actions_enabled" ${s.auto_actions_enabled ? "checked" : ""}><span class="track"></span>
          <span class="txt"><b>Разрешить автоматическое выполнение опасных команд</b>
          <span>restart и scale_up выполняются сразу у сервисов с включённым флагом «авто-действия». Иначе ждут подтверждения администратора.</span></span></label>
        <label class="switch"><input type="checkbox" data-key="ai_enabled" ${s.ai_enabled ? "checked" : ""}><span class="track"></span>
          <span class="txt"><b>Использовать LLM (OpenRouter)</b><span>Если выключено или недоступно — работает локальный классификатор scikit-learn.</span></span></label>
        <label class="switch"><input type="checkbox" data-key="telegram_notifications" ${s.telegram_notifications ? "checked" : ""}><span class="track"></span>
          <span class="txt"><b>Уведомления в Telegram</b><span>Об инцидентах, упавших автотестах и команде notify_admin.</span></span></label>
        <div class="faint small">${s.updated_at ? `Изменено ${fmtDate(s.updated_at)}${s.updated_by ? ` пользователем ${esc(s.updated_by)}` : ""}` : "Настройки по умолчанию"}</div>
      </div>
      <div class="card stack" style="align-self:start">
        <h2>Интеграции</h2>
        <dl class="kv">
          <dt>OpenRouter</dt><dd>${s.openrouter_configured ? badge("up", "настроен") : badge("degraded", "нет ключа")}</dd>
          <dt>Модель</dt><dd class="mono small">${esc(s.openrouter_model)}</dd>
          <dt>Telegram</dt><dd>${s.telegram_configured ? badge("up", "настроен") : badge("degraded", "не настроен")}</dd>
        </dl>
        ${!s.openrouter_configured ? '<div class="notice">Задайте OPENROUTER_API_KEY в .env — сейчас рекомендации выдаёт fallback-классификатор.</div>' : ""}
        <div class="row">
          <button class="btn" id="preview">Предпросмотр отчёта</button>
          <button class="btn primary" id="send" ${s.telegram_configured ? "" : "disabled"}>${icon("send")}Отчёт в Telegram</button>
        </div>
      </div>
    </div>`;
    el.querySelectorAll("[data-key]").forEach((input) => (input.onchange = async () => {
      try {
        await api("/settings", { method: "PUT", body: { [input.dataset.key]: input.checked } });
        toast("Настройки сохранены", "success");
        load();
      } catch (err) { toast(err.message, "error"); input.checked = !input.checked; }
    }));
    el.querySelector("#preview").onclick = async () => {
      const text = await api("/reports/preview", { text: true });
      modal(`<h2 style="margin-bottom:12px">Отчёт за 24 ч</h2><pre>${esc(text.replace(/<\/?b>/g, ""))}</pre><div class="modal-foot"><button class="btn" data-close>Закрыть</button></div>`);
    };
    el.querySelector("#send").onclick = (e) => withLoading(e.currentTarget, async () => {
      try { const r = await api("/reports/telegram", { method: "POST" }); toast(r.sent ? "Отчёт отправлен" : "Не удалось отправить", r.sent ? "success" : "error"); } catch (err) { toast(err.message, "error"); }
    });
  };
  await load();
}

async function aiTab(el) {
  let page = 1;
  let provider = "";
  el.innerHTML = `<div class="card">
    <div class="card-head"><h2>Диалоги ИИ-агента</h2>
      <div class="segmented" id="prov"><button data-p="" class="active">Все</button><button data-p="openrouter">OpenRouter</button><button data-p="fallback">Fallback</button></div></div>
    <div class="table-wrap"><table><thead><tr><th>#</th><th>Время</th><th>Инцидент</th><th>Провайдер</th><th>Модель</th><th>Решение</th><th>Результат</th><th>Латентность</th></tr></thead>
    <tbody id="rows"></tbody></table></div><div class="pager" id="pager"></div></div>`;
  const load = async () => {
    const res = await api(`/ai/conversations?page=${page}&size=20${provider ? `&provider=${provider}` : ""}`);
    el.querySelector("#rows").innerHTML = res.items.length ? res.items.map((c) => `
      <tr class="clickable" data-conv="${c.id}">
        <td class="mono">${c.id}</td><td class="nowrap small">${fmtDate(c.created_at)}</td>
        <td>${c.incident_id ? `<a href="#/incidents/${c.incident_id}" onclick="event.stopPropagation()">#${c.incident_id}</a>` : "—"}</td>
        <td><span class="badge ${esc(c.provider)}">${esc(c.provider)}</span></td>
        <td class="mono small">${esc(c.model)}</td>
        <td class="small">${c.parsed ? `${PROBLEM_LABEL[c.parsed.problem_type] ?? esc(c.parsed.problem_type)} → <span class="chip">${esc(c.parsed.command?.action)}</span>` : "—"}</td>
        <td>${c.success ? badge("passed", "успех") : `<span class="badge failed" title="${esc(c.error)}">ошибка</span>`}</td>
        <td class="mono small">${fmtMs(c.latency_ms)}</td></tr>`).join("") : `<tr><td colspan="8">${emptyState("Диалогов пока нет")}</td></tr>`;
    el.querySelectorAll("[data-conv]").forEach((r) => (r.onclick = () => showConversation(r.dataset.conv)));
    pager(el.querySelector("#pager"), res, (p) => { page = p; load(); });
  };
  el.querySelector("#prov").onclick = (e) => {
    const b = e.target.closest("[data-p]");
    if (!b) return;
    provider = b.dataset.p; page = 1;
    el.querySelectorAll("#prov button").forEach((x) => x.classList.toggle("active", x === b));
    load();
  };
  await load();
}

async function actionsTab(el) {
  let page = 1;
  el.innerHTML = `<div class="card"><div class="card-head"><h2>Журнал действий агента</h2></div>
    <div class="table-wrap"><table><thead><tr><th>#</th><th>Время</th><th>Инцидент</th><th>Источник</th><th>Команда</th><th>Статус</th><th>Результат</th></tr></thead>
    <tbody id="rows"></tbody></table></div><div class="pager" id="pager"></div></div>`;
  const load = async () => {
    const res = await api(`/actions?page=${page}&size=20`);
    el.querySelector("#rows").innerHTML = res.items.length ? res.items.map((a) => `
      <tr class="clickable" onclick="location.hash='#/incidents/${a.incident_id}'">
        <td class="mono">${a.id}</td><td class="nowrap small">${fmtDate(a.created_at)}</td><td>#${a.incident_id}</td>
        <td><span class="badge ${esc(a.source)}">${esc(a.source)}</span></td>
        <td><span class="chip">${esc(a.command)}</span> <span class="muted small">${COMMAND_LABEL[a.command] ?? ""}</span></td>
        <td>${badge(a.status)} ${a.status === "executed" ? `<span class="faint small">${a.auto ? "авто" : "вручную"}</span>` : ""}</td>
        <td class="muted small" style="max-width:380px">${esc(a.result ?? "")}</td></tr>`).join("") : `<tr><td colspan="7">${emptyState("Действий пока нет")}</td></tr>`;
    pager(el.querySelector("#pager"), res, (p) => { page = p; load(); });
  };
  await load();
}

const SIM_MODES = [
  ["up", "Работает", "200 OK"], ["down", "Упал", "503"], ["db_error", "Ошибка БД", "500 + текст ошибки БД"],
  ["slow", "Медленно", "ответ через 2.5 с"], ["timeout", "Таймаут", "висит 30 с"], ["flaky", "Нестабилен", "50% ошибок"],
];

async function simTab(el) {
  const load = async () => {
    const modes = await api("/sim");
    if (!("demo" in modes)) modes.demo = "up";
    el.innerHTML = `<div class="split">
      <div class="card">
        <div class="card-head"><h2>Эмулируемые сервисы</h2></div>
        <p class="muted small" style="margin-top:0">Встроенный эндпоинт <code>/api/sim/&lt;имя&gt;</code> ведёт себя как внешний сервис. Переключите режим — и после 2 неудачных проверок откроется инцидент, а ИИ-агент выдаст рекомендацию.</p>
        ${Object.entries(modes).map(([name, mode]) => `
          <div class="action-card">
            <div class="row" style="justify-content:space-between;margin-bottom:10px">
              <div><b>${esc(name)}</b> <span class="mono faint small">/api/sim/${esc(name)}</span></div>${badge(mode === "up" ? "up" : mode === "slow" ? "degraded" : "down", SIM_MODES.find((m) => m[0] === mode)?.[1] ?? mode)}
            </div>
            <div class="row">${SIM_MODES.map(([m, label, hint]) => `<button class="btn sm ${m === mode ? "primary" : ""}" data-sim="${esc(name)}" data-mode="${m}" title="${hint}">${label}</button>`).join("")}</div>
          </div>`).join("")}
      </div>
      <div class="card stack" style="align-self:start">
        <h2>Новый эмулятор</h2>
        <form id="sim-form" class="stack">
          <label class="field">Имя<input type="text" name="name" pattern="[a-z0-9-]+" required placeholder="payments-api"></label>
          <button class="btn primary">Создать и добавить сервис</button>
        </form>
        <div class="notice info">Сервис «Demo-сервис (симулятор)» создаётся автоматически и указывает на <code>/api/sim/demo</code>.</div>
      </div></div>`;
    el.querySelectorAll("[data-sim]").forEach((b) => (b.onclick = async () => {
      await api(`/sim/${b.dataset.sim}`, { method: "PUT", body: { mode: b.dataset.mode } });
      toast(`${b.dataset.sim}: режим «${b.textContent}»`, "success");
      load();
    }));
    el.querySelector("#sim-form").onsubmit = async (e) => {
      e.preventDefault();
      const name = new FormData(e.target).get("name").trim();
      try {
        await api(`/sim/${encodeURIComponent(name)}/service`, { method: "POST" });
        toast("Эмулятор и сервис созданы", "success");
        load();
      } catch (err) { toast(err.message, "error"); }
    };
  };
  await load();
}

async function usersTab(el) {
  const load = async () => {
    const users = await api("/users");
    el.innerHTML = `<div class="card"><div class="card-head"><h2>Пользователи (${users.length})</h2></div>
      <div class="table-wrap"><table><thead><tr><th>#</th><th>Логин</th><th>Роль</th><th>Создан</th></tr></thead><tbody>
      ${users.map((u) => `<tr><td class="mono">${u.id}</td><td><b>${esc(u.username)}</b></td>
        <td><select data-user="${u.id}" style="width:auto;height:32px">
          <option value="viewer" ${u.role === "viewer" ? "selected" : ""}>viewer — только просмотр</option>
          <option value="admin" ${u.role === "admin" ? "selected" : ""}>admin — управление</option></select></td>
        <td class="small muted">${fmtDate(u.created_at)}</td></tr>`).join("")}
      </tbody></table></div></div>`;
    el.querySelectorAll("[data-user]").forEach((s) => (s.onchange = async () => {
      try { await api(`/users/${s.dataset.user}`, { method: "PATCH", body: { role: s.value } }); toast("Роль обновлена", "success"); } catch (err) { toast(err.message, "error"); load(); }
    }));
  };
  await load();
}
