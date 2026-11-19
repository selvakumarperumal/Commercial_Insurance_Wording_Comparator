// Small wrapper around the FastAPI backend. In development Vite proxies /api to it, in Docker nginx does.

const BASE = "/api";
const TOKEN_KEY = "ciwc_token";

export const LOGOUT_EVENT = "ciwc:logout";

export function getToken() {
  try {
    return localStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}

export function saveToken(token) {
  try {
    localStorage.setItem(TOKEN_KEY, token);
  } catch {
    // Private mode or blocked storage: the user stays logged in until the page reloads.
  }
}

export function clearToken() {
  try {
    localStorage.removeItem(TOKEN_KEY);
  } catch {
    // Nothing stored.
  }
}

function errorMessage(body, status) {
  const detail = body?.detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) return detail.map((item) => item.msg).join("; ");
  return `Request failed (${status})`;
}

async function request(path, { method = "GET", json, body } = {}) {
  const headers = {};
  const token = getToken();
  if (token) headers.Authorization = `Bearer ${token}`;
  if (json) headers["Content-Type"] = "application/json";

  const response = await fetch(BASE + path, {
    method,
    headers,
    body: json ? JSON.stringify(json) : body,
  });
  const data = await response.json().catch(() => null);

  if (response.status === 401 && token) {
    clearToken();
    window.dispatchEvent(new Event(LOGOUT_EVENT));
  }
  if (!response.ok) throw new Error(errorMessage(data, response.status));

  return data;
}

export const api = {
  signup: (email, password) => request("/auth/signup", { method: "POST", json: { email, password } }),

  login: (email, password) =>
    request("/auth/login", { method: "POST", body: new URLSearchParams({ username: email, password }) }),

  me: () => request("/auth/me"),

  createJob: (pdfA, pdfB) => {
    const form = new FormData();
    form.append("pdf_a", pdfA);
    form.append("pdf_b", pdfB);
    return request("/jobs", { method: "POST", body: form });
  },

  listJobs: () => request("/jobs?limit=50"),

  getJob: (jobId) => request(`/jobs/${jobId}`),

  // EventSource cannot send headers, so the token goes in the URL.
  streamUrl: () => `${BASE}/jobs/stream?token=${encodeURIComponent(getToken() ?? "")}`,
};
