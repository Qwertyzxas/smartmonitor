import { api, auth } from "../api.js";
import {
  badge, COMMAND_LABEL, confirmDialog, emptyState, esc, fmtDate, fmtDuration, fmtMs, icon, modal,
  PROBLEM_LABEL, SEVERITY_CLASS, SEVERITY_LABEL, toast, withLoading,
} from "../ui.js";

const SOURCE_LABEL = { openrouter: "OpenRouter LLM", fallback: "Локальный классификатор (sklearn)", manual: "Вручную" };

export async function render(ctx) {
  const { main, params } = ctx;
  const id = params.id;

  const load = async () => {
    const inc = await api(`/incidents/${id}`);
    const convs = auth.isAdmin ? await api(`/incidents/${id}/conversations`) : [];
    main.innerHTML = `
      <div class="crumbs"><a href="#/incidents">Инциденты</a> / <a href="#/services/${inc.service_id}">${esc(inc.service_name)}</a></div>
      <div class="page-head">
        <div>
          <div class="row"><h1>Инцидент #${inc.id}</h1>${badge(inc.status)}
            ${inc.severity ? `<span class="badge ${SEVERITY_CLASS[inc.severity] ?? ""}">${SEVERITY_LABEL[inc.severity] ?? esc(inc.severity)}</span>` : ""}</div>
          <div class="sub">${esc(inc.reason)}</div>
        </div>
        ${auth.isAdmin ? `<div class="row">
          <button class="btn" id="reanalyze">${icon("sparkles")}Повторный анализ ИИ</button>
          ${inc.status === "open" ? `<button class="btn" id="resolve">${icon("check")}Закрыть вручную</button>` : ""}
        </div>` : ""}
      </div>
      <div class="kpis">
        <div class="card kpi"><div class="label">Сервис</div><div class="value" style="font-size:18px"><a href="#/services/${inc.service_id}">${esc(inc.service_name)}</a></div></div>
        <div class="card kpi"><div class="label">Начало</div><div class="value" style="font-size:18px">${fmtDate(inc.started_at)}</div></div>
        <div class="card kpi"><div class="label">Длительность</div><div class="value" style="font-size:18px">${fmtDuration(inc.started_at, inc.resolved_at)}</div><div class="hint">${inc.resolved_at ? `закрыт ${fmtDate(inc.resolved_at)}` : "продолжается"}</div></div>
        <div class="card kpi"><div class="label">Неудачных проверок</div><div class="value">${inc.failed_checks}</div></div>
      </div>
      <div class="split">
        <div class="stack">
          <section class="card">
            <div class="ai-head" style="margin-bottom:14px">
              <div class="ai-icon">${icon("sparkles")}</div>
              <div class="grow">
                <h2>Анализ ИИ-агента</h2>
                <div class="muted small">${inc.problem_type ? `Тип проблемы: <b style="color:var(--text)">${PROBLEM_LABEL[inc.problem_type] ?? esc(inc.problem_type)}</b>` : "Агент анализирует инцидент…"}</div>
              </div>
            </div>
            ${inc.ai_summary ? `<p style="margin:0 0 14px">${esc(inc.ai_summary)}</p>` : ""}
            <div id="actions">${inc.actions.length ? inc.actions.slice().reverse().map(actionCard).join("") : emptyState("Рекомендаций пока нет — страница обновится автоматически")}</div>
          </section>
          ${auth.isAdmin ? `<section class="card">
            <div class="card-head"><h2>Диалоги с ИИ (аудит)</h2><span class="muted small">${convs.length} записей</span></div>
            ${convs.length ? `<div class="table-wrap"><table><thead><tr><th>Время</th><th>Провайдер</th><th>Модель</th><th>Результат</th><th>Латентность</th></tr></thead><tbody>
              ${convs.map((c) => `<tr class="clickable" data-conv="${c.id}"><td class="nowrap small">${fmtDate(c.created_at)}</td>
                <td><span class="badge ${esc(c.provider)}">${esc(c.provider)}</span></td><td class="mono small">${esc(c.model)}</td>
                <td>${c.success ? badge("passed", "успех") : `<span class="badge failed" title="${esc(c.error)}">ошибка</span>`}</td>
                <td class="mono small">${fmtMs(c.latency_ms)}</td></tr>`).join("")}
            </tbody></table></div>` : emptyState("Диалогов нет")}
          </section>` : ""}
        </div>
        <section class="card" style="align-self:start">
          <div class="card-head"><h2>Последние проверки</h2></div>
          ${inc.recent_checks.map((c) => `
            <div class="row" style="padding:8px 0;border-bottom:1px solid var(--border)">
              <span class="dot ${c.status}" style="margin-top:0"></span>
              <div class="grow" style="min-width:0"><div class="small">${fmtDate(c.checked_at)}</div>
                <div class="faint small ellipsis">${esc(c.error ?? "OK")}</div></div>
              <span class="mono small">${c.status_code ?? "—"}</span><span class="mono small muted">${fmtMs(c.duration_ms)}</span>
            </div>`).join("")}
        </section>
      </div>`;
    bind(inc);
    return inc;
  };

  const bind = (inc) => {
    main.querySelector("#reanalyze")?.addEventListener("click", (e) => withLoading(e.currentTarget, async () => {
      try {
        const r = await api(`/incidents/${id}/analyze`, { method: "POST" });
        toast(r.status === "done" ? "Агент подготовил новую рекомендацию" : "Анализ уже выполняется", "success");
        await load();
      } catch (err) { toast(err.message, "error"); }
    }));
    main.querySelector("#resolve")?.addEventListener("click", async () => {
      if (!(await confirmDialog("Закрыть инцидент вручную?", "Закрыть"))) return;
      await api(`/incidents/${id}/resolve`, { method: "POST" });
      toast("Инцидент закрыт", "success");
      load();
    });
    main.querySelector("#actions").addEventListener("click", async (e) => {
      const ex = e.target.closest("[data-exec]");
      const rj = e.target.closest("[data-reject]");
      if (ex) {
        const a = inc.actions.find((x) => String(x.id) === ex.dataset.exec);
        if (!(await confirmDialog(`Выполнить команду «${COMMAND_LABEL[a.command] ?? a.command}» для сервиса ${inc.service_name}?`, "Выполнить"))) return;
        try { await api(`/actions/${a.id}/execute`, { method: "POST" }); toast("Команда выполнена", "success"); } catch (err) { toast(err.message, "error"); }
        load();
      } else if (rj) {
        try { await api(`/actions/${rj.dataset.reject}/reject`, { method: "POST" }); toast("Действие отклонено"); } catch (err) { toast(err.message, "error"); }
        load();
      }
    });
    main.querySelectorAll("[data-conv]").forEach((row) => (row.onclick = () => showConversation(row.dataset.conv)));
  };

  let inc = await load();
  ctx.every(async () => {
    if (inc.status === "open" || !inc.actions.length) inc = await load().catch(() => inc);
  }, 8000);
}

function actionCard(a) {
  const canAct = auth.isAdmin && (a.status === "suggested" || a.status === "failed") && a.command !== "none";
  return `<div class="action-card">
    <div class="row" style="justify-content:space-between">
      <div class="row">
        <span class="badge ${esc(a.source)}">${SOURCE_LABEL[a.source] ?? esc(a.source)}</span>
        ${a.problem_type ? `<span class="badge accent">${PROBLEM_LABEL[a.problem_type] ?? esc(a.problem_type)}</span>` : ""}
      </div>
      <span class="faint small">${fmtDate(a.created_at)}</span>
    </div>
    <div class="rec">${esc(a.recommendation)}</div>
    <div class="row" style="justify-content:space-between">
      <div class="row small">
        <span class="muted">Команда:</span><span class="chip">${esc(a.command)}</span>
        <span class="muted">${COMMAND_LABEL[a.command] ?? ""}</span>
        ${badge(a.status)}
        ${a.status === "executed" ? `<span class="badge ${a.auto ? "info" : ""}">${a.auto ? "автоматически" : "администратором"}</span>` : ""}
      </div>
      ${canAct ? `<div class="row"><button class="btn sm success" data-exec="${a.id}">${icon("play")}Выполнить</button>
        ${a.status === "suggested" ? `<button class="btn sm danger" data-reject="${a.id}">${icon("x")}Отклонить</button>` : ""}</div>` : ""}
    </div>
    ${a.result ? `<div class="muted small" style="margin-top:10px">↳ ${esc(a.result)}${a.executed_at ? ` · ${fmtDate(a.executed_at)}` : ""}</div>` : ""}
    ${a.command_payload ? `<details style="margin-top:10px"><summary class="faint small" style="cursor:pointer">JSON команды</summary><pre style="margin-top:8px">${esc(JSON.stringify(a.command_payload, null, 2))}</pre></details>` : ""}
  </div>`;
}

export async function showConversation(convId) {
  const c = await api(`/ai/conversations/${convId}`);
  const messages = c.request?.messages;
  const body = messages
    ? messages.map((m) => `<div class="msg ${esc(m.role)}"><div class="role">${esc(m.role)}</div><pre>${esc(m.content)}</pre></div>`).join("")
    : `<div class="msg system"><div class="role">входные данные</div><pre>${esc(JSON.stringify(c.request, null, 2))}</pre></div>`;
  modal(`
    <div class="card-head"><h2>Диалог #${c.id}</h2><div class="row"><span class="badge ${esc(c.provider)}">${esc(c.provider)}</span><span class="chip">${esc(c.model)}</span></div></div>
    <div class="muted small" style="margin-bottom:14px">${fmtDate(c.created_at)} · ${fmtMs(c.latency_ms)} · инцидент #${c.incident_id ?? "—"}</div>
    ${body}
    <div class="msg assistant"><div class="role">ответ</div><pre>${esc(c.response ?? "—")}</pre></div>
    ${c.error ? `<div class="notice" style="margin-bottom:12px">Ошибка: ${esc(c.error)}</div>` : ""}
    ${c.parsed ? `<div class="msg"><div class="role">разобранное решение</div><pre>${esc(JSON.stringify(c.parsed, null, 2))}</pre></div>` : ""}
    <div class="modal-foot"><button class="btn" data-close>Закрыть</button></div>`, { wide: true });
}
