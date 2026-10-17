// --- Task page owns its own multi-Project filter; sidebar Projects remain independent. ---
const tasksProjectFilterButton=document.getElementById('tasksProjectFilterButton');
const tasksProjectFilterMenu=document.getElementById('tasksProjectFilterMenu');
const tasksProjectFilterOptions=document.getElementById('tasksProjectFilterOptions');
const tasksProjectFilterSummary=document.getElementById('tasksProjectFilterSummary');
let selectedTaskProjectKeys=new Set(Object.keys(projectMeta));

function availableTaskProjectKeys(){return projectRegistryEntries().map(([key])=>key).filter(key=>projectMeta[key])}
function taskMatchesSelectedProjects(t){
  if(!t||selectedTaskProjectKeys.size===0)return false;
  const keys=taskProjectKeys(t);
  return keys.some(key=>selectedTaskProjectKeys.has(key));
}
function selectedTaskProjects(){
  // Board identity is the parent Task ID. A multi-Project Task List is still one Board card.
  return Object.values(taskMap||{}).filter(taskMatchesSelectedProjects);
}
function renderTasksProjectFilter(){
  const entries=projectRegistryEntries().filter(([key])=>projectMeta[key]);
  for(const key of [...selectedTaskProjectKeys])if(!projectMeta[key])selectedTaskProjectKeys.delete(key);
  tasksProjectFilterOptions.innerHTML=entries.map(([key,meta])=>`<button type="button" class="tasks-project-option ${selectedTaskProjectKeys.has(key)?'selected':''}" data-task-project-filter="${escapeAttr(key)}"><span class="tasks-project-check">✓</span><span><strong>${escapeHtml(key)}</strong><small>${escapeHtml(meta.path||'')} · ${escapeHtml(meta.branch||'main')}</small></span></button>`).join('');
  tasksProjectFilterOptions.querySelectorAll('[data-task-project-filter]').forEach(btn=>btn.onclick=()=>toggleTaskProject(btn.dataset.taskProjectFilter));
  const selected=[...selectedTaskProjectKeys].filter(key=>projectMeta[key]),all=entries.map(([key])=>key);
  const boardCount=Object.values(taskMap||{}).filter(taskMatchesSelectedProjects).length;
  tasksProjectFilterSummary.textContent=selected.length===0?'No Project':selected.length===1?selected[0]:(selected.length===all.length&&all.length>1?`All Projects · ${boardCount} Tasks`:`${selected.length} Projects · ${boardCount} Tasks`);
  if(selected.length===1)document.getElementById('tasksProjectLine').textContent=`${projectMeta[selected[0]]?.path||selected[0]} · Tasks`;
  else document.getElementById('tasksProjectLine').textContent=`${selected.length} Projects selected · Tasks from selected Projects`;
}
function refreshTaskProjectFilter(){
  renderTasksProjectFilter();
  if(typeof applyTaskFilter==='function')applyTaskFilter();
}
function toggleTaskProject(key){
  if(!projectMeta[key])return;
  if(selectedTaskProjectKeys.has(key))selectedTaskProjectKeys.delete(key);else selectedTaskProjectKeys.add(key);
  refreshTaskProjectFilter();
}
function setAllTaskProjects(){
  selectedTaskProjectKeys=new Set(availableTaskProjectKeys());refreshTaskProjectFilter();
}
function openTaskProjectFilter(){
  renderTasksProjectFilter();tasksProjectFilterMenu.hidden=false;tasksProjectFilterButton.setAttribute('aria-expanded','true');
}
function closeTaskProjectFilter(){
  tasksProjectFilterMenu.hidden=true;tasksProjectFilterButton.setAttribute('aria-expanded','false');
}
tasksProjectFilterButton.onclick=e=>{e.stopPropagation();tasksProjectFilterMenu.hidden?openTaskProjectFilter():closeTaskProjectFilter()};
tasksProjectFilterMenu.addEventListener('click',e=>e.stopPropagation());
tasksProjectFilterMenu.querySelector('[data-project-filter-all]').onclick=setAllTaskProjects;
tasksProjectFilterMenu.querySelector('[data-project-filter-clear]').onclick=()=>{selectedTaskProjectKeys.clear();refreshTaskProjectFilter()};
document.addEventListener('click',e=>{if(!e.target.closest('#tasksProjectMulti'))closeTaskProjectFilter()});

applyTaskFilter=function(){
  const q=document.getElementById('taskSearch').value.trim().toLowerCase();
  document.querySelectorAll('.taskcard').forEach(card=>{const t=taskMap[card.dataset.id],projectOk=taskMatchesSelectedProjects(t),queryOk=!q||card.textContent.toLowerCase().includes(q),runOk=!runningOnly||['running','recover'].includes(t?.runtime);card.hidden=!(projectOk&&queryOk&&runOk)});
  document.querySelectorAll('#taskListView [data-taskrow]').forEach(row=>{const t=taskMap[row.dataset.taskrow],projectOk=taskMatchesSelectedProjects(t),queryOk=!q||row.textContent.toLowerCase().includes(q),runOk=!runningOnly||['running','recover'].includes(t?.runtime);row.hidden=!(projectOk&&queryOk&&runOk)});
  updateCounts();
};
visibleProjectTasks=function(){return selectedTaskProjects()};

updateCounts=function(){
  projectScopedUpdateCounts();
  const visible=selectedTaskProjects(),q=document.getElementById('taskSearch').value.trim().toLowerCase();
  const filtered=visible.filter(t=>(!runningOnly||['running','recover'].includes(t.runtime))&&(!q||document.querySelector(`.taskcard[data-id="${CSS.escape(t.id)}"]`)?.textContent.toLowerCase().includes(q)));
  document.getElementById('taskNavCount').textContent=filtered.length;
  document.getElementById('runningCount').textContent=`${filtered.filter(t=>['running','recover'].includes(t.runtime)).length} Running`;
  document.querySelectorAll('.col').forEach(col=>col.querySelector('.count').textContent=col.querySelectorAll('.taskcard:not([hidden])').length);
};

const taskMultiSelectBefore=selectProject;
selectProject=function(key){taskMultiSelectBefore(key);renderTasksProjectFilter()};

const ensureProjectBeforeTaskSwitcher=ensureProjectFromInput;
ensureProjectFromInput=function(raw){const key=ensureProjectBeforeTaskSwitcher(raw);if(key)selectedTaskProjectKeys.add(key);renderTasksProjectFilter();return key};
const renameProjectBeforeTaskSwitcher=renameProject;
renameProject=function(oldKey,newKey){
  const wasSelected=selectedTaskProjectKeys.has(oldKey),result=renameProjectBeforeTaskSwitcher(oldKey,newKey);
  const clean=String(newKey||'').trim();
  if(result&&wasSelected){selectedTaskProjectKeys.delete(oldKey);if(projectMeta[clean])selectedTaskProjectKeys.add(clean)}
  renderTasksProjectFilter();return result;
};
const deleteProjectBeforeTaskSwitcher=deleteProject;
deleteProject=function(key){selectedTaskProjectKeys.delete(key);deleteProjectBeforeTaskSwitcher(key);renderTasksProjectFilter();applyTaskFilter()};

renderTasksProjectFilter();

// --- Final Paused edit policy: completed frozen; current editable with restart; future freely editable. ---
function taskItemCanEdit(owner,index){
  if(!owner||!taskEditable(owner))return false;
  const items=canonicalTaskItems(owner),s=planStateFor(owner,index,items.length);
  if(s.done)return false;
  if(owner.status==='paused'&&index<batchState.index)return false;
  return true;
}
function taskItemCanRestructure(owner,index){
  if(!taskItemCanEdit(owner,index))return false;
  if(owner.status==='paused'&&index<=batchState.index)return false;
  return true;
}

const pausedPolicyLoadTaskEditor=loadTaskEditor;
loadTaskEditor=function(mode,args={}){
  if(mode==='edit-item'){
    const owner=taskMap[args.ownerId||currentTaskId],index=Number(args.index);
    if(!taskItemCanEdit(owner,index)){
      showToast(owner?.status==='paused'?'Paused · completed task is locked':'Task is read-only');
      return;
    }
  }
  pausedPolicyLoadTaskEditor(mode,args);
};

const pausedPolicyRenderFullPlan=renderFullPlan;
renderFullPlan=function(t){
  pausedPolicyRenderFullPlan(t);
  const items=canonicalTaskItems(t);
  if(t.status==='paused'){
    document.getElementById('planStatePill').textContent=t.configDirty?'Current changed · restart required':'Current + future editable';
    document.getElementById('planEditYaml').disabled=true;
    document.getElementById('planEditYaml').title='Paused keeps completed history frozen. Edit current/future tasks individually; changing current requires restart.';
  }else{
    document.getElementById('planEditYaml').title='';
  }
  document.querySelectorAll('#planFormList [data-plan-row]').forEach(row=>{
    const i=+row.dataset.planRow,canEdit=taskItemCanEdit(t,i),canMove=taskItemCanRestructure(t,i);
    const edit=row.querySelector('[data-task-item-edit]');if(edit)edit.disabled=!canEdit;
    const up=row.querySelector('[data-plan-up]');if(up)up.disabled=!canMove||i<1||(t.status==='paused'&&i-1<=batchState.index);
    const down=row.querySelector('[data-plan-down]');if(down)down.disabled=!canMove||i>=items.length-1;
    const remove=row.querySelector('[data-plan-remove]');if(remove)remove.disabled=!canMove;
    row.ondblclick=e=>{if(e.target.closest('button'))return;if(taskItemCanEdit(t,i))loadTaskEditor('edit-item',{ownerId:t.id,index:i})};
  });
};

const pausedPolicyRenderDrawerPlan=renderDrawerPlan;
renderDrawerPlan=function(t){
  pausedPolicyRenderDrawerPlan(t);
  const items=canonicalTaskItems(t);
  const openList=document.getElementById('openFullPlan');if(openList)openList.textContent=t.status==='paused'?'Edit Task List':'Open list';
  document.querySelectorAll('#formList [data-drawer-item]').forEach(row=>{
    const i=+row.dataset.drawerItem,canEdit=taskItemCanEdit(t,i);
    const edit=row.querySelector('[data-drawer-edit]');if(edit)edit.disabled=!canEdit;
    row.ondblclick=e=>{if(e.target.closest('button'))return;if(taskItemCanEdit(t,i))loadTaskEditor('edit-item',{ownerId:t.id,index:i})};
  });
};

const pausedPolicyOpenItemContextMenu=openItemContextMenu;
openItemContextMenu=function(e,owner,index){
  pausedPolicyOpenItemContextMenu(e,owner,index);
  const canEdit=taskItemCanEdit(owner,index);
  setContextAction('edit',{visible:true,enabled:canEdit,label:'Edit'});
  setContextAction('remove',{visible:true,enabled:taskItemCanRestructure(owner,index),label:'Remove'});
};

let pendingResetToNewTaskId=null;
function resetTaskToNew(t){
  if(!t||!['paused','closed'].includes(t.status))return;
  const items=canonicalTaskItems(t),previousStatus=t.status,previousProgress=t.progress?.[0]||0,previousElapsed=t.elapsed||'—';
  const previousRun=t.runNumber||1;
  if(previousStatus==='closed'){
    pushTaskHistory(t,`Run #${previousRun} preserved · Completed · ${previousProgress}/${items.length} · ${previousElapsed}`);
  }else{
    pushTaskHistory(t,`Run #${previousRun} abandoned · Paused → New after ${previousProgress}/${items.length} completed`);
  }
  t.runNumber=previousRun+1;
  pushTaskHistory(t,`Run #${t.runNumber} prepared · ${statusLabel(previousStatus)} → New`);
  t.status='new';t.runtime='idle';t.progress=[0,items.length];t.stage='Ready';t.session='—';t.elapsed='—';t.configDirty=false;
  t.desc=items.length===1?'Ready to run from the beginning':`${items.length} ordered tasks · ready to run from the beginning`;
  if(batchParentTaskId===t.id){
    clearInterval(batchRunTimer);batchRunTimer=null;
    batchDraft=cloneBatch(items);batchState={status:'idle',index:0,recovered:false,currentDirty:false};setBatchControls();
  }
  persistCurrentPresetFromTaskMap();renderBoardFromMap();
}
function requestTaskResetToNew(t){
  if(!t||!['paused','closed'].includes(t.status))return;
  pendingResetToNewTaskId=t.id;
  const items=canonicalTaskItems(t),done=Math.min(t.progress?.[0]||0,items.length),closed=t.status==='closed';
  document.getElementById('taskResetToNewTitle').textContent=closed?'Run this Task again from the beginning?':'Move Task back to New?';
  document.getElementById('taskResetToNewMeta').textContent=`${t.id} · ${t.title} · progress ${done}/${items.length}`;
  document.getElementById('taskResetToNewNote').innerHTML=closed
    ?'<strong>The completed run stays in History.</strong><br>Task configuration stays intact. A new execution starts from Task 1 with fresh runtime state.'
    :'<strong>This abandons the current resumable execution.</strong><br>Task configuration stays intact, execution progress resets to the beginning, and the abandoned run remains visible in History.';
  document.getElementById('confirmTaskResetToNew').textContent=closed?'Move to New & Run Again':'Move to New & Reset';
  openModal('taskResetToNewModal');
}
document.getElementById('confirmTaskResetToNew').onclick=()=>{
  const t=taskMap[pendingResetToNewTaskId],fromInfo=document.getElementById('taskOverlay').classList.contains('open');
  pendingResetToNewTaskId=null;closeModal('taskResetToNewModal');
  if(!t||!['paused','closed'].includes(t.status))return;
  const wasClosed=t.status==='closed';resetTaskToNew(t);
  if(fromInfo){document.getElementById('taskOverlay').classList.remove('open');openPlanDialog(t.id)}
  showToast(wasClosed?'Task moved to New · previous run preserved':'Task moved to New · execution reset from start');
};

// Intercept Paused / Closed → New before the generic Board drop handler mutates status.
const newDropzone=document.querySelector('.col[data-status="new"] .dropzone');
newDropzone.addEventListener('drop',e=>{
  if(!dragged)return;
  const t=taskMap[dragged.dataset.id];
  if(!['paused','closed'].includes(t?.status))return;
  e.preventDefault();e.stopImmediatePropagation();newDropzone.classList.remove('over');
  requestTaskResetToNew(t);
},true);

const taskRerunBeforeResetPolicy=document.getElementById('taskSecondaryDemo').onclick;
document.getElementById('taskSecondaryDemo').onclick=()=>{
  const t=taskMap[currentTaskId];
  if(t?.status==='closed'){requestTaskResetToNew(t);return}
  taskRerunBeforeResetPolicy();
};

function openTaskFromBoard(t){
  if(!t)return;
  if(t.status==='new'){openPlanDialog(t.id);return}
  openTaskById(t.id);
}
const lifecycleBindTaskCards=bindTaskCards;
bindTaskCards=function(){
  lifecycleBindTaskCards();
  document.querySelectorAll('.taskcard').forEach(card=>{
    const t=taskMap[card.dataset.id];if(!t)return;
    card.title=t.status==='new'?'Open Task list':'Open Task info';
    card.onclick=()=>{if(!card.classList.contains('dragging'))openTaskFromBoard(taskMap[card.dataset.id])};
  });
};
const lifecycleRenderTaskList=renderTaskList;
renderTaskList=function(){
  lifecycleRenderTaskList();
  document.querySelectorAll('#taskListView [data-taskrow]').forEach(row=>{
    const t=taskMap[row.dataset.taskrow];if(!t)return;
    row.title=t.status==='new'?'Open Task list':'Open Task info';
    row.onclick=()=>openTaskFromBoard(taskMap[row.dataset.taskrow]);
  });
};
renderTaskKindUi=function(){};
renderNewTaskSources();
renderChatSession();
renderBoard('today');
renderTasksProjectFilter();
renderTaskKindUi();
