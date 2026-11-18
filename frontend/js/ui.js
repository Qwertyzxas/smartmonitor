export const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => (
  { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

export const $ = (sel, root = document) => root.querySelector(sel);
export const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];

const dtf = new Intl.DateTimeFormat("ru-RU", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit", second: "2-digit" });
export const fmtDate = (v) => (v ? dtf.format(new Date(v)) : "—");

export function fmtAgo(v) {
  if (!v) return "никогда";
  const s = Math.max(0, Math.round((Date.now() - new Date(v).getTime()) / 1000));
  if (s < 60) return `${s} с назад`;
  if (s < 3600) return `${Math.floor(s / 60)} мин назад`;
  if (s < 86400) return `${Math.floor(s / 3600)} ч назад`;
  return `${Math.floor(s / 86400)} дн назад`;
}

export function fmtDuration(fromIso, toIso) {
  const s = Math.round(((toIso ? new Date(toIso) : new Date()) - new Date(fromIso)) / 1000);
  if (s < 60) return `${s} с`;
  if (s < 3600) return `${Math.floor(s / 60)} мин ${s % 60} с`;
  const h = Math.floor(s / 3600);
  return h < 48 ? `${h} ч ${Math.floor((s % 3600) / 60)} мин` : `${Math.floor(h / 24)} дн`;
}

export const fmtMs = (v) => (v == null ? "—" : v >= 1000 ? `${(v / 1000).toFixed(2)} с` : `${Math.round(v)} мс`);
export const fmtPct = (v) => (v == null ? "—" : `${Number(v).toFixed(v >= 99.95 || v === 0 ? 0 : 2)}%`);

const STATUS_LABEL = {
  up: "Работает", degraded: "Медленно", down: "Недоступен", null: "Нет данных",
  open: "Открыт", resolved: "Закрыт",
  suggested: "Ждёт решения", executed: "Выполнено", skipped: "Отклонено", failed: "Ошибка", info: "Рекомендация",
  passed: "Пройдено", running: "Выполняется", error: "Сбой",
};
export const statusLabel = (s) => STATUS_LABEL[s] ?? s ?? "—";
export const badge = (s, label) => `<span class="badge ${esc(s ?? "")}">${esc(label ?? statusLabel(s))}</span>`;
const RUN_LABEL = { passed: "Все пройдены", failed: "Есть падения", error: "Сбой запуска", running: "Выполняется" };
export const runBadge = (s) => badge(s, RUN_LABEL[s] ?? s);

export const PROBLEM_LABEL = { network: "Сеть", server: "Сервер", database: "База данных", performance: "Производительность", unknown: "Не определено" };
export const COMMAND_LABEL = { restart: "Перезапуск", scale_up: "Масштабирование", notify_admin: "Уведомить админа", none: "Без команды" };
export const SEVERITY_CLASS = { low: "info", medium: "degraded", high: "down", critical: "down" };
export const SEVERITY_LABEL = { low: "низкая важность", medium: "средняя важность", high: "высокая важность", critical: "критично" };

export function toast(message, type = "info") {
  const el = document.createElement("div");
  el.className = `toast ${type}`;
  el.textContent = message;
  document.getElementById("toasts").appendChild(el);
  setTimeout(() => el.remove(), 4200);
}

export function modal(html, { wide = false } = {}) {
  const root = document.getElementById("modal-root");
  root.innerHTML = `<div class="modal-backdrop"><div class="card modal ${wide ? "wide" : ""}">${html}</div></div>`;
  const backdrop = root.firstElementChild;
  const close = () => { root.innerHTML = ""; document.removeEventListener("keydown", onKey); };
  const onKey = (e) => e.key === "Escape" && close();
  document.addEventListener("keydown", onKey);
  backdrop.addEventListener("click", (e) => {
    if (e.target === backdrop || e.target.closest("[data-close]")) close();
  });
  return { el: backdrop.firstElementChild, close };
}

export function confirmDialog(text, okLabel = "Подтвердить") {
  return new Promise((resolve) => {
    const m = modal(`<h2>Подтверждение</h2><p class="muted">${esc(text)}</p>
      <div class="modal-foot"><button class="btn" data-close>Отмена</button><button class="btn primary" data-ok>${esc(okLabel)}</button></div>`);
    m.el.querySelector("[data-ok]").onclick = () => { m.close(); resolve(true); };
    m.el.querySelectorAll("[data-close]").forEach((b) => b.addEventListener("click", () => resolve(false)));
  });
}

export function pager(container, { total, page, size }, onPage) {
  const pages = Math.max(1, Math.ceil(total / size));
  container.innerHTML = total <= size ? `<span>Всего: ${total}</span>` : `
    <span>Всего: ${total} · стр. ${page} из ${pages}</span>
    <span class="row">
      <button class="btn sm" data-p="${page - 1}" ${page <= 1 ? "disabled" : ""}>← Назад</button>
      <button class="btn sm" data-p="${page + 1}" ${page >= pages ? "disabled" : ""}>Вперёд →</button>
    </span>`;
  container.querySelectorAll("[data-p]").forEach((b) => (b.onclick = () => onPage(Number(b.dataset.p))));
}

export async function withLoading(btn, fn) {
  btn.classList.add("loading");
  btn.disabled = true;
  try { return await fn(); } finally { btn.classList.remove("loading"); btn.disabled = false; }
}

export const emptyState = (text) => `<div class="empty">${icon("inbox")}${esc(text)}</div>`;

const ICONS = {
  dashboard: '<rect x="3" y="3" width="7" height="9" rx="1.5"/><rect x="14" y="3" width="7" height="5" rx="1.5"/><rect x="14" y="12" width="7" height="9" rx="1.5"/><rect x="3" y="16" width="7" height="5" rx="1.5"/>',
  alert: '<path d="M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0Z"/><path d="M12 9v4M12 17h.01"/>',
  settings: '<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1Z"/>',
  flask: '<path d="M9 3h6M10 3v6L4.5 18.5A2 2 0 0 0 6.2 21.5h11.6a2 2 0 0 0 1.7-3L14 9V3"/><path d="M7 15h10"/>',
  logout: '<path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4M16 17l5-5-5-5M21 12H9"/>',
  refresh: '<path d="M21 12a9 9 0 1 1-2.6-6.4L21 8"/><path d="M21 3v5h-5"/>',
  plus: '<path d="M12 5v14M5 12h14"/>',
  play: '<path d="m6 4 14 8-14 8Z"/>',
  sparkles: '<path d="M12 3l1.9 5.1L19 10l-5.1 1.9L12 17l-1.9-5.1L5 10l5.1-1.9Z"/><path d="M19 15l.8 2.2L22 18l-2.2.8L19 21l-.8-2.2L16 18l2.2-.8Z"/>',
  inbox: '<path d="M22 12h-6l-2 3h-4l-2-3H2"/><path d="M5.5 5.1 2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.5-6.9A2 2 0 0 0 16.8 4H7.2a2 2 0 0 0-1.7 1.1Z"/>',
  edit: '<path d="M12 20h9"/><path d="M16.5 3.5a2.1 2.1 0 1 1 3 3L7 19l-4 1 1-4Z"/>',
  trash: '<path d="M3 6h18M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/>',
  ext: '<path d="M15 3h6v6M10 14 21 3M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/>',
  send: '<path d="M22 2 11 13M22 2l-7 20-4-9-9-4Z"/>',
  check: '<path d="M20 6 9 17l-5-5"/>',
  x: '<path d="M18 6 6 18M6 6l12 12"/>',
};
export const icon = (name) => `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${ICONS[name] ?? ""}</svg>`;

export function chartDefaults() {
  if (!window.Chart) return;
  const C = window.Chart;
  C.defaults.color = "#8b94ab";
  C.defaults.borderColor = "rgba(46,58,84,.45)";
  C.defaults.font.family = "Inter, system-ui, sans-serif";
  C.defaults.font.size = 12;
  C.defaults.plugins.tooltip.backgroundColor = "#192032";
  C.defaults.plugins.tooltip.borderColor = "#2e3a54";
  C.defaults.plugins.tooltip.borderWidth = 1;
  C.defaults.plugins.tooltip.padding = 10;
  C.defaults.plugins.tooltip.titleColor = "#e6e9f2";
  C.defaults.plugins.tooltip.bodyColor = "#e6e9f2";
}

export const STATUS_COLOR = { up: "#22c55e", degraded: "#f5b931", down: "#f2545b" };
