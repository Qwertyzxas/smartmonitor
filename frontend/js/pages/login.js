import { api, auth } from "../api.js";
import { esc } from "../ui.js";

export async function render({ main, params }) {
  const isLogin = params.mode === "login";
  main.innerHTML = `
    <div class="auth-wrap">
      <div class="card auth-card">
        <div class="brand">
          <div class="brand-logo"><svg width="20" height="20" viewBox="0 0 32 32"><path d="M3 17h6l3.5-8 6 15 3.5-7H29" stroke="white" stroke-width="3" fill="none" stroke-linecap="round" stroke-linejoin="round"/></svg></div>
          <div>SmartMonitor<small>AI AUTO-REMEDIATION</small></div>
        </div>
        <h1 style="margin-bottom:6px">${isLogin ? "Вход" : "Регистрация"}</h1>
        <p class="muted" style="margin:0 0 20px">${isLogin ? "Мониторинг сервисов с ИИ-агентом восстановления" : "Новые пользователи получают роль «наблюдатель»"}</p>
        <form id="auth-form" autocomplete="on">
          <label class="field">Логин<input type="text" name="username" required minlength="3" autocomplete="username" autofocus></label>
          <label class="field">Пароль<input type="password" name="password" required minlength="6" autocomplete="${isLogin ? "current-password" : "new-password"}"></label>
          <div class="error" id="auth-error"></div>
          <button class="btn primary" type="submit">${isLogin ? "Войти" : "Создать аккаунт"}</button>
        </form>
        <p class="muted small" style="margin-top:16px;text-align:center">
          ${isLogin ? 'Нет аккаунта? <a href="#/register">Зарегистрироваться</a>' : 'Уже есть аккаунт? <a href="#/login">Войти</a>'}
        </p>
        ${isLogin ? '<div class="auth-demo">Администратор по умолчанию задаётся в <code>.env</code> (ADMIN_USERNAME / ADMIN_PASSWORD, по умолчанию <code>admin</code> / <code>admin123</code>).</div>' : ""}
      </div>
    </div>`;

  const form = main.querySelector("#auth-form");
  form.onsubmit = async (e) => {
    e.preventDefault();
    const btn = form.querySelector("button");
    const err = main.querySelector("#auth-error");
    err.textContent = "";
    btn.classList.add("loading");
    try {
      const data = Object.fromEntries(new FormData(form));
      const res = await api(isLogin ? "/auth/login" : "/auth/register", { method: "POST", body: data });
      auth.save(res.access_token, res.user);
      location.hash = "#/";
    } catch (ex) {
      err.innerHTML = esc(ex.message);
    } finally {
      btn.classList.remove("loading");
    }
  };
}
