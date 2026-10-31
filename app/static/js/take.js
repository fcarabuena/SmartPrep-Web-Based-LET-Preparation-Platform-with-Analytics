// Taking an assessment: one question at a time, server-synced timer, autosave, auto-submit.
(function () {
  "use strict";
  const form = document.getElementById("attemptForm");
  const cfg = window.SP.data("attempt-config");
  if (!form || !cfg) return;

  const cards = Array.from(form.querySelectorAll("[data-question]"));
  const navLinks = Array.from(form.querySelectorAll("[data-goto]"));
  const statusEl = document.getElementById("saveStatus");
  let current = 0;
  let lastTick = Date.now();
  const pendingTimes = {}; // answer_id -> seconds not yet sent
  let dirty = {}; // answer_id -> letter changed since last save
  let submitting = false;

  // ---- one-question-at-a-time paging ----
  function show(i) {
    accrue();
    current = Math.max(0, Math.min(cards.length - 1, i));
    cards.forEach(function (c, idx) { c.classList.toggle("d-none", idx !== current); });
    navLinks.forEach(function (a, idx) { a.classList.toggle("border-primary", idx === current); });
    window.scrollTo({ top: 0, behavior: "smooth" });
  }
  form.addEventListener("click", function (e) {
    if (e.target.closest("[data-next]")) { e.preventDefault(); show(current + 1); }
    if (e.target.closest("[data-prev]")) { e.preventDefault(); show(current - 1); }
    const go = e.target.closest("[data-goto]");
    if (go) { e.preventDefault(); show(parseInt(go.getAttribute("data-goto"), 10)); }
  });

  // ---- time spent on the visible question ----
  function accrue() {
    const now = Date.now();
    const secs = Math.round((now - lastTick) / 1000);
    lastTick = now;
    if (secs <= 0 || !cards[current] || document.hidden) return;
    const id = cards[current].getAttribute("data-answer-id");
    pendingTimes[id] = (pendingTimes[id] || 0) + secs;
  }

  // ---- answers ----
  function refreshProgress() {
    let answered = 0;
    cards.forEach(function (c, idx) {
      const checked = c.querySelector("input[type=radio]:checked");
      if (checked) answered++;
      if (navLinks[idx]) navLinks[idx].classList.toggle("answered", !!checked);
    });
    document.getElementById("answeredCount").textContent = answered;
    document.getElementById("answeredBar").style.width = Math.round((100 * answered) / (cards.length || 1)) + "%";
  }
  form.addEventListener("change", function (e) {
    if (e.target.type === "radio") {
      dirty[e.target.name.slice(4)] = e.target.value;
      refreshProgress();
      save();
    }
  });

  // ---- autosave ----
  function save() {
    accrue();
    const times = Object.assign({}, pendingTimes);
    const answers = dirty;
    if (!Object.keys(answers).length && !Object.keys(times).length) return Promise.resolve();
    dirty = {};
    Object.keys(times).forEach(function (k) { delete pendingTimes[k]; });
    statusEl.textContent = "Saving…";
    return window.SP.post(cfg.save_url, { answers: answers, times: times })
      .then(function (r) { return r.json().then(function (d) { return { status: r.status, data: d }; }); })
      .then(function (res) {
        if (res.status === 409) {
          statusEl.textContent = res.data.message || "Submitted";
          submitting = true;
          window.location.href = res.data.redirect || cfg.result_url;
          return;
        }
        statusEl.innerHTML = '<i class="bi bi-cloud-check"></i> Saved ' + (res.data.saved_at || "");
        if (typeof res.data.remaining === "number") syncTimer(res.data.remaining);
      })
      .catch(function () {
        // keep unsent data for the next try
        Object.assign(dirty, answers);
        Object.keys(times).forEach(function (k) { pendingTimes[k] = (pendingTimes[k] || 0) + times[k]; });
        statusEl.textContent = "Offline – will retry";
      });
  }
  setInterval(save, 15000);

  // ---- timer (server is the source of truth) ----
  let deadline = typeof cfg.remaining === "number" ? Date.now() + cfg.remaining * 1000 : null;
  function syncTimer(remaining) { deadline = Date.now() + remaining * 1000; }
  const timerEl = document.getElementById("timer");
  const timerText = document.getElementById("timerText");
  function tick() {
    if (deadline === null || !timerEl) return;
    const left = Math.max(0, Math.round((deadline - Date.now()) / 1000));
    const h = Math.floor(left / 3600), m = Math.floor((left % 3600) / 60), s = left % 60;
    timerText.textContent = (h ? h + ":" + String(m).padStart(2, "0") : m) + ":" + String(s).padStart(2, "0");
    timerEl.classList.toggle("warn", left <= 300 && left > 60);
    timerEl.classList.toggle("danger", left <= 60);
    if (left === 60) timerEl.setAttribute("aria-live", "assertive");
    if (left <= 0 && !submitting) autoSubmit();
  }
  setInterval(tick, 1000);
  tick();

  function fillTimes() {
    accrue();
    form.querySelectorAll("[data-time-field]").forEach(function (f) {
      const id = f.name.slice(5);
      f.value = pendingTimes[id] || 0;
    });
  }
  function autoSubmit() {
    submitting = true;
    document.getElementById("autoField").value = "1";
    fillTimes();
    form.submit(); // bypasses the confirm dialog
  }
  form.addEventListener("submit", function (e) {
    if (e.defaultPrevented) return;
    submitting = true;
    fillTimes();
  });
  window.addEventListener("beforeunload", function (e) {
    if (!submitting && Object.keys(dirty).length) { save(); e.preventDefault(); }
  });
  document.addEventListener("visibilitychange", function () {
    if (document.hidden) save(); else lastTick = Date.now();
  });

  show(0);
})();
