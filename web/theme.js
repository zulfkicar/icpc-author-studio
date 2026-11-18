/*
 * Apply the saved theme before the stylesheet paints. This file is loaded
 * synchronously in <head>; the workbench keeps the rest of its scripts deferred.
 */
(function () {
  "use strict";
  try {
    const saved = localStorage.getItem("author-agent-theme");
    if (saved === "system" || (saved === null && location.pathname === "/")) {
      document.documentElement.dataset.theme = matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
    } else if (saved === "light" || saved === "dark") {
      document.documentElement.dataset.theme = saved;
    } else {
      document.documentElement.dataset.theme = "light";
    }
  } catch { /* storage may be unavailable */ }
})();
