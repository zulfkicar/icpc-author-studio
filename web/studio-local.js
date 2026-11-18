/* Local drafts are separate from saved workspace bytes and agent requests. */
(() => {
  "use strict";
  const prefix = "studio.recovery.v1:";
  const memory = new Map();
  let unavailable = false;

  function warn() {
    unavailable = true;
    const status = document.getElementById("studio-storage-warning");
    if (status) status.hidden = false;
  }

  function read(key, fallback = null, session = false) {
    const scoped = prefix + key;
    if (memory.has(scoped)) return memory.get(scoped);
    try {
      const value = (session ? sessionStorage : localStorage).getItem(scoped);
      return value === null ? fallback : JSON.parse(value);
    } catch {
      warn();
      return fallback;
    }
  }

  function write(key, value, session = false) {
    const scoped = prefix + key;
    memory.set(scoped, value);
    try {
      const storage = session ? sessionStorage : localStorage;
      if (value === null) storage.removeItem(scoped);
      else storage.setItem(scoped, JSON.stringify(value));
      memory.delete(scoped);
      return true;
    } catch {
      warn();
      return false;
    }
  }

  function entries(key) {
    const matching = new Map();
    try {
      for (let i = 0; i < localStorage.length; i++) {
        const name = localStorage.key(i);
        if (name?.startsWith(prefix + key)) matching.set(name.slice(prefix.length), JSON.parse(localStorage.getItem(name)));
      }
    } catch { warn(); }
    for (const [name, value] of memory) {
      if (name.startsWith(prefix + key)) matching.set(name.slice(prefix.length), value);
    }
    return [...matching].filter(([, value]) => value !== null);
  }

  function legacy(key, fallback = null, session = false) {
    try { return (session ? sessionStorage : localStorage).getItem(key) ?? fallback; }
    catch { warn(); return fallback; }
  }

  function rememberLegacy(key, value, session = false) {
    try {
      const storage = session ? sessionStorage : localStorage;
      if (value === null) storage.removeItem(key);
      else storage.setItem(key, value);
    } catch { warn(); }
  }

  const tab = read("tab", null, true) || (crypto.randomUUID?.() || String(Date.now()) + Math.random());
  write("tab", tab, true);
  window.StudioLocal = { tab, read, write, entries, legacy, rememberLegacy, unavailable: () => unavailable };
})();
