(() => {
  const STORAGE_KEY = "ai-task-runner.ui.bootstrap.v1";
  const THEMES = new Set(["teal", "blue", "violet", "amber", "rose"]);
  const APPEARANCES = new Set(["system", "light", "dark"]);
  const MOTIONS = new Set(["full", "system", "reduced"]);

  function normalize(value = {}) {
    const source = value && typeof value === "object" ? value : {};
    const theme = THEMES.has(source.theme) ? source.theme : "teal";
    const appearance = APPEARANCES.has(source.appearance) ? source.appearance : "system";
    const motion = MOTIONS.has(source.motion) ? source.motion : "full";
    return { theme, appearance, motion };
  }

  function read() {
    try {
      return normalize(JSON.parse(localStorage.getItem(STORAGE_KEY) || "{}"));
    } catch (_) {
      return normalize();
    }
  }

  function resolvedAppearance(preference) {
    if (preference !== "system") return preference;
    return window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches
      ? "dark"
      : "light";
  }

  function apply(value) {
    const settings = normalize(value);
    document.documentElement.dataset.theme = settings.theme;
    document.documentElement.dataset.appearancePreference = settings.appearance;
    document.documentElement.dataset.appearance = resolvedAppearance(settings.appearance);
    document.documentElement.dataset.motion = settings.motion;
    return settings;
  }

  function storeGlobalSettings(value) {
    const settings = normalize(value?.interface || {});
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(settings));
    } catch (_) {}
    return settings;
  }

  const root = document.documentElement;
  const startedAt = performance.now();
  let finished = false;

  root.classList.add("ui-booting");

  function finish() {
    if (finished) return;
    finished = true;
    const reveal = () => requestAnimationFrame(() => requestAnimationFrame(() => {
      root.classList.add("ui-ready");
      root.classList.remove("ui-booting");
      document.getElementById("appBootstrapLoader")?.setAttribute("aria-hidden", "true");
    }));
    const remaining = Math.max(0, 120 - (performance.now() - startedAt));
    if (remaining) window.setTimeout(reveal, remaining);
    else reveal();
  }

  window.UiBootstrap = { apply, read, storeGlobalSettings, finish };
  apply(read());

  // Fail open if later module/bootstrap work fails before the normal finish call.
  window.setTimeout(finish, 1800);
})();
