// --- Project sidebar management: click Project to open; ellipsis owns Rename / Delete. ---
const projectActionMenu=document.getElementById('projectActionMenu');
const projectManageModal=document.getElementById('projectManageModal');
const projectRenameField=document.getElementById('projectRenameField');
const projectRenameInput=document.getElementById('projectRenameInput');
const projectDeleteNote=document.getElementById('projectDeleteNote');
const projectManageConfirm=document.getElementById('projectManageConfirm');
let projectManageState=null;

function syncProjectRowMenus(){
  document.querySelectorAll('#projectScroll .project[data-project]').forEach(btn=>{
    if(btn.closest('.project-row'))return;
    const row=document.createElement('div');row.className='project-row';row.dataset.projectRow=btn.dataset.project;
    btn.parentNode.insertBefore(row,btn);row.appendChild(btn);
    const more=document.createElement('button');more.type='button';more.className='project-more';more.dataset.projectMenu=btn.dataset.project;more.title='Project actions';more.setAttribute('aria-label',`${btn.dataset.project} actions`);more.setAttribute('aria-expanded','false');more.textContent='⋯';row.appendChild(more);
  });
}
function hideProjectActionMenu(){
  projectActionMenu.hidden=true;
  document.querySelectorAll('.project-more[aria-expanded="true"]').forEach(b=>b.setAttribute('aria-expanded','false'));
}
function openProjectActionMenu(btn){
  hideProjectActionMenu();const key=btn.dataset.projectMenu;if(!projectMeta[key])return;
  btn.setAttribute('aria-expanded','true');projectManageState={key,mode:null};
  projectActionMenu.hidden=false;
  const r=btn.getBoundingClientRect(),w=172,h=78;
  projectActionMenu.style.left=`${Math.min(window.innerWidth-w-8,Math.max(8,r.right-w))}px`;
  projectActionMenu.style.top=`${Math.min(window.innerHeight-h-8,Math.max(8,r.bottom+4))}px`;
}
function refreshProjectRowKey(oldKey,newKey){
  const btn=document.querySelector(`#projectScroll .project[data-project="${CSS.escape(oldKey)}"]`);if(!btn)return;
  btn.dataset.project=newKey;btn.querySelector('.project-copy strong').textContent=newKey;
  const row=btn.closest('.project-row');if(row)row.dataset.projectRow=newKey;
  const more=row?.querySelector('.project-more');if(more){more.dataset.projectMenu=newKey;more.setAttribute('aria-label',`${newKey} actions`)}
}
function updateProjectRefs(oldKey,nextValue){
  Object.values(taskMap||{}).forEach(t=>{
    if(t.project===oldKey)t.project=nextValue;
    if(t.projectContext===oldKey)t.projectContext=nextValue;
    [t.items,t.listItems].forEach(items=>items?.forEach(x=>{if(x.project===oldKey)x.project=nextValue}));
  });
  batchDraft?.forEach(x=>{if(x.project===oldKey)x.project=nextValue});
  const input=document.getElementById('newTaskProject');if(input?.value===oldKey)input.value=nextValue;
}
function openProjectManage(mode){
  const key=projectManageState?.key,meta=projectMeta[key];if(!meta)return;
  projectManageState={key,mode};hideProjectActionMenu();
  document.getElementById('projectManageTitle').textContent=mode==='rename'?'Rename Project':'Delete Project';
  document.getElementById('projectManageMeta').textContent=meta.path;
  projectRenameField.hidden=mode!=='rename';projectDeleteNote.hidden=mode!=='delete';
  if(mode==='rename'){projectRenameInput.value=key;projectManageConfirm.textContent='Rename';projectManageConfirm.className='btn primary';setTimeout(()=>{projectRenameInput.focus();projectRenameInput.select()},0)}
  else{projectDeleteNote.innerHTML=`Remove <strong>${escapeHtml(key)}</strong> from Projects?<br>The local folder and existing Tasks are not deleted.`;projectManageConfirm.textContent='Delete Project';projectManageConfirm.className='btn danger'}
  openModal('projectManageModal');
}
function renameProject(oldKey,newKey){
  newKey=String(newKey||'').trim();if(!newKey){showToast('Project name cannot be empty');return false}
  if(newKey===oldKey){closeModal('projectManageModal');return true}
  if(projectMeta[newKey]){showToast('A Project with this name already exists');return false}
  const meta=projectMeta[oldKey];if(!meta)return false;
  projectMeta[newKey]=meta;delete projectMeta[oldKey];updateProjectRefs(oldKey,newKey);refreshProjectRowKey(oldKey,newKey);
  if(currentProjectKey===oldKey)currentProjectKey=newKey;
  renderProjectOptions(currentProjectKey);renderBoardFromMap();selectProject(currentProjectKey);
  closeModal('projectManageModal');showToast(`Project renamed · ${newKey}`);return true;
}
function deleteProject(key){
  const meta=projectMeta[key];if(!meta)return;
  const stablePath=meta.path||key;updateProjectRefs(key,stablePath);
  delete projectMeta[key];
  document.querySelector(`#projectScroll .project[data-project="${CSS.escape(key)}"]`)?.closest('.project-row')?.remove();
  const remaining=projectRegistryEntries().map(([k])=>k).filter(k=>projectMeta[k]);
  if(currentProjectKey===key){
    currentProjectKey=remaining[0]||'';
    if(currentProjectKey){selectProject(currentProjectKey)}
    else{
      document.getElementById('projectSwitcherPath').textContent='No Project';
      document.getElementById('chatProjectTitle').textContent='No Project';
      document.getElementById('chatProjectLine').textContent='Add a Project to continue.';
      document.getElementById('tasksProjectLine').textContent='No Project selected';
    }
  }
  renderProjectOptions(currentProjectKey);renderBoardFromMap();closeModal('projectManageModal');showToast(`Project removed · ${key}`);
}
document.getElementById('projectScroll').addEventListener('click',e=>{
  const more=e.target.closest('.project-more');
  if(more){e.preventDefault();e.stopPropagation();openProjectActionMenu(more);return}
  const project=e.target.closest('.project[data-project]');if(!project)return;
  e.preventDefault();selectProject(project.dataset.project);showView('chat');renderChatSession();
});
projectActionMenu.querySelector('[data-project-action="rename"]').onclick=()=>openProjectManage('rename');
projectActionMenu.querySelector('[data-project-action="delete"]').onclick=()=>openProjectManage('delete');
projectManageConfirm.onclick=()=>{
  if(!projectManageState)return;
  if(projectManageState.mode==='rename')renameProject(projectManageState.key,projectRenameInput.value);
  else if(projectManageState.mode==='delete')deleteProject(projectManageState.key);
};
projectRenameInput.addEventListener('keydown',e=>{if(e.key==='Enter'){e.preventDefault();projectManageConfirm.click()}});
document.addEventListener('click',e=>{if(!projectActionMenu.hidden&&!e.target.closest('#projectActionMenu')&&!e.target.closest('.project-more'))hideProjectActionMenu()});
window.addEventListener('resize',hideProjectActionMenu);window.addEventListener('scroll',hideProjectActionMenu,true);

const ensureProjectFromInputBeforeMenu=ensureProjectFromInput;
ensureProjectFromInput=function(raw){const key=ensureProjectFromInputBeforeMenu(raw);syncProjectRowMenus();return key};
syncProjectRowMenus();
selectProject(currentProjectKey);
