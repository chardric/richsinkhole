// RichSinkhole Lite — minimal client-side helpers.
// Server-rendered pages do the heavy lifting; this file is intentionally tiny.
(function () {
  "use strict";

  // Auto-dismiss flash messages after 5s.
  document.querySelectorAll(".flash").forEach(function (el) {
    setTimeout(function () {
      el.style.transition = "opacity .4s ease";
      el.style.opacity = "0";
      setTimeout(function () { el.remove(); }, 450);
    }, 5000);
  });
})();
