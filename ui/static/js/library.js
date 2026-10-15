const $=id=>document.getElementById(id);
let mode="workflow", data={workflows:[],prompts:[]}, projects=[];
async function api(url){const r=await fetch(url);const v=await r.json();if(!r.ok||v.error)throw new Error(v.error||"Request failed");return v}
function selectedProject(){return $("libraryScope").value}
function status(text,error=false){$("libraryStatus").textContent=text;$("libraryStatus").dataset.error=String(error)}
function editorUrl(item){
  const project=selectedProject();
  if(item.kind==="workflow"){
    const p=new URLSearchParams({id:item.id});if(project)p.set("project",project);
    return "/workflow-studio-app/index.html?"+p;
  }
  const p=new URLSearchParams({view:"workflow",source:"prompt",studio:item.id});if(project)p.set("project",project);
  return "/?"+p;
}
function render(){
  const root=$("assetList"), q=$("librarySearch").value.trim().toLowerCase();
  root.replaceChildren();
  const rows=(mode==="workflow"?data.workflows:data.prompts).filter(x=>!q||String(x.name||"").toLowerCase().includes(q)||String(x.path||"").toLowerCase().includes(q));
  if(!rows.length){const e=document.createElement("div");e.className="asset-empty";e.textContent=q?"No results. Clear search to see all assets.":mode==="workflow"?"No Workflows. Open the existing Workflow editor to create one.":"No Prompts. Open the existing Prompt editor to create one.";root.append(e);return}
  for(const item of rows){
    const b=document.createElement("button");b.type="button";b.className="asset-row";
    const name=document.createElement("strong");name.textContent=item.name||item.id;
    const scope=document.createElement("span");scope.textContent=item.scope==="project"?"Project":"Global";
    const meta=document.createElement("span");meta.textContent=item.kind==="workflow"?(item.hidden?"Hidden from Task picker":"Visible in Task picker"):"Prompt";
    b.title=item.path||item.name||"";b.append(name,scope,meta);b.addEventListener("click",()=>{window.location.href=editorUrl(item)});root.append(b);
  }
}
async function loadAssets(){
  status("Loading…");
  const project=selectedProject(), query=project?"&project="+encodeURIComponent(project):"";
  try{data=await api("/api/studio/files?x=1"+query);render();status("")}catch(e){status(e.message,true);data={workflows:[],prompts:[]};render()}
}
async function boot(){
  try{
    const p=await api("/api/projects");projects=p.projects||[];
    for(const project of projects){const o=document.createElement("option");o.value=project.path;o.textContent="Project · "+project.name;o.disabled=!project.exists;$("libraryScope").append(o)}
  }catch(e){status(e.message,true)}
  await loadAssets();
}
$("workflowLibraryTab").addEventListener("click",()=>{mode="workflow";$("workflowLibraryTab").setAttribute("aria-selected","true");$("promptLibraryTab").setAttribute("aria-selected","false");render()});
$("promptLibraryTab").addEventListener("click",()=>{mode="prompt";$("workflowLibraryTab").setAttribute("aria-selected","false");$("promptLibraryTab").setAttribute("aria-selected","true");render()});
$("libraryScope").addEventListener("change",loadAssets);$("librarySearch").addEventListener("input",render);
boot();