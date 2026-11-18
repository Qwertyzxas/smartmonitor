// SPA shell: hash router, layout, page lifecycle
import { api, auth } from "./api.js";
import { chartDefaults, esc, icon } from "./ui.js";
import * as loginPage from "./pages/login.js";
import * as dashboardPage from "./pages/dashboard.js";
import * as servicePage from "./pages/service.js";
import * as incidentsPage from "./pages/incidents.js";
import * as incidentPage from "./pages/incident.js";
import * as adminPage from "./pages/admin.js";
import * as qualityPage from "./pages/quality.js";

const routes = [
  { re: /^\/login$/, page: loginPage, public: true, args: () => ({ mode: "login" }) },
  { re: /^\/register$/, page: loginPage, public: true, args: () => ({ mode: "register" }) },
  { re: /^\/?$/, page: dashboardPage, nav: "dashboard" },
  { re: /^\/services\/(\d+)$/, page: servicePage, nav: "dashboard", args: (m) => ({ id: Number(m[1]) }) },
  { re: /^\/incidents$/, page: incidentsPage, nav: "incidents" },
  { re: /^\/incidents\/(\d+)$/, page: incidentPage, nav: "incidents", args: (m) => ({ id: Number(m[1]) }) },
  { re: /^\/quality$/, page: qualityPage, nav: "quality" },
  { re: /^\/admin(?:\/(\w+))?$/, page: adminPage, nav: "admin", admin: true, args: (m) => ({ tab: m[1] || "services" }) },
];

let cleanups = [];
function runCleanups() {
  cleanups.forEach((fn) => { try { fn(); } catch { /* ignore */ } });
  cleanups = [];
}

function navLink(key, href, iconName, label, active, extra = "") {
  return `<a href="${href}" class="${active === key ? "active" : ""}">${icon(iconName)}<span class="lbl">${label}</span>${extra}</a>`;
}

function renderShell(activeNav) {
  const user = auth.user;
  const app = document.getElementById("app");
  app.innerHTML = `
    <div class="shell">
      <aside class="sidebar">
        <div class="brand">
          <div class="brand-logo"><svg width="20" height="20" viewBox="0 0 32 32"><path d="M3 17h6l3.5-8 6 15 3.5-7H29" stroke="white" stroke-width="3" fill="none" stroke-linecap="round" stroke-linejoin="round"/></svg></div>
          <div>SmartMonitor<small>AI AUTO-REMEDIATION</small></div>
        </div>
        <nav class="nav">
          ${navLink("dashboard", "#/", "dashboard", "Дашборд", activeNav)}
          ${navLink("incidents", "#/incidents", "alert", "Инциденты", activeNav, '<span class="count hidden" id="open-count"></span>')}
          ${navLink("quality", "#/quality", "flask", "Качество", activeNav)}
          ${auth.isAdmin ? navLink("admin", "#/admin", "settings", "Админка", activeNav) : ""}
        </nav>
        <div class="sidebar-foot">
          <div class="who">
            <div class="avatar">${esc(user?.username?.[0] ?? "?")}</div>
            <div><div style="font-weight:600">${esc(user?.username)}</div>
            <span class="badge ${user?.role === "admin" ? "admin" : ""}">${user?.role === "admin" ? "Администратор" : "Наблюдатель"}</span></div>
          </div>
          <button class="btn sm ghost" id="logout" style="width:100%">${icon("logout")}<span class="lbl">Выйти</span></button>
        </div>
      </aside>
      <main class="main" id="main"></main>
    </div>`;
  document.getElementById("logout").onclick = () => { auth.clear(); location.hash = "#/login"; };
  refreshOpenCount();
}

export async function refreshOpenCount() {
  const el = document.getElementById("open-count");
  if (!el || !auth.token) return;
  try {
    const res = await api("/incidents?status=open&size=1");
    el.textContent = res.total;
    el.classList.toggle("hidden", !res.total);
  } catch { /* ignore */ }
}

async function route() {
  runCleanups();
  const path = location.hash.replace(/^#/, "") || "/";
  const match = routes.map((r) => ({ r, m: path.match(r.re) })).find((x) => x.m);
  if (!match) { location.hash = "#/"; return; }
  const { r, m } = match;

  if (!r.public && !auth.token) { location.hash = "#/login"; return; }
  if (r.public && auth.token) { location.hash = "#/"; return; }
  if (r.admin && !auth.isAdmin) { location.hash = "#/"; return; }

  const ctx = {
    params: r.args ? r.args(m) : {},
    onCleanup: (fn) => cleanups.push(fn),
    every: (fn, ms) => { const t = setInterval(fn, ms); cleanups.push(() => clearInterval(t)); },
  };

  if (r.public) {
    ctx.main = document.getElementById("app");
  } else {
    renderShell(r.nav);
    ctx.main = document.getElementById("main");
    ctx.every(refreshOpenCount, 20000);
  }
  try {
    await r.page.render(ctx);
  } catch (err) {
    console.error(err);
    ctx.main.innerHTML = `<div class="card empty">Не удалось загрузить страницу: ${esc(err.message)}</div>`;
  }
  window.scrollTo(0, 0);
}

chartDefaults();
window.addEventListener("hashchange", route);
route();
