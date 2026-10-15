const $=id=>document.getElementById(id);
const t=(key,fallback="")=>window.I18n?.t(key,fallback)??fallback??key;
const keys={appearance:"ai-task-runner.appearance",theme:"ai-task-runner.theme",motion:"ai-task-runner.motion",language:"ai-task-runner.language"};
function read(id,fallback){try{return localStorage.getItem(keys[id])||fallback}catch(_){return fallback}}
function apply(){
  const appearance=$("appearance").value;
  const resolved=appearance==="system"?(matchMedia("(prefers-color-scheme: dark)").matches?"dark":"light"):appearance;
  document.documentElement.dataset.appearance=resolved;
  document.documentElement.dataset.appearancePreference=appearance;
  document.documentElement.dataset.theme=$("theme").value;
  document.documentElement.dataset.motion=$("motion").value;
}
for(const [id,fallback] of Object.entries({appearance:"system",theme:"teal",motion:"full",language:"zh-TW"})){$(id).value=read(id,fallback);$(id).addEventListener("change",()=>{try{localStorage.setItem(keys[id],$(id).value);if(id==="language")window.I18n?.setLanguage($(id).value,{persist:true});$("settingsStatus").textContent=t("settings.saved","Saved");apply()}catch(e){$("settingsStatus").textContent=e.message}})}
apply();
const settingsShell=document.querySelector(".settings-shell");
function setSettingsContextCollapsed(collapsed){
  settingsShell.classList.toggle("context-collapsed",collapsed);
  $("toggleSettingsContext").setAttribute("aria-expanded",String(!collapsed));
  $("toggleSettingsContext").title=collapsed?"Expand Settings sidebar":"Collapse Settings sidebar";
  try{localStorage.setItem("ai-task-runner.settings.context-collapsed",String(collapsed))}catch(_){}
}
$("toggleSettingsContext").addEventListener("click",()=>setSettingsContextCollapsed(!settingsShell.classList.contains("context-collapsed")));
try{setSettingsContextCollapsed(localStorage.getItem("ai-task-runner.settings.context-collapsed")==="true")}catch(_){}

window.addEventListener("app-language-changed",()=>{$("settingsStatus").textContent="";});
