const $=id=>document.getElementById(id);
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
for(const [id,fallback] of Object.entries({appearance:"system",theme:"teal",motion:"full",language:"zh-TW"})){$(id).value=read(id,fallback);$(id).addEventListener("change",()=>{try{localStorage.setItem(keys[id],$(id).value);$("settingsStatus").textContent="Saved";apply()}catch(e){$("settingsStatus").textContent=e.message}})}
apply();