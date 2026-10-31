// Live duplicate check on the question form
(function () {
  "use strict";
  const form = document.getElementById("questionForm");
  const stem = document.getElementById("stem");
  const hint = document.getElementById("dupHint");
  if (!form || !stem || !hint) return;
  const exclude = form.getAttribute("data-exclude") || "0";
  let timer = null;

  function esc(s) {
    const d = document.createElement("div");
    d.textContent = s;
    return d.innerHTML;
  }

  function check() {
    const v = stem.value.trim();
    if (v.length < 15) { hint.innerHTML = ""; return; }
    fetch("/api/questions/duplicates?exclude=" + exclude + "&stem=" + encodeURIComponent(v), { credentials: "same-origin" })
      .then(function (r) { return r.ok ? r.json() : { items: [] }; })
      .then(function (data) {
        if (!data.items.length) {
          hint.innerHTML = '<span class="text-success"><i class="bi bi-check-circle"></i> No similar questions found.</span>';
          return;
        }
        hint.innerHTML = '<span class="text-warning-emphasis"><i class="bi bi-exclamation-triangle"></i> Similar: ' +
          data.items.map(function (q) {
            return '<a href="/questions/' + q.id + '" target="_blank">#' + q.id + "</a> " + esc(q.stem.slice(0, 70)) + "…";
          }).join(" · ") + "</span>";
      })
      .catch(function () {});
  }

  stem.addEventListener("input", function () {
    clearTimeout(timer);
    timer = setTimeout(check, 600);
  });
})();
