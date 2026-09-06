(() => {
  "use strict";
  function normalizeQuery(value) { return String(value || "").trim().toLocaleLowerCase(); }
  function filterItems(items, query) { const needle = normalizeQuery(query); if (!needle) return [...(items || [])]; return (items || []).filter((item) => [item.name, item.path, item.scope, item.group].some((value) => String(value || "").toLocaleLowerCase().includes(needle))); }
  function splitExtension(name) { const value = String(name || ""); if (value.toLowerCase().endsWith(".workflow.yaml")) return [value.slice(0, -14), ".workflow.yaml"]; if (value.toLowerCase().endsWith(".workflow.yml")) return [value.slice(0, -13), ".workflow.yml"]; const index = value.lastIndexOf("."); return index > 0 ? [value.slice(0, index), value.slice(index)] : [value, ""]; }
  function duplicateName(name) { const [base, ext] = splitExtension(name); return `${base} copy${ext}`; }
  function duplicateDestination(item) { return item?.scope === "project" ? "Project" : "Custom"; }
  window.StudioSupport = Object.freeze({ normalizeQuery, filterItems, duplicateName, duplicateDestination });
})();
