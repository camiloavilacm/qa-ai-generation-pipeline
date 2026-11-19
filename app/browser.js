const storageKey = "jwt";

async function showSettings() {
  const token = localStorage.getItem(storageKey);
  const headers = token ? { Authorization: "Token " + token } : {};
  const response = await fetch("/settings/access", { headers });
  if (!response.ok) {
    location.replace("/login");
    return;
  }
  const { email } = await response.json();
  const identity = document.createElement("p");
  identity.dataset.testid = "account-email";
  identity.textContent = email;
  document.querySelector("main").append(identity);
}

function enterSettings(form, alert) {
  // A same-document transition preserves the observed response across the
  // route change, as a client-side router would.
  history.pushState(null, "", "/settings");
  document.querySelector("h1").textContent = "Settings";
  form.remove();
  alert.remove();
  document.body.append(document.createElement("main"));
  showSettings();
}

window.addEventListener("popstate", () => location.reload());

function setupForm() {
  const form = document.querySelector("form");
  const alert = document.querySelector("[role=alert]");
  const endpoint = location.pathname === "/register" ? "/api/users" : "/api/users/login";
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const button = form.querySelector("button");
    button.disabled = true;
    alert.hidden = true;
    try {
      const user = Object.fromEntries(new FormData(form));
      const response = await fetch(endpoint, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ user }),
      });
      const payload = await response.json();
      const sessionHeader = response.headers.get("X-QA-Session");
      if (sessionHeader) localStorage.setItem(storageKey, sessionHeader);
      if (response.ok) {
        localStorage.setItem(storageKey, payload.user.token);
        enterSettings(form, alert);
      } else {
        const invalid = payload.errors?.["email or password"]?.includes("is invalid");
        alert.textContent = invalid ? "Email or password is invalid." : "The request could not be completed.";
        alert.hidden = false;
      }
    } catch {
      alert.textContent = "The request could not be completed.";
      alert.hidden = false;
    } finally {
      button.disabled = false;
    }
  });
}

if (location.pathname === "/settings") showSettings();
else setupForm();
