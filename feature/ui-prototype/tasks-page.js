// --- Task page owns its own multi-Project filter; sidebar Projects remain independent. ---
const tasksProjectFilterButton=document.getElementById('tasksProjectFilterButton');
const tasksProjectFilterMenu=document.getElementById('tasksProjectFilterMenu');
const tasksProjectFilterOptions=document.getElementById('tasksProjectFilterOptions');
const tasksProjectFilterSummary=document.getElementById('tasksProjectFilterSummary');
const bootTaskProjectKeys=window.UiBootstrap?.state?.taskProjectKeys;
let selectedTaskProjectKeys=Array.isArray(bootTaskProjectKeys)
  ?new Set(bootTaskProjectKeys.filter(key=>projectMeta[key]))
  :new Set(Object.keys(projectMeta));
function persistTaskProjectFilter(){
  try{localStorage.setItem(window.UiBootstrap?.keys?.taskProjectFilters||'ai-task-runner.prototype.taskProjectFilters',JSON.stringify([...selectedTaskProjectKeys]))}catch(_){}
}

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
  persistTaskProjectFilter();
  tasksProjectFilterButton.classList.remove('ui-pending');
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
  const items=canonicalTaskItems(t),editable=taskEditable(t);
  const lockedReason=t.status==='ongoing'?'Pause before editing this Task':t.status==='closed'?'Closed Task is read-only':'';
  ['planAddTask','planAddExisting','planRenameList'].forEach(id=>{
    const b=document.getElementById(id);if(!b)return;b.disabled=!editable;b.title=b.disabled?lockedReason:'';
  });
  const yaml=document.getElementById('planEditYaml');
  if(t.status==='paused'){
    document.getElementById('planStatePill').textContent=t.configDirty?'Current changed · restart required':'Current + future editable';
    yaml.disabled=true;
    yaml.title='Paused keeps completed history frozen. Edit current/future tasks individually; changing current requires restart.';
  }else{
    yaml.disabled=!editable;
    yaml.title=yaml.disabled?lockedReason:'';
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
  const items=canonicalTaskItems(t),editable=taskEditable(t);
  const lockedReason=t.status==='ongoing'?'Pause before editing this Task':t.status==='closed'?'Closed Task is read-only':'';
  const openList=document.getElementById('openFullPlan');if(openList)openList.textContent=t.status==='paused'?'Edit Task List':'Open list';
  ['drawerAddStep','drawerAddExisting','editTaskDemo'].forEach(id=>{
    const b=document.getElementById(id);if(!b)return;b.disabled=!editable;b.title=b.disabled?lockedReason:'';
  });
  const yaml=document.getElementById('stepsAdvanced');
  if(yaml){
    yaml.disabled=!editable||t.status==='paused';
    yaml.title=t.status==='paused'
      ?'Paused keeps completed history frozen. Edit current/future tasks individually.'
      :(yaml.disabled?lockedReason:'');
  }
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

let pendingTaskLifecycleAction=null;

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

function resetTaskRuntimeConfirmed(t){
  if(!t)return;
  t.runtime='idle';t.stage='Idle';t.session='—';t.progress=[0,canonicalTaskItems(t).length];t.elapsed='—';t.configDirty=false;
  t.desc='Runtime reset from the beginning.';
  pushTaskHistory(t,'Runtime reset confirmed');
  persistCurrentPresetFromTaskMap();renderBoardFromMap();
}

function rerunTaskConfirmed(t){
  if(!t)return;
  t.runtime='running';t.status='ongoing';t.stage='planning';t.session='fresh';t.progress=[0,canonicalTaskItems(t).length];t.elapsed='0m';t.configDirty=false;
  t.desc='Rerun started from a fresh run; previous history remains visible.';
  pushTaskHistory(t,'Rerun confirmed · new run identity');
  persistCurrentPresetFromTaskMap();renderBoardFromMap();
}

function requestTaskLifecycleConfirmation(t,action){
  if(!t||!['reset','rerun','move-to-new'].includes(action))return;
  pendingTaskLifecycleAction={taskId:t.id,action};
  const items=canonicalTaskItems(t),done=Math.min(t.progress?.[0]||0,items.length);
  const title=document.getElementById('taskResetToNewTitle');
  const meta=document.getElementById('taskResetToNewMeta');
  const note=document.getElementById('taskResetToNewNote');
  const confirm=document.getElementById('confirmTaskResetToNew');
  meta.textContent=`${t.id} · ${t.title} · progress ${done}/${items.length}`;

  if(action==='reset'){
    const movesToNew=t.status==='paused';
    title.textContent=movesToNew?'Reset paused Task and move it to New?':'Reset this Task?';
    note.innerHTML=movesToNew
      ?'<strong>Paused → New.</strong><br>The current resumable execution is abandoned, progress resets to the beginning, and Task configuration stays intact.'
      :'<strong>Reset execution progress?</strong><br>The Task keeps its current Board status, but runtime progress returns to the beginning.';
    confirm.textContent=movesToNew?'Reset & Move to New':'Reset Task';
  }else if(action==='rerun'){
    const completed=t.status==='closed';
    title.textContent=completed?'Rerun this completed Task?':'Rerun this Task from the beginning?';
    note.innerHTML=completed
      ?'<strong>The completed run stays in History.</strong><br>The Task moves back to New with fresh runtime state, ready to run again from Task 1.'
      :'<strong>Start a fresh run?</strong><br>Current runtime progress is replaced by a new run from the beginning; existing History remains visible.';
    confirm.textContent=completed?'Move to New & Rerun':'Rerun Task';
  }else{
    const completed=t.status==='closed';
    title.textContent=completed?'Move completed Task back to New?':'Move paused Task back to New?';
    note.innerHTML=completed
      ?'<strong>The completed run stays in History.</strong><br>Task configuration stays intact and runtime progress resets to the beginning.'
      :'<strong>This abandons the current resumable execution.</strong><br>Task configuration stays intact, progress resets to the beginning, and the abandoned run remains visible in History.';
    confirm.textContent='Move to New';
  }
  openModal('taskResetToNewModal');
}

function requestTaskResetToNew(t){
  if(!t||!['paused','closed'].includes(t.status))return;
  requestTaskLifecycleConfirmation(t,'move-to-new');
}

document.getElementById('confirmTaskResetToNew').onclick=()=>{
  const pending=pendingTaskLifecycleAction;
  pendingTaskLifecycleAction=null;
  closeModal('taskResetToNewModal');
  if(!pending)return;
  const t=taskMap[pending.taskId],fromInfo=document.getElementById('taskOverlay').classList.contains('open')&&currentTaskId===pending.taskId;
  if(!t)return;

  if(pending.action==='move-to-new'){
    if(!['paused','closed'].includes(t.status))return;
    resetTaskToNew(t);
    showToast('Task moved to New · execution reset from start');
  }else if(pending.action==='reset'){
    if(t.status==='paused'){
      resetTaskToNew(t);
      showToast('Paused Task reset · moved to New');
    }else{
      resetTaskRuntimeConfirmed(t);
      showToast('Task reset confirmed');
    }
  }else if(pending.action==='rerun'){
    if(t.status==='closed'){
      resetTaskToNew(t);
      showToast('Completed Task moved to New · previous run preserved');
    }else{
      rerunTaskConfirmed(t);
      showToast('Task rerun started');
    }
  }
  if(fromInfo)openTaskById(t.id);
};

document.querySelectorAll('[data-close-modal="taskResetToNewModal"]').forEach(button=>button.addEventListener('click',()=>{pendingTaskLifecycleAction=null}));
document.getElementById('taskResetToNewModal')?.addEventListener('click',e=>{if(e.target===e.currentTarget)pendingTaskLifecycleAction=null});

// Intercept Paused / Closed → New before the generic Board drop handler mutates status.
const newDropzone=document.querySelector('.col[data-status="new"] .dropzone');
newDropzone.addEventListener('drop',e=>{
  if(!dragged)return;
  const t=taskMap[dragged.dataset.id];
  if(!['paused','closed'].includes(t?.status))return;
  e.preventDefault();e.stopImmediatePropagation();newDropzone.classList.remove('over');
  requestTaskResetToNew(t);
},true);

// Final lifecycle owner: Reset and Rerun always require confirmation.
document.getElementById('taskResetDemo').onclick=()=>{
  const t=taskMap[currentTaskId];if(t)requestTaskLifecycleConfirmation(t,'reset');
};
document.getElementById('taskSecondaryDemo').onclick=()=>{
  const t=taskMap[currentTaskId];if(t)requestTaskLifecycleConfirmation(t,'rerun');
};

function openTaskFromBoard(t){
  if(!t)return;
  if(t.status==='new'){openPlanDialog(t.id);return}
  openTaskById(t.id);
}
const deleteGuardOpenTask=openTaskById;
openTaskById=function(id){
  deleteGuardOpenTask(id);
  const t=taskMap[id],del=document.getElementById('deleteTaskDemo');if(!t||!del)return;
  del.disabled=!taskCanDelete(t);
  del.title=del.disabled?'Pause / Stop this Task before deleting it':'Delete Task';
};

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
