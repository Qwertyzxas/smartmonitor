const TOKEN_KEY = "sm_token";
const USER_KEY = "sm_user";

function read(key) {
  try { return localStorage.getItem(key); } catch { return null; }
}
function write(key, value) {
  try { value === null ? localStorage.removeItem(key) : localStorage.setItem(key, value); } catch { }
}

export const auth = {
  get token() { return read(TOKEN_KEY); },
  get user() {
    try { return JSON.parse(read(USER_KEY) || "null"); } catch { return null; }
  },
  get isAdmin() { return this.user?.role === "admin"; },
  save(token, user) { write(TOKEN_KEY, token); write(USER_KEY, JSON.stringify(user)); },
  clear() { write(TOKEN_KEY, null); write(USER_KEY, null); },
};

export class ApiError extends Error {
  constructor(status, message) { super(message); this.status = status; }
}

export async function api(path, { method = "GET", body, text = false } = {}) {
  const headers = { Accept: "application/json" };
  if (body !== undefined) headers["Content-Type"] = "application/json";
  if (auth.token) headers.Authorization = `Bearer ${auth.token}`;

  let res;
  try {
    res = await fetch(`/api${path}`, { method, headers, body: body !== undefined ? JSON.stringify(body) : undefined });
  } catch {
    throw new ApiError(0, "Сервер недоступен");
  }
  if (res.status === 401 && !path.startsWith("/auth/")) {
    auth.clear();
    location.hash = "#/login";
    throw new ApiError(401, "Сессия истекла, войдите снова");
  }
  if (res.status === 204) return null;
  const payload = text ? await res.text() : await res.json().catch(() => null);
  if (!res.ok) {
    let msg = payload?.detail ?? `Ошибка ${res.status}`;
    if (Array.isArray(msg)) msg = msg.map((e) => `${e.loc?.slice(-1)[0] ?? ""}: ${e.msg}`).join("; ");
    throw new ApiError(res.status, msg);
  }
  return payload;
}
