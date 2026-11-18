import { api } from "../api.js";
import { badge, emptyState, esc, fmtDate, fmtDuration, pager, PROBLEM_LABEL, SEVERITY_CLASS, SEVERITY_LABEL } from "../ui.js";

export async function render(ctx) {
  const { main } = ctx;
  let status = "";
  let page = 1;
  main.innerHTML = `
    <div class="page-head">
      <div><h1>Инциденты</h1><div class="sub">Инцидент открывается после 2 подряд неудачных проверок и закрывается при восстановлении</div></div>
      <div class="segmented" id="filter">
        <button data-s="" class="active">Все</button><button data-s="open">Открытые</button><button data-s="resolved">Закрытые</button>
      </div>
    </div>
    <div class="card">
      <div class="table-wrap"><table>
        <thead><tr><th>#</th><th>Сервис</th><th>Статус</th><th>Тип / важность</th><th>Причина / вывод ИИ</th><th>Начало</th><th>Длительность</th></tr></thead>
        <tbody id="rows"></tbody>
      </table></div>
      <div class="pager" id="pager"></div>
    </div>`;

  const load = async () => {
    const res = await api(`/incidents?page=${page}&size=20${status ? `&status=${status}` : ""}`);
    const tbody = main.querySelector("#rows");
    tbody.innerHTML = res.items.length ? res.items.map((i) => `
      <tr class="clickable" onclick="location.hash='#/incidents/${i.id}'">
        <td class="mono">${i.id}</td>
        <td><b>${esc(i.service_name)}</b></td>
        <td>${badge(i.status)}</td>
        <td class="nowrap">${i.problem_type ? `<span class="badge accent">${PROBLEM_LABEL[i.problem_type] ?? esc(i.problem_type)}</span>` : '<span class="faint">анализ…</span>'}
            ${i.severity ? `<span class="badge ${SEVERITY_CLASS[i.severity] ?? ""}">${SEVERITY_LABEL[i.severity] ?? esc(i.severity)}</span>` : ""}</td>
        <td class="muted small" style="max-width:420px">${esc(i.ai_summary || i.reason)}</td>
        <td class="nowrap small">${fmtDate(i.started_at)}</td>
        <td class="nowrap small">${fmtDuration(i.started_at, i.resolved_at)}</td>
      </tr>`).join("") : `<tr><td colspan="7">${emptyState("Инцидентов нет")}</td></tr>`;
    pager(main.querySelector("#pager"), res, (p) => { page = p; load(); });
  };

  main.querySelector("#filter").onclick = (e) => {
    const b = e.target.closest("[data-s]");
    if (!b) return;
    status = b.dataset.s;
    page = 1;
    main.querySelectorAll("#filter button").forEach((x) => x.classList.toggle("active", x === b));
    load();
  };
  await load();
  ctx.every(() => load().catch(() => {}), 20000);
}
