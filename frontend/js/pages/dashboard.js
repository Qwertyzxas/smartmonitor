import { api, auth } from "../api.js";
import { badge, emptyState, esc, fmtAgo, fmtMs, fmtPct, icon, runBadge, statusLabel, toast, withLoading } from "../ui.js";
import { openServiceForm } from "./admin.js";

export async function render(ctx) {
  const { main } = ctx;
  main.innerHTML = `
    <div class="page-head">
      <div><h1>Дашборд</h1><div class="sub" id="updated">Загрузка…</div></div>
      <div class="row">
        <button class="btn" id="reload">${icon("refresh")}Обновить</button>
        ${auth.isAdmin ? `<button class="btn primary" id="add">${icon("plus")}Добавить сервис</button>` : ""}
      </div>
    </div>
    <div class="kpis" id="kpis">${'<div class="card kpi skeleton" style="height:96px"></div>'.repeat(5)}</div>
    <div class="split">
      <section>
        <div class="card-head"><h2>Сервисы</h2><span class="muted small" id="svc-count"></span></div>
        <div class="services" id="services"></div>
      </section>
      <section class="card" style="align-self:start">
        <div class="card-head"><h2>Последние инциденты</h2><a href="#/incidents" class="small">Все →</a></div>
        <div id="incidents"></div>
      </section>
    </div>`;

  const load = async () => {
    const [summary, services, incidents] = await Promise.all([
      api("/stats/summary"), api("/services"), api("/incidents?size=6"),
    ]);
    renderKpis(main.querySelector("#kpis"), summary);
    renderServices(main.querySelector("#services"), services);
    main.querySelector("#svc-count").textContent = `${services.length} шт.`;
    renderIncidents(main.querySelector("#incidents"), incidents.items);
    main.querySelector("#updated").textContent = `Обновлено ${new Date().toLocaleTimeString("ru-RU")} · автообновление каждые 15 с`;
  };

  main.querySelector("#reload").onclick = (e) => withLoading(e.currentTarget, load);
  main.querySelector("#add")?.addEventListener("click", () => openServiceForm(null, load));

  main.querySelector("#services").addEventListener("click", async (e) => {
    const checkBtn = e.target.closest("[data-check]");
    if (checkBtn) {
      e.stopPropagation();
      await withLoading(checkBtn, async () => {
        try {
          const res = await api(`/services/${checkBtn.dataset.check}/check`, { method: "POST" });
          const c = res.check;
          toast(`${statusLabel(c.status)} · ${c.status_code ?? c.error_kind ?? ""} · ${fmtMs(c.duration_ms)}`,
            c.status === "up" ? "success" : "error");
          if (res.incident_opened) toast(`Открыт инцидент #${res.incident_opened}, ИИ-агент анализирует…`, "error");
          await load();
        } catch (err) { toast(err.message, "error"); }
      });
      return;
    }
    const card = e.target.closest("[data-id]");
    if (card) location.hash = `#/services/${card.dataset.id}`;
  });

  await load();
  ctx.every(() => load().catch(() => {}), 15000);
}

function renderKpis(el, s) {
  const last = s.last_test_run;
  el.innerHTML = `
    <div class="card kpi"><div class="label">Доступность за 24 ч</div>
      <div class="value" style="color:${s.uptime_24h == null ? "inherit" : s.uptime_24h >= 99 ? "var(--up)" : s.uptime_24h >= 95 ? "var(--warn)" : "var(--down)"}">${fmtPct(s.uptime_24h)}</div>
      <div class="hint">${s.checks_24h} проверок</div></div>
    <div class="card kpi"><div class="label">Среднее время ответа</div>
      <div class="value">${s.avg_ms_24h == null ? "—" : Math.round(s.avg_ms_24h)}<small>мс</small></div>
      <div class="hint">успешные проверки за 24 ч</div></div>
    <div class="card kpi"><div class="label">Статусы сервисов</div>
      <div class="value"><span style="color:var(--up)">${s.up}</span> <small>/</small> <span style="color:var(--warn)">${s.degraded}</span> <small>/</small> <span style="color:var(--down)">${s.down}</span></div>
      <div class="hint">работают / медленно / недоступны</div></div>
    <div class="card kpi"><div class="label">Открытые инциденты</div>
      <div class="value" style="color:${s.open_incidents ? "var(--down)" : "inherit"}">${s.open_incidents}</div>
      <div class="hint">${s.incidents_24h} за сутки · ${s.actions_24h} действий ИИ</div></div>
    <div class="card kpi" style="cursor:pointer" onclick="location.hash='#/quality'"><div class="label">Автотесты системы</div>
      <div class="value">${last ? runBadge(last.status) : '<span class="muted" style="font-size:16px">нет прогонов</span>'}</div>
      <div class="hint">${last ? `${last.passed}/${last.total} · ${fmtAgo(last.started_at)}` : "запускаются раз в час"}</div></div>`;
}

function renderServices(el, services) {
  if (!services.length) {
    el.innerHTML = `<div class="card" style="grid-column:1/-1">${emptyState(auth.isAdmin ? "Добавьте первый сервис кнопкой выше" : "Сервисы ещё не добавлены")}</div>`;
    return;
  }
  el.innerHTML = services.map((s) => {
    const st = s.is_active ? s.current_status : null;
    return `
    <article class="card svc s-${esc(st ?? "none")}" data-id="${s.id}">
      <div class="svc-top">
        <span class="dot ${esc(st ?? "")}"></span>
        <div class="grow" style="min-width:0">
          <div class="svc-name ellipsis">${esc(s.name)}</div>
          <div class="svc-url ellipsis" title="${esc(s.url)}">${esc(s.url.replace(/^https?:\/\//, ""))}</div>
        </div>
        ${s.is_active ? badge(st) : badge("", "Пауза")}
      </div>
      <div class="svc-stats">
        <div><b>${fmtPct(s.uptime_24h)}</b><span>uptime 24ч</span></div>
        <div><b>${fmtMs(s.last_duration_ms)}</b><span>последний</span></div>
        <div><b>${fmtMs(s.avg_ms_24h)}</b><span>средний</span></div>
      </div>
      <div class="uptime-bar"><i style="width:${s.uptime_24h ?? 0}%"></i></div>
      <div class="svc-foot">
        <span>${s.open_incident_id ? `<span class="badge open">Инцидент #${s.open_incident_id}</span>` : `проверка ${fmtAgo(s.last_checked_at)}`}</span>
        ${auth.isAdmin ? `<button class="btn sm" data-check="${s.id}">${icon("play")}Проверить</button>` : `<span class="faint">каждые ${s.interval_seconds} с</span>`}
      </div>
    </article>`;
  }).join("");
}

function renderIncidents(el, items) {
  if (!items.length) { el.innerHTML = emptyState("Инцидентов нет — всё работает"); return; }
  el.innerHTML = items.map((i) => `
    <a href="#/incidents/${i.id}" class="row" style="padding:10px 0;border-bottom:1px solid var(--border);color:inherit;text-decoration:none">
      <span class="dot ${i.status === "open" ? "down" : "up"}" style="margin-top:0"></span>
      <div class="grow" style="min-width:0">
        <div style="font-weight:600" class="ellipsis">#${i.id} · ${esc(i.service_name)}</div>
        <div class="muted small ellipsis">${esc(i.ai_summary || i.reason)}</div>
      </div>
      <span class="faint small nowrap">${fmtAgo(i.started_at)}</span>
    </a>`).join("");
}
