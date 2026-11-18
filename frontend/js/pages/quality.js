import { api, auth } from "../api.js";
import { emptyState, esc, fmtAgo, fmtDate, icon, modal, pager, runBadge as badge, toast, withLoading } from "../ui.js";

export async function render(ctx) {
  const { main } = ctx;
  let page = 1;
  let chart = null;
  ctx.onCleanup(() => chart?.destroy());

  main.innerHTML = `
    <div class="page-head">
      <div><h1>Дашборд качества</h1><div class="sub">Автотесты самой системы (pytest): API, ИИ-агент на мок-данных, целостность БД. Запуск раз в час.</div></div>
      ${auth.isAdmin ? `<button class="btn primary" id="run">${icon("play")}Запустить сейчас</button>` : ""}
    </div>
    <div class="kpis" id="kpis"></div>
    <div class="card" style="margin-bottom:16px">
      <div class="card-head"><h2>Последние прогоны</h2><span class="muted small">пройдено / упало</span></div>
      <div class="chart-box sm"><canvas id="chart"></canvas></div>
    </div>
    <div class="card">
      <div class="card-head"><h2>История прогонов</h2></div>
      <div class="table-wrap"><table><thead><tr><th>#</th><th>Запуск</th><th>Триггер</th><th>Статус</th><th>Тесты</th><th>Длительность</th></tr></thead>
      <tbody id="rows"></tbody></table></div>
      <div class="pager" id="pager"></div>
    </div>`;

  const load = async () => {
    const [res, recent] = await Promise.all([api(`/qa/runs?page=${page}&size=15`), api("/qa/runs?page=1&size=30")]);
    const runs = recent.items.filter((r) => r.status !== "running");
    const passRate = runs.length ? Math.round((runs.filter((r) => r.status === "passed").length / runs.length) * 100) : null;
    const avgDur = runs.length ? runs.reduce((a, r) => a + (r.duration_s || 0), 0) / runs.length : null;
    const last = recent.items[0];
    main.querySelector("#kpis").innerHTML = `
      <div class="card kpi"><div class="label">Последний прогон</div><div class="value">${last ? badge(last.status) : '<span class="muted" style="font-size:16px">нет</span>'}</div><div class="hint">${last ? fmtAgo(last.started_at) : "дождитесь планировщика"}</div></div>
      <div class="card kpi"><div class="label">Успешных прогонов</div><div class="value">${passRate ?? "—"}<small>${passRate == null ? "" : "%"}</small></div><div class="hint">за последние ${runs.length}</div></div>
      <div class="card kpi"><div class="label">Тестов в наборе</div><div class="value">${last?.total ?? "—"}</div><div class="hint">${last ? `${last.passed} ✓ · ${last.failed + last.errors} ✗ · ${last.skipped} пропущено` : ""}</div></div>
      <div class="card kpi"><div class="label">Средняя длительность</div><div class="value">${avgDur == null ? "—" : avgDur.toFixed(1)}<small>с</small></div></div>`;

    const series = runs.slice().reverse();
    if (window.Chart) {
      const data = {
        labels: series.map((r) => `#${r.id}`),
        datasets: [
          { label: "Пройдено", data: series.map((r) => r.passed), backgroundColor: "#22c55e", borderRadius: 3, stack: "s", maxBarThickness: 34 },
          { label: "Упало", data: series.map((r) => r.failed + r.errors), backgroundColor: "#f2545b", borderRadius: 3, stack: "s", maxBarThickness: 34 },
          { label: "Пропущено", data: series.map((r) => r.skipped), backgroundColor: "#3a4766", borderRadius: 3, stack: "s", maxBarThickness: 34 },
        ],
      };
      if (chart) { chart.data = data; chart.update("none"); } else {
        chart = new window.Chart(main.querySelector("#chart"), {
          type: "bar", data,
          options: {
            responsive: true, maintainAspectRatio: false, animation: false,
            scales: { x: { grid: { display: false } }, y: { beginAtZero: true, ticks: { precision: 0 } } },
            plugins: { legend: { position: "bottom", labels: { boxWidth: 10, boxHeight: 10 } } },
            onClick: (_, els) => { if (els[0]) showRun(series[els[0].index].id); },
          },
        });
      }
    }

    main.querySelector("#rows").innerHTML = res.items.length ? res.items.map((r) => `
      <tr class="clickable" data-run="${r.id}">
        <td class="mono">${r.id}</td><td class="nowrap small">${fmtDate(r.started_at)}</td>
        <td><span class="badge">${({ manual: "вручную", startup: "при старте" })[r.trigger] ?? "по расписанию"}</span></td>
        <td>${badge(r.status)}</td>
        <td class="small"><span style="color:var(--up)">${r.passed} ✓</span> · <span style="color:var(--down)">${r.failed + r.errors} ✗</span> · <span class="muted">${r.skipped} ⏭</span> <span class="faint">из ${r.total}</span></td>
        <td class="mono small">${r.duration_s != null ? `${r.duration_s.toFixed(1)} с` : "…"}</td>
      </tr>`).join("") : `<tr><td colspan="6">${emptyState("Прогонов ещё не было")}</td></tr>`;
    main.querySelectorAll("[data-run]").forEach((row) => (row.onclick = () => showRun(row.dataset.run)));
    pager(main.querySelector("#pager"), res, (p) => { page = p; load(); });
  };

  main.querySelector("#run")?.addEventListener("click", (e) => withLoading(e.currentTarget, async () => {
    try {
      await api("/qa/runs", { method: "POST" });
      toast("Прогон запущен — результаты появятся через ~10–30 с", "success");
      setTimeout(() => load().catch(() => {}), 2500);
    } catch (err) { toast(err.message, "error"); }
  }));

  await load();
  ctx.every(() => load().catch(() => {}), 10000);
}

async function showRun(id) {
  const r = await api(`/qa/runs/${id}`);
  const groups = {};
  for (const c of r.cases) (groups[c.module || "tests"] ||= []).push(c);
  const icons = { passed: "✓", failed: "✗", error: "✗", skipped: "⏭" };
  const colors = { passed: "var(--up)", failed: "var(--down)", error: "var(--down)", skipped: "var(--muted)" };
  modal(`
    <div class="card-head"><h2>Прогон #${r.id}</h2>${badge(r.status)}</div>
    <div class="muted small" style="margin-bottom:16px">${fmtDate(r.started_at)} · ${r.duration_s?.toFixed(1) ?? "…"} с · ${r.passed}/${r.total} пройдено</div>
    ${Object.entries(groups).map(([mod, cases]) => `
      <h3 style="margin:14px 0 8px" class="mono">${esc(mod)}</h3>
      ${cases.map((c) => `<div style="padding:6px 0;border-bottom:1px solid var(--border)">
        <div class="row"><span style="color:${colors[c.outcome]};font-weight:700;width:16px">${icons[c.outcome] ?? "?"}</span>
          <span class="mono small grow">${esc(c.name)}</span><span class="faint small">${(c.time ?? 0).toFixed(2)} с</span></div>
        ${c.message && c.outcome !== "passed" ? `<div class="small" style="color:${colors[c.outcome]};margin:4px 0 0 26px">${esc(c.message)}</div>` : ""}
        ${c.details && (c.outcome === "failed" || c.outcome === "error") ? `<details style="margin:6px 0 0 26px"><summary class="faint small" style="cursor:pointer">трейсбек</summary><pre style="margin-top:6px">${esc(c.details)}</pre></details>` : ""}
      </div>`).join("")}`).join("") || emptyState("Нет данных о тестах")}
    ${r.output ? `<details style="margin-top:16px"><summary class="muted small" style="cursor:pointer">Вывод pytest</summary><pre style="margin-top:8px">${esc(r.output)}</pre></details>` : ""}
    <div class="modal-foot"><button class="btn" data-close>Закрыть</button></div>`, { wide: true });
}
