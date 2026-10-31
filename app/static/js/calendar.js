// FullCalendar: month / week / agenda views with a Today button; events from /api/calendar/events.
(function () {
  "use strict";
  const el = document.getElementById("calendar");
  if (!el || !window.FullCalendar) return;
  const detail = document.getElementById("eventDetail");
  const narrow = window.matchMedia("(max-width: 768px)").matches;

  const cal = new FullCalendar.Calendar(el, {
    initialView: narrow ? "listMonth" : "dayGridMonth",
    headerToolbar: { left: "prev,next today", center: "title", right: "dayGridMonth,timeGridWeek,listMonth" },
    buttonText: { today: "Today", month: "Month", week: "Week", list: "Agenda" },
    height: "auto",
    nowIndicator: true,
    dayMaxEvents: 3,
    events: el.getAttribute("data-feed"),
    eventClick: function (info) {
      const props = info.event.extendedProps || {};
      if (info.event.url) return; // follow link (assessment / goals)
      info.jsEvent.preventDefault();
      if (!detail) return;
      detail.classList.remove("d-none");
      document.getElementById("evTitle").textContent = info.event.title;
      document.getElementById("evWhen").textContent = info.event.start ? info.event.start.toLocaleString() : "";
      document.getElementById("evDesc").textContent = props.description || "";
      const del = document.getElementById("evDelete");
      if (props.mine && props.eid) {
        del.action = "/calendar/events/" + props.eid + "/delete";
        del.classList.remove("d-none");
      } else {
        del.classList.add("d-none");
      }
    },
  });
  cal.render();
})();
