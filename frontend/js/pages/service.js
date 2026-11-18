import { api, auth } from "../api.js";
import {
  badge, emptyState, esc, fmtAgo, fmtDate, fmtDuration, fmtMs, fmtPct, icon, modal,
  pager, PROBLEM_LABEL, STATUS_COLOR, toast, withLoading,
} from "../ui.js";
import { openServiceForm } from "./admin.js";

export async function render(ctx) {
  const { main, params } = ctx;
  const id = params.id;
  let hours = 24;
  let checksPage = 1;
  let incidentsPage = 1;
  let chart = null;
  ctx.onCleanup(() => chart?.destroy());

  main.innerHTML = `
    <div class="crumbs"><a href="#/">Дашборд</a> / сервис</div>
    <div class="page-head" id="head"></div>
    <div class="kpis" id="kpis"></div>
    <div class="card" style="margin-bottom:16px">
      <div class="card-head">
        <h2>Время ответа</h2>
        <div class="segmented" id="range">
          ${[1, 6, 24, 168].map((h) => `<button data-h="${h}" class="${h === hours ? "active" : ""}">${h === 168 ? "7 дн" : `${h} ч`}</button>`).join("")}
        </div>
      </div>
      <div class="chart-box"><canvas id="chart"></canvas></div>
      <div style="margin-top:16px">
        <div class="row muted small" style="justify-content:space-between;margin-bottom:6px"><span>Последние 60 проверок</span><span id="strip-legend"></span></div>
        <div class="strip" id="strip"></div>
      </div>
    </div>
    <div class="card">
      <div class="tabs"><button class="active" data-tab="checks">История проверок</button><button data-tab="incidents">Инциденты и действия ИИ</button></div>
      <div id="tab-checks"><div class="table-wrap"><table>
        <thead><tr><th>Время</th><th>Статус</th><th>HTTP</th><th>Длительность</th><th>Детали</th></tr></thead>
        <tbody id="checks"></tbody></table></div><div class="pager" id="checks-pager"></div></div>
      <div id="tab-incidents" class="hidden"><div id="incidents"></div><div class="pager" id="inc-pager"></div></div>
    </div>`;

  const loadHead = async () => {
    const s = await api(`/services/${id}`);
    main.querySelector("#head").innerHTML = `
      <div style="min-width:0">
        <div class="row"><span class="dot ${esc(s.current_status ?? "")}" style="margin-top:0"></span><h1>${esc(s.name)}</h1>
          ${s.is_active ? badge(s.current_status) : badge("", "Пауза")}
          ${s.open_incident_id ? `<a class="badge open" href="#/incidents/${s.open_incident_id}">Инцидент #${s.open_incident_id}</a>` : ""}</div>
        <div class="sub"><a href="${esc(s.url)}" target="_blank" rel="noopener" class="mono">${esc(s.url)} ${icon("ext").replace("<svg", '<svg width="12" height="12"')}</a></div>
      </div>
      ${auth.isAdmin ? `<div class="row">
        <button class="btn" id="edit">${icon("edit")}Настроить</button>
        <button class="btn primary" id="check">${icon("play")}Проверить сейчас</button></div>` : ""}`;
    main.querySelector("#kpis").innerHTML = `
      <div class="card kpi"><div class="label">Uptime 24 ч</div><div class="value">${fmtPct(s.uptime_24h)}</div><div class="hint">${s.checks_24h} проверок</div></div>
      <div class="card kpi"><div class="label">Средний ответ</div><div class="value">${fmtMs(s.avg_ms_24h)}</div><div class="hint">порог «медленно» ${fmtMs(s.slow_threshold_ms)}</div></div>
      <div class="card kpi"><div class="label">Последняя проверка</div><div class="value" style="font-size:20px">${fmtAgo(s.last_checked_at)}</div><div class="hint">интервал ${s.interval_seconds} с · таймаут ${s.timeout_seconds} с</div></div>
      <div class="card kpi"><div class="label">Авто-действия ИИ</div><div class="value" style="font-size:20px">${s.auto_actions_enabled ? '<span style="color:var(--up)">Разрешены</span>' : '<span class="muted">Выключены</span>'}</div><div class="hint">restart / scale_up без подтверждения</div></div>`;
    main.querySelector("#edit")?.addEventListener("click", () => openServiceForm(s, refreshAll));
    main.querySelector("#check")?.addEventListener("click", (e) => withLoading(e.currentTarget, async () => {
      try {
        const res = await api(`/services/${id}/check`, { method: "POST" });
        toast(`Проверка: ${res.check.status} · ${res.check.status_code ?? res.check.error_kind ?? ""} · ${fmtMs(res.check.duration_ms)}`,
          res.check.status === "up" ? "success" : "error");
        if (res.incident_opened) toast(`Открыт инцидент #${res.incident_opened}`, "error");
        if (res.incident_resolved) toast(`Инцидент #${res.incident_resolved} закрыт`, "success");
        await refreshAll();
      } catch (err) { toast(err.message, "error"); }
    }));
  };

  const loadChart = async () => {
    const points = await api(`/services/${id}/timeseries?hours=${hours}`);
    const strip = points.slice(-60);
    main.querySelector("#strip").innerHTML = strip.length
      ? Array.from({ length: 60 - strip.length }, () => "<i></i>").join("") +
        strip.map((p) => `<i class="${p.status}" title="${fmtDate(p.t)} · ${p.status} · ${fmtMs(p.ms)}"></i>`).join("")
      : '<span class="muted small">нет данных</span>';
    const fails = strip.filter((p) => p.status !== "up").length;
    main.querySelector("#strip-legend").textContent = strip.length ? `${strip.length - fails} OK · ${fails} сбоев` : "";

    const data = points.map((p) => ({ x: new Date(p.t), y: p.ms, status: p.status, code: p.code }));
    if (!window.Chart) return;
    if (chart) {
      chart.data.datasets[0].data = data;
      chart.options.scales.x.min = Date.now() - hours * 3600 * 1000;
      chart.options.scales.x.max = Date.now();
      chart.update("none");
      return;
    }
    chart = new window.Chart(main.querySelector("#chart"), {
      type: "line",
      data: {
        datasets: [{
          label: "Время ответа, мс", data, borderColor: "#7c83ff", borderWidth: 2, tension: 0.3, fill: true,
          backgroundColor: (c) => {
            const { ctx: g, chartArea } = c.chart;
            if (!chartArea) return "rgba(124,131,255,.1)";
            const grad = g.createLinearGradient(0, chartArea.top, 0, chartArea.bottom);
            grad.addColorStop(0, "rgba(124,131,255,.28)");
            grad.addColorStop(1, "rgba(124,131,255,0)");
            return grad;
          },
          pointRadius: (c) => (c.raw?.status && c.raw.status !== "up" ? 4 : data.length > 120 ? 0 : 2),
          pointBackgroundColor: (c) => STATUS_COLOR[c.raw?.status] ?? "#7c83ff",
          pointBorderWidth: 0, spanGaps: true,
        }],
      },
      options: {
        responsive: true, maintainAspectRatio: false, animation: false,
        interaction: { mode: "nearest", intersect: false },
        layout: { padding: { left: 6 } },
        scales: {
          x: {
            type: "time", grid: { display: false },
            min: Date.now() - hours * 3600 * 1000, max: Date.now(),
            time: { tooltipFormat: "dd.MM HH:mm:ss", displayFormats: { millisecond: "HH:mm:ss", second: "HH:mm:ss", minute: "HH:mm", hour: "HH:mm", day: "dd.MM" } },
            ticks: { maxTicksLimit: 8, maxRotation: 0, autoSkip: true },
          },
          y: { beginAtZero: true, title: { display: true, text: "мс" }, ticks: { maxTicksLimit: 6 } },
        },
        plugins: {
          legend: { display: false },
          tooltip: { callbacks: { label: (c) => ` ${fmtMs(c.raw.y)} · ${c.raw.status}${c.raw.code ? ` · HTTP ${c.raw.code}` : ""}` } },
        },
      },
    });
  };

  const loadChecks = async () => {
    const res = await api(`/services/${id}/checks?page=${checksPage}&size=15`);
    const tbody = main.querySelector("#checks");
    tbody.innerHTML = res.items.length ? res.items.map((c) => `
      <tr class="clickable" data-check='${c.id}'>
        <td class="nowrap">${fmtDate(c.checked_at)} ${c.manual ? '<span class="badge">вручную</span>' : ""}</td>
        <td>${badge(c.status)}</td>
        <td class="mono">${c.status_code ?? "—"}</td>
        <td class="mono">${fmtMs(c.duration_ms)}</td>
        <td class="muted small ellipsis" style="max-width:360px">${esc(c.error ?? "")}</td>
      </tr>`).join("") : `<tr><td colspan="5">${emptyState("Проверок пока нет")}</td></tr>`;
    tbody.onclick = (e) => {
      const row = e.target.closest("[data-check]");
      const c = row && res.items.find((x) => String(x.id) === row.dataset.check);
      if (c) modal(`<h2>Проверка #${c.id}</h2><dl class="kv" style="margin:16px 0">
          <dt>Время</dt><dd>${fmtDate(c.checked_at)}</dd><dt>Статус</dt><dd>${badge(c.status)}</dd>
          <dt>HTTP</dt><dd>${c.status_code ?? "—"}</dd><dt>Длительность</dt><dd>${fmtMs(c.duration_ms)}</dd>
          <dt>Ошибка</dt><dd>${esc(c.error ?? "—")}</dd></dl>
          <h3 style="margin-bottom:8px">Тело ответа (первые 2 КБ)</h3><pre>${esc(c.response_body ?? "—")}</pre>
          <div class="modal-foot"><button class="btn" data-close>Закрыть</button></div>`, { wide: true });
    };
    pager(main.querySelector("#checks-pager"), res, (p) => { checksPage = p; loadChecks(); });
  };

  const loadIncidents = async () => {
    const res = await api(`/services/${id}/incidents?page=${incidentsPage}&size=10`);
    const el = main.querySelector("#incidents");
    if (!res.items.length) { el.innerHTML = emptyState("Инцидентов не было"); pager(main.querySelector("#inc-pager"), res, () => {}); return; }
    const details = await Promise.all(res.items.map((i) => api(`/incidents/${i.id}`)));
    el.innerHTML = details.map((i) => {
      const a = i.actions[i.actions.length - 1];
      return `<a class="action-card" href="#/incidents/${i.id}" style="display:block;color:inherit;text-decoration:none">
        <div class="row" style="justify-content:space-between">
          <div class="row"><b>Инцидент #${i.id}</b>${badge(i.status)}${i.problem_type ? `<span class="badge accent">${PROBLEM_LABEL[i.problem_type] ?? i.problem_type}</span>` : ""}</div>
          <span class="muted small">${fmtDate(i.started_at)} · ${fmtDuration(i.started_at, i.resolved_at)}</span>
        </div>
        <div class="muted small" style="margin-top:6px">${esc(i.reason)}</div>
        ${a ? `<div class="rec">${icon("sparkles").replace("<svg", '<svg width="14" height="14" style="vertical-align:-2px;color:var(--accent)"')} ${esc(a.recommendation)}</div>
          <div class="row small"><span class="chip">${esc(a.command)}</span> ${badge(a.status)} <span class="badge ${esc(a.source)}">${a.source === "openrouter" ? "OpenRouter" : a.source === "fallback" ? "sklearn fallback" : esc(a.source)}</span></div>`
          : '<div class="muted small" style="margin-top:8px">ИИ-агент ещё анализирует…</div>'}
      </a>`;
    }).join("");
    pager(main.querySelector("#inc-pager"), res, (p) => { incidentsPage = p; loadIncidents(); });
  };

  const refreshAll = () => Promise.all([loadHead(), loadChart(), loadChecks(), loadIncidents()]);

  main.querySelector("#range").onclick = (e) => {
    const b = e.target.closest("[data-h]");
    if (!b) return;
    hours = Number(b.dataset.h);
    main.querySelectorAll("#range button").forEach((x) => x.classList.toggle("active", x === b));
    loadChart();
  };
  main.querySelector(".tabs").onclick = (e) => {
    const b = e.target.closest("[data-tab]");
    if (!b) return;
    main.querySelectorAll(".tabs button").forEach((x) => x.classList.toggle("active", x === b));
    main.querySelector("#tab-checks").classList.toggle("hidden", b.dataset.tab !== "checks");
    main.querySelector("#tab-incidents").classList.toggle("hidden", b.dataset.tab !== "incidents");
  };

  await refreshAll();
  ctx.every(() => Promise.all([loadHead(), loadChart(), checksPage === 1 ? loadChecks() : null]).catch(() => {}), 20000);
}
