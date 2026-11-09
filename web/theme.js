/*
 * Apply the saved theme before the stylesheet paints. This file is loaded
 * synchronously in <head>; the workbench keeps the rest of its scripts deferred.
 */
(function () {
  "use strict";
  try {
    const saved = localStorage.getItem("author-agent-theme");
    if (saved === "light" || saved === "dark") {
      document.documentElement.dataset.theme = saved;
    }
  } catch { /* storage may be unavailable */ }
})();
