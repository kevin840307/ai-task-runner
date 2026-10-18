// --- One Task Drawer shell owns Info / List / Editor / YAML routes. ---
const taskOverlayEl=document.getElementById('taskOverlay');
const taskDrawerEl=taskOverlayEl.querySelector('.drawer');
const taskDrawerBack=document.getElementById('planBackToTask');
const taskDrawerInfoMeta=document.getElementById('drawerInfoMeta');
const taskDrawerRouteMeta=document.getElementById('drawerRouteMeta');
const taskDrawerRuntimeSlot=document.getElementById('drawerRuntimeSlot');
const taskDrawerWorkspaceActions=document.getElementById('drawerWorkspaceActions');
const taskDrawerRename=document.getElementById('planRenameList');
const taskDrawerTabs=document.querySelector('#taskOverlay .drawertabs');
const taskDrawerBody=document.querySelector('#taskOverlay .drawerbody');
const taskDrawerFoot=document.querySelector('#taskOverlay .drawerfoot');
const taskDrawerBanner=document.getElementById('drawerWorktreeBanner');
const planModalEl=document.getElementById('planModal');
const planListSurface=planModalEl.querySelector('.plan-page-body')||planModalEl;
const planSubviewMount=document.getElementById('planSubviewMount');
const taskEditorHome=document.getElementById('newTaskModal');
const taskEditorSurface=taskEditorHome;
const yamlEditorHome=document.getElementById('yamlPlanModal');
const yamlEditorSurface=yamlEditorHome.querySelector('.yaml-plan-modal');
let planSubviewType=null,planSubviewOwnerId=null,planSubviewIndex=null,planReturnScroll=0,planSubviewReturnTarget='list';
let taskEditorReturnContext=null,taskDrawerListReturnTarget='close';

function taskDrawerMetaFor(t,prefix=''){
  if(!t)return prefix||'';
  const items=canonicalTaskItems(t);
  return prefix||`${t.id} · ${statusLabel(t.status)} · ${items.length} task${items.length===1?'':'s'}`;
}
function setTaskDrawerShell(route,{title='',meta='',showBack=false,backTitle='Back'}={}){
  const workspace=route!=='info';
  taskDrawerEl.dataset.route=route;
  taskDrawerEl.classList.toggle('workspace-route',workspace);
  taskDrawerTabs.hidden=workspace;
  taskDrawerBody.hidden=workspace;
  taskDrawerFoot.hidden=workspace;
  if(taskDrawerBanner)taskDrawerBanner.hidden=workspace?true:taskDrawerBanner.hidden;
  taskDrawerInfoMeta.hidden=workspace;
  taskDrawerRouteMeta.hidden=!workspace;
  taskDrawerRuntimeSlot.hidden=workspace;
  taskDrawerWorkspaceActions.hidden=route!=='list';
  taskDrawerRename.hidden=route!=='list';
  taskDrawerBack.hidden=!showBack;
  taskDrawerBack.title=backTitle;
  taskDrawerBack.textContent='←';
  if(route==='list')taskDrawerBack.onclick=handleTaskDrawerBack;
  if(title)document.getElementById('drawerTitle').textContent=title;
  if(workspace)taskDrawerRouteMeta.textContent=meta||'';
  taskOverlayEl.classList.add('open');
}
function restoreTaskInfoShell(t){
  if(!t)return;
  setTaskDrawerShell('info',{title:t.title});
  taskDrawerInfoMeta.hidden=false;taskDrawerRouteMeta.hidden=true;taskDrawerRuntimeSlot.hidden=false;
  taskDrawerWorkspaceActions.hidden=true;taskDrawerRename.hidden=true;taskDrawerBack.hidden=true;
}
function closeTaskDrawerShell(){
  taskEditorReturnContext=null;
  if(taskEditorHome.classList.contains('open'))taskEditorHome.classList.remove('open');
  if(planSubviewType==='yaml'&&yamlEditorSurface.parentNode===planSubviewMount){
    yamlEditorHome.appendChild(yamlEditorSurface);restoreSurfaceCloseBehavior(yamlEditorSurface,'yamlPlanModal');
  }
  planSubviewType=null;planSubviewOwnerId=null;planSubviewIndex=null;
  planSubviewMount.hidden=true;planModalEl.classList.remove('subview-open','open');
  clearTaskSelection?.();
  taskOverlayEl.classList.remove('open');
}

function restoreSurfaceCloseBehavior(surface,overlayId){
  const close=surface.querySelector('.modal-head .close'),cancel=surface.querySelector('.modal-foot [data-close-modal]');
  if(close){close.textContent='×';close.title='Close';close.onclick=()=>closeModal(overlayId)}
  if(cancel){cancel.textContent='Cancel';cancel.onclick=()=>closeModal(overlayId)}
}
function taskEditorBackLabel(returnTarget){
  return returnTarget==='info'?'Back to Info':returnTarget==='chat'?'Back to Chat Draft':returnTarget==='list'?'Back to Task List':'Close';
}
function detectTaskEditorReturnTarget(){
  if(planModalEl.classList.contains('open')&&!planModalEl.classList.contains('subview-open'))return 'list';
  if(document.getElementById('taskOverlay').classList.contains('open'))return 'info';
  return 'close';
}
function showTaskEditorView(){
  planSubviewMount.hidden=false;
  planModalEl.classList.add('subview-open','open');
  taskEditorHome.classList.add('open');
  const ctx=taskEditorReturnContext,owner=ctx?.ownerId?taskMap[ctx.ownerId]:null;
  const title=document.getElementById('taskFormTitle')?.textContent||'Task';
  const meta=owner
    ? `${owner.id} · ${ctx?.index==null?'Task':`Task ${ctx.index+1} of ${canonicalTaskItems(owner).length}`}`
    : 'New Task';
  setTaskDrawerShell('editor',{title,meta,showBack:ctx?.returnTarget!=='close',backTitle:taskEditorBackLabel(ctx?.returnTarget)});
}
function hideTaskEditorView(){
  taskEditorHome.classList.remove('open');
  planSubviewMount.hidden=true;
  planModalEl.classList.remove('subview-open');
}
function leaveTaskEditorOverlay(){
  const ctx=taskEditorReturnContext;if(!ctx)return;
  taskEditorReturnContext=null;
  hideTaskEditorView();
  const owner=ctx.ownerId?taskMap[ctx.ownerId]:null;
  if(owner){setPlanDraftForTask(owner);renderFullPlan(owner);renderDrawerPlan(owner)}
  if(ctx.returnTarget==='chat'){
    planModalEl.classList.remove('open');taskOverlayEl.classList.remove('open');showView('chat');renderChatSession();return;
  }
  if(ctx.returnTarget==='info'){
    closeModal('planModal');if(owner)openTaskById(owner.id);return;
  }
  if(ctx.returnTarget==='close'){
    planModalEl.classList.remove('open');
    if(taskDrawerEl.dataset.route!=='info')taskOverlayEl.classList.remove('open');
    return;
  }
  if(owner){
    planModalEl.classList.add('open');renderFullPlan(owner);
    setTaskDrawerShell('list',{title:owner.title,meta:taskDrawerMetaFor(owner),showBack:taskDrawerListReturnTarget!=='close',backTitle:taskDrawerListReturnTarget==='info'?'Back to Task Info':taskDrawerListReturnTarget==='chat'?'Back to Chat Draft':'Back'});
    const scrollHost=planListSurface.querySelector('.plan-main')||planListSurface;
    scrollHost.scrollTop=ctx.scrollTop||0;
    if(ctx.index!=null)setTimeout(()=>document.querySelector(`#planFormList [data-plan-row="${ctx.index}"]`)?.scrollIntoView({block:'nearest'}),0);
  }
}
function setSurfaceBackBehavior(surface,type,returnTarget='list'){
  const close=surface.querySelector('.modal-head .close'),cancel=surface.querySelector('.modal-foot [data-close-modal]');
  const label=type==='task'?taskEditorBackLabel(returnTarget):'Back to Task List';
  const leave=type==='task'?leaveTaskEditorOverlay:leavePlanSubview;
  if(close){close.textContent='×';close.title='Close';close.onclick=e=>{e.preventDefault();closeTaskDrawerShell()}}
  taskDrawerBack.hidden=returnTarget==='close'&&type==='task';
  taskDrawerBack.title=label;taskDrawerBack.textContent='←';
  taskDrawerBack.onclick=e=>{e.preventDefault();leave()};
  if(cancel){cancel.textContent=returnTarget==='close'&&type==='task'?'Cancel':label;cancel.onclick=e=>{e.preventDefault();leave()}}
}
function enterPlanSubview(type,surface,sourceOverlay,ownerId,index=null,returnTarget='list'){
  const scrollHost=planListSurface.querySelector('.plan-main')||planListSurface;
  planReturnScroll=scrollHost.scrollTop||0;planSubviewType=type;planSubviewOwnerId=ownerId;planSubviewIndex=index;planSubviewReturnTarget=returnTarget;
  closeModal(sourceOverlay.id);
  taskEditorHome.classList.remove('open');
  planSubviewMount.appendChild(surface);planSubviewMount.hidden=false;planModalEl.classList.add('subview-open','open');
  const owner=taskMap[ownerId];
  setTaskDrawerShell(type==='yaml'?'yaml':type,{title:type==='yaml'?'Edit task list YAML':'Task',meta:owner?`${owner.id} · ${owner.title}`:'',showBack:true,backTitle:'Back to Task List'});
  setSurfaceBackBehavior(surface,type,returnTarget);
}
function leavePlanSubview(){
  if(!planSubviewType)return;
  const type=planSubviewType,ownerId=planSubviewOwnerId,index=planSubviewIndex;
  if(type==='yaml'){yamlEditorHome.appendChild(yamlEditorSurface);restoreSurfaceCloseBehavior(yamlEditorSurface,'yamlPlanModal')}
  planSubviewType=null;planSubviewOwnerId=null;planSubviewIndex=null;planSubviewReturnTarget='list';planSubviewMount.hidden=true;planModalEl.classList.remove('subview-open');
  const owner=taskMap[ownerId];if(owner){setPlanDraftForTask(owner);renderFullPlan(owner);renderDrawerPlan(owner);setTaskDrawerShell('list',{title:owner.title,meta:taskDrawerMetaFor(owner),showBack:taskDrawerListReturnTarget!=='close',backTitle:taskDrawerListReturnTarget==='info'?'Back to Task Info':taskDrawerListReturnTarget==='chat'?'Back to Chat Draft':'Back'})}
  const scrollHost=planListSurface.querySelector('.plan-main')||planListSurface;scrollHost.scrollTop=planReturnScroll;
  if(index!=null)setTimeout(()=>document.querySelector(`#planFormList [data-plan-row="${index}"]`)?.scrollIntoView({block:'nearest'}),0);
}

const taskEditorLoadBeforeOverlay=loadTaskEditor;
loadTaskEditor=function(mode,args={}){
  const ownerId=args.ownerId||currentTaskId,owner=mode==='root-create'?null:taskMap[ownerId];
  if(mode!=='root-create'&&!owner)return;
  const returnTarget=args.returnTarget||(mode==='root-create'?'close':detectTaskEditorReturnTarget());
  if(typeof hideComposerSuggestions==='function')hideComposerSuggestions();
  if(typeof closeComposerPicker==='function')closeComposerPicker();
  if(returnTarget==='chat')showView('chat');
  const scrollHost=planListSurface.querySelector('.plan-main')||planListSurface;
  closeModal('addPlanTaskModal');
  taskEditorLoadBeforeOverlay(mode,args);
  taskEditorReturnContext={mode,ownerId:owner?.id||null,index:args.index??(owner?canonicalTaskItems(owner).length:null),returnTarget,scrollTop:scrollHost.scrollTop||0};
  document.getElementById('taskFormTitle').textContent=mode==='edit-item'?'Edit task':mode==='root-create'?'New Task':'New task';
  document.getElementById('taskFormHelp').textContent=returnTarget==='chat'
    ?(mode==='edit-item'?'Edit this Task Draft item. Chat stays behind this workspace.':'Configure this Task Draft item. Chat stays behind this workspace.')
    :(mode==='root-create'?'Create one Task in this workspace.':mode==='edit-item'?'Edit this task only.':'Configure this task only.');
  document.getElementById('editTaskScopeNote').hidden=true;
  showTaskEditorView();
  const editorOwner=ownerId?taskMap[ownerId]:null;
  setTaskDrawerShell('editor',{
    title:document.getElementById('taskFormTitle').textContent,
    meta:editorOwner?`${editorOwner.id} · ${mode==='edit-item'?`Task ${(args.index??0)+1} of ${canonicalTaskItems(editorOwner).length}`:'New child task'}`:'New Task',
    showBack:returnTarget!=='close',
    backTitle:taskEditorBackLabel(returnTarget)
  });
  setSurfaceBackBehavior(taskEditorSurface,'task',returnTarget);
};

const taskEditorSaveBeforeOverlay=document.getElementById('createTaskConfirm').onclick;
document.getElementById('createTaskConfirm').onclick=()=>{
  const ctx=taskEditorReturnContext;
  taskEditorSaveBeforeOverlay();
  if(!ctx)return;
  const itemSaved=['Task saved','Saved · current task will restart'].includes(toast.textContent);
  const rootSaved=ctx.mode==='root-create'&&String(toast.textContent).startsWith('Task created');
  if(itemSaved||rootSaved)leaveTaskEditorOverlay();
};

// YAML is also a long-form editor, so it uses the same Plan subview instead of another large modal.
const yamlOpenBeforeSubview=openYamlPlanModal;
openYamlPlanModal=function(){
  const ownerId=currentTaskId;if(!ownerId)return;
  if(!planModalEl.classList.contains('open'))openPlanDialog(ownerId);
  yamlOpenBeforeSubview();
  if(yamlEditorHome.classList.contains('open'))enterPlanSubview('yaml',yamlEditorSurface,yamlEditorHome,ownerId,null);
};
document.getElementById('stepsAdvanced').onclick=openYamlPlanModal;
document.getElementById('planEditYaml').onclick=openYamlPlanModal;
const yamlApplyBeforeSubview=document.getElementById('applyYamlPlan').onclick;
document.getElementById('applyYamlPlan').onclick=()=>{
  const embedded=planSubviewType==='yaml';yamlApplyBeforeSubview();
  if(embedded&&toast.textContent==='Task list YAML applied')leavePlanSubview();
};

// --- Shared right-click context menu for list rows and Board cards. ---
const taskContextMenu=document.getElementById('taskContextMenu');
let taskContextState=null;
function hideTaskContextMenu(){taskContextMenu.hidden=true;taskContextState=null}
function positionTaskContextMenu(x,y){
  taskContextMenu.hidden=false;const w=454,h=260;
  taskContextMenu.style.left=`${Math.min(window.innerWidth-w-8,Math.max(8,x))}px`;taskContextMenu.style.top=`${Math.min(window.innerHeight-h-8,Math.max(8,y))}px`;
}
function setContextAction(name,{visible=true,enabled=true,label=null}={}){
  const b=taskContextMenu.querySelector(`[data-context-action="${name}"]`);if(!b)return;
  b.hidden=!visible;b.disabled=!enabled;if(label)b.querySelector('span').textContent=label;
}
function renderContextSideInfo(state){
  const t=taskMap[state.ownerId];if(!t)return;
  const title=document.getElementById('taskInfoTitle'),meta=document.getElementById('taskInfoMeta'),body=document.getElementById('taskInfoBody');
  if(state.scope==='list'){
    const items=canonicalTaskItems(t);
    title.textContent=t.title;meta.textContent=`${t.id} · Task List`;
    body.innerHTML=`<span>Status</span><strong>${escapeHtml(statusLabel(t.status))}</strong><span>Runtime</span><strong>${escapeHtml(runtimeLabel(t.runtime))}</strong><span>Tasks</span><strong>${items.length}</strong><span>Progress</span><strong>${t.progress?.[0]||0} / ${items.length}</strong><span>Elapsed</span><strong>${escapeHtml(t.elapsed||'—')}</strong>`;
    return;
  }
  const items=canonicalTaskItems(t),x=items[state.index];if(!x)return;
  const s=planStateFor(t,state.index,items.length),ai=x.aiMode==='default'?'Workflow default':x.aiMode;
  title.textContent=planTitle(x,state.index);meta.textContent=`Task ${state.index+1} · ${s.label}`;
  body.innerHTML=`<span>Project</span><strong>${escapeHtml(x.project)}</strong><span>Workflow</span><strong>${escapeHtml(x.workflow)}</strong><span>Prompt</span><strong>${escapeHtml(x.goalMode||'inline')}</strong><span>File validator</span><strong>${escapeHtml(x.validator||'—')}</strong><span>AI validation</span><strong>${escapeHtml(ai)}</strong><span>Workspace</span><strong>${escapeHtml(workspaceLabelForItem(x))}</strong><span>Branch</span><strong>${escapeHtml(x.branch||'—')}</strong><span>Path</span><strong>${escapeHtml(x.executionRoot||'—')}</strong>`;
}
function openItemContextMenu(e,owner,index){
  e.preventDefault();e.stopPropagation();hideCreateTypeMenu();
  const items=canonicalTaskItems(owner),s=planStateFor(owner,index,items.length),editable=taskEditable(owner),currentLocked=owner.status==='paused'&&s.current;
  const canEdit=editable&&!s.done,canRestructure=canEdit&&!currentLocked;
  taskContextState={scope:'item',ownerId:owner.id,index};
  setContextAction('open',{visible:false});setContextAction('edit',{visible:true,enabled:canEdit,label:'Edit'});
  setContextAction('up',{visible:true,enabled:canRestructure&&index>0&&(owner.status!=='paused'||index-1>batchState.index),label:'Move up'});setContextAction('down',{visible:true,enabled:canRestructure&&index<items.length-1,label:'Move down'});setContextAction('remove',{visible:true,enabled:canRestructure,label:'Remove'});
  renderContextSideInfo(taskContextState);positionTaskContextMenu(e.clientX,e.clientY);
}
function openListContextMenu(e,t){
  e.preventDefault();e.stopPropagation();hideCreateTypeMenu();const editable=taskEditable(t),canDelete=t.status==='new'&&t.runtime==='idle';
  taskContextState={scope:'list',ownerId:t.id,index:null};
  setContextAction('open',{visible:true,enabled:true,label:'Open list'});setContextAction('edit',{visible:true,enabled:editable,label:'Rename'});
  setContextAction('up',{visible:false});setContextAction('down',{visible:false});setContextAction('remove',{visible:true,enabled:canDelete,label:'Delete'});
  renderContextSideInfo(taskContextState);positionTaskContextMenu(e.clientX,e.clientY);
}
function showContextInfo(state){
  const t=taskMap[state.ownerId];if(!t)return;
  const body=document.getElementById('taskInfoBody'),title=document.getElementById('taskInfoTitle'),meta=document.getElementById('taskInfoMeta');
  if(state.scope==='list'){
    const items=canonicalTaskItems(t);title.textContent=t.title;meta.textContent=`${t.id} · ${statusLabel(t.status)} · ${runtimeLabel(t.runtime)}`;
    body.innerHTML=`<span>Type</span><strong>Task List</strong><span>Tasks</span><strong>${items.length}</strong><span>Progress</span><strong>${t.progress?.[0]||0} / ${items.length}</strong><span>Status</span><strong>${statusLabel(t.status)}</strong><span>Runtime</span><strong>${runtimeLabel(t.runtime)}</strong>`;
  }else{
    const x=canonicalTaskItems(t)[state.index],s=planStateFor(t,state.index,canonicalTaskItems(t).length);if(!x)return;
    title.textContent=planTitle(x,state.index);meta.textContent=`Task ${state.index+1} · ${s.label}`;
    const ai=x.aiMode==='default'?'Workflow default':x.aiMode;
    body.innerHTML=`<span>Project</span><strong>${escapeHtml(x.project)}</strong><span>Workflow</span><strong>${escapeHtml(x.workflow)}</strong><span>Prompt source</span><strong>${escapeHtml(x.goalMode)}</strong><span>File validator</span><strong>${escapeHtml(x.validator||'—')}</strong><span>AI validation</span><strong>${escapeHtml(ai)}</strong><span>Workspace</span><strong>${escapeHtml(workspaceLabelForItem(x))}</strong><span>Branch</span><strong>${escapeHtml(x.branch||'—')}</strong><span>Path</span><strong>${escapeHtml(x.executionRoot||'—')}</strong>`;
  }
  openModal('taskInfoModal');
}
function mutateContextItem(action,state){
  const t=taskMap[state.ownerId];if(!t)return;if(batchParentTaskId!==t.id)setPlanDraftForTask(t);const i=state.index,items=canonicalTaskItems(t),s=planStateFor(t,i,items.length),currentLocked=t.status==='paused'&&s.current;
  const canEdit=taskEditable(t)&&!s.done,canRestructure=canEdit&&!currentLocked;if(!canRestructure)return;
  if(action==='up'&&i>0){[batchDraft[i-1],batchDraft[i]]=[batchDraft[i],batchDraft[i-1]]}
  if(action==='down'&&i<batchDraft.length-1){[batchDraft[i+1],batchDraft[i]]=[batchDraft[i],batchDraft[i+1]]}
  if(action==='remove'){batchDraft.splice(i,1)}
  commitPlanDraft(t);persistCurrentPresetFromTaskMap();renderBoardFromMap();renderFullPlan(t);renderDrawerPlan(t);
}
taskContextMenu.querySelectorAll('[data-context-action]').forEach(b=>b.onclick=()=>{
  if(b.disabled||!taskContextState)return;const state={...taskContextState},action=b.dataset.contextAction;hideTaskContextMenu();
  const t=taskMap[state.ownerId];if(!t)return;
  if(action==='open'&&state.scope==='list'){openPlanDialog(t.id);return}
  if(action==='edit'){if(state.scope==='list'){if(taskEditable(t))openListNameDialog(t)}else{const s=planStateFor(t,state.index,canonicalTaskItems(t).length);if(taskEditable(t)&&!s.done)loadTaskEditor('edit-item',{ownerId:t.id,index:state.index})}return}
  if(['up','down','remove'].includes(action)&&state.scope==='item'){mutateContextItem(action,state);return}
  if(action==='remove'&&state.scope==='list'){requestTaskDelete(t.id)}
});
document.addEventListener('click',e=>{if(!taskContextMenu.hidden&&!taskContextMenu.contains(e.target))hideTaskContextMenu()});
document.addEventListener('keydown',e=>{if(e.key==='Escape'){hideTaskContextMenu();const childOpen=['pathPickerModal','addPlanTaskModal','taskInfoModal','taskListNameModal'].some(id=>document.getElementById(id)?.classList.contains('open'));if(!childOpen&&planSubviewType)leavePlanSubview()}});
window.addEventListener('scroll',hideTaskContextMenu,true);window.addEventListener('resize',hideTaskContextMenu);

const renderFullPlanBeforeContext=renderFullPlan;
renderFullPlan=function(t){
  renderFullPlanBeforeContext(t);
  document.querySelectorAll('#planFormList [data-plan-row]').forEach(r=>r.oncontextmenu=e=>openItemContextMenu(e,t,+r.dataset.planRow));
};
const renderDrawerPlanBeforeContext=renderDrawerPlan;
renderDrawerPlan=function(t){
  renderDrawerPlanBeforeContext(t);
  document.querySelectorAll('#formList [data-drawer-item]').forEach(r=>r.oncontextmenu=e=>openItemContextMenu(e,t,+r.dataset.drawerItem));
};
const bindTaskCardsBeforeContext=bindTaskCards;
bindTaskCards=function(){
  bindTaskCardsBeforeContext();
  document.querySelectorAll('.taskcard').forEach(card=>card.oncontextmenu=e=>{const t=taskMap[card.dataset.id];if(t)openListContextMenu(e,t)});
};

// --- Task selection, drag ordering, Project scope and editable Project combobox ---
let selectedTaskRef=null;
function projectPathFor(key){return projectMeta[key]?.path||key||''}
function normalizeProjectRef(v){return String(v||'').replace(/[\\/]+$/,'').toLowerCase()}
function projectRefMatches(ref,key){const a=normalizeProjectRef(ref),b=normalizeProjectRef(key),p=normalizeProjectRef(projectMeta[key]?.path);return !!a&&(a===b||a===p)}
function taskRelatedToProject(t,key=currentProjectKey){
  if(!t)return false;
  if(t.projectContext===key||projectRefMatches(t.project,key))return true;
  return canonicalTaskItems(t).some(x=>projectRefMatches(x.project,key));
}
function visibleProjectTasks(){return productTaskRecords().filter(t=>taskRelatedToProject(t,currentProjectKey))}

function renderProjectOptions(){
  const dl=document.getElementById('projectOptions');if(!dl)return;
  dl.innerHTML=Object.entries(projectMeta).flatMap(([k,m])=>[`<option value="${escapeAttr(k)}" label="${escapeAttr(m.path)}"></option>`,`<option value="${escapeAttr(m.path)}" label="${escapeAttr(k)}"></option>`]).join('');
}
function uniqueProjectKey(base,path){
  let clean=String(base||'project').trim().replace(/[^A-Za-z0-9._-]+/g,'-').replace(/^-+|-+$/g,'')||'project',key=clean,n=2;
  while(projectMeta[key]&&normalizeProjectRef(projectMeta[key].path)!==normalizeProjectRef(path))key=`${clean}-${n++}`;
  return key;
}
function appendProjectSidebarEntry(key,subtitle='main · Added'){
  const host=document.getElementById('projectScroll');if(!host||host.querySelector(`.project[data-project="${CSS.escape(key)}"]`))return;
  const btn=document.createElement('button');btn.className='project project-list-item project-combobox-new';btn.type='button';btn.dataset.project=key;
  btn.innerHTML=`<span class="dot"></span><span class="project-copy"><strong>${escapeHtml(key)}</strong><small>${escapeHtml(subtitle)}</small></span>`;
  host.appendChild(btn);if(typeof syncProjectRowMenus==='function')syncProjectRowMenus();
}
function registerProject(key,path,{subtitle='main · Added'}={}){
  key=String(key||'').trim();path=String(path||'').trim();if(!key||!path||projectMeta[key])return null;
  projectMeta[key]={path,branch:'main'};
  if(typeof initializeProjectChatSettings==='function')initializeProjectChatSettings(key);
  appendProjectSidebarEntry(key,subtitle);renderProjectOptions();return key;
}
function ensureProjectFromInput(raw){
  raw=String(raw||'').trim();if(projectMeta[raw])return raw;
  const found=Object.keys(projectMeta).find(k=>normalizeProjectRef(projectMeta[k].path)===normalizeProjectRef(raw));if(found)return found;
  const key=uniqueProjectKey(basename(raw),raw);
  registerProject(key,raw,{subtitle:'main · Added from Task'});
  showToast(`Project added · ${key}`);return key;
}
renderProjectOptions();
document.getElementById('newTaskProject').addEventListener('input',()=>renderNewTaskWorkspace());

function setTaskViewMode(mode){
  listMode=mode==='list';document.getElementById('board').classList.toggle('hiddenboard',listMode);document.getElementById('taskListView').classList.toggle('active',listMode);
  document.getElementById('boardMode').classList.toggle('active',!listMode);document.getElementById('listMode').classList.toggle('active',listMode);
}
document.getElementById('boardMode').onclick=()=>setTaskViewMode('board');document.getElementById('listMode').onclick=()=>setTaskViewMode('list');

applyTaskFilter=function(){
  const q=document.getElementById('taskSearch').value.trim().toLowerCase();
  document.querySelectorAll('.taskcard').forEach(card=>{const t=taskMap[card.dataset.id],projectOk=taskRelatedToProject(t,currentProjectKey),queryOk=!q||card.textContent.toLowerCase().includes(q),runOk=!runningOnly||['running','recover'].includes(t?.runtime);card.hidden=!(projectOk&&queryOk&&runOk)});
  document.querySelectorAll('#taskListView [data-taskrow]').forEach(row=>{const t=taskMap[row.dataset.taskrow],projectOk=taskRelatedToProject(t,currentProjectKey),queryOk=!q||row.textContent.toLowerCase().includes(q),runOk=!runningOnly||['running','recover'].includes(t?.runtime);row.hidden=!(projectOk&&queryOk&&runOk)});
  updateCounts();
};
const projectScopedRenderTaskList=renderTaskList;
renderTaskList=function(){projectScopedRenderTaskList();applyTaskFilter()};
const projectScopedUpdateCounts=updateCounts;
updateCounts=function(){
  projectScopedUpdateCounts();const visible=visibleProjectTasks();document.getElementById('taskNavCount').textContent=visible.length;document.getElementById('runningCount').textContent=`${visible.filter(t=>['running','recover'].includes(t.runtime)).length} Running`;
};
const projectScopedSelect=selectProject;
selectProject=function(key){projectScopedSelect(key);if(typeof renderBoardFromMap==='function')renderBoardFromMap()};

function selectedItem(){if(!selectedTaskRef)return null;const owner=taskMap[selectedTaskRef.ownerId],item=owner?canonicalTaskItems(owner)[selectedTaskRef.index]:null;return owner&&item?{owner,item,index:selectedTaskRef.index}:null}
function syncWorkflowActions(){
  const s=selectedItem(),ok=!!(s?.item?.workflow&&s.item.workflow!=='—'&&s.item.workflow!=='Tasks');
  const planBtn=document.getElementById('planOpenWorkflow'),drawerBtn=document.getElementById('openWorkflowDemo');
  planBtn.hidden=!(ok&&document.getElementById('planModal').classList.contains('open'));
  drawerBtn.hidden=!(ok&&document.getElementById('taskOverlay').classList.contains('open')&&s.owner.id===currentTaskId);
}
function selectTaskItem(owner,index){
  if(!owner||!canonicalTaskItems(owner)[index])return;selectedTaskRef={ownerId:owner.id,index};
  document.querySelectorAll('#planFormList [data-plan-row]').forEach(r=>r.classList.toggle('selected',owner.id===selectedTaskRef.ownerId&&+r.dataset.planRow===index));
  document.querySelectorAll('#formList [data-drawer-item]').forEach(r=>r.classList.toggle('selected',owner.id===selectedTaskRef.ownerId&&+r.dataset.drawerItem===index));
  syncWorkflowActions();
}
function clearTaskSelection(){selectedTaskRef=null;syncWorkflowActions()}
function openSelectedWorkflow(){const s=selectedItem();if(!s)return;closeModal('planModal');document.getElementById('taskOverlay').classList.remove('open');showView('workflows');showToast(`Open Workflow · ${s.item.workflow}`)}
document.getElementById('planOpenWorkflow').onclick=openSelectedWorkflow;document.getElementById('openWorkflowDemo').onclick=openSelectedWorkflow;

function canDragTaskItem(t,index){const items=canonicalTaskItems(t),s=planStateFor(t,index,items.length);if(!taskEditable(t)||s.done)return false;if(t.status==='paused'&&index<=batchState.index)return false;return true}
let planDragIndex=null;
function bindPlanSelectionAndDrag(t){
  const host=document.getElementById('planFormList');
  host.querySelectorAll('[data-plan-row]').forEach(row=>{
    const i=+row.dataset.planRow,canDrag=canDragTaskItem(t,i);row.draggable=canDrag;
    const num=row.querySelector('.plan-row-num');if(num){num.querySelectorAll('.drag-grip').forEach(x=>x.remove());if(!row.querySelector('.plan-row-head > .drag-grip'))num.insertAdjacentHTML('beforebegin','<span class="drag-grip" aria-hidden="true">⠿</span>')}
    row.onclick=e=>{if(e.target.closest('button'))return;selectTaskItem(t,i)};
    row.ondblclick=e=>{if(e.target.closest('button'))return;selectTaskItem(t,i);const s=planStateFor(t,i,canonicalTaskItems(t).length);if(taskEditable(t)&&!s.done)loadTaskEditor('edit-item',{ownerId:t.id,index:i})};
    row.ondragstart=e=>{if(!canDrag){e.preventDefault();return}planDragIndex=i;row.classList.add('dragging');e.dataTransfer.effectAllowed='move'};
    row.ondragover=e=>{if(planDragIndex==null||!canDragTaskItem(t,i))return;e.preventDefault();row.classList.add('drag-over')};
    row.ondragleave=()=>row.classList.remove('drag-over');
    row.ondrop=e=>{e.preventDefault();row.classList.remove('drag-over');if(planDragIndex==null||planDragIndex===i||!canDragTaskItem(t,i))return;if(batchParentTaskId!==t.id)setPlanDraftForTask(t);const moved=batchDraft.splice(planDragIndex,1)[0];let target=i;if(planDragIndex<i)target--;batchDraft.splice(target,0,moved);commitPlanDraft(t);persistCurrentPresetFromTaskMap();selectedTaskRef={ownerId:t.id,index:target};planDragIndex=null;renderBoardFromMap();renderFullPlan(t);renderDrawerPlan(t);showToast('Task order updated')};
    row.ondragend=()=>{planDragIndex=null;row.classList.remove('dragging');host.querySelectorAll('.drag-over').forEach(x=>x.classList.remove('drag-over'))};
  });
}

const taskSelectRenderFullPlan=renderFullPlan;
renderFullPlan=function(t){taskSelectRenderFullPlan(t);bindPlanSelectionAndDrag(t);if(selectedTaskRef?.ownerId===t.id&&canonicalTaskItems(t)[selectedTaskRef.index])selectTaskItem(t,selectedTaskRef.index);else syncWorkflowActions()};
const taskSelectRenderDrawerPlan=renderDrawerPlan;
renderDrawerPlan=function(t){
  taskSelectRenderDrawerPlan(t);document.querySelectorAll('#formList [data-drawer-item]').forEach(row=>{const i=+row.dataset.drawerItem;row.onclick=e=>{if(e.target.closest('button'))return;selectTaskItem(t,i)};row.ondblclick=e=>{if(e.target.closest('button'))return;selectTaskItem(t,i);const s=planStateFor(t,i,canonicalTaskItems(t).length);if(taskEditable(t)&&!s.done)loadTaskEditor('edit-item',{ownerId:t.id,index:i})}});
  if(selectedTaskRef?.ownerId===t.id&&canonicalTaskItems(t)[selectedTaskRef.index])selectTaskItem(t,selectedTaskRef.index);else syncWorkflowActions();
};
const taskSelectOpenTask=openTaskById;
openTaskById=function(id){
  clearTaskSelection();
  planModalEl.classList.remove('open','subview-open');
  planSubviewMount.hidden=true;
  taskEditorReturnContext=null;planSubviewType=null;
  taskSelectOpenTask(id);
  const t=taskMap[id];if(t)restoreTaskInfoShell(t);
  syncWorkflowActions();
};

// Right-click selects the Task, keeps Info on the right, and offers only useful actions.
const contextItemBeforeSelection=openItemContextMenu;
openItemContextMenu=function(e,owner,index){selectTaskItem(owner,index);contextItemBeforeSelection(e,owner,index);setContextAction('workflow',{visible:true,enabled:!!canonicalTaskItems(owner)[index]?.workflow,label:'Open Workflow'});setContextAction('up',{visible:false});setContextAction('down',{visible:false})};
const contextListBeforeWorkflow=openListContextMenu;
openListContextMenu=function(e,t){contextListBeforeWorkflow(e,t);setContextAction('workflow',{visible:false})};
const contextWorkflowButton=taskContextMenu.querySelector('[data-context-action="workflow"]');if(contextWorkflowButton)contextWorkflowButton.onclick=()=>{if(contextWorkflowButton.disabled||!taskContextState)return;const state={...taskContextState};hideTaskContextMenu();if(state.scope==='item'){selectTaskItem(taskMap[state.ownerId],state.index);openSelectedWorkflow()}};

// --- Final context-menu semantics: Info = the normal right-side detail Drawer. ---
function openContextInfoDrawer(state){
  const t=taskMap[state.ownerId];if(!t)return;
  hideTaskContextMenu();
  if(planSubviewType)leavePlanSubview();
  closeModal('planModal');closeModal('addPlanTaskModal');
  openTaskById(t.id);
  if(state.scope==='item'){
    setTimeout(()=>{selectTaskItem(t,state.index);document.querySelector(`#formList [data-drawer-item="${state.index}"]`)?.scrollIntoView({block:'nearest'})},0);
  }
}
openItemContextMenu=function(e,owner,index){
  e.preventDefault();e.stopPropagation();hideCreateTypeMenu();selectTaskItem(owner,index);
  const items=canonicalTaskItems(owner),s=planStateFor(owner,index,items.length),editable=taskEditable(owner),currentLocked=owner.status==='paused'&&s.current;
  const canEdit=editable&&!s.done,canRemove=canEdit&&!currentLocked;
  taskContextState={scope:'item',ownerId:owner.id,index};
  setContextAction('open',{visible:false});
  setContextAction('edit',{visible:true,enabled:canEdit,label:'Edit'});
  setContextAction('info',{visible:true,enabled:true,label:'Info'});
  setContextAction('workflow',{visible:true,enabled:!!items[index]?.workflow&&items[index]?.workflow!=='—'&&items[index]?.workflow!=='Tasks',label:'Open Workflow'});
  setContextAction('up',{visible:false});setContextAction('down',{visible:false});
  setContextAction('remove',{visible:true,enabled:canRemove,label:'Remove'});
  positionTaskContextMenu(e.clientX,e.clientY);
};
openListContextMenu=function(e,t){
  e.preventDefault();e.stopPropagation();hideCreateTypeMenu();
  const editable=taskEditable(t),canDelete=t.status==='new'&&t.runtime==='idle';
  taskContextState={scope:'list',ownerId:t.id,index:null};
  setContextAction('open',{visible:true,enabled:true,label:'Open list'});
  setContextAction('edit',{visible:true,enabled:editable,label:'Rename'});
  setContextAction('info',{visible:true,enabled:true,label:'Info'});
  setContextAction('workflow',{visible:false});setContextAction('up',{visible:false});setContextAction('down',{visible:false});
  setContextAction('remove',{visible:true,enabled:canDelete,label:'Delete'});
  positionTaskContextMenu(e.clientX,e.clientY);
};
const contextInfoButton=taskContextMenu.querySelector('[data-context-action="info"]');
contextInfoButton.onclick=()=>{if(contextInfoButton.disabled||!taskContextState)return;openContextInfoDrawer({...taskContextState})};

// --- Project combobox polish: all Projects, current first, current as create default. ---
renderProjectOptions=function(priorityKey=currentProjectKey){
  const dl=document.getElementById('projectOptions');if(!dl)return;
  const entries=Object.entries(projectMeta).sort(([a],[b])=>{if(a===priorityKey)return -1;if(b===priorityKey)return 1;return a.localeCompare(b)});
  dl.innerHTML=entries.map(([k,m])=>`<option value="${escapeAttr(k)}" label="${escapeAttr(m.path)}${k===priorityKey?' · current':''}"></option>`).join('');
  const help=document.getElementById('projectFieldHelp'),meta=projectMeta[priorityKey];
  if(help)help.textContent=meta?`Current: ${priorityKey} · ${meta.path} · or type a new local path.`:'Select a Project or type a new local path.';
};
const projectPriorityLoadTaskEditor=loadTaskEditor;
loadTaskEditor=function(mode,args={}){
  renderProjectOptions(currentProjectKey);
  projectPriorityLoadTaskEditor(mode,args);
  const input=document.getElementById('newTaskProject');
  if(mode!=='edit-item'){input.value=currentProjectKey}else{
    const owner=taskMap[args.ownerId],item=owner?canonicalTaskItems(owner)[args.index]:null;
    if(item){const key=Object.keys(projectMeta).find(k=>projectRefMatches(item.project,k));input.value=key||item.project}
  }
  renderNewTaskWorkspace();
};
const projectOptionSelect=selectProject;
selectProject=function(key){projectOptionSelect(key);renderProjectOptions(key)};
renderProjectOptions(currentProjectKey);

// --- Explicit Project combobox: always show every added Project. ---
const projectDropdown=document.getElementById('projectDropdown');
const projectDropdownToggle=document.getElementById('projectDropdownToggle');
const projectComboInput=document.getElementById('newTaskProject');
function projectRegistryEntries(){
  const out=[],seen=new Set();
  document.querySelectorAll('.project[data-project]').forEach(btn=>{const key=btn.dataset.project;if(projectMeta[key]&&!seen.has(key)){seen.add(key);out.push([key,projectMeta[key]])}});
  Object.entries(projectMeta).forEach(([key,meta])=>{if(!seen.has(key)){seen.add(key);out.push([key,meta])}});
  return out;
}
function renderProjectDropdown(filter=''){
  const q=String(filter||'').trim().toLowerCase();
  const entries=projectRegistryEntries().filter(([key,meta])=>!q||key.toLowerCase().includes(q)||String(meta.path||'').toLowerCase().includes(q));
  projectDropdown.innerHTML=entries.length?entries.map(([key,meta])=>`<button type="button" class="project-dropdown-option ${projectRefMatches(projectComboInput.value,key)?'selected':''}" data-project-choice="${escapeAttr(key)}"><strong>${escapeHtml(key)}${key===currentProjectKey?' · current':''}</strong><small>${escapeHtml(meta.path||'')}</small></button>`).join(''):'<div class="project-dropdown-empty">No matching Project. Type a local path to add it when saving.</div>';
  projectDropdown.querySelectorAll('[data-project-choice]').forEach(b=>b.onclick=()=>{projectComboInput.value=b.dataset.projectChoice;setProjectDropdownOpen(false);renderNewTaskWorkspace()});
}
function setProjectDropdownOpen(open){
  projectDropdown.hidden=!open;projectDropdownToggle.setAttribute('aria-expanded',String(open));
}
function openProjectDropdown(showAll=true){renderProjectDropdown(showAll?'':projectComboInput.value);setProjectDropdownOpen(true)}
projectDropdownToggle.onclick=e=>{e.preventDefault();e.stopPropagation();if(projectDropdown.hidden)openProjectDropdown(true);else setProjectDropdownOpen(false)};
projectComboInput.addEventListener('focus',()=>openProjectDropdown(true));
projectComboInput.addEventListener('input',()=>{renderProjectDropdown(projectComboInput.value);setProjectDropdownOpen(true);renderNewTaskWorkspace()});
projectComboInput.addEventListener('keydown',e=>{if(e.key==='Escape')setProjectDropdownOpen(false)});
document.addEventListener('click',e=>{if(!e.target.closest('.project-combobox'))setProjectDropdownOpen(false)});

// Keep legacy datalist population harmless, but drive visible choices from the custom menu.
const visibleProjectOptions=renderProjectOptions;
renderProjectOptions=function(priorityKey=currentProjectKey){
  visibleProjectOptions(priorityKey);
  renderProjectDropdown('');
};

// --- Task Workspace final polish: direct add, inline inspector, no Russian-doll workflow. ---
function resetWorkspaceInspector(t){
  const heading=document.getElementById('planInfoHeading'),card=heading?.closest('.plan-side-card');
  if(heading)heading.textContent='List info';if(card)card.classList.remove('info-active');
  document.getElementById('planTaskSummary').innerHTML=`<span>List</span><strong>${escapeHtml(t.title)}</strong><span>Status</span><strong>${escapeHtml(statusLabel(t.status))}</strong><span>Runtime</span><strong>${escapeHtml(runtimeLabel(t.runtime))}</strong><span>Progress</span><strong>${t.progress?.[0]||0} / ${canonicalTaskItems(t).length}</strong>`;
}
function showWorkspaceItemInfo(owner,index){
  const item=canonicalTaskItems(owner)[index];if(!item)return;
  selectTaskItem(owner,index);
  const s=planStateFor(owner,index,canonicalTaskItems(owner).length),caps=workflowCaps(item.workflow);
  const goal=item.goalMode==='file'?`File · ${item.goalFile||'—'}`:item.goalMode==='asset'?`Asset · ${item.goalAsset||'—'}`:'Write';
  const ai=!caps.ai?'—':item.aiMode==='default'?'Workflow default':item.aiMode==='file'?`File · ${item.aiFile||'—'}`:item.aiMode==='asset'?`Asset · ${item.aiAsset||'—'}`:'Custom text';
  const heading=document.getElementById('planInfoHeading'),card=heading?.closest('.plan-side-card');
  if(heading)heading.textContent='Task info';if(card)card.classList.add('info-active');
  document.getElementById('planTaskSummary').innerHTML=`<span>Task</span><strong>${escapeHtml(planTitle(item,index))}</strong><span>Status</span><strong>${escapeHtml(s.label)}</strong><span>Project</span><strong>${escapeHtml(item.project||'—')}</strong><span>Workflow</span><strong>${escapeHtml(item.workflow||'—')}</strong><span>Prompt</span><strong>${escapeHtml(goal)}</strong><span>AI validation</span><strong>${escapeHtml(ai)}</strong><span>Workspace</span><strong>${escapeHtml(workspaceLabelForItem(item))}</strong><span>Branch</span><strong>${escapeHtml(item.branch||'—')}</strong><span>Path</span><strong>${escapeHtml(item.executionRoot||'—')}</strong>`;
}

// Primary Add task goes straight to the same embedded Task Editor.
function createTaskDirectlyInWorkspace(ownerId=currentTaskId,returnTarget=detectTaskEditorReturnTarget()){
  const owner=taskMap[ownerId];if(!owner||!taskEditable(owner)){showToast(owner?.status==='ongoing'?'Pause Task before editing':'Task is read-only');return}
  if(batchParentTaskId!==owner.id)setPlanDraftForTask(owner);
  loadTaskEditor('create-item',{ownerId:owner.id,index:canonicalTaskItems(owner).length,returnTarget});
}
document.getElementById('planAddTask').onclick=()=>createTaskDirectlyInWorkspace(currentTaskId,'list');
document.getElementById('drawerAddStep').onclick=()=>createTaskDirectlyInWorkspace(currentTaskId,'info');

// Move existing remains a secondary operation; only it uses the small chooser.
document.getElementById('planAddExisting').onclick=()=>{
  const owner=taskMap[currentTaskId];if(!owner||!taskEditable(owner))return;
  addPlanOwnerId=owner.id;setAddTaskMode('move');openModal('addPlanTaskModal');
};

// Keep Task Workspace open when Info is requested from an item context menu.
const workspaceInfoButton=taskContextMenu.querySelector('[data-context-action="info"]');
workspaceInfoButton.onclick=()=>{
  if(workspaceInfoButton.disabled||!taskContextState)return;
  const state={...taskContextState};hideTaskContextMenu();const owner=taskMap[state.ownerId];if(!owner)return;
  if(state.scope==='item'&&document.getElementById('planModal').classList.contains('open')){showWorkspaceItemInfo(owner,state.index);return}
  openContextInfoDrawer(state);
};

// Selecting a row only selects it; Info is opt-in from right click.
const workspaceRenderFull=renderFullPlan;
renderFullPlan=function(t){workspaceRenderFull(t);if(!selectedTaskRef||selectedTaskRef.ownerId!==t.id)resetWorkspaceInspector(t)};

// Opening a workspace switches the existing Drawer from Info -> List; no second shell is opened.
const workspaceOpenPlan=openPlanDialog;
openPlanDialog=function(id=currentTaskId,options={}){
  const t=taskMap[id];if(!t)return;
  const previousRoute=taskDrawerEl.dataset.route||'info',overlayWasOpen=taskOverlayEl.classList.contains('open');
  taskDrawerListReturnTarget=options.returnTarget||(
    t._chatDraft?'chat':
    (overlayWasOpen&&previousRoute==='info'?'info':
      overlayWasOpen&&previousRoute==='list'?taskDrawerListReturnTarget:'close')
  );
  if(taskEditorReturnContext){taskEditorReturnContext=null;hideTaskEditorView()}
  if(planSubviewType)leavePlanSubview();
  workspaceOpenPlan(id);
  planModalEl.classList.add('open');
  resetWorkspaceInspector(t);
  const meta=t._chatDraft
    ?`MOCK AI Draft · ${canonicalTaskItems(t).length} task${canonicalTaskItems(t).length===1?'':'s'}`
    :taskDrawerMetaFor(t);
  setTaskDrawerShell('list',{
    title:t.title,
    meta,
    showBack:taskDrawerListReturnTarget!=='close',
    backTitle:taskDrawerListReturnTarget==='info'?'Back to Task Info':taskDrawerListReturnTarget==='chat'?'Back to Chat Draft':'Back'
  });
  taskDrawerBack.onclick=handleTaskDrawerBack;
};
openFullPlanPage=openPlanDialog;

function handleTaskDrawerBack(){
  if(taskEditorReturnContext){leaveTaskEditorOverlay();return}
  if(planSubviewType){leavePlanSubview();return}
  workspaceInfoRef=null;clearTaskSelection();
  const t=taskMap[currentTaskId];
  if(taskDrawerListReturnTarget==='chat'||t?._chatDraft){
    planModalEl.classList.remove('open');taskOverlayEl.classList.remove('open');showView('chat');renderChatSession();return;
  }
  if(taskDrawerListReturnTarget==='info'&&t){
    planModalEl.classList.remove('open');openTaskById(t.id);return;
  }
  closeTaskDrawerShell();
}
taskDrawerBack.onclick=handleTaskDrawerBack;

// --- Workspace inspector state + secondary-action guards. ---
let workspaceInfoRef=null;
const workspaceInfoShow=showWorkspaceItemInfo;
showWorkspaceItemInfo=function(owner,index){workspaceInfoRef={ownerId:owner.id,index};workspaceInfoShow(owner,index)};
const workspaceInfoReset=resetWorkspaceInspector;
resetWorkspaceInspector=function(t){workspaceInfoRef=null;workspaceInfoReset(t)};

const workspaceGuardRender=renderFullPlan;
renderFullPlan=function(t){
  workspaceGuardRender(t);
  const editable=taskEditable(t),addExisting=document.getElementById('planAddExisting');
  addExisting.disabled=!editable||!!t._chatDraft;
  addExisting.title=t._chatDraft?'Create the Task before moving an existing Board Task into it.':'';
  if(workspaceInfoRef?.ownerId===t.id&&canonicalTaskItems(t)[workspaceInfoRef.index])workspaceInfoShow(t,workspaceInfoRef.index);
};


// --- Empty-list CTAs use the same embedded Task Editor too. ---
const directEmptyRenderFull=renderFullPlan;
renderFullPlan=function(t){
  directEmptyRenderFull(t);
  const first=document.getElementById('planEmptyAddTask');if(first)first.onclick=()=>createTaskDirectlyInWorkspace(t.id,'list');
};
const directEmptyRenderDrawer=renderDrawerPlan;
renderDrawerPlan=function(t){
  directEmptyRenderDrawer(t);
  const first=document.getElementById('emptyPlanAddTask');if(first)first.onclick=()=>{openPlanDialog(t.id);createTaskDirectlyInWorkspace(t.id,'list')};
};


// --- Practical interaction pass: fewer controls, inline rename, useful List view. ---
let workspaceRenameOriginal='';
function commitWorkspaceRename(cancel=false){
  const title=document.getElementById('drawerTitle'),t=taskMap[currentTaskId];
  if(!title||!t||title.contentEditable!=='true')return;
  const next=cancel?workspaceRenameOriginal:title.textContent.trim();
  title.contentEditable='false';title.classList.remove('editing');
  if(cancel||!next){title.textContent=t.title;return}
  if(next!==t.title){
    t.title=next;pushTaskHistory(t,'Task List renamed');persistCurrentPresetFromTaskMap();renderBoardFromMap();showToast('Task List renamed');
  }
  title.textContent=t.title;
}
function beginWorkspaceRename(t=taskMap[currentTaskId]){
  if(!t||!taskEditable(t)){showToast(t?.status==='ongoing'?'Pause before renaming':'Task List is read-only');return}
  const title=document.getElementById('drawerTitle');if(!title)return;
  workspaceRenameOriginal=t.title;title.contentEditable='true';title.classList.add('editing');title.focus();
  const range=document.createRange();range.selectNodeContents(title);const sel=window.getSelection();sel.removeAllRanges();sel.addRange(range);
}
document.getElementById('planRenameList').onclick=()=>beginWorkspaceRename();
document.getElementById('drawerTitle').addEventListener('keydown',e=>{
  if(e.key==='Enter'){e.preventDefault();commitWorkspaceRename(false)}
  if(e.key==='Escape'){e.preventDefault();commitWorkspaceRename(true)}
});
document.getElementById('drawerTitle').addEventListener('blur',()=>commitWorkspaceRename(false));

document.getElementById('closeDrawer').onclick=closeTaskDrawerShell;
taskOverlayEl.addEventListener('click',e=>{
  if(e.target!==taskOverlayEl)return;
  e.preventDefault();e.stopImmediatePropagation();closeTaskDrawerShell();
},true);
document.addEventListener('keydown',e=>{
  if(e.key!=='Escape'||!taskOverlayEl.classList.contains('open'))return;
  e.preventDefault();e.stopImmediatePropagation();
  if(taskEditorReturnContext)leaveTaskEditorOverlay();
  else if(planSubviewType)leavePlanSubview();
  else closeTaskDrawerShell();
},true);

document.getElementById('editTaskDemo').onclick=()=>{
  const t=taskMap[currentTaskId];if(!t||!taskEditable(t))return;
  openPlanDialog(t.id);setTimeout(()=>beginWorkspaceRename(t),0);
};
const contextEditAction=taskContextMenu.querySelector('[data-context-action="edit"]');
contextEditAction.onclick=()=>{
  if(contextEditAction.disabled||!taskContextState)return;
  const state={...taskContextState};hideTaskContextMenu();const t=taskMap[state.ownerId];if(!t)return;
  if(state.scope==='list'){openPlanDialog(t.id);setTimeout(()=>beginWorkspaceRename(t),0);return}
  const s=planStateFor(t,state.index,canonicalTaskItems(t).length);
  if(taskEditable(t)&&!s.done)loadTaskEditor('edit-item',{ownerId:t.id,index:state.index});
};

function polishTaskRows(t){
  document.querySelectorAll('#planFormList [data-plan-row]').forEach(row=>{
    const i=+row.dataset.planRow,grip=row.querySelector('.drag-grip');
    if(grip)grip.title=row.draggable?'Drag to reorder':'This task cannot be reordered';
    row.querySelectorAll('[data-plan-up],[data-plan-down]').forEach(b=>b.remove());
    const more=row.querySelector('[data-plan-remove]');
    if(more){
      more.disabled=false;more.textContent='⋯';more.title='More actions';more.className='row-more';
      more.onclick=e=>{
        e.preventDefault();e.stopPropagation();selectTaskItem(t,i);
        const r=more.getBoundingClientRect();
        openItemContextMenu({preventDefault(){},stopPropagation(){},clientX:r.right-4,clientY:r.bottom+4},t,i);
      };
    }
  });
}
const practicalRenderFullPlan=renderFullPlan;
renderFullPlan=function(t){
  practicalRenderFullPlan(t);polishTaskRows(t);
  const rename=document.getElementById('planRenameList');if(rename)rename.disabled=!taskEditable(t);

  const host=document.getElementById('planFormList');
  host.querySelectorAll('#planEmptyAddTask,.empty-plan-cta,.plan-add-task-footer').forEach(x=>x.remove());

  host.insertAdjacentHTML('beforeend',TaskUiTemplates.addTaskFooter());
  const add=host.querySelector(':scope > .plan-add-task-footer:last-child');
  add.disabled=!taskEditable(t);
  add.title=add.disabled?(t.status==='ongoing'?'Pause before adding tasks':'Task List is read-only'):'Add task';
  add.onclick=()=>createTaskDirectlyInWorkspace(t.id,'list');
};

renderTaskList=function(){
  const host=document.getElementById('taskListView'),rows=productTaskRecords();
  if(!rows.length){host.innerHTML='<div class="task-list-empty">No tasks in this board.</div>';return}
  const body=rows.map(t=>{
    const items=canonicalTaskItems(t),related=items.filter(x=>projectRefMatches(x.project,currentProjectKey)).length;
    const projectSummary=items.length>1?(`${related}/${items.length} in ${currentProjectKey}`):(items[0]?basename(items[0].project):currentProjectKey);
    const worktree=taskUsesWorktree(t);
    return `<div class="taskrow taskrow-data ${worktree?'worktree-row':''}" data-taskrow="${t.id}">
      <span class="pill">${escapeHtml(statusLabel(t.status))}</span>
      <span class="taskrow-title"><strong>${escapeHtml(t.title)}</strong><small>${escapeHtml(t.desc||'')}${worktree?' · WORKTREE':''}</small></span>
      <span class="taskrow-count">${items.length}</span>
      <span class="runtime ${runtimeClass(t.runtime)}">${escapeHtml(runtimeLabel(t.runtime))}</span>
      <span class="taskrow-project">${escapeHtml(projectSummary)}</span>
      <span class="taskrow-progress">${t.progress?.[0]||0} / ${items.length}</span>
    </div>`;
  }).join('');
  host.innerHTML=`<div class="task-list-table">
    <div class="taskrow taskrow-head"><span>Status</span><span>Name</span><span>Tasks</span><span>Runtime</span><span>Project</span><span>Progress</span></div>
    ${body}
  </div>`;
  host.querySelectorAll('[data-taskrow]').forEach(r=>{
    r.onclick=()=>openTaskById(r.dataset.taskrow);
    r.ondblclick=()=>openPlanDialog(r.dataset.taskrow);
    r.oncontextmenu=e=>{const t=taskMap[r.dataset.taskrow];if(t)openListContextMenu(e,t)};
  });
  applyTaskFilter();
};

const practicalResetWorkspaceInspector=resetWorkspaceInspector;
resetWorkspaceInspector=function(t){
  workspaceInfoRef=null;
  const heading=document.getElementById('planInfoHeading'),card=heading?.closest('.plan-side-card');
  if(heading)heading.textContent='List info';if(card)card.classList.remove('info-active');
  const items=canonicalTaskItems(t),active=items.length?Math.min(t.progress?.[0]||0,items.length-1)+1:0;
  document.getElementById('planTaskSummary').innerHTML=`<span>List</span><strong>${escapeHtml(t.title)}</strong><span>Status</span><strong>${escapeHtml(statusLabel(t.status))}</strong><span>Runtime</span><strong>${escapeHtml(runtimeLabel(t.runtime))}</strong><span>Tasks</span><strong>${items.length}</strong><span>Progress</span><strong>${t.progress?.[0]||0} / ${items.length}</strong><span>Current</span><strong>${items.length?('Task '+active):'—'}</strong>`;
};

positionTaskContextMenu=function(x,y){
  taskContextMenu.hidden=false;const w=205,h=220;
  taskContextMenu.style.left=`${Math.min(window.innerWidth-w-8,Math.max(8,x))}px`;
  taskContextMenu.style.top=`${Math.min(window.innerHeight-h-8,Math.max(8,y))}px`;
};


/* Shared Task UI controller.
   Chat / Board / Task List call this facade instead of owning separate DOM/renderers.
   Future React maps this boundary to TaskEditor + TaskListWorkspace components. */
window.TaskUi=Object.freeze({
  openEditor(mode,args={}){return loadTaskEditor(mode,args)},
  openList(ownerId=currentTaskId){return openPlanDialog(ownerId)},
  createList(){return createEmptyTaskListAndOpen()},
  addTask(ownerId=currentTaskId,returnTarget=detectTaskEditorReturnTarget()){return createTaskDirectlyInWorkspace(ownerId,returnTarget)}
});
