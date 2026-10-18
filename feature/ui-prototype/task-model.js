// --- Unified Task / Task List mock behavior ---
function defaultTaskListItems(projectKey){
  const root=projectMeta[projectKey]?.path||projectKey||'C:\\project';
  return [
    {prompt:'Implement the requested change',goalMode:'inline',goalFile:'',goalAsset:'common/review.md',project:root,workflow:'ralphy_ai_validate.yaml',validatorMode:'none',validator:'',aiMode:'default',aiPrompt:'',aiFile:'',aiAsset:'common/ai_validator.md'},
    {prompt:'Review and verify the result',goalMode:'asset',goalFile:'',goalAsset:'common/review.md',project:root,workflow:'ralphy_ai_validate.yaml',validatorMode:'none',validator:'',aiMode:'asset',aiPrompt:'',aiFile:'',aiAsset:'common/ai_validator.md'}
  ];
}

let newTaskKind='task';
function renderTaskKindUi(){
  document.querySelectorAll('[data-task-kind]').forEach(b=>b.classList.toggle('active',b.dataset.taskKind===newTaskKind));
  const isList=newTaskKind==='list';
  document.getElementById('newTaskWorkflowField').hidden=isList;
  document.getElementById('newTaskWorkflowCaps').hidden=isList;
  document.querySelector('.workspace-selector-wrap').hidden=isList;
  document.getElementById('newTaskPromptSource').hidden=isList;
  document.getElementById('newTaskValidationSource').hidden=isList;
  document.getElementById('newTaskListSetup').hidden=!isList;
  document.getElementById('createTaskConfirm').textContent=isList?'Create Task List':'Create Task';
}
document.querySelectorAll('[data-task-kind]').forEach(b=>b.onclick=()=>{
  newTaskKind=b.dataset.taskKind;
  if(newTaskKind==='list'&&document.getElementById('newTaskTitle').value==='New Task')document.getElementById('newTaskTitle').value='New Task List';
  renderTaskKindUi();
});

const originalNewTaskClick=()=>{};
document.getElementById('newTask').addEventListener('click',()=>{newTaskKind='task';renderTaskKindUi()});
document.querySelectorAll('.coladd').forEach(b=>b.addEventListener('click',()=>{newTaskKind='task';renderTaskKindUi()}));

function createTaskListParent(){
  const title=document.getElementById('newTaskTitle').value.trim();
  const project=document.getElementById('newTaskProject').value;
  if(!title){showToast('Task List title 不可空白');return null}
  const id='T-'+(++taskSequence),items=defaultTaskListItems(project);
  const t={id,kind:'list',status:'new',title,runtime:'idle',desc:`Task List · ${items.length} child RunRequests · ready to edit`,tags:[`${items.length} items`],workflow:'Task List',project,progress:[0,items.length],elapsed:'—',stage:'Draft',session:'batch',goal:'Execute an ordered Task List using the existing YAML List / RunRequest contract.',workspaceKind:'batch',branch:'—',executionRoot:'Child workspaces',listItems:cloneBatch(items)};
  taskMap[id]=t;renderBoardFromMap();
  return t;
}

document.getElementById('createTaskConfirm').onclick=()=>{
  if(newTaskKind==='list'){
    const t=createTaskListParent();if(!t)return;
    closeModal('newTaskModal');openTaskListEditor(t.id);showToast('Task List created · New');return;
  }
  captureNewTaskSources();
  let title=document.getElementById('newTaskTitle').value.trim(),workflow=document.getElementById('newTaskWorkflow').value,caps=workflowCaps(workflow);
  let goal='';
  if(newTaskDraft.goalMode==='inline')goal=newTaskDraft.prompt.trim();
  else if(newTaskDraft.goalMode==='file')goal=`goal_file: ${newTaskDraft.goalFile.trim()}`;
  else goal=`Prompt asset: ${newTaskDraft.goalAsset}`;
  if(!goal){showToast('Task Prompt 不可空白');return}
  if(caps.file&&!newTaskDraft.validator.trim()){showToast('這個 Workflow 需要 File Validator');return}
  if(!title)title=(newTaskDraft.prompt||goal).replace(/^goal_file:\s*/,'').slice(0,72)||'New Task';
  const id='T-'+(++taskSequence),project=document.getElementById('newTaskProject').value;
  const workspace=resolveTaskWorkspace(project,id,newTaskWorkspaceMode);
  if(!workspace.ok){taskSequence--;showToast(workspace.reason);return}
  const tags=['workflow'];if(caps.file)tags.push('file validation');if(caps.ai)tags.push('AI validation');
  const t={id,kind:'task',status:'new',title,runtime:'idle',desc:workspace.kind==='worktree'?'尚未開始；Run 時會使用 isolated worktree。':'尚未開始；Run 時使用 Main workspace。',tags,workflow,project,progress:[0,4],elapsed:'—',stage:'Idle',session:'—',goal,promptSource:{...newTaskDraft},workspacePolicy:newTaskWorkspaceMode,workspaceKind:workspace.kind,branch:workspace.branch,executionRoot:workspace.root};
  taskMap[id]=t;renderBoardFromMap();closeModal('newTaskModal');showToast(`已建立 mock Task · ${workspaceName(t)}`);openTaskById(id);
};

function syncTaskListDraftToParent(){
  const t=batchParentTaskId?taskMap[batchParentTaskId]:null;if(!t)return;
  t.kind='list';t.listItems=cloneBatch(batchDraft);t.progress=[Math.min(batchState.index,batchDraft.length),batchDraft.length];
  t.tags=[`${batchDraft.length} items`];
  t.executionRoot=`${batchDraft.length} child workspaces`;
  if(t.runtime==='idle')t.desc=`Task List · ${batchDraft.length} child RunRequests · ready to edit`;
}

function openTaskListEditor(id){
  const t=taskMap[id];if(!t||!(t.kind==='list'||t.workspaceKind==='batch'))return;
  document.getElementById('taskOverlay').classList.remove('open');
  batchParentTaskId=id;
  batchDraft=cloneBatch(t.listItems?.length?t.listItems:defaultTaskListItems(t.project));
  if(t.runtime==='running'||t.runtime==='recover'){batchState={status:'running',index:t.progress?.[0]||0,recovered:t.runtime==='recover',currentDirty:false}}
  else if(t.runtime==='stopped'||t.runtime==='failed'||t.status==='paused'){batchState={status:'stopped',index:t.progress?.[0]||0,recovered:false,currentDirty:false}}
  else if(t.runtime==='done'){batchState={status:'completed',index:batchDraft.length,recovered:false,currentDirty:false}}
  else{batchState={status:'idle',index:t.progress?.[0]||0,recovered:false,currentDirty:false}}
  document.getElementById('taskListEditorTitle').textContent=t.title;
  document.getElementById('taskListParentHint').textContent=`${t.id} · ${statusLabel(t.status)} · ${runtimeLabel(t.runtime)}`;
  renderBatchDraft();showView('yaml');
}
document.getElementById('backToTasks').onclick=()=>{syncTaskListDraftToParent();renderBoardFromMap();showView('tasks')};
// Legacy Edit List button removed; execution plan is edited in Overview.

const baseOpenTaskById=openTaskById;
openTaskById=function(id){
  baseOpenTaskById(id);
  const t=taskMap[id],isList=!!t&&(t.kind==='list'||t.workspaceKind==='batch');
  const tab=document.getElementById('drawerItemsTab');tab.hidden=!isList;
  const host=document.getElementById('drawerListItems');
  if(!isList){host.innerHTML='';return}
  const items=t.listItems||[];host.className='drawer-list-items';
  host.innerHTML=items.map((x,i)=>{
    const state=i<(t.progress?.[0]||0)?'PASS':(i===(t.progress?.[0]||0)&&['running','recover','stopped','failed'].includes(t.runtime)?runtimeLabel(t.runtime):'Waiting');
    return `<div class="drawer-list-item ${state==='PASS'?'done':''}"><span class="n">${i+1}</span><div><strong>${escapeHtml(itemTitle(x,i))}</strong><small>${escapeHtml(basename(x.project))} · ${escapeHtml(x.workflow)}</small></div><span class="state">${escapeHtml(state)}</span></div>`;
  }).join('')||'<div class="empty-panel">No items</div>';
};

const baseRenderDrawerActions=renderDrawerActions;
renderDrawerActions=function(t){
  baseRenderDrawerActions(t);
  if(t.kind==='list'||t.workspaceKind==='batch'){
    const p=document.getElementById('taskPrimaryDemo');
    if(t.runtime==='idle'){p.hidden=false;p.className='btn primary';p.textContent='Run'}
    else if(['running','recover'].includes(t.runtime)){p.hidden=false;p.className='btn primary';p.textContent='Pause'}
    else if(['stopped','attention','failed'].includes(t.runtime)){p.hidden=false;p.className='btn primary';p.textContent='Resume'}
  }
};

// Task List editor: Running is locked. Paused/New can edit unfinished items.
const baseRenderBatchDraft=renderBatchDraft;
const baseSyncBatchViews=syncBatchViews;
renderBatchDraft=function(){
  const saved={...batchState},timer=batchRunTimer;
  baseRenderBatchDraft();
  batchState=saved;batchRunTimer=timer;setBatchControls();syncTaskListDraftToParent();
};
setBatchControls=function(){
  const running=batchState.status==='running';
  document.getElementById('stopBatch').hidden=!running;
  document.getElementById('resumeBatch').hidden=batchState.status!=='stopped';
  document.getElementById('resetBatch').hidden=batchState.status!=='stopped';
  document.getElementById('runBatch').disabled=running||batchState.status==='stopped'||batchState.status==='completed';
  document.querySelectorAll('#formList input,#formList textarea,#formList select,#formList button').forEach(el=>el.disabled=running);
  document.getElementById('yamlEditor').disabled=running||(batchState.status==='stopped'&&batchState.index>0);
  document.querySelectorAll('[data-yamltab]').forEach(el=>el.disabled=false);
  document.querySelectorAll('.request[data-req]').forEach(row=>{
    const i=+row.dataset.req,completed=i<batchState.index,current=i===batchState.index;
    row.classList.toggle('completed-lock',completed);
    if(completed)row.querySelectorAll('input,textarea,select,button').forEach(el=>el.disabled=true);
    if(batchState.status==='stopped'&&current)row.querySelectorAll('[data-remove],[data-moveup],[data-movedown]').forEach(el=>el.disabled=true);
  });
  const add=document.getElementById('addRequest');if(add)add.disabled=running;
  const hint=document.getElementById('taskListEditHint');
  if(hint)hint.textContent=running?'Running · list locked':batchState.status==='stopped'?(batchState.index>0?'Paused · completed prefix locked; edit current/future items':'Paused · list editable'):'New / idle · list editable';
};

syncBatchViews=function(){
  baseSyncBatchViews();
  syncTaskListDraftToParent();
  document.querySelectorAll('.previewitem').forEach((row,i)=>{
    const chip=row.querySelector('.orderchip');
    if(i<batchState.index){row.classList.add('done');chip.textContent='PASS'}
    else if(i===batchState.index&&batchState.status==='running'){row.classList.add('active');chip.textContent=batchState.recovered?'Recovering':'Running'}
    else if(i===batchState.index&&batchState.status==='stopped'){chip.textContent=batchState.currentDirty?'Restart on resume':'Stopped'}
  });
};

const baseBindBatchForm=bindBatchForm;
bindBatchForm=function(){
  baseBindBatchForm();
  document.querySelectorAll('[data-item][data-field]').forEach(el=>{
    el.addEventListener(el.tagName==='SELECT'?'change':'input',()=>{
      const i=+el.dataset.item;
      if(batchState.status==='stopped'&&i===batchState.index){batchState.currentDirty=true;document.getElementById('batchLog').textContent+='\n[edit] current paused item changed · Resume will fresh restart this item'}
      syncTaskListDraftToParent();
    });
  });
  setBatchControls();
};

document.getElementById('batchPreset').onchange=e=>{
  if(batchState.status==='running'){showToast('Running 時不能替換 Task List');return}
  batchDraft=cloneBatch(batchPresets[e.target.value]||[]);
  if(batchState.status==='stopped'){batchState.currentDirty=true}
  renderBatchDraft();showToast(`套用 ${e.target.options[e.target.selectedIndex].text}`);
};

document.getElementById('runBatch').onclick=()=>{
  const errors=batchValidationErrors(batchDraft);if(!batchDraft.length)errors.push('Task List is empty');
  if(errors.length){document.getElementById('batchLog').textContent='[run] BLOCKED\n- '+errors.join('\n- ');showToast('請先修正 Task List');return}
  let t=batchParentTaskId?taskMap[batchParentTaskId]:null;
  if(!t){t=createTaskListParent();if(!t)return;batchParentTaskId=t.id}
  t.listItems=cloneBatch(batchDraft);
  clearInterval(batchRunTimer);document.querySelectorAll('.previewitem').forEach(i=>{i.classList.remove('active','done');i.querySelector('.orderchip').textContent='Waiting'});
  batchState={status:'running',index:0,recovered:false,currentDirty:false};setBatchControls();
  updateBatchParentTask('running','ongoing',0);
  document.getElementById('batchLog').textContent='[00:00] Task List started · parent Task is Ongoing\n[00:00] child RunRequests stay nested inside the Task';
  batchTick();batchRunTimer=setInterval(batchTick,900);
};

document.getElementById('stopBatch').onclick=()=>{
  if(batchState.status!=='running')return;clearInterval(batchRunTimer);batchRunTimer=null;batchState.status='stopped';batchState.currentDirty=false;setBatchControls();
  const item=document.querySelector(`.previewitem[data-step="${batchState.index}"]`);if(item)item.querySelector('.orderchip').textContent='Stopped';
  updateBatchParentTask('stopped','paused',batchState.index);syncTaskListDraftToParent();
  document.getElementById('batchLog').textContent+='\n[user] Task List paused · completed items locked, remaining items editable';showToast('Task List Paused · 可編輯剩餘 items');
};

document.getElementById('resumeBatch').onclick=()=>{
  if(batchState.status!=='stopped')return;
  const restart=batchState.currentDirty;batchState.status='running';batchState.recovered=false;batchState.currentDirty=false;setBatchControls();updateBatchParentTask('running','ongoing',batchState.index);
  document.getElementById('batchLog').textContent+=restart?'\n[user] Resume · current edited item starts with a fresh child run':'\n[user] Resume · continue current child durable state';
  batchRunTimer=setInterval(batchTick,900);showToast(restart?'Resume · current item fresh restart':'Task List resumed');
};

document.getElementById('resetBatch').onclick=()=>{
  if(batchState.status!=='stopped')return;batchState.currentDirty=false;batchState.recovered=false;
  const t=batchParentTaskId?taskMap[batchParentTaskId]:null;if(t){t.runtime='stopped';t.status='paused';t.stage=`Item ${batchState.index+1} ready to restart`;pushTaskHistory(t,'Current Task List item reset · completed prefix preserved')}
  setBatchControls();syncBatchViews();document.getElementById('batchLog').textContent+='\n[reset] current item reset · completed prefix preserved';showToast('Current item reset');
};

document.getElementById('backToTasks').onclick=()=>{syncTaskListDraftToParent();renderBoardFromMap();showView('tasks')};

let pendingTaskDeleteId=null;
function taskCanDelete(t){return !!t&&t.status!=='ongoing'&&!['running','recover'].includes(t.runtime)}
function deleteTaskConfirmed(id){
  const t=taskMap[id];if(!t)return;
  if(!taskCanDelete(t)){showToast('Ongoing Task 不能直接刪除，請先 Pause / Stop');return}
  if(id===batchParentTaskId){clearInterval(batchRunTimer);batchRunTimer=null;batchParentTaskId=null;batchState={status:'idle',index:0,recovered:false,currentDirty:false}}
  delete taskMap[id];persistCurrentPresetFromTaskMap();
  if(typeof closeTaskDrawerShell==='function')closeTaskDrawerShell({force:true,restoreFocus:false});else document.getElementById('taskOverlay').classList.remove('open');
  renderBoardFromMap();showToast('Task deleted');
}
function requestTaskDelete(id=currentTaskId){
  const t=taskMap[id];if(!t)return;
  if(!taskCanDelete(t)){showToast('Ongoing Task 不能直接刪除，請先 Pause / Stop');return}
  pendingTaskDeleteId=id;
  const items=canonicalTaskItems(t),worktrees=items.filter(itemUsesWorktree).length;
  document.getElementById('taskDeleteMeta').textContent=`${t.id} · ${t.title}`;
  document.getElementById('taskDeleteNote').innerHTML=`<strong>This cannot be undone.</strong><br>This removes the Task and its ${items.length} task${items.length===1?'':'s'} from the Board/history view.${worktrees?` <br>${worktrees} Worktree${worktrees===1?'':'s'} will not be merged automatically.`:''}`;
  openModal('taskDeleteModal');
}
document.getElementById('confirmTaskDelete').onclick=()=>{
  const id=pendingTaskDeleteId;pendingTaskDeleteId=null;closeModal('taskDeleteModal');
  if(id)deleteTaskConfirmed(id);
};
document.getElementById('deleteTaskDemo').onclick=()=>requestTaskDelete(currentTaskId);

// --- Sequence Composer: Task List is composed from the same Task configuration ---
let sequenceExpandedIndex=0;
let existingPickerContext=null;
function taskFormToListItem(){
  captureNewTaskSources();
  const projectKey=document.getElementById('newTaskProject').value;
  const project=projectMeta[projectKey]?.path||projectKey;
  return {
    prompt:newTaskDraft.prompt||document.getElementById('newTaskTitle').value.trim()||'Task',
    goalMode:newTaskDraft.goalMode,goalFile:newTaskDraft.goalFile,goalAsset:newTaskDraft.goalAsset,
    project,workflow:document.getElementById('newTaskWorkflow').value,
    validatorMode:newTaskDraft.validator?'file':'none',validator:newTaskDraft.validator,
    aiMode:newTaskDraft.aiMode,aiPrompt:newTaskDraft.aiPrompt,aiFile:newTaskDraft.aiFile,aiAsset:newTaskDraft.aiAsset
  };
}
function taskToListItem(t){
  const p=t.promptSource||{};
  return {
    prompt:p.prompt||t.goal||t.title,
    goalMode:p.goalMode||'inline',goalFile:p.goalFile||'',goalAsset:p.goalAsset||'common/review.md',
    project:projectMeta[t.project]?.path||t.project,workflow:t.workflow&&t.workflow!=='Task List'?t.workflow:'ralphy_ai_validate.yaml',
    validatorMode:p.validator?'file':'none',validator:p.validator||'',
    aiMode:p.aiMode||'default',aiPrompt:p.aiPrompt||'',aiFile:p.aiFile||'',aiAsset:p.aiAsset||'common/ai_validator.md'
  };
}
function createTaskListFromItems(items){
  const title=document.getElementById('newTaskTitle').value.trim()||'New Task List';
  const project=document.getElementById('newTaskProject').value;
  const id='T-'+(++taskSequence);
  const t={id,kind:'list',status:'new',title,runtime:'idle',desc:`Task List · ${items.length} tasks · ready to edit`,tags:[`${items.length} tasks`],workflow:'Task List',project,progress:[0,items.length],elapsed:'—',stage:'Draft',session:'batch',goal:'Execute an ordered sequence of Tasks using the existing RunRequest contract.',workspaceKind:'batch',branch:'—',executionRoot:'Child task workspaces',listItems:cloneBatch(items)};
  taskMap[id]=t;renderBoardFromMap();return t;
}
function defaultNextItem(projectKey){
  const root=projectMeta[projectKey]?.path||projectKey||'C:\\project';
  return {prompt:'Next task',goalMode:'inline',goalFile:'',goalAsset:'common/review.md',project:root,workflow:'ralphy_ai_validate.yaml',validatorMode:'none',validator:'',aiMode:'default',aiPrompt:'',aiFile:'',aiAsset:'common/ai_validator.md'};
}
function openExistingTaskPicker(context){
  existingPickerContext=context;
  const host=document.getElementById('existingTaskPicker');
  const candidates=Object.values(taskMap).filter(t=>t.kind!=='list'&&t.workspaceKind!=='batch');
  host.innerHTML=candidates.length?candidates.map(t=>`<button type="button" class="existing-task-option" data-existing-id="${t.id}"><div><strong>${escapeHtml(t.title)}</strong><small>${escapeHtml(t.id)} · ${escapeHtml(t.project)} · ${escapeHtml(t.workflow)}</small></div><span>${escapeHtml(runtimeLabel(t.runtime))}</span></button>`).join(''):'<div class="empty-panel">No standalone Tasks in this mock board.</div>';
  host.querySelectorAll('[data-existing-id]').forEach(b=>b.onclick=()=>{
    const source=taskMap[b.dataset.existingId],item=taskToListItem(source);if(!source)return;
    if(existingPickerContext==='new'){
      const first=taskFormToListItem(),t=createTaskListFromItems([first,item]);closeModal('newTaskModal');closeModal('existingTaskModal');sequenceExpandedIndex=1;openTaskListEditor(t.id);showToast('Task upgraded to Task List · existing Task copied as item 2');
    }else{
      batchDraft.push(item);sequenceExpandedIndex=batchDraft.length-1;closeModal('existingTaskModal');renderBatchDraft();showToast('Existing Task copied into sequence');
    }
  });
  openModal('existingTaskModal');
}
document.getElementById('addNextTaskFromNew').onclick=()=>{
  const first=taskFormToListItem(),next=defaultNextItem(document.getElementById('newTaskProject').value);
  const t=createTaskListFromItems([first,next]);closeModal('newTaskModal');sequenceExpandedIndex=1;openTaskListEditor(t.id);showToast('Task upgraded to Task List · Item 1 preserved');
};
document.getElementById('addExistingTaskFromNew').onclick=()=>openExistingTaskPicker('new');

function sequenceState(i){
  if(i<batchState.index)return ['PASS','pass'];
  if(i===batchState.index&&batchState.status==='running')return [batchState.recovered?'Recovering':'Running','running'];
  if(i===batchState.index&&batchState.status==='stopped')return [batchState.currentDirty?'Restart on resume':'Stopped','stopped'];
  if(i===batchState.index&&batchState.status==='failed')return ['Failed','stopped'];
  return ['Waiting',''];
}
renderBatchDraft=function(){
  const form=document.getElementById('formList');
  if(!batchDraft.length){
    form.innerHTML='<div class="empty-panel"><div><strong>No tasks in this sequence</strong><br><br>Add a new Task or copy an existing one.</div></div><div class="sequence-add-row"><button class="btn" id="addRequest">+ Add task</button><button class="btn ghost" id="addExistingSequence">Add existing</button></div>';
  }else{
    const rows=batchDraft.map((x,i)=>{
      const caps=workflowCaps(x.workflow),validation=[],state=sequenceState(i),expanded=i===sequenceExpandedIndex;
      if(caps.file)validation.push(`<div class="source-card"><div class="source-head"><div><strong>File Validator</strong><small>validator</small></div><span class="cap-chip">Required</span></div><div class="source-body"><div class="pathrow"><input data-item="${i}" data-field="validator" value="${escapeAttr(x.validator||'')}" placeholder="Python validator path"><button class="mini-btn" type="button" data-pick-index="${i}" data-pick-field="validator" data-pick-kind="validator">Choose</button></div></div></div>`);
      if(caps.ai)validation.push(`<div class="source-card"><div class="source-head"><div><strong>AI Validator Prompt</strong><small>ai_validator_prompt_file</small></div>${yamlSourceTabs(i,'aiMode',x.aiMode,[['default','Default'],['inline','Write'],['file','File'],['asset','Asset']])}</div><div class="source-body">${aiSourceBody(x,i)}</div></div>`);
      return `<div class="request sequence-item ${expanded?'expanded':''} ${i<batchState.index?'completed-lock':''} ${i===batchState.index&&batchState.status==='running'?'active-item':''}" data-req="${i}">
        <div class="reqhead"><span class="reqnum">${i+1}</span><div class="sequence-item-title"><strong>${escapeHtml(itemTitle(x,i))}</strong><small>${escapeHtml(basename(x.project))} · ${escapeHtml(x.workflow)}</small></div><div class="req-actions"><span class="sequence-state ${state[1]}">${state[0]}</span><button class="sequence-expand" type="button" data-expand="${i}">${expanded?'Collapse':'Edit'}</button><button data-moveup="${i}" title="Move up">↑</button><button data-movedown="${i}" title="Move down">↓</button><button data-remove="${i}" title="Remove">×</button></div></div>
        <div class="request-body"><div class="workflow-row"><div class="field"><label>Project root</label><input data-item="${i}" data-field="project" value="${escapeAttr(x.project)}"></div><div class="field"><label>Workflow</label><select data-item="${i}" data-field="workflow"><option ${x.workflow==='ralphy_ai_validate.yaml'?'selected':''}>ralphy_ai_validate.yaml</option><option ${x.workflow==='mixed.yaml'?'selected':''}>mixed.yaml</option><option ${x.workflow==='file.yaml'?'selected':''}>file.yaml</option><option ${x.workflow==='dynamic_handoff.yaml'?'selected':''}>dynamic_handoff.yaml</option></select></div></div><div class="workflow-caps">${workflowCapsHtml(x.workflow)}</div><div class="source-card"><div class="source-head"><div><strong>Task Prompt</strong><small>goal_file</small></div>${yamlSourceTabs(i,'goalMode',x.goalMode,[['inline','Write'],['file','File'],['asset','Asset']])}</div><div class="source-body">${goalSourceBody(x,i)}</div></div>${validation.length?`<div class="validation-grid ${validation.length===1?'one':''}">${validation.join('')}</div>`:'<div class="validation-empty">This Workflow needs no extra validator input.</div>'}</div>
      </div>`;
    }).join('');
    form.innerHTML=`<div class="sequence-composer">${rows}<div class="sequence-add-row"><button class="btn" id="addRequest">+ Add task</button><button class="btn ghost" id="addExistingSequence">Add existing</button></div></div>`;
  }
  bindBatchForm();
  document.querySelectorAll('[data-expand]').forEach(b=>b.onclick=()=>{sequenceExpandedIndex=sequenceExpandedIndex===+b.dataset.expand?-1:+b.dataset.expand;renderBatchDraft()});
  document.getElementById('addExistingSequence')?.addEventListener('click',()=>openExistingTaskPicker('sequence'));
  syncBatchViews();setBatchControls();syncTaskListDraftToParent();
};

// Keep Add task compact and expand only the new item.
const sequenceBaseBindBatchForm=bindBatchForm;
bindBatchForm=function(){
  sequenceBaseBindBatchForm();
  const add=document.getElementById('addRequest');
  if(add)add.onclick=()=>{
    const root=batchDraft[0]?.project||projectMeta[currentProjectKey]?.path||'C:\\project';
    batchDraft.push({prompt:'New task',goalMode:'inline',goalFile:'',goalAsset:'common/review.md',project:root,workflow:'ralphy_ai_validate.yaml',validatorMode:'none',validator:'',aiMode:'default',aiPrompt:'',aiFile:'',aiAsset:'common/ai_validator.md'});
    sequenceExpandedIndex=batchDraft.length-1;if(batchState.status==='stopped')batchState.currentDirty=true;renderBatchDraft();showToast('Task added to sequence');
  };
  document.querySelectorAll('[data-remove]').forEach(b=>{const old=b.onclick;b.onclick=()=>{const i=+b.dataset.remove;if(i<batchState.index)return;batchDraft.splice(i,1);sequenceExpandedIndex=Math.min(sequenceExpandedIndex,batchDraft.length-1);if(batchState.status==='stopped')batchState.currentDirty=true;renderBatchDraft()}});
  document.querySelectorAll('[data-moveup]').forEach(b=>b.onclick=()=>{const i=+b.dataset.moveup;if(i<=batchState.index||i<1)return;[batchDraft[i-1],batchDraft[i]]=[batchDraft[i],batchDraft[i-1]];sequenceExpandedIndex=i-1;if(batchState.status==='stopped')batchState.currentDirty=true;renderBatchDraft()});
  document.querySelectorAll('[data-movedown]').forEach(b=>b.onclick=()=>{const i=+b.dataset.movedown;if(i<batchState.index||i>=batchDraft.length-1)return;[batchDraft[i+1],batchDraft[i]]=[batchDraft[i],batchDraft[i+1]];sequenceExpandedIndex=i+1;if(batchState.status==='stopped')batchState.currentDirty=true;renderBatchDraft()});
  setBatchControls();
};

// Re-render using the sequence composer after binding override.
// --- In-place Steps editor behavior ---
function isSequenceTask(t){return !!t&&(t.kind==='list'||t.workspaceKind==='batch'||(t.listItems&&t.listItems.length>1))}
function singleTaskItem(t){
  const p=t.promptSource||{};
  return {prompt:p.prompt||t.goal||t.title,goalMode:p.goalMode||'inline',goalFile:p.goalFile||'',goalAsset:p.goalAsset||'common/review.md',project:projectMeta[t.project]?.path||t.project,workflow:t.workflow&&t.workflow!=='Task List'?t.workflow:'ralphy_ai_validate.yaml',validatorMode:p.validator?'file':'none',validator:p.validator||'',aiMode:p.aiMode||'default',aiPrompt:p.aiPrompt||'',aiFile:p.aiFile||'',aiAsset:p.aiAsset||'common/ai_validator.md'};
}
function deriveStepState(t){
  const multi=isSequenceTask(t),index=multi?(t.progress?.[0]||0):(t.runtime==='done'?1:0);
  if(t.runtime==='running'||t.runtime==='recover')return {status:'running',index,recovered:t.runtime==='recover',currentDirty:false};
  if(t.runtime==='stopped'||t.runtime==='attention'||t.runtime==='failed'||t.status==='paused')return {status:'stopped',index,recovered:false,currentDirty:!!t.configDirty};
  if(t.runtime==='done')return {status:'completed',index:multi?(t.listItems?.length||1):1,recovered:false,currentDirty:false};
  return {status:'idle',index:0,recovered:false,currentDirty:false};
}
function prepareStepsForTask(t){
  if(!t)return;
  batchParentTaskId=t.id;
  batchDraft=cloneBatch(isSequenceTask(t)&&t.listItems?.length?t.listItems:[singleTaskItem(t)]);
  batchState=deriveStepState(t);
  sequenceExpandedIndex=-1;
  document.getElementById('taskListParentHint').textContent=batchDraft.length===1?'1 step · this Task':`${batchDraft.length} steps · one Board Task`;
  renderBatchDraft();
}

// A single step stays a normal Task. Adding step 2 upgrades the same Task in place.
syncTaskListDraftToParent=function(){
  const t=batchParentTaskId?taskMap[batchParentTaskId]:null;if(!t)return;
  if(batchDraft.length<=1&&!isSequenceTask(t)){
    const x=batchDraft[0];if(x){
      t.workflow=x.workflow;t.goal=x.prompt||t.goal;
      t.promptSource={goalMode:x.goalMode,prompt:x.prompt,goalFile:x.goalFile,goalAsset:x.goalAsset,validator:x.validator,aiMode:x.aiMode,aiPrompt:x.aiPrompt,aiFile:x.aiFile,aiAsset:x.aiAsset};
    }
    return;
  }
  t.kind='list';t.workspaceKind='batch';t.workflow='Task List';t.listItems=cloneBatch(batchDraft);
  t.progress=[Math.min(batchState.index,batchDraft.length),batchDraft.length];t.tags=[`${batchDraft.length} steps`];
  t.executionRoot=`${batchDraft.length} child workspaces`;t.desc=`${batchDraft.length} ordered steps · ${runtimeLabel(t.runtime)}`;
};

openTaskListEditor=function(id){
  const t=taskMap[id];if(!t)return;
  prepareStepsForTask(t);
  document.querySelectorAll('.drawertab').forEach(b=>b.classList.toggle('active',b.dataset.drawertab==='items'));
  document.querySelectorAll('.drawer-pane').forEach(p=>p.classList.toggle('active',p.id==='drawer-items'));
};

const finalBaseOpenTaskById=openTaskById;
openTaskById=function(id){
  finalBaseOpenTaskById(id);
  const t=taskMap[id];if(!t)return;
  document.getElementById('drawerItemsTab').hidden=false;
  prepareStepsForTask(t);
};

document.getElementById('drawerAddStep').onclick=()=>{
  const t=taskMap[currentTaskId];if(!t)return;
  if(['running','recover'].includes(t.runtime)){showToast('Running 時 Steps 鎖定；請先 Pause');return}
  if(batchParentTaskId!==t.id)prepareStepsForTask(t);
  const root=batchDraft[0]?.project||projectMeta[t.project]?.path||'C:\\project';
  batchDraft.push({prompt:'New step',goalMode:'inline',goalFile:'',goalAsset:'common/review.md',project:root,workflow:'ralphy_ai_validate.yaml',validatorMode:'none',validator:'',aiMode:'default',aiPrompt:'',aiFile:'',aiAsset:'common/ai_validator.md'});
  sequenceExpandedIndex=batchDraft.length-1;if(batchState.status==='stopped')batchState.currentDirty=true;syncTaskListDraftToParent();renderBatchDraft();renderBoardFromMap();showToast('Step added · same Task upgraded in place');
};
document.getElementById('drawerAddExisting').onclick=()=>{
  const t=taskMap[currentTaskId];if(!t)return;
  if(['running','recover'].includes(t.runtime)){showToast('Running 時 Steps 鎖定；請先 Pause');return}
  if(batchParentTaskId!==t.id)prepareStepsForTask(t);openExistingTaskPicker('sequence');
};
// YAML advanced editor is opened by the final yamlPlanModal handler.

// Task footer remains the single Run / Stop / Resume control for both 1-step and multi-step Tasks.
document.getElementById('taskPrimaryDemo').onclick=()=>{
  const t=taskMap[currentTaskId];if(!t)return;
  if(isSequenceTask(t)){
    if(batchParentTaskId!==t.id)prepareStepsForTask(t);
    if(t.runtime==='idle'){document.getElementById('runBatch').click();openTaskById(t.id);return}
    if(['running','recover'].includes(t.runtime)){document.getElementById('stopBatch').click();openTaskById(t.id);return}
    if(['stopped','attention','failed'].includes(t.runtime)){document.getElementById('resumeBatch').click();openTaskById(t.id);return}
  }
  if(t.runtime==='idle'){
    const workspace=prepareTaskWorkspaceForRun(t);if(!workspace.ok){showToast(workspace.reason);return}
    if(workspace.changed)pushTaskHistory(t,`Auto workspace resolved → ${workspace.kind}`);
    t.runtime='running';t.stage='planning';t.session='main';t.elapsed='0m';if(t.status==='new')t.status='ongoing';pushTaskHistory(t,'Run started');showToast('Mock Run started');
  }else if(['running','recover'].includes(t.runtime)){t.runtime='stopped';t.status='paused';pushTaskHistory(t,'Paused by user');showToast('Mock Pause')}
  else if(['stopped','attention','failed'].includes(t.runtime)){t.runtime='running';t.status='ongoing';pushTaskHistory(t,'Resume accepted');showToast('Mock Resume')}
  renderBoardFromMap();openTaskById(t.id);
};

// Normal Task creation is now always one Task; composition happens later in Details > Steps.
newTaskKind='task';renderTaskKindUi();

// --- Final execution-plan UX: no mode switching; YAML is modal only ---
let pendingYamlPlan=null;
function isSinglePlainTask(){
  const t=taskMap[currentTaskId];return !!t&&!isSequenceTask(t)&&batchDraft.length<=1;
}
const visualRenderBatchDraft=renderBatchDraft;
renderBatchDraft=function(){
  const t=batchParentTaskId?taskMap[batchParentTaskId]:taskMap[currentTaskId];
  const form=document.getElementById('formList');
  if(t&&!isSequenceTask(t)&&batchDraft.length===1){
    const x=batchDraft[0],locked=['running','recover'].includes(t.runtime);
    form.innerHTML=`<div class="single-plan-strip"><div class="single-plan-icon">1</div><div class="single-plan-copy"><strong>Single task</strong><small>${escapeHtml(x.workflow)} · ${escapeHtml(basename(x.project))}</small></div><span class="single-plan-state ${runtimeClass(t.runtime)}">${escapeHtml(runtimeLabel(t.runtime))}</span></div>`;
    document.getElementById('taskListParentHint').textContent='Runs once · add another task only if this work needs a sequence';
    document.getElementById('drawerAddStep').disabled=locked;document.getElementById('drawerAddExisting').disabled=locked;
    document.getElementById('stepsAdvanced').disabled=locked;
    syncBatchViews();syncTaskListDraftToParent();return;
  }
  visualRenderBatchDraft();
  const count=batchDraft.length;
  document.getElementById('taskListParentHint').textContent=`${count} tasks · executed top to bottom · one Board Task`;
  const locked=t&&['running','recover'].includes(t.runtime);
  document.getElementById('drawerAddStep').disabled=locked;document.getElementById('drawerAddExisting').disabled=locked;
};

function openYamlPlanModal(){
  const t=taskMap[currentTaskId];if(!t)return;
  if(batchParentTaskId!==t.id)prepareStepsForTask(t);
  pendingYamlPlan=null;
  document.getElementById('yamlEditor').value=batchToYaml(batchDraft);
  const status=document.getElementById('yamlPlanStatus');status.className='yaml-plan-status';status.textContent='Editing the same ordered task list. Validate before Apply.';
  document.getElementById('applyYamlPlan').disabled=true;
  openModal('yamlPlanModal');
}
document.getElementById('stepsAdvanced').onclick=openYamlPlanModal;
document.getElementById('yamlEditor').oninput=()=>{
  pendingYamlPlan=null;document.getElementById('applyYamlPlan').disabled=true;
  const s=document.getElementById('yamlPlanStatus');s.className='yaml-plan-status';s.textContent='Changed · validate before Apply.';
};
document.getElementById('validateYaml').onclick=()=>{
  const source=document.getElementById('yamlEditor').value.trim(),items=parseSimpleYamlList(source),errors=batchValidationErrors(items);
  if(!items.length)errors.push('execution plan must contain at least one task');
  const status=document.getElementById('yamlPlanStatus');
  if(errors.length){pendingYamlPlan=null;document.getElementById('applyYamlPlan').disabled=true;status.className='yaml-plan-status bad';status.textContent='Invalid · '+errors.join(' · ');showToast(`YAML invalid · ${errors.length} issue(s)`);return}
  pendingYamlPlan=items;document.getElementById('applyYamlPlan').disabled=false;status.className='yaml-plan-status ok';status.textContent=`Valid · ${items.length} task${items.length===1?'':'s'} ready to apply.`;showToast('YAML valid');
};
document.getElementById('applyYamlPlan').onclick=()=>{
  if(!pendingYamlPlan)return;
  const t=taskMap[currentTaskId];if(!t)return;
  if(['running','recover'].includes(t.runtime)){showToast('Running 時不能修改 execution plan');return}
  const previousCount=batchDraft.length;batchDraft=cloneBatch(pendingYamlPlan);
  batchState.currentDirty=batchState.status==='stopped';sequenceExpandedIndex=-1;syncTaskListDraftToParent();
  if(batchDraft.length>1){t.kind='list';t.workspaceKind='batch';t.workflow='Task List';t.listItems=cloneBatch(batchDraft);t.tags=[`${batchDraft.length} steps`];}
  else if(previousCount>1&&batchDraft.length===1){
    const x=batchDraft[0];t.kind='task';t.workspaceKind='main';t.workflow=x.workflow;t.goal=x.prompt||t.goal;t.listItems=null;t.tags=['workflow'];
    t.promptSource={goalMode:x.goalMode,prompt:x.prompt,goalFile:x.goalFile,goalAsset:x.goalAsset,validator:x.validator,aiMode:x.aiMode,aiPrompt:x.aiPrompt,aiFile:x.aiFile,aiAsset:x.aiAsset};
  }
  renderBatchDraft();renderBoardFromMap();closeModal('yamlPlanModal');pendingYamlPlan=null;showToast('Task list YAML applied');
};

// New Task always creates one Task. Composition happens later from Overview.
document.getElementById('addNextTaskFromNew').onclick=()=>{};
document.getElementById('addExistingTaskFromNew').onclick=()=>{};

// Keep the drawer on Overview; composition never navigates away.
document.getElementById('drawerAddStep').onclick=()=>{
  const t=taskMap[currentTaskId];if(!t)return;
  if(['running','recover'].includes(t.runtime)){showToast('Running 時 execution plan 鎖定；請先 Pause');return}
  if(batchParentTaskId!==t.id)prepareStepsForTask(t);
  const root=batchDraft[0]?.project||projectMeta[t.project]?.path||'C:\\project';
  batchDraft.push({prompt:'Next task',goalMode:'inline',goalFile:'',goalAsset:'common/review.md',project:root,workflow:'ralphy_ai_validate.yaml',validatorMode:'none',validator:'',aiMode:'default',aiPrompt:'',aiFile:'',aiAsset:'common/ai_validator.md'});
  sequenceExpandedIndex=batchDraft.length-1;if(batchState.status==='stopped')batchState.currentDirty=true;syncTaskListDraftToParent();renderBatchDraft();renderBoardFromMap();showToast('Next task added');
};
document.getElementById('drawerAddExisting').onclick=()=>{
  const t=taskMap[currentTaskId];if(!t)return;
  if(['running','recover'].includes(t.runtime)){showToast('Running 時 execution plan 鎖定；請先 Pause');return}
  if(batchParentTaskId!==t.id)prepareStepsForTask(t);openExistingTaskPicker('sequence');
};

// --- Task edit policy: New / Paused editable; Ongoing / Closed read-only ---
let taskFormMode='create';
let editingTaskId=null;
function taskEditable(t){return !!t&&['new','paused'].includes(t.status)}
function projectKeyForTask(t){return projectMeta[t.project]?t.project:(Object.keys(projectMeta).find(k=>projectMeta[k].path===t.project)||currentProjectKey||'ai-task-runner')}
function taskRuntimeFingerprint(t){return JSON.stringify({project:t.project,workflow:t.workflow,goal:t.goal,promptSource:t.promptSource||{},workspacePolicy:t.workspacePolicy||'',workspaceKind:t.workspaceKind||'',branch:t.branch||'',executionRoot:t.executionRoot||''})}
function setTaskFormCreateMode(){
  taskFormMode='create';editingTaskId=null;
  document.getElementById('taskFormTitle').textContent='New Task';
  document.getElementById('taskFormHelp').textContent='先建立第一個 task；之後可從 Task Details 繼續加入更多 tasks。';
  document.getElementById('createTaskConfirm').textContent='Create Task';
  document.getElementById('editTaskScopeNote').hidden=true;
  document.getElementById('newTaskWorkflowField').hidden=false;
  document.getElementById('newTaskWorkflowCaps').hidden=false;
  document.querySelector('.workspace-selector-wrap').hidden=false;
  document.getElementById('newTaskPromptSource').hidden=false;
  document.getElementById('newTaskValidationSource').hidden=false;
}
function applyEditFormScope(t){
  const multi=isSequenceTask(t);
  const note=document.getElementById('editTaskScopeNote');
  note.hidden=false;
  if(multi){
    note.innerHTML='<strong>Multi-step Task</strong>：這裡只編輯 Task title / owning project。每個 Step 的 Workflow、Prompt、Validator 請直接在 Execution plan 裡 Edit。';
    document.getElementById('newTaskWorkflowField').hidden=true;
    document.getElementById('newTaskWorkflowCaps').hidden=true;
    document.querySelector('.workspace-selector-wrap').hidden=true;
    document.getElementById('newTaskPromptSource').hidden=true;
    document.getElementById('newTaskValidationSource').hidden=true;
  }else{
    note.innerHTML=t.status==='paused'?'<strong>Paused Task</strong>：可編輯。若變更 Project / Workflow / Prompt / Validator / Workspace，下一次會 fresh restart，不沿用舊 frozen run。':'<strong>New Task</strong>：尚未執行，可自由修改。';
    document.getElementById('newTaskWorkflowField').hidden=false;
    document.getElementById('newTaskWorkflowCaps').hidden=false;
    document.querySelector('.workspace-selector-wrap').hidden=false;
    document.getElementById('newTaskPromptSource').hidden=false;
    document.getElementById('newTaskValidationSource').hidden=false;
  }
}
function openEditTaskForm(t){
  if(!taskEditable(t)){showToast(t.status==='ongoing'?'Ongoing Task 請先 Pause 再編輯':'Closed Task 為唯讀');return}
  taskFormMode='edit';editingTaskId=t.id;
  document.getElementById('taskFormTitle').textContent='Edit Task';
  document.getElementById('taskFormHelp').textContent='使用與 New Task 相同的設定介面；Save 不會另外建立 Task。';
  document.getElementById('createTaskConfirm').textContent='Save changes';
  document.getElementById('newTaskTitle').value=t.title;
  const key=projectKeyForTask(t);document.getElementById('newTaskProject').value=key;
  if(!isSequenceTask(t)){
    document.getElementById('newTaskWorkflow').value=t.workflow||'ralphy_ai_validate.yaml';
    const p=t.promptSource||{};
    newTaskDraft={goalMode:p.goalMode||'inline',prompt:p.prompt||t.goal||'',goalFile:p.goalFile||'',goalAsset:p.goalAsset||'common/review.md',validator:p.validator||'',aiMode:p.aiMode||'default',aiPrompt:p.aiPrompt||'',aiFile:p.aiFile||'',aiAsset:p.aiAsset||'common/ai_validator.md'};
    newTaskWorkspaceMode=t.workspacePolicy||((t.workspaceKind==='worktree')?'worktree':'auto');
    renderNewTaskSources();renderNewTaskWorkspace();
  }
  applyEditFormScope(t);openModal('newTaskModal');
}
document.getElementById('editTaskDemo').onclick=()=>{const t=taskMap[currentTaskId];if(t)openEditTaskForm(t)};

const createTaskAction=document.getElementById('createTaskConfirm').onclick;
document.getElementById('createTaskConfirm').onclick=()=>{
  if(taskFormMode!=='edit'||!editingTaskId||!taskMap[editingTaskId])return createTaskAction();
  const t=taskMap[editingTaskId];if(!taskEditable(t))return;
  const before=taskRuntimeFingerprint(t);
  const title=document.getElementById('newTaskTitle').value.trim();if(!title){showToast('Task title 不可空白');return}
  const project=document.getElementById('newTaskProject').value;
  t.title=title;t.project=project;
  if(!isSequenceTask(t)){
    captureNewTaskSources();
    const workflow=document.getElementById('newTaskWorkflow').value,caps=workflowCaps(workflow);
    let goal='';if(newTaskDraft.goalMode==='inline')goal=newTaskDraft.prompt.trim();else if(newTaskDraft.goalMode==='file')goal=`goal_file: ${newTaskDraft.goalFile.trim()}`;else goal=`Prompt asset: ${newTaskDraft.goalAsset}`;
    if(!goal){showToast('Task Prompt 不可空白');return}
    if(caps.file&&!newTaskDraft.validator.trim()){showToast('這個 Workflow 需要 File Validator');return}
    const workspace=resolveTaskWorkspace(project,t.id,newTaskWorkspaceMode);if(!workspace.ok){showToast(workspace.reason);return}
    t.workflow=workflow;t.goal=goal;t.promptSource={...newTaskDraft};t.workspacePolicy=newTaskWorkspaceMode;
    if(workspace.ok){t.workspaceKind=workspace.kind;t.branch=workspace.branch;t.executionRoot=workspace.root}
    const tags=['workflow'];if(caps.file)tags.push('file validation');if(caps.ai)tags.push('AI validation');t.tags=tags;
  }
  const runtimeChanged=!isSequenceTask(t)&&before!==taskRuntimeFingerprint(t);
  if(t.status==='paused'&&runtimeChanged){
    t.configDirty=true;t.desc='Paused Task 已修改執行設定 · 下一次將 fresh restart 目前工作。';
    pushTaskHistory(t,'Task edited while Paused · restart required');
  }else{pushTaskHistory(t,'Task metadata updated')}
  closeModal('newTaskModal');renderBoardFromMap();openTaskById(t.id);showToast(t.configDirty?'Saved · restart required':'Task updated');
};

// Any create entry resets the shared form back to create mode.
document.getElementById('newTask').addEventListener('click',setTaskFormCreateMode,true);
document.querySelectorAll('.coladd').forEach(b=>b.addEventListener('click',setTaskFormCreateMode,true));

const editAwareOpenTaskById=openTaskById;
openTaskById=function(id){
  editAwareOpenTaskById(id);
  const t=taskMap[id];if(!t)return;
  const edit=document.getElementById('editTaskDemo'),editable=taskEditable(t);
  edit.disabled=!editable;
  edit.textContent=editable?'Edit Task':(t.status==='ongoing'?'Pause to edit':'Read-only');
  edit.title=editable?'Edit this Task':(t.status==='ongoing'?'Pause the Task before editing':'Closed Tasks are read-only');
  const notice=document.getElementById('taskEditNotice');
  if(t.configDirty){notice.hidden=false;notice.innerHTML='<strong>Configuration changed while Paused.</strong> Resume will fresh restart the current Task/Step using the new settings.'}
  else{notice.hidden=true;notice.textContent=''}
  const canEdit=editable;
  document.getElementById('drawerAddStep').disabled=!canEdit;
  document.getElementById('drawerAddExisting').disabled=!canEdit;
  document.getElementById('stepsAdvanced').disabled=!canEdit;
  if(t.status==='paused'&&t.configDirty&&document.getElementById('taskPrimaryDemo').textContent==='Resume')document.getElementById('taskPrimaryDemo').textContent='Restart';
};

// Board status, not runtime badge, owns editability for execution-plan controls.
const finalPlanRender=renderBatchDraft;
renderBatchDraft=function(){
  finalPlanRender();
  const t=taskMap[currentTaskId]||taskMap[batchParentTaskId];if(!t)return;
  const editable=taskEditable(t);
  if(!editable){document.querySelectorAll('#formList input,#formList textarea,#formList select,#formList button').forEach(el=>el.disabled=true)}
  document.getElementById('drawerAddStep').disabled=!editable;
  document.getElementById('drawerAddExisting').disabled=!editable;
  document.getElementById('stepsAdvanced').disabled=!editable;
};

// Runtime-affecting edit on a Paused single Task becomes Restart, not fake Resume.
const taskPrimaryBeforeEditPolicy=document.getElementById('taskPrimaryDemo').onclick;
document.getElementById('taskPrimaryDemo').onclick=()=>{
  const t=taskMap[currentTaskId];
  if(t&&t.status==='paused'&&t.configDirty&&!isSequenceTask(t)){
    t.configDirty=false;t.runtime='running';t.status='ongoing';t.stage='planning';t.session='fresh';t.elapsed='0m';t.progress=[0,t.progress?.[1]||4];
    t.desc='Restarted with edited configuration';pushTaskHistory(t,'Fresh restart with edited Task configuration');renderBoardFromMap();openTaskById(t.id);showToast('Fresh restart started');return;
  }
  taskPrimaryBeforeEditPolicy();
};

// YAML editing is also governed by Board status.
const yamlOpenBeforeEditPolicy=openYamlPlanModal;
openYamlPlanModal=function(){
  const t=taskMap[currentTaskId];if(!t)return;
  if(!taskEditable(t)){showToast(t.status==='ongoing'?'Pause Task before editing YAML':'Closed Task is read-only');return}
  yamlOpenBeforeEditPolicy();
};
document.getElementById('stepsAdvanced').onclick=openYamlPlanModal;
