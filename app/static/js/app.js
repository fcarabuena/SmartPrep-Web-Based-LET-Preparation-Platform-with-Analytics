// Smart Prep global helpers (no inline scripts: CSP-friendly)
(function () {
  "use strict";
  const csrf = document.querySelector('meta[name="csrf-token"]')?.content || "";
  window.SP = window.SP || {};
  window.SP.csrf = csrf;

  // fetch wrapper that adds the CSRF header for unsafe methods
  window.SP.post = function (url, data) {
    return fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf, Accept: "application/json" },
      body: JSON.stringify(data || {}),
      credentials: "same-origin",
    });
  };

  // read JSON from <script type="application/json" id="...">
  window.SP.data = function (id) {
    const el = document.getElementById(id);
    if (!el) return null;
    try { return JSON.parse(el.textContent); } catch (e) { return null; }
  };

  document.addEventListener("submit", function (e) {
    const form = e.target;
    const msg = form.getAttribute("data-confirm");
    if (msg && !window.confirm(msg)) {
      e.preventDefault();
      return;
    }
    const btn = form.querySelector('button[type="submit"]:not([data-no-disable])');
    if (btn && !form.hasAttribute("data-no-disable")) {
      setTimeout(function () { btn.disabled = true; }, 0);
    }
  });

  document.addEventListener("click", function (e) {
    const t = e.target.closest("[data-toggle-password]");
    if (t) {
      const input = document.getElementById(t.getAttribute("data-toggle-password"));
      if (input) {
        const show = input.type === "password";
        input.type = show ? "text" : "password";
        t.innerHTML = show ? '<i class="bi bi-eye-slash"></i>' : '<i class="bi bi-eye"></i>';
        t.setAttribute("aria-label", show ? "Hide" : "Show");
      }
    }
    const reveal = e.target.closest("[data-reveal]");
    if (reveal) {
      const el = document.getElementById(reveal.getAttribute("data-reveal"));
      if (el) {
        const hidden = el.classList.toggle("d-none");
        reveal.innerHTML = hidden ? '<i class="bi bi-eye"></i> Show' : '<i class="bi bi-eye-slash"></i> Hide';
      }
    }
    const copy = e.target.closest("[data-copy]");
    if (copy && navigator.clipboard) {
      navigator.clipboard.writeText(copy.getAttribute("data-copy"));
      copy.innerHTML = '<i class="bi bi-check2"></i> Copied';
    }
    const pr = e.target.closest("[data-print]");
    if (pr) { e.preventDefault(); window.print(); }
  });

  // auto-submit selects inside forms marked data-autosubmit
  document.addEventListener("change", function (e) {
    const form = e.target.closest("form[data-autosubmit]");
    if (form && (e.target.tagName === "SELECT" || e.target.type === "checkbox")) form.submit();
  });

  // select-all checkbox helper: <input type=checkbox data-check-all="name">
  document.addEventListener("change", function (e) {
    const name = e.target.getAttribute && e.target.getAttribute("data-check-all");
    if (name) {
      document.querySelectorAll('input[name="' + name + '"]').forEach(function (cb) { cb.checked = e.target.checked; });
    }
  });

  // enable Bootstrap tooltips
  document.querySelectorAll('[data-bs-toggle="tooltip"]').forEach(function (el) {
    if (window.bootstrap) new bootstrap.Tooltip(el);
  });
})();
