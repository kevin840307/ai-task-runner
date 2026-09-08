export function autosizeTextarea(textarea, { minHeight = 46, maxHeight = 210 } = {}) {
  if (!textarea) return 0;
  textarea.style.setProperty("height", "auto", "important");
  const next = Math.max(minHeight, Math.min(maxHeight, textarea.scrollHeight || minHeight));
  textarea.style.setProperty("height", `${next}px`, "important");
  textarea.style.setProperty("overflow-y", (textarea.scrollHeight || minHeight) > maxHeight ? "auto" : "hidden", "important");
  return next;
}

export function setControlLocked(control, locked, reason = "") {
  if (!control) return;
  if (control.dataset.unlockedTitle === undefined) control.dataset.unlockedTitle = control.title || "";
  if ("disabled" in control) control.disabled = Boolean(locked);
  control.setAttribute("aria-disabled", String(Boolean(locked)));
  control.title = locked && reason ? reason : control.dataset.unlockedTitle;
}

export function createLatestActionGate() {
  let token = 0;
  return {
    begin() { token += 1; return token; },
    isCurrent(value) { return value === token; },
    invalidate() { token += 1; },
  };
}
