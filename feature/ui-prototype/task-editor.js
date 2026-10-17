// --- Canonical prototype execution-plan renderer ---
function planItemDefaults(x={},t=null,i=0){
  const fallbackProject=projectMeta[t?.project]?.path||t?.project||projectMeta[currentProjectKey]?.path||'C:\\project';
  return {
    prompt:String(x.prompt||x.goal||`Task ${i+1}`),
    goalMode:x.goalMode||'inline',goalFile:x.goalFile||'',goalAsset:x.goalAsset||'common/review.md',
    project:x.project||fallbackProject,workflow:x.workflow||'ralphy_ai_validate.yaml',
    validatorMode:x.validatorMode||((x.validator&&x.validator!=='ai')?'file':x.validator==='ai'?'ai':'none'),validator:x.validator&&x.validator!=='ai'?x.validator:'',
    aiMode:x.aiMode||'default',aiPrompt:x.aiPrompt||'',aiFile:x.aiFile||'',aiAsset:x.aiAsset||'common/ai_validator.md',
    originTaskId:x.originTaskId||x.origin_task_id||'',originTaskTitle:x.originTaskTitle||''
  };
}
function planItemsForTask(t){
  const raw=isSequenceTask(t)&&Array.isArray(t.listItems)&&t.listItems.length?t.listItems:[singleTaskItem(t)];
  return raw.map((x,i)=>planItemDefaults(x,t,i));
}
function planStateFor(t,i,count){
  const done=Math.min(t.progress?.[0]||0,count);
  if(t.runtime==='done'||i<done)return {label:'PASS',cls:'pass',done:true,current:false};
  const current=i===Math.min(done,count-1);
  if(current&&t.runtime==='recover')return {label:'Recovering',cls:'running',done:false,current:true};
  if(current&&t.runtime==='running')return {label:'Running',cls:'running',done:false,current:true};
  if(current&&['stopped','attention'].includes(t.runtime))return {label:t.configDirty?'Restart':'Stopped',cls:'stopped',done:false,current:true};
  if(current&&t.runtime==='failed')return {label:'Failed',cls:'stopped',done:false,current:true};
  return {label:'Waiting',cls:'',done:false,current:false};
}
function planTitle(x,i){
  const title=itemTitle(x,i);return title&&String(title).trim()?title:`Task ${i+1}`;
}
function setPlanDraftForTask(t){
  batchParentTaskId=t.id;
  batchDraft=cloneBatch(planItemsForTask(t));
  batchState=deriveStepState(t);
  if(sequenceExpandedIndex>=batchDraft.length)sequenceExpandedIndex=-1;
}
function commitPlanDraft(t,{markDirty=false}={}){
  batchDraft=batchDraft.map((x,i)=>planItemDefaults(x,t,i));
  if(batchDraft.length<=1){
    const x=batchDraft[0]||planItemDefaults({},t,0);
    t.kind='task';t.listItems=null;
    if(t.workspaceKind==='batch')t.workspaceKind='main';
    t.workflow=x.workflow;t.goal=x.prompt;
    t.promptSource={goalMode:x.goalMode,prompt:x.prompt,goalFile:x.goalFile,goalAsset:x.goalAsset,validator:x.validator,aiMode:x.aiMode,aiPrompt:x.aiPrompt,aiFile:x.aiFile,aiAsset:x.aiAsset};
    t.tags=['workflow'];t.progress=[Math.min(t.progress?.[0]||0,1),1];
    t.desc=t.status==='paused'&&markDirty?'Paused Task · execution plan changed · restart required.':'Single task';
  }else{
    t.kind='list';t.workspaceKind='batch';t.workflow='Task List';t.listItems=cloneBatch(batchDraft);
    t.tags=[`${batchDraft.length} tasks`];t.progress=[Math.min(t.progress?.[0]||0,batchDraft.length),batchDraft.length];
    t.executionRoot=`${batchDraft.length} child workspaces`;t.desc=`${batchDraft.length} ordered tasks · ${runtimeLabel(t.runtime)}`;
  }
  if(markDirty&&t.status==='paused'){t.configDirty=true;batchState.currentDirty=true;t.desc='Paused Task · current task changed · restart required.';}
}
function planizeSourceHtml(html,i){
  return String(html||'')
    .replaceAll(`data-item="${i}"`,`data-plan-item="${i}"`)
    .replaceAll('data-field=','data-plan-field=')
    .replaceAll(`data-pick-index="${i}"`,`data-plan-pick="${i}"`)
    .replaceAll('data-pick-field=','data-plan-pick-field=')
    .replaceAll('data-pick-kind=','data-plan-pick-kind=')
    .replaceAll('data-view-prompts="1"','data-plan-view-prompts="1"');
}
function planRowBody(x,i,editable){
  const caps=workflowCaps(x.workflow),validation=[];
  if(caps.file)validation.push(`<div class="source-card"><div class="source-head"><div><strong>File Validator</strong><small>validator</small></div><span class="cap-chip">Required</span></div><div class="source-body"><div class="pathrow"><input data-plan-item="${i}" data-plan-field="validator" value="${escapeAttr(x.validator||'')}" placeholder="Python validator path"><button class="mini-btn" type="button" data-plan-pick="${i}" data-plan-pick-field="validator" data-plan-pick-kind="validator">Choose</button></div></div></div>`);
  if(caps.ai)validation.push(`<div class="source-card"><div class="source-head"><div><strong>AI Validator Prompt</strong><small>ai_validator_prompt_file</small></div>${sourceTabs(x.aiMode,[['default','Default'],['inline','Write'],['file','File'],['asset','Asset']],`data-plan-source data-plan-item="${i}" data-plan-field="aiMode"`)}</div><div class="source-body">${planizeSourceHtml(aiSourceBody(x,i),i)}</div></div>`);
  return `<div class="workflow-row"><div class="field"><label>Project root</label><input data-plan-item="${i}" data-plan-field="project" value="${escapeAttr(x.project)}"></div><div class="field"><label>Workflow</label><select data-plan-item="${i}" data-plan-field="workflow"><option ${x.workflow==='ralphy_ai_validate.yaml'?'selected':''}>ralphy_ai_validate.yaml</option><option ${x.workflow==='mixed.yaml'?'selected':''}>mixed.yaml</option><option ${x.workflow==='file.yaml'?'selected':''}>file.yaml</option><option ${x.workflow==='dynamic_handoff.yaml'?'selected':''}>dynamic_handoff.yaml</option></select></div></div><div class="workflow-caps">${workflowCapsHtml(x.workflow)}</div><div class="source-card"><div class="source-head"><div><strong>Task Prompt</strong><small>goal_file</small></div>${sourceTabs(x.goalMode,[['inline','Write'],['file','File'],['asset','Asset']],`data-plan-source data-plan-item="${i}" data-plan-field="goalMode"`)}</div><div class="source-body">${planizeSourceHtml(goalSourceBody(x,i),i)}</div></div>${validation.length?`<div class="validation-grid ${validation.length===1?'one':''}">${validation.join('')}</div>`:'<div class="validation-empty">This Workflow needs no extra validator input.</div>'}`;
}
function renderDrawerPlan(t){
  const host=document.getElementById('formList'),items=batchDraft.length?batchDraft:planItemsForTask(t),editable=taskEditable(t);
  document.getElementById('taskListEditHint').textContent=items.length===1?'Single task · add another only when needed':`${items.length} tasks · top-to-bottom sequence`;
  document.getElementById('taskListParentHint').textContent=items.length===1?'Runs once · same Board Task':`${items.length} tasks · one Board Task`;
  document.getElementById('openFullPlan').hidden=items.length<2;
  if(items.length===1){
    const x=items[0],s=planStateFor(t,0,1);
    host.innerHTML=`<div class="single-plan-strip"><div class="single-plan-icon">1</div><div class="single-plan-copy"><strong>${escapeHtml(planTitle(x,0))}</strong><small>${escapeHtml(x.workflow)} · ${escapeHtml(basename(x.project))}</small></div><span class="single-plan-state ${s.cls}">${escapeHtml(s.label)}</span></div>`;
  }else{
    host.innerHTML=items.slice(0,4).map((x,i)=>{const s=planStateFor(t,i,items.length);return `<div class="drawer-plan-row ${s.done?'done':''} ${s.current?'current':''}"><span class="n">${i+1}</span><div><strong>${escapeHtml(planTitle(x,i))}</strong><small>${escapeHtml(basename(x.project))} · ${escapeHtml(x.workflow)}</small></div><span class="state">${escapeHtml(s.label)}</span></div>`}).join('')+(items.length>4?`<div class="steps-summary">+ ${items.length-4} more · Open list to edit</div>`:'');
  }
  ['drawerAddStep','drawerAddExisting','stepsAdvanced'].forEach(id=>document.getElementById(id).disabled=!editable);
}
function renderFullPlan(t){
  const host=document.getElementById('planFormList'),items=batchDraft.length?batchDraft:planItemsForTask(t),editable=taskEditable(t);
  document.getElementById('planPageTitle').textContent=t.title;
  document.getElementById('planPageMeta').textContent=`${t.id} · ${statusLabel(t.status)} · ${items.length} task${items.length===1?'':'s'}`;
  document.getElementById('planStatePill').textContent=editable?'Editable':(t.status==='ongoing'?'Pause to edit':'Read-only');
  document.getElementById('planTaskSummary').innerHTML=`<span>Project</span><strong>${escapeHtml(t.project)}</strong><span>Status</span><strong>${escapeHtml(statusLabel(t.status))}</strong><span>Runtime</span><strong>${escapeHtml(runtimeLabel(t.runtime))}</strong><span>Progress</span><strong>${t.progress?.[0]||0} / ${items.length}</strong>`;
  host.innerHTML=items.map((x,i)=>{
    const s=planStateFor(t,i,items.length),expanded=i===sequenceExpandedIndex,completed=s.done;
    const currentLocked=t.status==='paused'&&s.current;
    const canMutate=editable&&!completed;
    const canRestructure=canMutate&&!currentLocked;
    return `<article class="plan-row ${expanded?'expanded':''} ${s.done?'done':''} ${s.current?'current':''}" data-plan-row="${i}"><div class="plan-row-head"><span class="plan-row-num">${i+1}</span><div class="plan-row-copy"><strong>${escapeHtml(planTitle(x,i))}</strong><small>${escapeHtml(basename(x.project))} · ${escapeHtml(x.workflow)}</small></div><div class="plan-row-actions"><span class="plan-row-state ${s.cls}">${escapeHtml(s.label)}</span><div class="plan-row-controls"><button type="button" data-plan-expand="${i}">${expanded?'Close':'Edit'}</button><button type="button" data-plan-up="${i}" ${!canRestructure||i<=Math.max(0,batchState.index)?'disabled':''}>↑</button><button type="button" data-plan-down="${i}" ${!canRestructure||i>=items.length-1?'disabled':''}>↓</button><button type="button" data-plan-remove="${i}" ${!canRestructure?'disabled':''}>×</button></div></div></div><div class="plan-row-body">${planRowBody(x,i,editable)}</div></article>`;
  }).join('');
  ['planAddTask','planAddExisting','planEditYaml'].forEach(id=>document.getElementById(id).disabled=!editable);
  bindFullPlan(t);
}
function bindFullPlan(t){
  document.querySelectorAll('[data-plan-expand]').forEach(b=>b.onclick=()=>{sequenceExpandedIndex=sequenceExpandedIndex===+b.dataset.planExpand?-1:+b.dataset.planExpand;renderFullPlan(t)});
  document.querySelectorAll('[data-plan-item][data-plan-field]').forEach(el=>{
    el.disabled=!taskEditable(t)||(+el.dataset.planItem)<batchState.index;
    const ev=el.tagName==='SELECT'?'change':'input';el.addEventListener(ev,()=>{
      const i=+el.dataset.planItem,field=el.dataset.planField;if(!batchDraft[i])return;batchDraft[i][field]=el.value;
      commitPlanDraft(t,{markDirty:t.status==='paused'&&i===batchState.index});if(field==='workflow')renderFullPlan(t);renderDrawerPlan(t);renderBoardFromMap();
    });
  });
  document.querySelectorAll('[data-plan-source]').forEach(b=>b.onclick=()=>{if(!taskEditable(t))return;const i=+b.dataset.planItem;if(i<batchState.index)return;batchDraft[i][b.dataset.planField]=b.dataset.sourceValue;commitPlanDraft(t,{markDirty:t.status==='paused'&&i===batchState.index});renderFullPlan(t);renderDrawerPlan(t);renderBoardFromMap()});
  document.querySelectorAll('[data-plan-pick]').forEach(b=>b.onclick=()=>openPathPicker(+b.dataset.planPick,b.dataset.planPickField,b.dataset.planPickKind,'plan'));
  document.querySelectorAll('[data-plan-view-prompts]').forEach(b=>b.onclick=()=>{showView('prompts');showToast('Prompt 管理仍使用原本 Prompts workspace')});
  document.querySelectorAll('[data-plan-up]').forEach(b=>b.onclick=()=>{const i=+b.dataset.planUp;if(i<=batchState.index||i<1)return;[batchDraft[i-1],batchDraft[i]]=[batchDraft[i],batchDraft[i-1]];sequenceExpandedIndex=i-1;commitPlanDraft(t,{markDirty:false});renderFullPlan(t);renderDrawerPlan(t);renderBoardFromMap()});
  document.querySelectorAll('[data-plan-down]').forEach(b=>b.onclick=()=>{const i=+b.dataset.planDown;if(i<batchState.index||i>=batchDraft.length-1)return;[batchDraft[i+1],batchDraft[i]]=[batchDraft[i],batchDraft[i+1]];sequenceExpandedIndex=i+1;commitPlanDraft(t,{markDirty:false});renderFullPlan(t);renderDrawerPlan(t);renderBoardFromMap()});
  document.querySelectorAll('[data-plan-remove]').forEach(b=>b.onclick=()=>{const i=+b.dataset.planRemove;if(i<batchState.index||batchDraft.length<=1)return;batchDraft.splice(i,1);sequenceExpandedIndex=Math.min(sequenceExpandedIndex,batchDraft.length-1);commitPlanDraft(t,{markDirty:false});renderFullPlan(t);renderDrawerPlan(t);renderBoardFromMap()});
}
function renderExecutionPlan(t){
  if(!t)return;
  renderDrawerPlan(t);
  const preview=document.getElementById('batchPreview'),items=batchDraft.length?batchDraft:planItemsForTask(t);
  preview.innerHTML=items.map((x,i)=>{
    const s=planStateFor(t,i,items.length);
    return `<div class="previewitem ${s.done?'done':''} ${s.current?'active':''}" data-step="${i}"><span class="step">${i+1}</span><div><strong>${escapeHtml(planTitle(x,i))}</strong><small>${escapeHtml(basename(x.project))} · ${escapeHtml(x.workflow)}</small></div><span class="orderchip">${escapeHtml(s.label)}</span></div>`;
  }).join('');
  if(document.getElementById('planModal').classList.contains('open'))renderFullPlan(t);
}

// Final renderer replaces all previous batch/sequence visual wrappers.
prepareStepsForTask=function(t){if(!t)return;setPlanDraftForTask(t);renderExecutionPlan(t)};
renderBatchDraft=function(){const t=taskMap[currentTaskId]||taskMap[batchParentTaskId];if(t)renderExecutionPlan(t)};
syncTaskListDraftToParent=function(){const t=taskMap[batchParentTaskId]||taskMap[currentTaskId];if(t)commitPlanDraft(t,{markDirty:false})};

function addPlanTask(t,{openPlan=true}={}){
  if(!taskEditable(t)){showToast(t.status==='ongoing'?'Pause Task before editing':'Closed Task is read-only');return}
  if(batchParentTaskId!==t.id)setPlanDraftForTask(t);
  const root=batchDraft[0]?.project||projectMeta[t.project]?.path||'C:\\project';
  batchDraft.push(planItemDefaults({prompt:'Next task',project:root},t,batchDraft.length));sequenceExpandedIndex=batchDraft.length-1;commitPlanDraft(t,{markDirty:false});renderBoardFromMap();renderExecutionPlan(t);
  if(openPlan)openFullPlanPage(t.id);
}
function openFullPlanPage(id=currentTaskId){
  const t=taskMap[id];if(!t)return;
  currentTaskId=id;setPlanDraftForTask(t);
  document.getElementById('taskOverlay').classList.remove('open');
  showView('plan');
  document.querySelectorAll('.navbtn[data-view]').forEach(b=>b.classList.toggle('active',b.dataset.view==='tasks'));
  renderFullPlan(t);
}
document.getElementById('openFullPlan').onclick=()=>openFullPlanPage(currentTaskId);
document.getElementById('planBackToTask').onclick=()=>{const id=currentTaskId;showView('tasks');openTaskById(id)};
document.getElementById('drawerAddStep').onclick=()=>{const t=taskMap[currentTaskId];if(t)addPlanTask(t,{openPlan:true})};
document.getElementById('planAddTask').onclick=()=>{const t=taskMap[currentTaskId];if(t)addPlanTask(t,{openPlan:false});renderFullPlan(t)};

openExistingTaskPicker=function(context){
  existingPickerContext=context;const host=document.getElementById('existingTaskPicker');
  const candidates=Object.values(taskMap).filter(t=>t.id!==currentTaskId&&t.kind!=='list'&&t.workspaceKind!=='batch');
  host.innerHTML=candidates.length?candidates.map(t=>`<button type="button" class="existing-task-option" data-existing-id="${t.id}"><div><strong>${escapeHtml(t.title)}</strong><small>${escapeHtml(t.id)} · ${escapeHtml(t.project)} · ${escapeHtml(t.workflow)}</small></div><span>${escapeHtml(runtimeLabel(t.runtime))}</span></button>`).join(''):'<div class="empty-panel">No standalone Tasks available.</div>';
  host.querySelectorAll('[data-existing-id]').forEach(b=>b.onclick=()=>{
    const owner=taskMap[currentTaskId],source=taskMap[b.dataset.existingId];if(!owner||!source||!taskEditable(owner))return;
    if(batchParentTaskId!==owner.id)setPlanDraftForTask(owner);batchDraft.push(planItemDefaults(taskToListItem(source),owner,batchDraft.length));sequenceExpandedIndex=batchDraft.length-1;commitPlanDraft(owner,{markDirty:false});closeModal('existingTaskModal');renderBoardFromMap();renderExecutionPlan(owner);
    if(context==='drawer')openFullPlanPage(owner.id);else if(document.getElementById('planModal').classList.contains('open'))renderFullPlan(owner);showToast('Existing Task copied into execution plan');
  });openModal('existingTaskModal');
};
document.getElementById('drawerAddExisting').onclick=()=>{const t=taskMap[currentTaskId];if(!t||!taskEditable(t))return;openExistingTaskPicker('drawer')};
document.getElementById('planAddExisting').onclick=()=>{const t=taskMap[currentTaskId];if(!t||!taskEditable(t))return;openExistingTaskPicker('plan')};

function openPlanYamlForTask(t){
  if(!taskEditable(t)){showToast(t.status==='ongoing'?'Pause Task before editing YAML':'Closed Task is read-only');return}
  if(t.status==='paused'&&(t.progress?.[0]||0)>0){showToast('已有完成 tasks；請用 Full Plan 編輯 current / future tasks，避免改寫 PASS 歷史');return}
  if(batchParentTaskId!==t.id)setPlanDraftForTask(t);pendingYamlPlan=null;document.getElementById('yamlEditor').value=batchToYaml(batchDraft);
  const s=document.getElementById('yamlPlanStatus');s.className='yaml-plan-status';s.textContent='Editing the same ordered task list. Validate before Apply.';document.getElementById('applyYamlPlan').disabled=true;openModal('yamlPlanModal');
}
openYamlPlanModal=function(){const t=taskMap[currentTaskId];if(t)openPlanYamlForTask(t)};
document.getElementById('stepsAdvanced').onclick=openYamlPlanModal;document.getElementById('planEditYaml').onclick=openYamlPlanModal;
document.getElementById('applyYamlPlan').onclick=()=>{
  const t=taskMap[currentTaskId];if(!t||!pendingYamlPlan||!taskEditable(t))return;batchDraft=cloneBatch(pendingYamlPlan.map((x,i)=>planItemDefaults(x,t,i)));sequenceExpandedIndex=-1;commitPlanDraft(t,{markDirty:t.status==='paused'});pendingYamlPlan=null;closeModal('yamlPlanModal');renderBoardFromMap();renderExecutionPlan(t);showToast('Task list YAML applied');
};

// Ensure Task Details always refreshes the canonical plan surfaces after older handlers finish.
const canonicalPlanOpenTask=openTaskById;
openTaskById=function(id){canonicalPlanOpenTask(id);const t=taskMap[id];if(t){setPlanDraftForTask(t);renderDrawerPlan(t);document.getElementById('drawerItemsTab').hidden=true}};

function persistCurrentPresetFromTaskMap(){
  if(!taskPresets[currentPreset])return;
  taskPresets[currentPreset]=Object.values(taskMap).map(t=>cloneBatch([t])[0]);
}
// --- Dialog-first Plan UX + move-only New Task composition ---
let addPlanOwnerId=null;
let addTaskMode='create';
let selectedMoveTaskId=null;
function eligibleMoveTasks(owner){
  return Object.values(taskMap).filter(t=>t.id!==owner.id&&t.status==='new'&&t.runtime==='idle'&&!isSequenceTask(t)&&t.workspaceKind!=='batch');
}
function setAddTaskMode(mode){
  addTaskMode=mode;selectedMoveTaskId=null;
  document.querySelectorAll('[data-add-task-mode]').forEach(b=>b.classList.toggle('active',b.dataset.addTaskMode===mode));
  document.getElementById('addTaskCreatePanel').hidden=mode!=='create';
  document.getElementById('addTaskMovePanel').hidden=mode!=='move';
  document.getElementById('confirmAddPlanTask').textContent=mode==='create'?'Add task':'Move here';
  renderMoveTaskPicker();
}
function renderMoveTaskPicker(){
  const owner=taskMap[addPlanOwnerId],host=document.getElementById('moveTaskPicker');if(!owner||!host)return;
  const items=eligibleMoveTasks(owner);
  if(!items.length){host.innerHTML='<div class="empty-panel">No eligible New tasks. Only standalone New + Idle tasks can be moved.</div>';document.getElementById('confirmAddPlanTask').disabled=addTaskMode==='move';return}
  host.innerHTML=items.map(t=>`<button type="button" class="existing-task-option ${selectedMoveTaskId===t.id?'selected':''}" data-move-task-id="${t.id}"><div><strong>${escapeHtml(t.title)}</strong><small>${escapeHtml(t.id)} · ${escapeHtml(t.project)} · ${escapeHtml(t.workflow)}</small></div><span>New</span></button>`).join('');
  host.querySelectorAll('[data-move-task-id]').forEach(b=>b.onclick=()=>{selectedMoveTaskId=b.dataset.moveTaskId;renderMoveTaskPicker()});
  document.getElementById('confirmAddPlanTask').disabled=addTaskMode==='move'&&!selectedMoveTaskId;
}
function openAddTaskDialog(ownerId=currentTaskId){
  const owner=taskMap[ownerId];if(!owner)return;
  if(!taskEditable(owner)){showToast(owner.status==='ongoing'?'Pause Task before editing':'Closed Task is read-only');return}
  addPlanOwnerId=ownerId;addTaskMode='create';selectedMoveTaskId=null;
  document.getElementById('confirmAddPlanTask').disabled=false;
  setAddTaskMode('create');openModal('addPlanTaskModal');
}
document.querySelectorAll('[data-add-task-mode]').forEach(b=>b.onclick=()=>setAddTaskMode(b.dataset.addTaskMode));
document.getElementById('confirmAddPlanTask').onclick=()=>{
  const owner=taskMap[addPlanOwnerId];if(!owner||!taskEditable(owner))return;
  if(batchParentTaskId!==owner.id)setPlanDraftForTask(owner);
  if(addTaskMode==='create'){return}else{
    const source=taskMap[selectedMoveTaskId];
    if(!source||!eligibleMoveTasks(owner).some(t=>t.id===source.id)){showToast('Selected Task is no longer eligible');renderMoveTaskPicker();return}
    const item=planItemDefaults(taskToListItem(source),owner,batchDraft.length);item.originTaskId=source.id;item.originTaskTitle=source.title;
    batchDraft.push(item);
    delete taskMap[source.id];
    pushTaskHistory(owner,`Moved ${source.id} into execution plan · original Board Task retired`);
  }
  sequenceExpandedIndex=batchDraft.length-1;commitPlanDraft(owner,{markDirty:false});persistCurrentPresetFromTaskMap();closeModal('addPlanTaskModal');renderBoardFromMap();renderExecutionPlan(owner);openPlanDialog(owner.id);
  showToast(addTaskMode==='create'?'Task added':'New Task moved into plan');
};

function openPlanDialog(id=currentTaskId){
  const t=taskMap[id];if(!t)return;currentTaskId=id;setPlanDraftForTask(t);renderFullPlan(t);openModal('planModal');
}
openFullPlanPage=openPlanDialog;
document.getElementById('openFullPlan').onclick=()=>openPlanDialog(currentTaskId);
document.getElementById('planBackToTask').onclick=()=>closeModal('planModal');
document.getElementById('drawerAddStep').onclick=()=>openAddTaskDialog(currentTaskId);
document.getElementById('planAddTask').onclick=()=>openAddTaskDialog(currentTaskId);
document.getElementById('drawerAddExisting').onclick=()=>openAddTaskDialog(currentTaskId);
document.getElementById('planAddExisting').onclick=()=>openAddTaskDialog(currentTaskId);

renderExecutionPlan=function(t){
  if(!t)return;renderDrawerPlan(t);
  const preview=document.getElementById('batchPreview'),items=batchDraft.length?batchDraft:planItemsForTask(t);
  preview.innerHTML=items.map((x,i)=>{const s=planStateFor(t,i,items.length);return `<div class="previewitem ${s.done?'done':''} ${s.current?'active':''}" data-step="${i}"><span class="step">${i+1}</span><div><strong>${escapeHtml(planTitle(x,i))}</strong><small>${escapeHtml(basename(x.project))} · ${escapeHtml(x.workflow)}</small></div><span class="orderchip">${escapeHtml(s.label)}</span></div>`}).join('');
  if(document.getElementById('planModal').classList.contains('open'))renderFullPlan(t);
};
renderDrawerPlan=(function(base){return function(t){base(t);document.getElementById('drawerAddExisting').hidden=true;document.getElementById('openFullPlan').textContent='Open list';};})(renderDrawerPlan);

// Show moved provenance in the full plan without creating a second Task identity.
renderFullPlan=(function(base){return function(t){base(t);document.querySelectorAll('#planFormList [data-plan-row]').forEach(row=>{const i=+row.dataset.planRow,x=batchDraft[i];if(x?.originTaskId){const small=row.querySelector('.plan-row-copy small');if(small)small.textContent+=` · moved ${x.originTaskId}`;}});};})(renderFullPlan);

function itemUsesWorktree(x){return !!x&&(x.workspaceKind==='worktree'||x.workspacePolicy==='worktree')}
function taskWorktreeItems(t){return t?canonicalTaskItems(t).filter(itemUsesWorktree):[]}
function taskUsesWorktree(t){return !!t&&(t.workspaceKind==='worktree'||t.workspacePolicy==='worktree'||taskWorktreeItems(t).length>0)}

function renderWorkspaceResult(t){
  const section=document.getElementById('workspaceResultSection'),grid=document.getElementById('workspaceResultGrid'),state=document.getElementById('workspaceResultState'),hint=document.getElementById('workspaceResultHint');
  const worktreeItems=taskWorktreeItems(t),banner=document.getElementById('drawerWorktreeBanner');
  const isolated=t.workspaceKind==='worktree'||(worktreeItems.length===1&&canonicalTaskItems(t).length===1);
  const multi=canonicalTaskItems(t).length>1;
  if(banner){
    banner.hidden=!taskUsesWorktree(t);
    const detail=document.getElementById('drawerWorktreeBannerDetail');
    if(detail)detail.textContent=multi?`${worktreeItems.length} task${worktreeItems.length===1?'':'s'} use isolated Worktrees · changes are not in Main until merged.`:'Isolated development · changes are not in Main until merged.';
  }
  section.hidden=!isolated&&!multi;
  if(multi){state.textContent='Task workspaces';hint.textContent='Each task may resolve its own Main / Worktree workspace.';grid.innerHTML='<span>Merge</span><strong>Handled per child result</strong><span>Cleanup</span><strong>Only after each worktree is merged or discarded</strong>';['reviewChangesDemo','mergeChatDemo','mergeTaskDemo','cleanupWorktreeDemo'].forEach(id=>document.getElementById(id).disabled=true);return}
  if(!isolated)return;
  const ready=['done'].includes(t.runtime)||t.status==='closed';
  const merged=t.mergeState==='merged',cleaned=!!t.worktreeCleaned;
  state.textContent=cleaned?'Cleaned':merged?'Merged':ready?'Ready to merge':'Worktree';
  hint.textContent=cleaned?'Worktree removed after merge.':merged?'Merged successfully · cleanup is now safe.':ready?'Runtime completed · review before merge.':'Worktree is still in use by this Task.';
  const target=projectMeta[t.project]?.branch||'main';
  grid.innerHTML=`<span>Branch</span><strong>${escapeHtml(t.branch||'—')}</strong><span>Target</span><strong>${escapeHtml(target)}</strong><span>Path</span><strong>${escapeHtml(t.executionRoot||'—')}</strong><span>Result</span><strong>${cleaned?'Merged + cleaned':merged?`Merged ${t.mergedCommit||''}`:ready?'Not merged':'In progress'}</strong>`;
  document.getElementById('reviewChangesDemo').disabled=!ready||cleaned;
  document.getElementById('mergeChatDemo').disabled=!ready||merged||cleaned;
  document.getElementById('mergeTaskDemo').disabled=!ready||merged||cleaned;
  document.getElementById('cleanupWorktreeDemo').disabled=!merged||cleaned;
}
document.getElementById('reviewChangesDemo').onclick=()=>showToast('Mock diff review · changed files / tests / branch comparison');
document.getElementById('mergeChatDemo').onclick=()=>showToast('Mock Chat receives branch, target, diff and test context for merge review');
document.getElementById('mergeTaskDemo').onclick=()=>{const t=taskMap[currentTaskId];if(!t||t.workspaceKind!=='worktree'||!(['done'].includes(t.runtime)||t.status==='closed'))return;t.mergeState='merged';t.mergedCommit='mock-a1b2c3d';pushTaskHistory(t,'Worktree merged into target branch');renderWorkspaceResult(t);showToast('Mock merge completed · worktree preserved until Cleanup')};
document.getElementById('cleanupWorktreeDemo').onclick=()=>{const t=taskMap[currentTaskId];if(!t||t.mergeState!=='merged')return;t.worktreeCleaned=true;pushTaskHistory(t,'Worktree cleaned after successful merge');renderWorkspaceResult(t);showToast('Mock worktree cleanup completed')};

const dialogPlanOpenTask=openTaskById;
openTaskById=function(id){dialogPlanOpenTask(id);const t=taskMap[id];if(t)renderWorkspaceResult(t)};

// --- Canonical Task List model: every Board Task owns items[]; one item is the simple case. ---
function canonicalTaskItems(t){
  if(!t)return [];
  let raw=Array.isArray(t.items)&&t.items.length?t.items:(Array.isArray(t.listItems)&&t.listItems.length?t.listItems:[singleTaskItem(t)]);
  const items=raw.map((x,i)=>planItemDefaults(x,t,i));
  t.items=items;t.listItems=t.items;t.kind='task_list';
  const count=items.length;
  const baseTags=(t.tags||[]).filter(x=>!/^\d+\s+tasks?$/.test(String(x))&&x!=='Task List');
  t.tags=[`${count} task${count===1?'':'s'}`,...baseTags].slice(0,4);
  return t.items;
}
function normalizeAllTaskLists(){Object.values(taskMap).forEach(canonicalTaskItems)}
isSequenceTask=function(t){return canonicalTaskItems(t).length>1};
planItemsForTask=function(t){return cloneBatch(canonicalTaskItems(t))};
setPlanDraftForTask=function(t){
  if(!t)return;batchParentTaskId=t.id;batchDraft=cloneBatch(canonicalTaskItems(t));batchState=deriveStepState(t);
  if(sequenceExpandedIndex>=batchDraft.length)sequenceExpandedIndex=-1;
};
commitPlanDraft=function(t,{markDirty=false}={}){
  if(!t)return;batchDraft=batchDraft.map((x,i)=>planItemDefaults(x,t,i));
  t.kind='task_list';t.items=cloneBatch(batchDraft);t.listItems=t.items;
  const count=t.items.length,x=t.items[0];
  t.progress=[Math.min(t.progress?.[0]||0,count),count];
  if(count===1){
    t.workflow=x.workflow;t.goal=x.prompt;
    t.promptSource={goalMode:x.goalMode,prompt:x.prompt,goalFile:x.goalFile,goalAsset:x.goalAsset,validator:x.validator,aiMode:x.aiMode,aiPrompt:x.aiPrompt,aiFile:x.aiFile,aiAsset:x.aiAsset};
    if(t.workspaceKind==='batch')t.workspaceKind='main';
    t.executionRoot=t.executionRoot==='Child task workspaces'?(projectMeta[t.project]?.path||t.project):t.executionRoot;
  }else{
    t.workflow='Task List';t.workspaceKind='batch';t.executionRoot=`${count} child workspaces`;t.goal=`${count} ordered tasks`;
  }
  canonicalTaskItems(t);
  t.desc=count===1?'Single task':`${count} ordered tasks · ${runtimeLabel(t.runtime)}`;
  if(markDirty&&t.status==='paused'){t.configDirty=true;batchState.currentDirty=true;t.desc='Paused Task · current task changed · restart required.'}
};

// Board / create / preset paths all normalize through the same work item adapter.
const canonicalBoardFromMap=renderBoardFromMap;
renderBoardFromMap=function(){normalizeAllTaskLists();canonicalBoardFromMap()};
const canonicalBoardPreset=renderBoard;
renderBoard=function(preset=currentPreset){canonicalBoardPreset(preset);normalizeAllTaskLists();canonicalBoardFromMap()};

// A 'Move existing' source is just a one-item Task List that has never run.
eligibleMoveTasks=function(owner){
  return Object.values(taskMap).filter(t=>t.id!==owner.id&&t.status==='new'&&t.runtime==='idle'&&canonicalTaskItems(t).length===1);
};

// Project click changes the shared Project context and preserves the current workspace.
const canonicalSelectProject=selectProject;
selectProject=function(key){
  canonicalSelectProject(key);
  const meta=projectMeta[key];if(!meta)return;
  document.getElementById('chatProjectTitle').textContent=key;
  document.getElementById('chatProjectLine').textContent=`${meta.path} · Project Chat · 不建立 Runner Task`;
  document.getElementById('tasksProjectLine').textContent=`${meta.path} · Tasks 使用同一個 ordered tasks`;
};
// Sidebar Project navigation is owned by project-sidebar.js.

// Drawer summary always exposes the same Plan dialog, even for a one-item list.
renderDrawerPlan=(function(base){return function(t){
  canonicalTaskItems(t);base(t);
  document.getElementById('openFullPlan').hidden=false;
  document.getElementById('openFullPlan').textContent='Open list';
  const n=t.items.length;
  document.getElementById('taskListEditHint').textContent=`${n} task${n===1?'':'s'} · same work item`;
  document.getElementById('taskListParentHint').textContent=n===1?'1 task':`${n} tasks · executed top to bottom`;
};})(renderDrawerPlan);

// Moved New task contributes its single item, then its standalone Board identity is retired.
document.getElementById('confirmAddPlanTask').onclick=()=>{
  const owner=taskMap[addPlanOwnerId];if(!owner||!taskEditable(owner))return;
  if(batchParentTaskId!==owner.id)setPlanDraftForTask(owner);
  if(addTaskMode==='create'){return}else{
    const source=taskMap[selectedMoveTaskId];
    if(!source||!eligibleMoveTasks(owner).some(t=>t.id===source.id)){showToast('Selected Task is no longer eligible');renderMoveTaskPicker();return}
    const sourceItem=cloneBatch(canonicalTaskItems(source))[0];
    const item=planItemDefaults(sourceItem,owner,batchDraft.length);item.originTaskId=source.id;item.originTaskTitle=source.title;
    batchDraft.push(item);delete taskMap[source.id];
    pushTaskHistory(owner,`Moved ${source.id} here · standalone Board identity retired`);
  }
  sequenceExpandedIndex=batchDraft.length-1;commitPlanDraft(owner,{markDirty:false});persistCurrentPresetFromTaskMap();
  closeModal('addPlanTaskModal');renderBoardFromMap();renderExecutionPlan(owner);openPlanDialog(owner.id);
  showToast(addTaskMode==='create'?'Task added':'New Task moved here');
};

// Workspace result uses item count, not a separate Task/List type flag.
renderWorkspaceResult=(function(base){return function(t){canonicalTaskItems(t);base(t);
  if(t.items.length>1){
    const section=document.getElementById('workspaceResultSection'),grid=document.getElementById('workspaceResultGrid'),state=document.getElementById('workspaceResultState'),hint=document.getElementById('workspaceResultHint');
    section.hidden=false;state.textContent=`${t.items.length} tasks`;hint.textContent='Each execution item resolves its own Main / Worktree workspace at run time.';
    grid.innerHTML='<span>Merge</span><strong>Handled per item result</strong><span>Cleanup</span><strong>Only after each worktree is merged or discarded</strong>';
    ['reviewChangesDemo','mergeChatDemo','mergeTaskDemo','cleanupWorktreeDemo'].forEach(id=>document.getElementById(id).disabled=true);
  }
};})(renderWorkspaceResult);

// Merge with Chat now navigates directly to the owning Project chat with merge context.
document.getElementById('mergeChatDemo').onclick=()=>{
  const t=taskMap[currentTaskId];if(!t)return;
  const target=projectMeta[t.project]?.branch||'main';
  document.getElementById('taskOverlay').classList.remove('open');closeModal('planModal');
  selectProject(t.project);showView('chat');
  const session=activeChat();
  session.messages.push(['user',`Review and merge ${t.id}: ${t.branch||'task branch'} → ${target}. Worktree: ${t.executionRoot||'—'}`]);
  session.messages.push(['assistant','已帶入 Task / branch / target / worktree context。這裡做 merge review；Runner Task 本身不會自動 merge。']);
  renderChatSession();showToast('Opened Project Chat with merge context');
};

// Ensure every Task opened after legacy handlers is normalized to the one-list model.
const canonicalListOpenTask=openTaskById;
openTaskById=function(id){const t=taskMap[id];if(t)canonicalTaskItems(t);canonicalListOpenTask(id);const current=taskMap[id];if(current){setPlanDraftForTask(current);renderDrawerPlan(current);renderWorkspaceResult(current)}};

// --- Project-scoped Chat sessions ---
const projectChats={};
const projectActiveChat={};
function cloneMessages(messages){return (messages||[]).map(x=>[x[0],x[1]])}
function ensureProjectChats(key=currentProjectKey){
  if(!projectChats[key]){
    if(key==='ai-task-runner'){
      projectChats[key]=chatSessions.map(s=>({id:s.id,name:s.name,messages:cloneMessages(s.messages)}));
      projectActiveChat[key]='design';
    }else{
      const id=`${key}-chat-1`;
      projectChats[key]=[{id,name:'Project Chat',messages:[['assistant',`這是 ${key} 的 Project Chat。這裡的對話與其他 Project 分開保存。`]]}];
      projectActiveChat[key]=id;
    }
  }
  return projectChats[key];
}
activeChat=function(){
  const sessions=ensureProjectChats(currentProjectKey),id=projectActiveChat[currentProjectKey];
  return sessions.find(x=>x.id===id)||sessions[0];
};
syncChatSessionSelect=function(){
  const sessions=ensureProjectChats(currentProjectKey),select=document.getElementById('chatPreset'),id=projectActiveChat[currentProjectKey];
  select.innerHTML=sessions.map(x=>`<option value="${x.id}" ${x.id===id?'selected':''}>${escapeHtml(x.name)}</option>`).join('');
};
renderChatSession=function(){
  syncChatSessionSelect();
  const session=activeChat(),box=document.getElementById('chatMessages');box.innerHTML='';
  (session?.messages||[]).forEach(([who,body])=>{const el=document.createElement('div');el.className='msg '+who;el.innerHTML=(who==='assistant'?'<div class="msgmeta"><span class="avatar">AI</span>Assistant</div>':'<div class="msgmeta">You</div>')+escapeHtml(body);box.appendChild(el)});
  if(!(session?.messages||[]).length)box.innerHTML='<div class="empty-panel"><div><strong>New Chat</strong><br><br>這個 session 只屬於目前 Project。</div></div>';
  box.scrollTop=box.scrollHeight;
};
document.getElementById('chatPreset').onchange=e=>{projectActiveChat[currentProjectKey]=e.target.value;renderChatSession()};
document.getElementById('newChat').onclick=()=>{
  const sessions=ensureProjectChats(currentProjectKey),id=`${currentProjectKey}-chat-${++chatSequence}`;
  sessions.unshift({id,name:`New Chat ${chatSequence}`,messages:[]});projectActiveChat[currentProjectKey]=id;renderChatSession();document.getElementById('chatInput').focus();showToast('New Project Chat');
};
document.getElementById('renameChatConfirm').onclick=()=>{
  const value=document.getElementById('renameChatInput').value.trim();if(!value){showToast('Chat name 不可空白');return}
  activeChat().name=value;closeModal('renameChatModal');renderChatSession();showToast('Chat renamed');
};
document.getElementById('chatSend').onclick=()=>{
  const input=document.getElementById('chatInput'),textValue=input.value.trim();if(!textValue)return;
  const session=activeChat();session.messages.push(['user',textValue]);
  const reply=/task|執行|run/i.test(textValue)?'若要長時間執行，可用「建立 Task」把目前內容帶到 Tasks。':'收到。這則訊息只保存在目前 Project 的 Chat session。';
  session.messages.push(['assistant',reply]);input.value='';renderChatSession();
};

// Project-aware navigation refreshes Chat immediately.
selectProject=(function(base){return function(key){
  base(key);ensureProjectChats(key);
  document.getElementById('chatProjectTitle').textContent=key;
  document.getElementById('chatProjectLine').textContent=`${projectMeta[key].path} · Project Chat`;
  document.getElementById('tasksProjectLine').textContent=`${projectMeta[key].path} · ordered tasks`;
  if(document.getElementById('view-chat').classList.contains('active'))renderChatSession();
};})(selectProject);

// Parent Task has no single workspace when it owns multiple tasks.
workspaceName=(function(base){return function(t){
  const items=canonicalTaskItems(t);if(items.length>1)return 'Per-task workspaces';return base(t);
};})(workspaceName);

// Remove legacy type words from card/Drawer presentation.
taskCardHtml=(function(base){return function(t){
  canonicalTaskItems(t);
  let html=base(t).replace('Task List','Tasks').replace('Multi-step','Per-task workspaces');
  if(taskUsesWorktree(t)){
    html=html.replace('class="taskcard ','class="taskcard worktree-card ');
    html=html.replace('<div class="cardmeta">','<div class="cardmeta"><span class="tag worktree-highlight">WORKTREE</span>');
  }
  return html;
};})(taskCardHtml);

// --- Simplified Task editor: one vertical flow, advanced prompt sources on demand ---
function simpleModeOptions(value,items){return items.map(([k,l])=>`<option value="${k}" ${value===k?'selected':''}>${l}</option>`).join('')}
function newTaskPromptBodySimple(){
  if(newTaskDraft.goalMode==='file')return `<div class="pathrow"><input id="taskGoalFile" value="${escapeAttr(newTaskDraft.goalFile)}" placeholder="Prompt / goal file path"><button class="mini-btn" type="button" id="taskPickGoal">Choose file</button></div>`;
  if(newTaskDraft.goalMode==='asset')return `<div class="pathrow"><select id="taskGoalAsset">${assetOptions(newTaskDraft.goalAsset)}</select><button class="mini-btn" type="button" data-view-prompts-task>Open Prompts</button></div>`;
  return `<textarea id="taskPromptInline" class="primary-task-prompt" placeholder="Describe what this task should do…">${escapeHtml(newTaskDraft.prompt)}</textarea>`;
}
function newTaskAiBodySimple(){
  if(newTaskDraft.aiMode==='file')return `<div class="pathrow"><input id="taskAiFile" value="${escapeAttr(newTaskDraft.aiFile)}" placeholder="AI validator prompt file"><button class="mini-btn" type="button" id="taskPickAi">Choose file</button></div>`;
  if(newTaskDraft.aiMode==='asset')return `<div class="pathrow"><select id="taskAiAsset">${assetOptions(newTaskDraft.aiAsset)}</select><button class="mini-btn" type="button" data-view-prompts-task>Open Prompts</button></div>`;
  if(newTaskDraft.aiMode==='inline')return `<textarea id="taskAiInline" placeholder="Only add instructions that differ from the workflow default">${escapeHtml(newTaskDraft.aiPrompt)}</textarea>`;
  return `<div class="compact-default-value"><strong>Workflow default</strong><span>No override prompt</span></div>`;
}
renderNewTaskSources=function(){
  const workflow=document.getElementById('newTaskWorkflow').value,caps=workflowCaps(workflow);
  document.getElementById('newTaskWorkflowCaps').innerHTML=workflowCapsHtml(workflow);
  document.getElementById('newTaskPromptSource').innerHTML=`
    <div class="source-card simple-source-card">
      <div class="source-head simple-source-head"><div><strong>Task Prompt</strong><small>What should this task do?</small></div><select class="simple-source-select" id="taskGoalModeSelect">${simpleModeOptions(newTaskDraft.goalMode,[['inline','Write'],['file','Use file'],['asset','Use Prompt asset']])}</select></div>
      <div class="source-body">${newTaskPromptBodySimple()}</div>
    </div>`;
  const rows=[];
  if(caps.file)rows.push(`<div class="source-card simple-source-card"><div class="source-head simple-source-head"><div><strong>File Validator</strong><small>Required by this workflow</small></div><span class="cap-chip">Required</span></div><div class="source-body"><div class="pathrow"><input id="taskValidatorFile" value="${escapeAttr(newTaskDraft.validator)}" placeholder="Python validator path"><button class="mini-btn" type="button" id="taskPickValidator">Choose file</button></div></div></div>`);
  if(caps.ai)rows.push(`<div class="source-card simple-source-card"><div class="source-head simple-source-head"><div><strong>AI Validation</strong><small>Use workflow default unless you really need an override</small></div><select class="simple-source-select" id="taskAiModeSelect">${simpleModeOptions(newTaskDraft.aiMode,[['default','Workflow default'],['inline','Override text'],['file','Override file'],['asset','Prompt asset']])}</select></div><div class="source-body">${newTaskAiBodySimple()}</div></div>`);
  document.getElementById('newTaskValidationSource').innerHTML=rows.length?`<div class="validation-stack">${rows.join('')}</div>`:'<div class="validation-empty">This workflow needs no extra validation input.</div>';
  document.getElementById('taskGoalModeSelect').onchange=e=>{captureNewTaskSources();newTaskDraft.goalMode=e.target.value;renderNewTaskSources()};
  document.getElementById('taskAiModeSelect')?.addEventListener('change',e=>{captureNewTaskSources();newTaskDraft.aiMode=e.target.value;renderNewTaskSources()});
  document.getElementById('taskPickGoal')?.addEventListener('click',()=>openPathPicker(-1,'goalFile','goal','task'));
  document.getElementById('taskPickValidator')?.addEventListener('click',()=>openPathPicker(-1,'validator','validator','task'));
  document.getElementById('taskPickAi')?.addEventListener('click',()=>openPathPicker(-1,'aiFile','ai','task'));
  document.querySelectorAll('[data-view-prompts-task]').forEach(b=>b.onclick=()=>{closeModal('newTaskModal');showView('prompts');showToast('Prompt assets are managed in Prompts')});
  renderNewTaskWorkspace();
};

function planPromptBodySimple(x,i){
  if(x.goalMode==='file')return `<div class="pathrow"><input data-plan-item="${i}" data-plan-field="goalFile" value="${escapeAttr(x.goalFile||'')}" placeholder="Prompt / goal file path"><button class="mini-btn" type="button" data-plan-pick="${i}" data-plan-pick-field="goalFile" data-plan-pick-kind="goal">Choose file</button></div>`;
  if(x.goalMode==='asset')return `<div class="pathrow"><select data-plan-item="${i}" data-plan-field="goalAsset">${assetOptions(x.goalAsset)}</select><button class="mini-btn" type="button" data-plan-view-prompts="1">Open Prompts</button></div>`;
  return `<textarea data-plan-item="${i}" data-plan-field="prompt" class="primary-task-prompt" placeholder="Describe what this task should do…">${escapeHtml(x.prompt||'')}</textarea>`;
}
function planAiBodySimple(x,i){
  if(x.aiMode==='file')return `<div class="pathrow"><input data-plan-item="${i}" data-plan-field="aiFile" value="${escapeAttr(x.aiFile||'')}" placeholder="AI validator prompt file"><button class="mini-btn" type="button" data-plan-pick="${i}" data-plan-pick-field="aiFile" data-plan-pick-kind="ai">Choose file</button></div>`;
  if(x.aiMode==='asset')return `<div class="pathrow"><select data-plan-item="${i}" data-plan-field="aiAsset">${assetOptions(x.aiAsset)}</select><button class="mini-btn" type="button" data-plan-view-prompts="1">Open Prompts</button></div>`;
  if(x.aiMode==='inline')return `<textarea data-plan-item="${i}" data-plan-field="aiPrompt" placeholder="Only add instructions that differ from the workflow default">${escapeHtml(x.aiPrompt||'')}</textarea>`;
  return `<div class="compact-default-value"><strong>Workflow default</strong><span>No override prompt</span></div>`;
}
planRowBody=function(x,i,editable){
  const caps=workflowCaps(x.workflow),rows=[];
  if(caps.file)rows.push(`<div class="source-card simple-source-card"><div class="source-head simple-source-head"><div><strong>File Validator</strong><small>Required by this workflow</small></div><span class="cap-chip">Required</span></div><div class="source-body"><div class="pathrow"><input data-plan-item="${i}" data-plan-field="validator" value="${escapeAttr(x.validator||'')}" placeholder="Python validator path"><button class="mini-btn" type="button" data-plan-pick="${i}" data-plan-pick-field="validator" data-plan-pick-kind="validator">Choose file</button></div></div></div>`);
  if(caps.ai)rows.push(`<div class="source-card simple-source-card"><div class="source-head simple-source-head"><div><strong>AI Validation</strong><small>Use workflow default unless an override is needed</small></div><select class="simple-source-select" data-plan-item="${i}" data-plan-field="aiMode">${simpleModeOptions(x.aiMode,[['default','Workflow default'],['inline','Override text'],['file','Override file'],['asset','Prompt asset']])}</select></div><div class="source-body">${planAiBodySimple(x,i)}</div></div>`);
  return `
    <div class="plan-basic-stack">
      <div class="field"><label>Project root</label><input data-plan-item="${i}" data-plan-field="project" value="${escapeAttr(x.project)}"></div>
      <div class="field"><label>Workflow</label><select data-plan-item="${i}" data-plan-field="workflow"><option ${x.workflow==='ralphy_ai_validate.yaml'?'selected':''}>ralphy_ai_validate.yaml</option><option ${x.workflow==='mixed.yaml'?'selected':''}>mixed.yaml</option><option ${x.workflow==='file.yaml'?'selected':''}>file.yaml</option><option ${x.workflow==='dynamic_handoff.yaml'?'selected':''}>dynamic_handoff.yaml</option></select></div>
    </div>
    <div class="workflow-caps">${workflowCapsHtml(x.workflow)}</div>
    <div class="source-card simple-source-card"><div class="source-head simple-source-head"><div><strong>Task Prompt</strong><small>Primary task instruction</small></div><select class="simple-source-select" data-plan-item="${i}" data-plan-field="goalMode">${simpleModeOptions(x.goalMode,[['inline','Write'],['file','Use file'],['asset','Prompt asset']])}</select></div><div class="source-body">${planPromptBodySimple(x,i)}</div></div>
    ${rows.length?`<div class="validation-stack">${rows.join('')}</div>`:''}`;
};

// Source-mode changes need to redraw only the selected item's editor body.
const simplifiedBindFullPlan=bindFullPlan;
bindFullPlan=function(t){
  simplifiedBindFullPlan(t);
  document.querySelectorAll('#planFormList select[data-plan-field="goalMode"],#planFormList select[data-plan-field="aiMode"]').forEach(el=>{
    el.onchange=()=>{const i=+el.dataset.planItem;if(!batchDraft[i])return;batchDraft[i][el.dataset.planField]=el.value;commitPlanDraft(t,{markDirty:t.status==='paused'&&i===batchState.index});renderFullPlan(t);renderDrawerPlan(t);renderBoardFromMap()};
  });
};

// --- Progressive disclosure for AI validation overrides ---
function aiOverrideHeadNew(){
  if(newTaskDraft.aiMode==='default')return '<button type="button" class="mini-btn" id="taskAiOverride">Override</button>';
  return `<div class="ai-override-actions"><select class="simple-source-select" id="taskAiModeSelect">${simpleModeOptions(newTaskDraft.aiMode,[['inline','Text'],['file','File'],['asset','Prompt asset']])}</select><button type="button" class="mini-btn" id="taskAiReset">Use default</button></div>`;
}
function aiOverrideHeadPlan(x,i){
  if(x.aiMode==='default')return `<button type="button" class="mini-btn" data-plan-ai-override="${i}">Override</button>`;
  return `<div class="ai-override-actions"><select class="simple-source-select" data-plan-item="${i}" data-plan-field="aiMode">${simpleModeOptions(x.aiMode,[['inline','Text'],['file','File'],['asset','Prompt asset']])}</select><button type="button" class="mini-btn" data-plan-ai-reset="${i}">Use default</button></div>`;
}
renderNewTaskSources=(function(){return function(){
  const workflow=document.getElementById('newTaskWorkflow').value,caps=workflowCaps(workflow);
  document.getElementById('newTaskWorkflowCaps').innerHTML=workflowCapsHtml(workflow);
  document.getElementById('newTaskPromptSource').innerHTML=`<div class="source-card simple-source-card"><div class="source-head simple-source-head"><div><strong>Task Prompt</strong><small>What should this task do?</small></div><select class="simple-source-select" id="taskGoalModeSelect">${simpleModeOptions(newTaskDraft.goalMode,[['inline','Write'],['file','Use file'],['asset','Prompt asset']])}</select></div><div class="source-body">${newTaskPromptBodySimple()}</div></div>`;
  const rows=[];
  if(caps.file)rows.push(`<div class="source-card simple-source-card"><div class="source-head simple-source-head"><div><strong>File Validator</strong><small>Required by this workflow</small></div><span class="cap-chip">Required</span></div><div class="source-body"><div class="pathrow"><input id="taskValidatorFile" value="${escapeAttr(newTaskDraft.validator)}" placeholder="Python validator path"><button class="mini-btn" type="button" id="taskPickValidator">Choose file</button></div></div></div>`);
  if(caps.ai)rows.push(`<div class="source-card simple-source-card"><div class="source-head simple-source-head"><div><strong>AI Validation</strong><small>${newTaskDraft.aiMode==='default'?'Workflow default':'Custom override'}</small></div>${aiOverrideHeadNew()}</div><div class="source-body">${newTaskAiBodySimple()}</div></div>`);
  document.getElementById('newTaskValidationSource').innerHTML=rows.length?`<div class="validation-stack">${rows.join('')}</div>`:'<div class="validation-empty">This workflow needs no extra validation input.</div>';
  document.getElementById('taskGoalModeSelect').onchange=e=>{captureNewTaskSources();newTaskDraft.goalMode=e.target.value;renderNewTaskSources()};
  document.getElementById('taskAiOverride')?.addEventListener('click',()=>{captureNewTaskSources();newTaskDraft.aiMode='inline';renderNewTaskSources()});
  document.getElementById('taskAiModeSelect')?.addEventListener('change',e=>{captureNewTaskSources();newTaskDraft.aiMode=e.target.value;renderNewTaskSources()});
  document.getElementById('taskAiReset')?.addEventListener('click',()=>{captureNewTaskSources();newTaskDraft.aiMode='default';newTaskDraft.aiPrompt='';newTaskDraft.aiFile='';renderNewTaskSources()});
  document.getElementById('taskPickGoal')?.addEventListener('click',()=>openPathPicker(-1,'goalFile','goal','task'));
  document.getElementById('taskPickValidator')?.addEventListener('click',()=>openPathPicker(-1,'validator','validator','task'));
  document.getElementById('taskPickAi')?.addEventListener('click',()=>openPathPicker(-1,'aiFile','ai','task'));
  document.querySelectorAll('[data-view-prompts-task]').forEach(b=>b.onclick=()=>{closeModal('newTaskModal');showView('prompts');showToast('Prompt assets are managed in Prompts')});
  renderNewTaskWorkspace();
};})();

planRowBody=(function(){return function(x,i,editable){
  const caps=workflowCaps(x.workflow),rows=[];
  if(caps.file)rows.push(`<div class="source-card simple-source-card"><div class="source-head simple-source-head"><div><strong>File Validator</strong><small>Required by this workflow</small></div><span class="cap-chip">Required</span></div><div class="source-body"><div class="pathrow"><input data-plan-item="${i}" data-plan-field="validator" value="${escapeAttr(x.validator||'')}" placeholder="Python validator path"><button class="mini-btn" type="button" data-plan-pick="${i}" data-plan-pick-field="validator" data-plan-pick-kind="validator">Choose file</button></div></div></div>`);
  if(caps.ai)rows.push(`<div class="source-card simple-source-card"><div class="source-head simple-source-head"><div><strong>AI Validation</strong><small>${x.aiMode==='default'?'Workflow default':'Custom override'}</small></div>${aiOverrideHeadPlan(x,i)}</div><div class="source-body">${planAiBodySimple(x,i)}</div></div>`);
  return `<div class="plan-basic-stack"><div class="field"><label>Project root</label><input data-plan-item="${i}" data-plan-field="project" value="${escapeAttr(x.project)}"></div><div class="field"><label>Workflow</label><select data-plan-item="${i}" data-plan-field="workflow"><option ${x.workflow==='ralphy_ai_validate.yaml'?'selected':''}>ralphy_ai_validate.yaml</option><option ${x.workflow==='mixed.yaml'?'selected':''}>mixed.yaml</option><option ${x.workflow==='file.yaml'?'selected':''}>file.yaml</option><option ${x.workflow==='dynamic_handoff.yaml'?'selected':''}>dynamic_handoff.yaml</option></select></div></div><div class="workflow-caps">${workflowCapsHtml(x.workflow)}</div><div class="source-card simple-source-card"><div class="source-head simple-source-head"><div><strong>Task Prompt</strong><small>Primary task instruction</small></div><select class="simple-source-select" data-plan-item="${i}" data-plan-field="goalMode">${simpleModeOptions(x.goalMode,[['inline','Write'],['file','Use file'],['asset','Prompt asset']])}</select></div><div class="source-body">${planPromptBodySimple(x,i)}</div></div>${rows.length?`<div class="validation-stack">${rows.join('')}</div>`:''}`;
};})();

bindFullPlan=(function(base){return function(t){
  base(t);
  document.querySelectorAll('[data-plan-ai-override]').forEach(b=>b.onclick=()=>{const i=+b.dataset.planAiOverride;if(!batchDraft[i])return;batchDraft[i].aiMode='inline';commitPlanDraft(t,{markDirty:t.status==='paused'&&i===batchState.index});renderFullPlan(t);renderDrawerPlan(t);renderBoardFromMap()});
  document.querySelectorAll('[data-plan-ai-reset]').forEach(b=>b.onclick=()=>{const i=+b.dataset.planAiReset;if(!batchDraft[i])return;batchDraft[i].aiMode='default';batchDraft[i].aiPrompt='';batchDraft[i].aiFile='';commitPlanDraft(t,{markDirty:t.status==='paused'&&i===batchState.index});renderFullPlan(t);renderDrawerPlan(t);renderBoardFromMap()});
};})(bindFullPlan);

// --- One canonical Task Editor for root task, list task creation, and list task editing ---
let taskItemSequence=1000;
let taskEditorContext={mode:'root-create',ownerId:null,index:null};
const baseUnifiedPlanItemDefaults=planItemDefaults;
planItemDefaults=function(x={},t=null,i=0){
  const y=baseUnifiedPlanItemDefaults(x,t,i);
  return {...y,
    itemId:x.itemId||x.item_id||`${t?.id||'draft'}-I${i+1}-${++taskItemSequence}`,
    title:x.title||x.itemTitle||'',
    workspacePolicy:x.workspacePolicy||x.workspace_policy||'auto',
    workspaceKind:x.workspaceKind||x.workspace_kind||'main',
    branch:x.branch||'',executionRoot:x.executionRoot||x.execution_root||'',
  };
};
itemTitle=(function(base){return function(item,index){return item?.title?.trim()||base(item,index)}})(itemTitle);
singleTaskItem=function(t){
  const p=t.promptSource||{};
  return planItemDefaults({
    title:(Array.isArray(t.items)&&t.items[0]?.title)||'',
    prompt:p.prompt||t.goal||t.title,goalMode:p.goalMode||'inline',goalFile:p.goalFile||'',goalAsset:p.goalAsset||'common/review.md',
    project:projectMeta[t.project]?.path||t.project,workflow:t.workflow&&t.workflow!=='Task List'?t.workflow:'ralphy_ai_validate.yaml',
    validatorMode:p.validator?'file':'none',validator:p.validator||'',aiMode:p.aiMode||'default',aiPrompt:p.aiPrompt||'',aiFile:p.aiFile||'',aiAsset:p.aiAsset||'common/ai_validator.md',
    workspacePolicy:t.workspacePolicy||'auto',workspaceKind:t.workspaceKind||'main',branch:t.branch||'',executionRoot:t.executionRoot||''
  },t,0);
};

commitPlanDraft=function(t,{markDirty=false}={}){
  if(!t)return;
  batchDraft=batchDraft.map((x,i)=>planItemDefaults(x,t,i));
  t.kind='task_list';t.items=cloneBatch(batchDraft);t.listItems=t.items;
  const count=t.items.length,x=t.items[0];
  t.progress=[Math.min(t.progress?.[0]||0,count),count];
  if(count===1){
    t.workflow=x.workflow;t.goal=x.prompt;t.project=Object.keys(projectMeta).find(k=>projectMeta[k].path===x.project)||t.project;
    t.promptSource={goalMode:x.goalMode,prompt:x.prompt,goalFile:x.goalFile,goalAsset:x.goalAsset,validator:x.validator,aiMode:x.aiMode,aiPrompt:x.aiPrompt,aiFile:x.aiFile,aiAsset:x.aiAsset};
    t.workspacePolicy=x.workspacePolicy;t.workspaceKind=x.workspaceKind;t.branch=x.branch;t.executionRoot=x.executionRoot;
  }else{
    t.workflow='Tasks';t.workspaceKind='per_item';t.workspacePolicy='per_item';t.branch='—';t.executionRoot='Per-task workspaces';t.goal=`${count} ordered tasks`;
  }
  const baseTags=(t.tags||[]).filter(x=>!/^\d+\s+tasks?$/.test(String(x))&&!['workflow','file validation','AI validation'].includes(x));
  t.tags=[`${count} task${count===1?'':'s'}`,...baseTags].slice(0,4);
  t.desc=count===1?'1 task':`${count} ordered tasks · ${runtimeLabel(t.runtime)}`;
  if(markDirty&&t.status==='paused'){t.configDirty=true;batchState.currentDirty=true;t.desc='Paused · current task changed · restart required.'}
};

function projectKeyFromPath(path, fallback=currentProjectKey){const found=Object.keys(projectMeta).find(k=>projectMeta[k].path===path);return found||(projectMeta[path]?path:fallback)}
function editorOwner(){return taskEditorContext.ownerId?taskMap[taskEditorContext.ownerId]:null}
function editorItemRef(){
  const owner=editorOwner();
  if(taskEditorContext.mode==='root-create')return `T-${taskSequence+1}`;
  return `${owner?.id||'T'}-I${(taskEditorContext.index??batchDraft.length)+1}`;
}
function blankTaskEditorDraft(){return {goalMode:'inline',prompt:'',goalFile:'',goalAsset:'common/review.md',validator:'',aiMode:'default',aiPrompt:'',aiFile:'',aiAsset:'common/ai_validator.md'}}
function loadTaskEditor(mode,{ownerId=null,index=null,fromChat='' }={}){
  if(mode==='root-create'){
    setTaskFormCreateMode();
    document.getElementById('createTaskConfirm').disabled=false;
  }
  taskEditorContext={mode,ownerId,index};
  const owner=ownerId?taskMap[ownerId]:null;
  let item=null;
  if(owner&&index!=null){if(batchParentTaskId!==owner.id)setPlanDraftForTask(owner);item=batchDraft[index]||null}
  if(mode==='edit-item'&&!item)return;
  newTaskDraft=item?{goalMode:item.goalMode,prompt:item.prompt,goalFile:item.goalFile,goalAsset:item.goalAsset,validator:item.validator,aiMode:item.aiMode,aiPrompt:item.aiPrompt,aiFile:item.aiFile,aiAsset:item.aiAsset}:blankTaskEditorDraft();
  if(fromChat)newTaskDraft.prompt=fromChat;
  newTaskWorkspaceMode=item?.workspacePolicy||'auto';
  const projectKey=item?projectKeyFromPath(item.project,owner?.project||currentProjectKey):(owner?.project||currentProjectKey);
  document.getElementById('newTaskProject').value=projectMeta[projectKey]?projectKey:currentProjectKey;
  document.getElementById('newTaskWorkflow').value=item?.workflow||'ralphy_ai_validate.yaml';
  document.getElementById('newTaskTitle').value=item?.title||'';
  document.getElementById('taskFormTitle').textContent=mode==='root-create'?'New Task':mode==='create-item'?'New task':'Edit task';
  document.getElementById('taskFormHelp').textContent=mode==='root-create'?'Create the first task. The Board item starts with items[0].':mode==='create-item'?`Add a task to ${owner?.title||'this list'} using the same editor.`:`Editing task ${(index??0)+1} with the same fields used at creation.`;
  document.getElementById('createTaskConfirm').textContent=mode==='edit-item'?'Save changes':'Create task';
  document.getElementById('editTaskScopeNote').hidden=true;
  document.getElementById('newTaskWorkflowField').hidden=false;document.getElementById('newTaskWorkflowCaps').hidden=false;
  document.querySelector('.workspace-selector-wrap').hidden=false;document.getElementById('newTaskPromptSource').hidden=false;document.getElementById('newTaskValidationSource').hidden=false;
  renderNewTaskSources();renderNewTaskWorkspace();openModal('newTaskModal');
}

renderNewTaskWorkspace=function(){
  const host=document.getElementById('newTaskWorkspace');if(!host)return;
  const project=document.getElementById('newTaskProject')?.value||currentProjectKey;
  const ref=editorItemRef(),busy=mainBusyTask(project),resolved=resolveTaskWorkspace(project,ref,newTaskWorkspaceMode);
  const option=(mode,title,desc,status,disabled=false)=>`<label class="workspace-option ${mode==='worktree'?'worktree-option':''} ${newTaskWorkspaceMode===mode?'selected':''} ${disabled?'disabled':''}"><input type="radio" name="workspaceMode" value="${mode}" ${newTaskWorkspaceMode===mode?'checked':''} ${disabled?'disabled':''}><strong>${title}</strong><small>${desc}</small><span class="workspace-status">${status}</span></label>`;
  const worktree=resolved.ok&&resolved.kind==='worktree';
  host.innerHTML=`<div class="workspace-options">
    ${option('auto','Auto','Use Main when available; create a Worktree when Main is busy.',busy?`Main busy → Worktree`:'Main available')}
    ${option('main','Main workspace','Use the project working tree directly.',busy?`Busy · ${busy.id}`:'Available',!!busy)}
    ${option('worktree','Isolated worktree','Create an isolated branch/path for this task.',`task/${ref}`)}
  </div><div class="workspace-preview ${worktree?'worktree-active':''}"><strong>${worktree?'WORKTREE · ISOLATED DEVELOPMENT':'Execution preview'}</strong><br>${resolved.ok?(worktree?`Branch · ${resolved.branch}<br>Path · ${resolved.root}<br>Changes stay isolated until merged.`:`Main · ${resolved.branch}<br>${resolved.root}`):resolved.reason}</div>`;
  host.querySelectorAll('input[name="workspaceMode"]').forEach(r=>r.onchange=()=>{newTaskWorkspaceMode=r.value;renderNewTaskWorkspace()});
};

function buildEditorItem(owner,index){
  captureNewTaskSources();
  const rawProject=document.getElementById('newTaskProject').value.trim(),workflow=document.getElementById('newTaskWorkflow').value,caps=workflowCaps(workflow);
  const title=document.getElementById('newTaskTitle').value.trim();
  let promptValue='';
  if(newTaskDraft.goalMode==='inline')promptValue=newTaskDraft.prompt.trim();
  else if(newTaskDraft.goalMode==='file')promptValue=`Prompt file · ${basename(newTaskDraft.goalFile)}`;
  else promptValue=`Prompt asset · ${newTaskDraft.goalAsset}`;
  if(newTaskDraft.goalMode==='inline'&&!newTaskDraft.prompt.trim()){showToast('Task Prompt 不可空白');return null}
  if(newTaskDraft.goalMode==='file'&&!newTaskDraft.goalFile.trim()){showToast('Prompt file is required');return null}
  if(caps.file&&!newTaskDraft.validator.trim()){showToast('This Workflow requires File Validator');return null}
  if(!rawProject){showToast('Project is required');return null}
  const projectKey=ensureProjectFromInput(rawProject);
  const resolved=resolveTaskWorkspace(projectKey,editorItemRef(),newTaskWorkspaceMode);if(!resolved.ok){showToast(resolved.reason);return null}
  return planItemDefaults({title,prompt:newTaskDraft.prompt||promptValue,goalMode:newTaskDraft.goalMode,goalFile:newTaskDraft.goalFile,goalAsset:newTaskDraft.goalAsset,
    project:projectMeta[projectKey]?.path||projectKey,workflow,validatorMode:caps.file?'file':'none',validator:newTaskDraft.validator,
    aiMode:newTaskDraft.aiMode,aiPrompt:newTaskDraft.aiPrompt,aiFile:newTaskDraft.aiFile,aiAsset:newTaskDraft.aiAsset,
    workspacePolicy:newTaskWorkspaceMode,workspaceKind:resolved.kind,branch:resolved.branch,executionRoot:resolved.root
  },owner,index||0);
}

document.getElementById('createTaskConfirm').onclick=()=>{
  const ctx=taskEditorContext;
  if(ctx.mode==='root-create'){
    const id='T-'+(++taskSequence),placeholder={id,project:document.getElementById('newTaskProject').value};
    const item=buildEditorItem(placeholder,0);if(!item){taskSequence--;return}
    const boardTitle=document.getElementById('newTaskTitle').value.trim()||planTitle(item,0).slice(0,72)||'New Task';
    const projectKey=projectKeyFromPath(item.project,currentProjectKey);
    const t={id,kind:'task_list',status:'new',title:boardTitle,runtime:'idle',desc:'1 task',tags:['1 task'],workflow:item.workflow,project:projectKey,progress:[0,1],elapsed:'—',stage:'Idle',session:'—',goal:item.prompt,
      items:[item],listItems:[item],promptSource:{goalMode:item.goalMode,prompt:item.prompt,goalFile:item.goalFile,goalAsset:item.goalAsset,validator:item.validator,aiMode:item.aiMode,aiPrompt:item.aiPrompt,aiFile:item.aiFile,aiAsset:item.aiAsset},
      workspacePolicy:item.workspacePolicy,workspaceKind:item.workspaceKind,branch:item.branch,executionRoot:item.executionRoot};
    taskMap[id]=t;closeModal('newTaskModal');persistCurrentPresetFromTaskMap();renderBoardFromMap();showToast(`Task created · ${item.workspacePolicy==='worktree'?'Worktree':item.workspacePolicy}`);openTaskById(id);return;
  }
  const owner=taskMap[ctx.ownerId];if(!owner||!taskEditable(owner))return;
  if(batchParentTaskId!==owner.id)setPlanDraftForTask(owner);
  const targetIndex=ctx.mode==='create-item'?batchDraft.length:ctx.index;
  const item=buildEditorItem(owner,targetIndex);if(!item)return;
  const markDirty=ctx.mode==='edit-item'&&owner.status==='paused'&&targetIndex===batchState.index;
  if(ctx.mode==='create-item'){batchDraft.push(item);sequenceExpandedIndex=-1;pushTaskHistory(owner,'Task added');}
  else{batchDraft[targetIndex]={...batchDraft[targetIndex],...item,itemId:batchDraft[targetIndex].itemId};pushTaskHistory(owner,`Task ${targetIndex+1} edited`)}
  commitPlanDraft(owner,{markDirty});
  if(owner.items.length===1&&item.title)owner.title=item.title;
  persistCurrentPresetFromTaskMap();closeModal('newTaskModal');renderBoardFromMap();renderExecutionPlan(owner);renderWorkspaceResult(owner);
  if(!document.getElementById('planModal').classList.contains('open'))openPlanDialog(owner.id);else renderFullPlan(owner);
  showToast(markDirty?'Saved · current task will restart':'Task saved');
};

// Suppress legacy New Task listeners and route root creation into the canonical editor.
// obsolete create-entry capture handler removed; final dropdown owns this entry.
document.getElementById('chatToTask').onclick=()=>{const textValue=document.getElementById('chatInput').value.trim();loadTaskEditor('root-create',{fromChat:textValue});document.getElementById('newTaskTitle').value=textValue?textValue.slice(0,72):''};

function workspaceLabelForItem(x){return itemUsesWorktree(x)?'WORKTREE':x.workspaceKind==='main'||x.workspacePolicy==='main'?'Main':'Auto'}
renderFullPlan=function(t){
  const host=document.getElementById('planFormList'),items=batchDraft.length?batchDraft:canonicalTaskItems(t),editable=taskEditable(t);
  document.getElementById('planPageTitle').textContent=t.title;
  document.getElementById('planPageMeta').textContent=`${t.id} · ${statusLabel(t.status)} · ${items.length} task${items.length===1?'':'s'}`;
  document.getElementById('planStatePill').textContent=editable?'Editable':(t.status==='ongoing'?'Pause to edit':'Read-only');
  document.getElementById('planTaskSummary').innerHTML=`<span>Project</span><strong>${escapeHtml(t.project)}</strong><span>Status</span><strong>${escapeHtml(statusLabel(t.status))}</strong><span>Runtime</span><strong>${escapeHtml(runtimeLabel(t.runtime))}</strong><span>Progress</span><strong>${t.progress?.[0]||0} / ${items.length}</strong>`;
  host.innerHTML=items.map((x,i)=>{
    const s=planStateFor(t,i,items.length),currentLocked=t.status==='paused'&&s.current,canEdit=editable&&!s.done,canRestructure=canEdit&&!currentLocked;
    return `<article class="plan-row-compact ${s.done?'done':''} ${s.current?'current':''}" data-plan-row="${i}"><div class="plan-row-head"><span class="plan-row-num">${i+1}</span><div class="plan-row-copy"><strong>${escapeHtml(planTitle(x,i))}</strong><small>${escapeHtml(basename(x.project))} · ${escapeHtml(x.workflow)}${x.originTaskId?` · moved ${escapeHtml(x.originTaskId)}`:''}</small></div><div class="plan-row-actions"><span class="plan-workspace-chip ${itemUsesWorktree(x)?'worktree':''}">${workspaceLabelForItem(x)}</span><span class="plan-row-state ${s.cls}">${escapeHtml(s.label)}</span><div class="plan-row-controls"><button type="button" data-task-item-edit="${i}" ${canEdit?'':'disabled'}>Edit</button><button type="button" data-plan-up="${i}" ${!canRestructure||i<=Math.max(0,batchState.index)?'disabled':''}>↑</button><button type="button" data-plan-down="${i}" ${!canRestructure||i>=items.length-1?'disabled':''}>↓</button><button type="button" data-plan-remove="${i}" ${!canRestructure||items.length<=1?'disabled':''}>×</button></div></div></div></article>`;
  }).join('');
  document.getElementById('planAddTask').disabled=!editable;document.getElementById('planEditYaml').disabled=!editable;
  host.querySelectorAll('[data-task-item-edit]').forEach(b=>b.onclick=()=>loadTaskEditor('edit-item',{ownerId:t.id,index:+b.dataset.taskItemEdit}));
  host.querySelectorAll('[data-plan-up]').forEach(b=>b.onclick=()=>{const i=+b.dataset.planUp;if(i<=batchState.index||i<1)return;[batchDraft[i-1],batchDraft[i]]=[batchDraft[i],batchDraft[i-1]];commitPlanDraft(t,{markDirty:false});renderFullPlan(t);renderDrawerPlan(t);renderBoardFromMap()});
  host.querySelectorAll('[data-plan-down]').forEach(b=>b.onclick=()=>{const i=+b.dataset.planDown;if(i<batchState.index||i>=batchDraft.length-1)return;[batchDraft[i+1],batchDraft[i]]=[batchDraft[i],batchDraft[i+1]];commitPlanDraft(t,{markDirty:false});renderFullPlan(t);renderDrawerPlan(t);renderBoardFromMap()});
  host.querySelectorAll('[data-plan-remove]').forEach(b=>b.onclick=()=>{const i=+b.dataset.planRemove;if(i<batchState.index||batchDraft.length<=1)return;batchDraft.splice(i,1);commitPlanDraft(t,{markDirty:false});persistCurrentPresetFromTaskMap();renderFullPlan(t);renderDrawerPlan(t);renderBoardFromMap()});
};

setAddTaskMode=function(mode){
  addTaskMode=mode;selectedMoveTaskId=null;
  document.querySelectorAll('[data-add-task-mode]').forEach(b=>b.classList.toggle('active',b.dataset.addTaskMode===mode));
  document.getElementById('addTaskCreatePanel').hidden=mode!=='create';document.getElementById('addTaskMovePanel').hidden=mode!=='move';
  document.getElementById('confirmAddPlanTask').textContent=mode==='create'?'Open editor':'Move here';
  document.getElementById('confirmAddPlanTask').disabled=false;renderMoveTaskPicker();
};
let addTaskReturnTarget='list';
function detectAddTaskReturnTarget(){
  if(document.getElementById('planModal').classList.contains('open'))return 'list';
  if(document.getElementById('taskOverlay').classList.contains('open'))return 'info';
  return 'list';
}
function renderAddTaskBackTarget(){
  const modal=document.getElementById('addPlanTaskModal'),label=addTaskReturnTarget==='info'?'Back to Info':'Back to Task List';
  const close=modal.querySelector('.modal-head .close'),back=modal.querySelector('.modal-foot [data-close-modal]');
  if(close){close.textContent='←';close.title=label;close.setAttribute('aria-label',label)}
  if(back)back.textContent=label;
}
function returnAfterAddTask(owner){
  if(!owner)return;
  if(addTaskReturnTarget==='info'){closeModal('planModal');openTaskById(owner.id);return}
  document.getElementById('taskOverlay').classList.remove('open');openPlanDialog(owner.id);
}
openAddTaskDialog=function(ownerId=currentTaskId){
  const owner=taskMap[ownerId];if(!owner||!taskEditable(owner)){showToast(owner?.status==='ongoing'?'Pause Task before editing':'Task is read-only');return}
  addTaskReturnTarget=detectAddTaskReturnTarget();addPlanOwnerId=ownerId;setAddTaskMode('create');renderAddTaskBackTarget();openModal('addPlanTaskModal');
};
function openCreateItemFromAdd(){
  const owner=taskMap[addPlanOwnerId];if(!owner)return;
  const returnTarget=addTaskReturnTarget;closeModal('addPlanTaskModal');
  loadTaskEditor('create-item',{ownerId:owner.id,index:canonicalTaskItems(owner).length,returnTarget});
}
document.getElementById('openUnifiedTaskEditor').onclick=openCreateItemFromAdd;
document.getElementById('confirmAddPlanTask').onclick=()=>{
  if(addTaskMode==='create'){openCreateItemFromAdd();return}
  const owner=taskMap[addPlanOwnerId],source=taskMap[selectedMoveTaskId];if(!owner||!source||!eligibleMoveTasks(owner).some(t=>t.id===source.id))return;
  if(batchParentTaskId!==owner.id)setPlanDraftForTask(owner);
  const sourceItem=cloneBatch(canonicalTaskItems(source))[0];sourceItem.originTaskId=source.id;sourceItem.originTaskTitle=source.title;
  batchDraft.push(planItemDefaults(sourceItem,owner,batchDraft.length));delete taskMap[source.id];commitPlanDraft(owner,{markDirty:false});pushTaskHistory(owner,`Moved ${source.id} here`);
  persistCurrentPresetFromTaskMap();closeModal('addPlanTaskModal');renderBoardFromMap();renderExecutionPlan(owner);returnAfterAddTask(owner);showToast('New Task moved here');
};
document.getElementById('drawerAddStep').onclick=()=>openAddTaskDialog(currentTaskId);document.getElementById('planAddTask').onclick=()=>openAddTaskDialog(currentTaskId);

document.getElementById('editTaskDemo').onclick=()=>{
  const t=taskMap[currentTaskId];if(!t||!taskEditable(t))return;
  const items=canonicalTaskItems(t);if(items.length===1)loadTaskEditor('edit-item',{ownerId:t.id,index:0});else openPlanDialog(t.id);
};
const oneEditorOpenTask=openTaskById;
openTaskById=function(id){
  oneEditorOpenTask(id);const t=taskMap[id];if(!t)return;const edit=document.getElementById('editTaskDemo'),items=canonicalTaskItems(t),editable=taskEditable(t);
  edit.disabled=!editable;edit.textContent=editable?(items.length===1?'Edit task':'Edit tasks'):(t.status==='ongoing'?'Pause to edit':'Read-only');
};

// --- Restore tag-based Prompt source switching in the one canonical Task Editor ---
renderNewTaskSources=function(){
  const workflow=document.getElementById('newTaskWorkflow').value,caps=workflowCaps(workflow);
  document.getElementById('newTaskWorkflowCaps').innerHTML=workflowCapsHtml(workflow);
  document.getElementById('newTaskPromptSource').innerHTML=`
    <div class="source-card simple-source-card">
      <div class="source-head simple-source-head">
        <div><strong>Task Prompt</strong><small>Choose how this task gets its prompt</small></div>
        ${sourceTabs(newTaskDraft.goalMode,[['inline','Write'],['file','File'],['asset','Asset']],'data-task-goal-mode')}
      </div>
      <div class="source-body">${newTaskPromptBodySimple()}</div>
    </div>`;
  const rows=[];
  if(caps.file)rows.push(`
    <div class="source-card simple-source-card">
      <div class="source-head simple-source-head"><div><strong>File Validator</strong><small>Required by this workflow</small></div><span class="cap-chip">Required</span></div>
      <div class="source-body"><div class="pathrow"><input id="taskValidatorFile" value="${escapeAttr(newTaskDraft.validator)}" placeholder="Python validator path"><button class="mini-btn" type="button" id="taskPickValidator">Choose file</button></div></div>
    </div>`);
  if(caps.ai)rows.push(`
    <div class="source-card simple-source-card">
      <div class="source-head simple-source-head">
        <div><strong>AI Validation</strong><small>${newTaskDraft.aiMode==='default'?'Workflow default':'Custom prompt source'}</small></div>
        ${sourceTabs(newTaskDraft.aiMode,[['default','Default'],['inline','Write'],['file','File'],['asset','Asset']],'data-task-ai-mode')}
      </div>
      <div class="source-body">${newTaskAiBodySimple()}</div>
    </div>`);
  document.getElementById('newTaskValidationSource').innerHTML=rows.length?`<div class="validation-stack">${rows.join('')}</div>`:'<div class="validation-empty">This workflow needs no extra validation input.</div>';

  document.querySelectorAll('[data-task-goal-mode]').forEach(b=>b.onclick=()=>{
    captureNewTaskSources();newTaskDraft.goalMode=b.dataset.sourceValue;renderNewTaskSources();
  });
  document.querySelectorAll('[data-task-ai-mode]').forEach(b=>b.onclick=()=>{
    captureNewTaskSources();newTaskDraft.aiMode=b.dataset.sourceValue;
    if(newTaskDraft.aiMode==='default'){newTaskDraft.aiPrompt='';newTaskDraft.aiFile=''}
    renderNewTaskSources();
  });
  document.getElementById('taskPickGoal')?.addEventListener('click',()=>openPathPicker(-1,'goalFile','goal','task'));
  document.getElementById('taskPickValidator')?.addEventListener('click',()=>openPathPicker(-1,'validator','validator','task'));
  document.getElementById('taskPickAi')?.addEventListener('click',()=>openPathPicker(-1,'aiFile','ai','task'));
  document.querySelectorAll('[data-view-prompts-task]').forEach(b=>b.onclick=()=>{closeModal('newTaskModal');showView('prompts');showToast('Prompt assets are managed in Prompts')});
  renderNewTaskWorkspace();
};

// --- Final unified model: every Board card is one Task List with items[0..N]. ---
let listNameMode='create';
let listNameTargetId=null;
canonicalTaskItems=function(t){
  if(!t)return [];
  let raw;
  if(Array.isArray(t.items))raw=t.items;
  else if(Array.isArray(t.listItems))raw=t.listItems;
  else raw=[singleTaskItem(t)];
  t.items=raw.map((x,i)=>planItemDefaults(x,t,i));
  t.listItems=t.items;t.kind='task_list';
  const count=t.items.length;
  const base=(t.tags||[]).filter(x=>!/^\d+\s+tasks?$/.test(String(x))&&x!=='Task List');
  t.tags=[`${count} task${count===1?'':'s'}`,...base].slice(0,4);
  t.progress=[Math.min(t.progress?.[0]||0,count),count];
  return t.items;
};
planItemsForTask=function(t){return cloneBatch(canonicalTaskItems(t))};
setPlanDraftForTask=function(t){
  if(!t)return;batchParentTaskId=t.id;batchDraft=cloneBatch(canonicalTaskItems(t));batchState=deriveStepState(t);
  if(sequenceExpandedIndex>=batchDraft.length)sequenceExpandedIndex=-1;
};
isSequenceTask=function(t){return canonicalTaskItems(t).length>1};

commitPlanDraft=function(t,{markDirty=false}={}){
  if(!t)return;
  batchDraft=batchDraft.map((x,i)=>planItemDefaults(x,t,i));
  t.kind='task_list';t.items=cloneBatch(batchDraft);t.listItems=t.items;
  const count=t.items.length,x=t.items[0];
  t.progress=[Math.min(t.progress?.[0]||0,count),count];
  if(count===0){
    t.workflow='—';t.goal='';t.workspacePolicy='none';t.workspaceKind='none';t.branch='—';t.executionRoot='—';
    t.desc='Empty task list';t.stage='Draft';t.session='—';
  }else if(count===1){
    t.workflow=x.workflow;t.goal=x.prompt;
    t.promptSource={goalMode:x.goalMode,prompt:x.prompt,goalFile:x.goalFile,goalAsset:x.goalAsset,validator:x.validator,aiMode:x.aiMode,aiPrompt:x.aiPrompt,aiFile:x.aiFile,aiAsset:x.aiAsset};
    t.workspacePolicy=x.workspacePolicy;t.workspaceKind=x.workspaceKind;t.branch=x.branch;t.executionRoot=x.executionRoot;
    t.desc='1 task';
  }else{
    t.workflow='Tasks';t.workspacePolicy='per_item';t.workspaceKind='per_item';t.branch='—';t.executionRoot='Per-task workspaces';t.goal=`${count} ordered tasks`;t.desc=`${count} ordered tasks · ${runtimeLabel(t.runtime)}`;
  }
  const keep=(t.tags||[]).filter(x=>!/^\d+\s+tasks?$/.test(String(x)));t.tags=[`${count} task${count===1?'':'s'}`,...keep].slice(0,4);
  if(markDirty&&t.status==='paused'){t.configDirty=true;batchState.currentDirty=true;t.desc='Paused · current task changed · restart required.'}
};

function openListNameDialog(mode='create',t=null){
  listNameMode=mode;listNameTargetId=t?.id||null;
  document.getElementById('listNameModalTitle').textContent=mode==='create'?'New Task List':'Rename Task List';
  document.getElementById('listNameModalHelp').textContent=mode==='create'?'Create the list first. Project, Workflow, Prompt and Workspace belong to each task.':'Only the Board/List name changes. Task execution settings stay untouched.';
  document.getElementById('emptyListTitle').value=mode==='create'?'':(t?.title||'');
  document.getElementById('confirmEmptyList').textContent=mode==='create'?'Create Task List':'Save name';
  openModal('emptyListModal');setTimeout(()=>document.getElementById('emptyListTitle').focus(),0);
}
// obsolete create-entry capture handler removed; final dropdown owns this entry.
document.querySelectorAll('.coladd').forEach(b=>b.onclick=()=>document.getElementById('newTask').click());
document.getElementById('confirmEmptyList').onclick=()=>{
  const title=document.getElementById('emptyListTitle').value.trim();if(!title){showToast('List name is required');return}
  if(listNameMode==='rename'){
    const t=taskMap[listNameTargetId];if(!t||!taskEditable(t))return;t.title=title;pushTaskHistory(t,'Task List renamed');closeModal('emptyListModal');persistCurrentPresetFromTaskMap();renderBoardFromMap();openTaskById(t.id);showToast('Task List renamed');return;
  }
  const id='T-'+(++taskSequence);
  const t={id,kind:'task_list',status:'new',title,runtime:'idle',desc:'Empty task list',tags:['0 tasks'],workflow:'—',projectContext:currentProjectKey,project:currentProjectKey,progress:[0,0],elapsed:'—',stage:'Draft',session:'—',goal:'',items:[],listItems:[],workspacePolicy:'none',workspaceKind:'none',branch:'—',executionRoot:'—'};
  taskMap[id]=t;closeModal('emptyListModal');persistCurrentPresetFromTaskMap();renderBoardFromMap();openPlanDialog(id);showToast('Empty Task List created');
};

renderDrawerPlan=function(t){
  const host=document.getElementById('formList'),items=canonicalTaskItems(t),editable=taskEditable(t);
  document.getElementById('taskListEditHint').textContent=`${items.length} task${items.length===1?'':'s'}`;
  document.getElementById('taskListParentHint').textContent=items.length===0?'No tasks yet':items.length===1?'1 task':`${items.length} tasks · executed top to bottom`;
  document.getElementById('openFullPlan').hidden=false;document.getElementById('openFullPlan').textContent='Open list';
  if(items.length===0){host.innerHTML='<button class="empty-plan-cta" id="emptyPlanAddTask" type="button"><strong>No tasks yet</strong><span>Add the first task using the standard Task Editor →</span></button>';document.getElementById('emptyPlanAddTask').onclick=()=>openAddTaskDialog(t.id)}
  else if(items.length===1){const x=items[0],s=planStateFor(t,0,1);host.innerHTML=`<div class="drawer-plan-row ${s.current?'current':''} ${itemUsesWorktree(x)?'worktree-row':''}" data-drawer-item="0"><span class="n">1</span><div><strong>${escapeHtml(planTitle(x,0))}</strong><small>${escapeHtml(basename(x.project))} · ${escapeHtml(x.workflow)}</small></div><div class="drawer-task-actions"><span class="plan-workspace-chip ${itemUsesWorktree(x)?'worktree':''}">${workspaceLabelForItem(x)}</span><span class="state">${escapeHtml(s.label)}</span><button class="mini-btn" type="button" data-drawer-edit="0">Edit</button></div></div>`}
  else host.innerHTML=items.slice(0,4).map((x,i)=>{const s=planStateFor(t,i,items.length);return `<div class="drawer-plan-row ${s.done?'done':''} ${s.current?'current':''} ${itemUsesWorktree(x)?'worktree-row':''}" data-drawer-item="${i}"><span class="n">${i+1}</span><div><strong>${escapeHtml(planTitle(x,i))}</strong><small>${escapeHtml(basename(x.project))} · ${escapeHtml(x.workflow)}</small></div><div class="drawer-task-actions"><span class="plan-workspace-chip ${itemUsesWorktree(x)?'worktree':''}">${workspaceLabelForItem(x)}</span><span class="state">${escapeHtml(s.label)}</span><button class="mini-btn" type="button" data-drawer-edit="${i}" ${editable&&!s.done?'':'disabled'}>Edit</button></div></div>`}).join('')+(items.length>4?`<div class="steps-summary">+ ${items.length-4} more · Open list</div>`:'');
  host.querySelectorAll('[data-drawer-edit]').forEach(b=>b.onclick=e=>{e.stopPropagation();loadTaskEditor('edit-item',{ownerId:t.id,index:+b.dataset.drawerEdit})});
  host.querySelectorAll('[data-drawer-item]').forEach(r=>r.ondblclick=()=>{const i=+r.dataset.drawerItem,s=planStateFor(t,i,items.length);if(editable&&!s.done)loadTaskEditor('edit-item',{ownerId:t.id,index:i})});
  ['drawerAddStep','drawerAddExisting','stepsAdvanced'].forEach(id=>document.getElementById(id).disabled=!editable);
};

renderFullPlan=function(t){
  const host=document.getElementById('planFormList'),items=canonicalTaskItems(t),editable=taskEditable(t);
  document.getElementById('planPageTitle').textContent=t.title;
  document.getElementById('planPageMeta').textContent=`${t.id} · ${statusLabel(t.status)} · ${items.length} task${items.length===1?'':'s'}`;
  document.getElementById('planStatePill').textContent=editable?'Editable':(t.status==='ongoing'?'Pause to edit':'Read-only');
  document.getElementById('planTaskSummary').innerHTML=`<span>List</span><strong>${escapeHtml(t.title)}</strong><span>Status</span><strong>${escapeHtml(statusLabel(t.status))}</strong><span>Runtime</span><strong>${escapeHtml(runtimeLabel(t.runtime))}</strong><span>Progress</span><strong>${t.progress?.[0]||0} / ${items.length}</strong>`;
  if(items.length===0){host.innerHTML='<button class="empty-plan-cta large" id="planEmptyAddTask" type="button"><strong>No tasks yet</strong><span>+ Add first task</span></button>';document.getElementById('planEmptyAddTask').onclick=()=>openAddTaskDialog(t.id)}
  else host.innerHTML=items.map((x,i)=>{const s=planStateFor(t,i,items.length),currentLocked=t.status==='paused'&&s.current,canEdit=editable&&!s.done,canRestructure=canEdit&&!currentLocked;return `<article class="plan-row-compact ${s.done?'done':''} ${s.current?'current':''}" data-plan-row="${i}"><div class="plan-row-head"><span class="plan-row-num">${i+1}</span><div class="plan-row-copy"><strong>${escapeHtml(planTitle(x,i))}</strong><small>${escapeHtml(basename(x.project))} · ${escapeHtml(x.workflow)}${x.originTaskId?` · moved ${escapeHtml(x.originTaskId)}`:''}</small></div><div class="plan-row-actions"><span class="plan-workspace-chip ${itemUsesWorktree(x)?'worktree':''}">${workspaceLabelForItem(x)}</span><span class="plan-row-state ${s.cls}">${escapeHtml(s.label)}</span><div class="plan-row-controls"><button type="button" data-task-item-edit="${i}" ${canEdit?'':'disabled'}>Edit</button><button type="button" data-plan-up="${i}" ${!canRestructure||i<1||(t.status==='paused'&&i-1<=batchState.index)?'disabled':''}>↑</button><button type="button" data-plan-down="${i}" ${!canRestructure||i>=items.length-1?'disabled':''}>↓</button><button type="button" data-plan-remove="${i}" ${!canRestructure?'disabled':''}>×</button></div></div></div></article>`}).join('');
  host.querySelectorAll('[data-task-item-edit]').forEach(b=>b.onclick=e=>{e.stopPropagation();loadTaskEditor('edit-item',{ownerId:t.id,index:+b.dataset.taskItemEdit})});
  host.querySelectorAll('[data-plan-row]').forEach(r=>r.ondblclick=()=>{const i=+r.dataset.planRow,s=planStateFor(t,i,items.length);if(editable&&!s.done)loadTaskEditor('edit-item',{ownerId:t.id,index:i})});
  host.querySelectorAll('[data-plan-up]').forEach(b=>b.onclick=e=>{e.stopPropagation();const i=+b.dataset.planUp;if(i<1||(t.status==='paused'&&i-1<=batchState.index))return;[batchDraft[i-1],batchDraft[i]]=[batchDraft[i],batchDraft[i-1]];commitPlanDraft(t);persistCurrentPresetFromTaskMap();renderFullPlan(t);renderDrawerPlan(t);renderBoardFromMap()});
  host.querySelectorAll('[data-plan-down]').forEach(b=>b.onclick=e=>{e.stopPropagation();const i=+b.dataset.planDown;if((t.status==='paused'&&i<=batchState.index)||i>=batchDraft.length-1)return;[batchDraft[i+1],batchDraft[i]]=[batchDraft[i],batchDraft[i+1]];commitPlanDraft(t);persistCurrentPresetFromTaskMap();renderFullPlan(t);renderDrawerPlan(t);renderBoardFromMap()});
  host.querySelectorAll('[data-plan-remove]').forEach(b=>b.onclick=e=>{e.stopPropagation();const i=+b.dataset.planRemove;if(i<batchState.index)return;batchDraft.splice(i,1);commitPlanDraft(t);persistCurrentPresetFromTaskMap();renderFullPlan(t);renderDrawerPlan(t);renderBoardFromMap()});
  document.getElementById('planAddTask').disabled=!editable;document.getElementById('planEditYaml').disabled=!editable;
};

// Add first/next task always uses the exact same Task Editor.
function openCreateItemFromAdd(){const owner=taskMap[addPlanOwnerId];if(!owner)return;closeModal('addPlanTaskModal');loadTaskEditor('create-item',{ownerId:owner.id,index:canonicalTaskItems(owner).length})}

// Parent edit only renames the list; task editing lives on each task row.
document.getElementById('editTaskDemo').onclick=()=>{const t=taskMap[currentTaskId];if(t&&taskEditable(t))openListNameDialog('rename',t)};
const unifiedListOpenTask=openTaskById;
openTaskById=function(id){
  unifiedListOpenTask(id);const t=taskMap[id];if(!t)return;const items=canonicalTaskItems(t),editable=taskEditable(t),edit=document.getElementById('editTaskDemo');
  edit.disabled=!editable;edit.textContent=editable?'Rename list':(t.status==='ongoing'?'Pause to rename':'Read-only');
  const primary=document.getElementById('taskPrimaryDemo');
  if(items.length===0){primary.disabled=true;primary.textContent='Run';primary.title='Add at least one task before running'}else{primary.disabled=false;primary.title=''}
  setPlanDraftForTask(t);renderDrawerPlan(t);
};

// --- Isolated Task Editor: editing a task never shows Task List context. ---
const isolatedTaskEditorLoad=loadTaskEditor;
loadTaskEditor=function(mode,args={}){
  if(mode==='create-item'||mode==='edit-item'){
    closeModal('addPlanTaskModal');
    closeModal('planModal');
    document.getElementById('taskOverlay').classList.remove('open');
  }
  isolatedTaskEditorLoad(mode,args);
  document.getElementById('taskFormTitle').textContent=mode==='edit-item'?'Edit task':'New task';
  document.getElementById('taskFormHelp').textContent=mode==='edit-item'
    ?'Edit this task only. Project, Workflow, Prompt, Validation and Workspace belong to this task.'
    :'Configure this task. Project, Workflow, Prompt, Validation and Workspace belong to this task.';
  document.getElementById('editTaskScopeNote').hidden=true;
};

// Remove List-oriented wording from the canonical Task Editor itself.
document.querySelector('#newTaskModal .state-hint').innerHTML='Task settings are saved on this task only. Workflow capabilities determine which validation fields are shown.';

// --- Unified + New / column + dropdown: Task or Task List ---
const createTypeMenu=document.getElementById('createTypeMenu');
let createMenuAnchor=null;
function hideCreateTypeMenu(){createTypeMenu.hidden=true;createMenuAnchor=null}
function showCreateTypeMenu(anchor){
  if(typeof hideTaskContextMenu==='function')hideTaskContextMenu();createMenuAnchor=anchor;createTypeMenu.hidden=false;
  const r=anchor.getBoundingClientRect(),w=250,gap=6;
  let left=Math.min(window.innerWidth-w-10,Math.max(10,r.right-w));
  let top=r.bottom+gap;
  if(top+112>window.innerHeight)top=Math.max(10,r.top-112-gap);
  createTypeMenu.style.left=`${left}px`;createTypeMenu.style.top=`${top}px`;
}
function createEmptyTaskListAndOpen(){
  const id='T-'+(++taskSequence);
  const t={id,kind:'task_list',status:'new',title:'New Task List',runtime:'idle',desc:'Empty task list',tags:['0 tasks'],workflow:'—',projectContext:currentProjectKey,project:currentProjectKey,progress:[0,0],elapsed:'—',stage:'Draft',session:'—',goal:'',items:[],listItems:[],workspacePolicy:'none',workspaceKind:'none',branch:'—',executionRoot:'—'};
  taskMap[id]=t;persistCurrentPresetFromTaskMap();renderBoardFromMap();openPlanDialog(id);showToast('Task List created · add tasks when ready');
}
function handleCreateEntryClick(e){
  e.preventDefault();e.stopImmediatePropagation();
  if(!createTypeMenu.hidden&&createMenuAnchor===e.currentTarget){hideCreateTypeMenu();return}
  showCreateTypeMenu(e.currentTarget);
}
document.getElementById('newTask').addEventListener('click',handleCreateEntryClick,true);
document.querySelectorAll('.coladd').forEach(b=>b.addEventListener('click',handleCreateEntryClick,true));
createTypeMenu.querySelector('[data-create-type="task"]').onclick=()=>{hideCreateTypeMenu();setTaskFormCreateMode();loadTaskEditor('root-create')};
createTypeMenu.querySelector('[data-create-type="list"]').onclick=()=>{hideCreateTypeMenu();createEmptyTaskListAndOpen()};
document.addEventListener('click',e=>{if(!createTypeMenu.hidden&&!createTypeMenu.contains(e.target)&&e.target!==createMenuAnchor)hideCreateTypeMenu()});
window.addEventListener('resize',hideCreateTypeMenu);window.addEventListener('scroll',hideCreateTypeMenu,true);
