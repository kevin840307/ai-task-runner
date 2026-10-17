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
    return `<article class="plan-row ${expanded?'expanded':''} ${s.done?'done':''} ${s.current?'current':''}" data-plan-row="${i}"><div class="plan-row-head"><span class="plan-row-num">${i+1}</span><div class="plan-row-copy"><strong>${escapeHtml(planTitle(x,i))}</strong><small>${escapeHtml(basename(x.project))} · ${escapeHtml(x.workflow)}</small></div><div class="plan-row-actions"><span class="plan-row-state ${s.cls}">${escapeHtml(s.label)}</span><div class="plan-row-controls"><button type="button" data-plan-expand="${i}">${expanded?'Close':'Edit'}</button><button type="button" data-plan-remove="${i}" ${!canRestructure?'disabled':''}>×</button></div></div></div><div class="plan-row-body">${planRowBody(x,i,editable)}</div></article>`;
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
  taskPresets[currentPreset]=productTaskRecords().map(t=>cloneBatch([t])[0]);
}
// --- Dialog-first Plan UX + move-only New Task composition ---
let addPlanOwnerId=null;
let addTaskMode='create';
let selectedMoveTaskId=null;
function eligibleMoveTasks(owner){
  return productTaskRecords().filter(t=>t.id!==owner.id&&t.status==='new'&&t.runtime==='idle'&&!isSequenceTask(t)&&t.workspaceKind!=='batch');
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
function worktreeProjectKey(item,t){
  return Object.keys(projectMeta).find(key=>projectRefMatches(item.project,key))||(projectMeta[t?.project]?t.project:currentProjectKey);
}
function worktreeMergePreflight(t,item,index){
  if(item.mergeState==='merged')return {key:'merged',label:'Merged',detail:item.mergedCommit?`Merged · ${item.mergedCommit}`:'Merged',canMerge:false,canChat:false};
  const items=canonicalTaskItems(t),step=planStateFor(t,index,items.length),ready=(t.status==='closed'||t.runtime==='done')&&step.done;
  if(!ready)return {key:'blocked',label:'Blocked',detail:'Execution must complete before merge',canMerge:false,canChat:false};
  if(item.mergeConflict||item.mergeState==='conflict')return {key:'conflict',label:'Conflict',detail:'Conflict detected · use Merge Chat',canMerge:false,canChat:true};
  if(item.mergeBlockedReason)return {key:'blocked',label:'Blocked',detail:item.mergeBlockedReason,canMerge:false,canChat:true};
  return {key:'ready',label:'Ready',detail:'No conflicts detected',canMerge:true,canChat:true};
}
function workspaceResultGroups(t){
  const groups=new Map();
  canonicalTaskItems(t).forEach((item,index)=>{
    if(!itemUsesWorktree(item))return;
    const projectKey=worktreeProjectKey(item,t),meta=projectMeta[projectKey]||{},entry={item,index,projectKey,projectPath:meta.path||item.project||projectKey,target:meta.branch||'main'};
    if(!groups.has(projectKey))groups.set(projectKey,[]);
    groups.get(projectKey).push(entry);
  });
  return [...groups.entries()];
}
function updateWorktreeResult(t,index,patch){
  const items=canonicalTaskItems(t);if(!items[index])return;
  Object.assign(items[index],patch);t.items=items;t.listItems=t.items;
  if(items.length===1){t.mergeState=items[0].mergeState||'';t.mergedCommit=items[0].mergedCommit||''}
  persistCurrentPresetFromTaskMap();
}
function mergeWorktreeResult(t,index){
  const item=canonicalTaskItems(t)[index];if(!item)return;
  const preflight=worktreeMergePreflight(t,item,index);if(!preflight.canMerge)return;
  const projectKey=worktreeProjectKey(item,t),target=projectMeta[projectKey]?.branch||'main',commit=`merged-${t.id}-${index+1}`;
  updateWorktreeResult(t,index,{mergeState:'merged',mergedCommit:commit,mergeConflict:false,mergeBlockedReason:''});
  pushTaskHistory(t,`Task ${index+1} worktree merged · ${item.branch||'worktree'} → ${target}`);
  renderWorkspaceResult(t);showToast(`Merged · ${projectKey}`);
}
function mergeChatPrompt(t,item,index,projectKey,preflight){
  const meta=projectMeta[projectKey]||{},target=meta.branch||'main';
  return `Please review and merge this worktree into the target Project.

Task:
${t.id} · ${t.title}
Child task:
${index+1} · ${planTitle(item,index)}

Project:
${projectKey}
Project path:
${meta.path||item.project||'—'}

Worktree path:
${item.executionRoot||'—'}
Source branch:
${item.branch||'—'}
Target branch:
${target}

Merge preflight:
${preflight.label} · ${preflight.detail}

Please inspect the worktree changes and the current target branch, resolve conflicts safely when needed, preserve unrelated changes, follow the Project development rules, verify the merged result, and merge this worktree into the target Project.`;
}
function openWorktreeMergeChat(t,index){
  const item=canonicalTaskItems(t)[index];if(!item)return;
  const preflight=worktreeMergePreflight(t,item,index);if(!preflight.canChat)return;
  const projectKey=worktreeProjectKey(item,t);if(!projectMeta[projectKey])return;
  document.getElementById('taskOverlay').classList.remove('open');closeModal('planModal');
  selectProject(projectKey);showView('chat');
  const sessions=ensureProjectChats(projectKey),id=`${projectKey}-chat-${++chatSequence}`;
  sessions.unshift({id,name:`Merge ${t.id} · Task ${index+1}`,messages:[]});projectActiveChat[projectKey]=id;
  renderChatSession();
  const input=document.getElementById('chatInput');input.value=mergeChatPrompt(t,item,index,projectKey,preflight);resizeChatComposer();input.focus();input.setSelectionRange(input.value.length,input.value.length);
  showToast('Merge prompt prepared · not sent');
}
function renderWorkspaceResult(t){
  const section=document.getElementById('workspaceResultSection'),list=document.getElementById('workspaceResultList'),state=document.getElementById('workspaceResultState'),hint=document.getElementById('workspaceResultHint');
  const items=canonicalTaskItems(t),worktreeItems=items.filter(itemUsesWorktree),groups=workspaceResultGroups(t),banner=document.getElementById('drawerWorktreeBanner');
  if(banner){
    banner.hidden=worktreeItems.length===0;
    const detail=document.getElementById('drawerWorktreeBannerDetail');
    if(detail)detail.textContent=worktreeItems.length>1?`${worktreeItems.length} tasks use isolated Worktrees · merge is managed per Project below.`:'Isolated development · merge is managed in Workspace results.';
  }
  section.hidden=worktreeItems.length===0;
  if(!worktreeItems.length){state.textContent='No worktrees';list.innerHTML='';return}
  const statuses=[];
  list.innerHTML=groups.map(([projectKey,entries])=>{
    const meta=projectMeta[projectKey]||{},rows=entries.map(({item,index,target})=>{
      const preflight=worktreeMergePreflight(t,item,index);statuses.push(preflight.key);
      const mergeClass=preflight.canMerge?'btn primary':'btn',chatClass=!preflight.canMerge&&preflight.canChat?'btn primary':'btn';
      return `<article class="workspace-merge-row ${preflight.key}">
        <div class="workspace-merge-main">
          <div class="workspace-merge-title"><span class="workspace-merge-status ${preflight.key}">${escapeHtml(preflight.label)}</span><strong>${escapeHtml(planTitle(item,index))}</strong></div>
          <div class="workspace-merge-meta"><span>Source</span><b>${escapeHtml(item.branch||'—')}</b><span>Target</span><b>${escapeHtml(target)}</b><span>Path</span><b title="${escapeAttr(item.executionRoot||'')}">${escapeHtml(item.executionRoot||'—')}</b><span>Preflight</span><b>${escapeHtml(preflight.detail)}</b></div>
        </div>
        <div class="workspace-merge-actions">
          ${preflight.key==='merged'?'':`<button class="${mergeClass}" type="button" data-worktree-merge="${index}" ${preflight.canMerge?'':'disabled'} title="${preflight.canMerge?'Merge into target Project':escapeAttr(preflight.detail)}">Merge</button><button class="${chatClass}" type="button" data-worktree-merge-chat="${index}" ${preflight.canChat?'':'disabled'} title="${preflight.canChat?'Open a new Project Chat with a prepared merge prompt':escapeAttr(preflight.detail)}">Merge Chat</button>`}
        </div>
      </article>`;
    }).join('');
    return `<section class="workspace-project-group"><div class="workspace-project-head"><strong>${escapeHtml(projectKey)}</strong><small title="${escapeAttr(meta.path||'')}">${entries.length} worktree${entries.length===1?'':'s'} · ${escapeHtml(meta.branch||'main')}</small></div>${rows}</section>`;
  }).join('');
  const pending=statuses.filter(x=>x!=='merged').length,conflicts=statuses.filter(x=>x==='conflict').length;
  state.textContent=pending?`${pending} pending`:'Merged';
  hint.textContent=conflicts?`${conflicts} conflict${conflicts===1?'':'s'} · conflicted worktrees require Merge Chat.`:'Worktrees are grouped by Project. Merge is enabled only when preflight is safe.';
  list.querySelectorAll('[data-worktree-merge]').forEach(btn=>btn.onclick=()=>mergeWorktreeResult(t,+btn.dataset.worktreeMerge));
  list.querySelectorAll('[data-worktree-merge-chat]').forEach(btn=>btn.onclick=()=>openWorktreeMergeChat(t,+btn.dataset.worktreeMergeChat));
}

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
  return productTaskRecords().filter(t=>t.id!==owner.id&&t.status==='new'&&t.runtime==='idle'&&canonicalTaskItems(t).length===1);
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
const mockSystemPrompts=[
  {token:'@task',title:'AI decides Task or Task List',description:'Create one Task or multiple ordered Tasks; Mock randomly chooses for testing.',source:'Runner'},
  {token:'@task-single',title:'Create one Task',description:'Force the generated TaskDraft to contain exactly one Task.',source:'Runner'},
  {token:'@task-list',title:'Create Task List',description:'Force the generated TaskDraft to contain two or more ordered Tasks.',source:'Runner'},
  {token:'@workflow',title:'Generate Workflow',description:'Mock the existing Generate Workflow-style system prompt.',source:'Runner mock'},
  {token:'@project',title:'Project context',description:'Show the Project context bound to this Chat.',source:'Runner'}
];
const mockAgentCapabilities={
  qwen:[
    {token:'/skills',title:'Browse Skills',description:'Qwen Code skill registry / panel entry.',source:'Built-in'},
    {token:'/review',title:'Code review',description:'Mock project skill discovered by Qwen SkillManager.',source:'Mock skill'},
    {token:'/frontend-design',title:'Frontend design',description:'Mock project skill for UI/UX implementation.',source:'Mock skill'},
    {token:'/test',title:'Focused tests',description:'Mock project skill for focused verification.',source:'Mock skill'}
  ],
  opencode:[
    {token:'/git-release',title:'Git release',description:'Mock slash-enabled OpenCode SKILL.md capability.',source:'Mock skill'},
    {token:'/code-review',title:'Code review',description:'Mock OpenCode skill resolved for this agent.',source:'Mock skill'},
    {token:'/plan',title:'Plan',description:'Mock OpenCode custom/built-in command.',source:'Command'},
    {token:'/test',title:'Focused tests',description:'Mock OpenCode project command.',source:'Command'}
  ]
};
function chatAgentKey(session=activeChat()){return session?.agent||'qwen'}
function chatAgentLabel(key){return key==='opencode'?'OpenCode':'Qwen Code'}
function syncChatAgentControl(){
  const select=document.getElementById('chatAgent'),session=activeChat();if(!select||!session)return;
  select.value=chatAgentKey(session);
}
function agentCapabilityItems(){return mockAgentCapabilities[chatAgentKey()]||[]}
function chatAgentCommand(text){
  const match=String(text||'').match(/^\s*\/([^\s]+)(?:\s+([\s\S]*))?\s*$/);
  return match?{matched:true,token:'/'+match[1],args:String(match[2]||'').trim()}:{matched:false,token:'',args:''};
}
function chatSystemCommand(text){
  const match=String(text||'').match(/^\s*@([^\s]+)(?:\s+([\s\S]*))?\s*$/);
  return match?{matched:true,token:'@'+match[1].toLowerCase(),args:String(match[2]||'').trim()}:{matched:false,token:'',args:''};
}
function mockInvokeAgentCommand(session,command){
  const item=agentCapabilityItems().find(x=>x.token.toLowerCase()===command.token.toLowerCase());
  if(!item){session.messages.push(['assistant',`Mock ${chatAgentLabel(chatAgentKey())}: unknown Agent command ${command.token}.`]);return}
  session.messages.push(['assistant',`MOCK ${chatAgentLabel(chatAgentKey())} · ${item.token} selected${command.args?` · args: ${command.args}`:''}. Formal implementation will invoke the selected Agent's resolved command/skill capability, not a frontend copy of SKILL.md.`]);
}
function mockInvokeSystemPrompt(session,command){
  if(command.token==='@workflow'){session.messages.push(['assistant',`MOCK Runner · @workflow ${command.args||'<spec>'} would use the backend fixed Generate Workflow prompt.`]);return}
  if(command.token==='@project'){const meta=projectMeta[currentProjectKey]||{};session.messages.push(['assistant',`Project · ${currentProjectKey}\nPath · ${meta.path||'—'}\nBranch · ${meta.branch||'—'}`]);return}
  session.messages.push(['assistant',`Unknown Runner command ${command.token}. Type @ to see available system prompts.`]);
}
let composerSuggestionItems=[],composerSuggestionIndex=0;
function composerTrigger(){
  const input=document.getElementById('chatInput');if(!input)return null;
  const before=input.value.slice(0,input.selectionStart);
  const match=before.match(/^\s*([@\/])([a-zA-Z0-9:_-]*)$/);if(!match)return null;
  return {prefix:match[1],query:match[2].toLowerCase()};
}
function hideComposerSuggestions(){
  const pop=document.getElementById('composerSuggest');if(pop)pop.hidden=true;
  composerSuggestionItems=[];composerSuggestionIndex=0;resizeChatComposer();
}
function acceptComposerSuggestion(index=composerSuggestionIndex){
  const item=composerSuggestionItems[index],input=document.getElementById('chatInput');if(!item||!input)return;
  const suffix=input.value.slice(input.selectionStart).replace(/^\s+/,'');
  input.value=item.token+' '+suffix;input.focus();input.setSelectionRange(item.token.length+1,item.token.length+1);
  hideComposerSuggestions();resizeChatComposer();
}
function renderComposerSuggestions(){
  const pop=document.getElementById('composerSuggest'),list=document.getElementById('composerSuggestList'),title=document.getElementById('composerSuggestTitle'),hint=document.getElementById('composerSuggestHint');
  if(!pop||!list)return;
  const trigger=composerTrigger();if(!trigger){hideComposerSuggestions();return}
  const source=trigger.prefix==='@'?mockSystemPrompts:agentCapabilityItems(),q=trigger.query;
  composerSuggestionItems=source.filter(x=>!q||x.token.slice(1).toLowerCase().includes(q)||x.title.toLowerCase().includes(q));
  if(!composerSuggestionItems.length){hideComposerSuggestions();return}
  composerSuggestionIndex=Math.min(composerSuggestionIndex,composerSuggestionItems.length-1);
  title.textContent=trigger.prefix==='@'?'Runner prompts':`${chatAgentLabel(chatAgentKey())} · Skills / Commands`;
  hint.textContent=trigger.prefix==='@'?'@ = AI Task Runner':`/ = selected Agent · MOCK ${chatAgentLabel(chatAgentKey())}`;
  list.innerHTML=composerSuggestionItems.map((x,i)=>`<button class="composer-suggest-item ${i===composerSuggestionIndex?'active':''}" type="button" data-composer-suggest="${i}"><span class="composer-suggest-token">${escapeHtml(x.token)}</span><span class="composer-suggest-copy"><strong>${escapeHtml(x.title)}</strong><small>${escapeHtml(x.description)}</small></span><span class="composer-suggest-source">${escapeHtml(x.source)}</span></button>`).join('');
  list.querySelectorAll('[data-composer-suggest]').forEach(b=>b.onclick=()=>acceptComposerSuggestion(+b.dataset.composerSuggest));
  pop.hidden=false;resizeChatComposer();
}

function chatTaskCommand(text){
  const match=String(text||'').match(/^\s*@(task|task-single|task-list)(?:\s+([\s\S]*?))?\s*$/i);
  if(!match)return {matched:false,mode:'',spec:''};
  const token=match[1].toLowerCase(),mode=token==='task-single'?'single':token==='task-list'?'list':'auto';
  return {matched:true,mode,spec:String(match[2]||'').trim()};
}
function mockTaskDraftTitle(text){
  const cleaned=String(text||'').replace(/^(?:請|麻煩)?\s*(?:幫我)?\s*/i,'').trim();
  return (cleaned.split(/\n/).find(Boolean)||'AI generated Task').slice(0,72);
}
function mockTaskDraftWantsList(text){
  const bullets=String(text||'').split(/\n/).filter(x=>/^\s*(?:[-*]|\d+[.)、])\s+/.test(x));
  return bullets.length>=2||/(?:task\s*list|任務清單|多任務|多步驟|拆成|分成|依序.+(?:task|任務)|multiple\s+tasks)/i.test(String(text||''));
}
function mockTaskDraftItems(text,wantsList){
  const source=String(text||'').trim(),bullets=source.split(/\n/).map(x=>x.trim()).filter(x=>/^(?:[-*]|\d+[.)、])\s+/.test(x)).map(x=>x.replace(/^(?:[-*]|\d+[.)、])\s+/,'').trim()).filter(Boolean);
  if(wantsList&&bullets.length>=2)return bullets.map(x=>({title:x.slice(0,56),prompt:x}));
  if(wantsList)return [
    {title:'實作需求',prompt:source},
    {title:'測試與驗證',prompt:`針對「${source}」執行 focused verification，確認沒有影響既有行為與相鄰功能。`}
  ];
  return [{title:mockTaskDraftTitle(source),prompt:source}];
}
let chatDraftSequence=0;
function mockBuildChatTaskDraft(spec,projectKey=currentProjectKey,mode='auto'){
  const source=String(spec||'').trim(),wantsList=mode==='list'?true:mode==='single'?false:(Math.random()<.5);
  const workspacePolicy=/worktree/i.test(source)?'worktree':/(?:main workspace|主工作區|直接用 main)/i.test(source)?'main':'auto';
  const workflow=/dynamic\s*handoff/i.test(source)?'dynamic_handoff.yaml':/\bmixed\b/i.test(source)?'mixed.yaml':'ralphy_ai_validate.yaml';
  const id=`DRAFT-${++chatDraftSequence}`,placeholder={id,project:projectKey},raw=mockTaskDraftItems(source,wantsList);
  const items=raw.map((x,i)=>{
    const resolved=resolveTaskWorkspace(projectKey,`${id}-I${i+1}`,workspacePolicy);
    return planItemDefaults({title:x.title,prompt:x.prompt,goalMode:'inline',project:projectMeta[projectKey]?.path||projectKey,workflow,validatorMode:'none',validator:'',aiMode:'default',aiPrompt:'',aiFile:'',aiAsset:'common/ai_validator.md',workspacePolicy,workspaceKind:resolved.ok?resolved.kind:'main',branch:resolved.ok?resolved.branch:'',executionRoot:resolved.ok?resolved.root:''},placeholder,i);
  });
  const count=items.length,first=items[0];
  const model={id,_chatDraft:true,kind:'task_list',status:'new',title:mockTaskDraftTitle(source),runtime:'idle',desc:'Mock AI Task Draft',tags:[`${count} task${count===1?'':'s'}`],workflow:count===1?first.workflow:'Tasks',project:projectKey,projectContext:projectKey,progress:[0,count],elapsed:'—',stage:'Draft',session:'—',goal:count===1?first.prompt:`${count} ordered tasks`,items,listItems:items};
  if(count===1)Object.assign(model,{promptSource:{goalMode:first.goalMode,prompt:first.prompt,goalFile:first.goalFile,goalAsset:first.goalAsset,validator:first.validator,aiMode:first.aiMode,aiPrompt:first.aiPrompt,aiFile:first.aiFile,aiAsset:first.aiAsset},workspacePolicy:first.workspacePolicy,workspaceKind:first.workspaceKind,branch:first.branch,executionRoot:first.executionRoot});
  else Object.assign(model,{workspacePolicy:'per_item',workspaceKind:'per_item',branch:'—',executionRoot:'Per-task workspaces'});
  taskMap[id]=model;
  return {mock:true,originalSpec:source,projectKey,model,createdTaskId:''};
}
function discardChatTaskDraft(session,{render=true}={}){
  const draft=session?.taskDraft,model=draft?.model;
  if(model?._chatDraft&&taskMap[model.id]===model)delete taskMap[model.id];
  if(session)session.taskDraft=null;
  if(render)renderChatSession();
}
function openChatTaskDraftEditor(session){
  const draft=session?.taskDraft,model=draft?.model;if(!model||draft.createdTaskId)return;
  taskMap[model.id]=model;
  const items=canonicalTaskItems(model);
  if(items.length===1){loadTaskEditor('edit-item',{ownerId:model.id,index:0,returnTarget:'chat'});return}
  openPlanDialog(model.id);
}
function createTaskFromChatDraft(session){
  const draft=session?.taskDraft,model=draft?.model;if(!model||draft.createdTaskId)return;
  const items=canonicalTaskItems(model);
  if(!items.length){showToast('Task Draft 至少需要一個 Task');return}
  if(items.some(x=>x.goalMode==='inline'&&!String(x.prompt||'').trim())){showToast('Task Draft contains an empty Task Prompt');return}
  const oldId=model.id,id='T-'+(++taskSequence);
  for(let i=0;i<items.length;i++){
    const item=items[i],projectKey=projectKeyFromPath(item.project,model.projectContext||currentProjectKey),resolved=resolveTaskWorkspace(projectKey,`${id}-I${i+1}`,item.workspacePolicy||'auto');
    if(!resolved.ok){taskSequence--;showToast(resolved.reason);return}
    item.workspaceKind=resolved.kind;item.branch=resolved.branch;item.executionRoot=resolved.root;item.itemId=`${id}-I${i+1}`;
  }
  delete taskMap[oldId];model.id=id;delete model._chatDraft;model.status='new';model.runtime='idle';model.stage='Idle';model.progress=[0,items.length];
  model.tags=[`${items.length} task${items.length===1?'':'s'}`];model.desc=items.length===1?'1 task':`${items.length} ordered tasks`;
  if(items.length===1){
    const x=items[0],projectKey=projectKeyFromPath(x.project,model.projectContext||currentProjectKey);
    Object.assign(model,{project:projectKey,workflow:x.workflow,goal:x.prompt,promptSource:{goalMode:x.goalMode,prompt:x.prompt,goalFile:x.goalFile,goalAsset:x.goalAsset,validator:x.validator,aiMode:x.aiMode,aiPrompt:x.aiPrompt,aiFile:x.aiFile,aiAsset:x.aiAsset},workspacePolicy:x.workspacePolicy,workspaceKind:x.workspaceKind,branch:x.branch,executionRoot:x.executionRoot});
  }else Object.assign(model,{workflow:'Tasks',goal:`${items.length} ordered tasks`,workspacePolicy:'per_item',workspaceKind:'per_item',branch:'—',executionRoot:'Per-task workspaces'});
  taskMap[id]=model;draft.createdTaskId=id;persistCurrentPresetFromTaskMap();renderBoardFromMap();
  session.messages.push(['assistant',`${id} 已建立在 New；尚未執行。`]);renderChatSession();showToast(`Task created · ${id}`);
}
function renderChatTaskDraft(session,box){
  const draft=session?.taskDraft,model=draft?.model;if(!draft||!model)return;
  const card=document.createElement('section');card.className='chat-task-draft';
  const items=canonicalTaskItems(model);
  if(draft.createdTaskId){
    card.innerHTML=`<div class="chat-task-draft-head"><div><span class="chat-task-draft-badge chat-task-draft-created">CREATED</span><h3>${escapeHtml(model.title)}</h3></div><strong>${escapeHtml(draft.createdTaskId)}</strong></div><div class="chat-task-draft-meta"><span>${items.length>1?'Task List':'Task'}</span><span>${escapeHtml(model.projectContext||model.project)}</span><span>New · not running</span></div><div class="chat-task-draft-actions"><button class="btn" type="button" data-chat-draft-dismiss>Dismiss</button><button class="btn primary" type="button" data-chat-draft-open>Open Task</button></div>`;
  }else{
    card.innerHTML=`<div class="chat-task-draft-head"><div><span class="chat-task-draft-badge">MOCK AI · TASK DRAFT</span><h3>${escapeHtml(model.title)}</h3></div><span class="pill">${items.length>1?'Task List':'Task'}</span></div><div class="chat-task-draft-meta"><span>${escapeHtml(model.projectContext||model.project)}</span><span>${items.length} task${items.length===1?'':'s'}</span><span>Review before Create</span></div><div class="chat-task-draft-items">${items.map((x,i)=>`<div class="chat-task-draft-item"><strong>${i+1}. ${escapeHtml(planTitle(x,i))}</strong><p>${escapeHtml(x.prompt||'')}</p><small>${escapeHtml(basename(x.project))} · ${escapeHtml(x.workflow)} · ${escapeHtml(x.workspacePolicy||'auto')}</small></div>`).join('')}</div><div class="chat-task-draft-actions"><button class="btn" type="button" data-chat-draft-dismiss>Dismiss</button><button class="btn" type="button" data-chat-draft-edit>Edit</button><button class="btn primary" type="button" data-chat-draft-create>Create Task</button></div>`;
  }
  box.appendChild(card);
  card.querySelector('[data-chat-draft-edit]')?.addEventListener('click',()=>openChatTaskDraftEditor(session));
  card.querySelector('[data-chat-draft-create]')?.addEventListener('click',()=>createTaskFromChatDraft(session));
  card.querySelector('[data-chat-draft-dismiss]')?.addEventListener('click',()=>discardChatTaskDraft(session));
  card.querySelector('[data-chat-draft-open]')?.addEventListener('click',()=>{const t=taskMap[draft.createdTaskId];if(!t)return;showView('tasks');openPlanDialog(t.id)});
}
function generateChatTaskDraft(spec,mode='auto'){
  const session=activeChat();if(!session)return;
  const source=String(spec||'').trim(),usage=mode==='single'?'@task-single <spec>':mode==='list'?'@task-list <spec>':'@task <spec>';if(!source){session.messages.push(['assistant',`Usage: ${usage}`]);showToast(`Usage: ${usage}`);renderChatSession();return}
  if(/^mock:error\b/i.test(source)){session.messages.push(['assistant','Mock generate-task backend error · Task Draft was not created.']);showToast('Mock backend error');renderChatSession();return}
  if(/^mock:invalid\b/i.test(source)){session.messages.push(['assistant','Mock AI returned an invalid TaskDraft · validation failed closed.']);showToast('Invalid TaskDraft');renderChatSession();return}
  if(session.taskDraft&&!session.taskDraft.createdTaskId)discardChatTaskDraft(session,{render:false});
  const modeLabel=mode==='single'?'single Task':mode==='list'?'Task List':'AI/Mock auto';
  session.messages.push(['assistant',`Mock generate-task completed · ${modeLabel}. Review the Task Draft before creating it.`]);
  session.taskDraft=mockBuildChatTaskDraft(source,currentProjectKey,mode);renderChatSession();
}

renderChatSession=function(){
  syncChatSessionSelect();syncChatAgentControl();
  const session=activeChat(),box=document.getElementById('chatMessages');box.innerHTML='';
  (session?.messages||[]).forEach(([who,body])=>{const el=document.createElement('div');el.className='msg '+who;el.innerHTML=(who==='assistant'?'<div class="msgmeta"><span class="avatar">AI</span>Assistant</div>':'<div class="msgmeta">You</div>')+escapeHtml(body);box.appendChild(el)});
  renderChatTaskDraft(session,box);
  if(!(session?.messages||[]).length&&!session?.taskDraft)box.innerHTML='<div class="empty-panel"><div><strong>New Chat</strong><br><br>這個 session 只屬於目前 Project。</div></div>';
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
  const session=activeChat(),taskCommand=chatTaskCommand(textValue),agentCommand=chatAgentCommand(textValue),systemCommand=chatSystemCommand(textValue);
  session.messages.push(['user',textValue]);hideComposerSuggestions();
  if(taskCommand.matched)generateChatTaskDraft(taskCommand.spec,taskCommand.mode);
  else if(agentCommand.matched){mockInvokeAgentCommand(session,agentCommand);renderChatSession()}
  else if(systemCommand.matched){mockInvokeSystemPrompt(session,systemCommand);renderChatSession()}
  else{session.messages.push(['assistant','收到。一般 Chat 不會建立 Task。使用 @ 查看 Runner prompts；使用 / 查看目前 Agent 的 Skills / Commands。']);renderChatSession()}
  input.value='';resizeChatComposer();
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
    mergeState:x.mergeState||'',mergedCommit:x.mergedCommit||'',mergeConflict:!!x.mergeConflict,mergeBlockedReason:x.mergeBlockedReason||'',
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
    workspacePolicy:t.workspacePolicy||'auto',workspaceKind:t.workspaceKind||'main',branch:t.branch||'',executionRoot:t.executionRoot||'',
    mergeState:t.mergeState||'',mergedCommit:t.mergedCommit||'',mergeConflict:!!t.mergeConflict,mergeBlockedReason:t.mergeBlockedReason||''
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
document.getElementById('chatToTask').onclick=()=>{
  const input=document.getElementById('chatInput'),raw=input.value;
  if(!/^\s*@task\b/i.test(raw))input.value=raw.trim()?'@task '+raw:'@task ';
  input.focus();input.setSelectionRange(input.value.length,input.value.length);resizeChatComposer();
};
const chatInputForSuggestions=document.getElementById('chatInput');
chatInputForSuggestions.addEventListener('input',renderComposerSuggestions);
chatInputForSuggestions.addEventListener('click',renderComposerSuggestions);
chatInputForSuggestions.addEventListener('keydown',e=>{
  const pop=document.getElementById('composerSuggest');
  if(pop?.hidden||!composerSuggestionItems.length)return;
  if(e.key==='ArrowDown'||e.key==='ArrowUp'){
    e.preventDefault();e.stopImmediatePropagation();
    const delta=e.key==='ArrowDown'?1:-1;
    composerSuggestionIndex=(composerSuggestionIndex+delta+composerSuggestionItems.length)%composerSuggestionItems.length;
    renderComposerSuggestions();return;
  }
  if(e.key==='Enter'||e.key==='Tab'){
    e.preventDefault();e.stopImmediatePropagation();acceptComposerSuggestion();return;
  }
  if(e.key==='Escape'){e.preventDefault();e.stopImmediatePropagation();hideComposerSuggestions()}
},true);
document.getElementById('chatAgent').onchange=e=>{
  const session=activeChat();if(session)session.agent=e.target.value;
  renderComposerSuggestions();showToast(`Mock Agent · ${chatAgentLabel(e.target.value)}`);
};
document.addEventListener('click',e=>{if(!e.target.closest('.composerwrap'))hideComposerSuggestions()});


function workspaceLabelForItem(x){return itemUsesWorktree(x)?'WORKTREE':x.workspaceKind==='main'||x.workspacePolicy==='main'?'Main':'Auto'}
renderFullPlan=function(t){
  const host=document.getElementById('planFormList'),items=batchDraft.length?batchDraft:canonicalTaskItems(t),editable=taskEditable(t);
  document.getElementById('planPageTitle').textContent=t.title;
  document.getElementById('planPageMeta').textContent=`${t.id} · ${statusLabel(t.status)} · ${items.length} task${items.length===1?'':'s'}`;
  document.getElementById('planStatePill').textContent=editable?'Editable':(t.status==='ongoing'?'Pause to edit':'Read-only');
  document.getElementById('planTaskSummary').innerHTML=`<span>Project</span><strong>${escapeHtml(t.project)}</strong><span>Status</span><strong>${escapeHtml(statusLabel(t.status))}</strong><span>Runtime</span><strong>${escapeHtml(runtimeLabel(t.runtime))}</strong><span>Progress</span><strong>${t.progress?.[0]||0} / ${items.length}</strong>`;
  host.innerHTML=items.map((x,i)=>{
    const s=planStateFor(t,i,items.length),currentLocked=t.status==='paused'&&s.current,canEdit=editable&&!s.done,canRestructure=canEdit&&!currentLocked;
    return `<article class="plan-row-compact ${s.done?'done':''} ${s.current?'current':''}" data-plan-row="${i}"><div class="plan-row-head"><span class="plan-row-num">${i+1}</span><div class="plan-row-copy"><strong>${escapeHtml(planTitle(x,i))}</strong><small>${escapeHtml(basename(x.project))} · ${escapeHtml(x.workflow)}${x.originTaskId?` · moved ${escapeHtml(x.originTaskId)}`:''}</small></div><div class="plan-row-actions"><span class="plan-workspace-chip ${itemUsesWorktree(x)?'worktree':''}">${workspaceLabelForItem(x)}</span><span class="plan-row-state ${s.cls}">${escapeHtml(s.label)}</span><div class="plan-row-controls"><button type="button" data-task-item-edit="${i}" ${canEdit?'':'disabled'}>Edit</button><button type="button" data-plan-remove="${i}" ${!canRestructure||items.length<=1?'disabled':''}>×</button></div></div></div></article>`;
  }).join('');
  document.getElementById('planAddTask').disabled=!editable;document.getElementById('planEditYaml').disabled=!editable;
  host.querySelectorAll('[data-task-item-edit]').forEach(b=>b.onclick=()=>loadTaskEditor('edit-item',{ownerId:t.id,index:+b.dataset.taskItemEdit}));
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
  else host.innerHTML=items.map((x,i)=>{const s=planStateFor(t,i,items.length),currentLocked=t.status==='paused'&&s.current,canEdit=editable&&!s.done,canRestructure=canEdit&&!currentLocked;return `<article class="plan-row-compact ${s.done?'done':''} ${s.current?'current':''}" data-plan-row="${i}"><div class="plan-row-head"><span class="plan-row-num">${i+1}</span><div class="plan-row-copy"><strong>${escapeHtml(planTitle(x,i))}</strong><small>${escapeHtml(basename(x.project))} · ${escapeHtml(x.workflow)}${x.originTaskId?` · moved ${escapeHtml(x.originTaskId)}`:''}</small></div><div class="plan-row-actions"><span class="plan-workspace-chip ${itemUsesWorktree(x)?'worktree':''}">${workspaceLabelForItem(x)}</span><span class="plan-row-state ${s.cls}">${escapeHtml(s.label)}</span><div class="plan-row-controls"><button type="button" data-task-item-edit="${i}" ${canEdit?'':'disabled'}>Edit</button><button type="button" data-plan-remove="${i}" ${!canRestructure?'disabled':''}>×</button></div></div></div></article>`}).join('');
  host.querySelectorAll('[data-task-item-edit]').forEach(b=>b.onclick=e=>{e.stopPropagation();loadTaskEditor('edit-item',{ownerId:t.id,index:+b.dataset.taskItemEdit})});
  host.querySelectorAll('[data-plan-row]').forEach(r=>r.ondblclick=()=>{const i=+r.dataset.planRow,s=planStateFor(t,i,items.length);if(editable&&!s.done)loadTaskEditor('edit-item',{ownerId:t.id,index:i})});
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

// --- Canonical Task Editor: every Task create/edit entry uses the same overlay surface. ---
const isolatedTaskEditorLoad=loadTaskEditor;
loadTaskEditor=function(mode,args={}){
  if(mode==='create-item'||mode==='edit-item')closeModal('addPlanTaskModal');
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
