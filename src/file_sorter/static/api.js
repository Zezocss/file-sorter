/** Same-origin JSON requests and per-session CSRF bootstrap. */
let csrf = "";

export async function requestJson(path, method = "GET", body) {
  // Inputs are relative API paths and JSON; errors become readable Error objects.
  const response = await fetch(path, {method, credentials: "same-origin", headers: {
    "Content-Type": "application/json", "X-CSRF-Token": csrf,
  }, ...(body === undefined ? {} : {body: JSON.stringify(body)})});
  const data = await response.json();
  if (!response.ok) {
    const error = new Error(data.error?.message || `Request failed (${response.status})`);
    error.field = data.error?.field;
    throw error;
  }
  return data;
}

export async function bootstrapSession() {
  // Bootstrap an HttpOnly session cookie and keep its CSRF token only in memory.
  const data = await requestJson("/api/session");
  csrf = data.csrf;
  return data;
}
