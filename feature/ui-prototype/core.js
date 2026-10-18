const views=[...document.querySelectorAll('.view')];
const nav=[...document.querySelectorAll('.navbtn[data-view]')];
function showView(name){
  views.forEach(v=>v.classList.toggle('active',v.id==='view-'+name));
  nav.forEach(b=>b.classList.toggle('active',b.dataset.view===name));
}
nav.forEach(b=>b.addEventListener('click',()=>showView(b.dataset.view)));

const toast=document.getElementById('toast');
let toastTimer;
function showToast(msg){toast.textContent=msg;toast.classList.add('show');clearTimeout(toastTimer);toastTimer=setTimeout(()=>toast.classList.remove('show'),1900)}
const AUTO_WORKSPACE_POLICY_KEY='ai-task-runner.prototype.autoWorkspacePolicy';
const INTERFACE_SETTINGS_KEY='ai-task-runner.prototype.interfaceSettings';
const AUTO_WORKSPACE_POLICIES=new Set(['busy_worktree','main_only','always_worktree']);
const THEME_PALETTES=new Set(['teal','blue','violet','amber','rose']);
const APPEARANCES=new Set(['system','light','dark']);
const LANGUAGES=new Set(['zh-TW','en']);
const UI_TEXT={
  'zh-TW':{
    'chat.rename':'重新命名','chat.delete':'刪除','chat.newChat':'+ 新對話','chat.deleteTitle':'刪除對話？','chat.deleteHelp':'只會刪除目前 Project 的這個 Chat；Tasks 不受影響。','chat.deleteCancel':'取消','chat.deleteConfirm':'刪除對話','chat.commands':'指令','chat.typeToFilter':'輸入以篩選',
    'chat.project':'PROJECT','chat.runSettings':'執行設定','chat.workflow':'Workflow','chat.workflowHelp':'供 @goal 與新的 Chat 任務使用',
    'chat.agent':'Agent','chat.savedProject':'儲存在目前 Project','chat.model':'Model','chat.reasoning':'推理程度','chat.reasoningHelp':'此 Project 使用的推理程度',
    'chat.turnRunning':'Agent 正在處理；送出訊息會自動加入 Queue','chat.turnWaiting':'Agent 正在等待 Ask 回答；新訊息會排隊',
    'chat.pending':'待處理','chat.queueHint':'Agent 忙碌時，送出會自動排隊',
    'chat.inputPlaceholder':'傳訊息給 AI…  @ = Runner 指令 · / = Agent Skill / Command',
    'chat.settingsTitle':'Chat 執行設定','chat.modeTitle':'權限 / 核准模式','chat.mode':'Mode',
    'chat.newTask':'+ 新增 Task','chat.newTaskTitle':'在目前 Project 建立 Task 或 Task List',
    'chat.send':'傳送',
    'chat.runnerPrompts':'Runner prompts','chat.agentCommands':'{agent} · Skills / Commands',
    'chat.runnerHint':'@ = AI Task Runner','chat.agentHint':'/ = 已選 Agent · MOCK {agent}',
    'chat.queueSave':'儲存','chat.queueCancel':'取消','chat.queueEdit':'編輯','chat.queueDelete':'刪除',
    'chat.queueEmpty':'排隊訊息不可空白','chat.queueUpdated':'Queue 已更新','chat.addedQueue':'已加入 Queue',
    'chat.askOptional':'選填','chat.askClarification':'釐清問題','chat.askQuestion':'第 {current} 題，共 {total} 題',
    'chat.askCancel':'取消','chat.askNext':'下一步','chat.askSubmit':'提交',
    'chat.askOther':'其他（自行輸入）','chat.askOtherDesc':'輸入自己的答案',
    'chat.askCustomPlaceholder':'輸入自訂答案…','chat.askOptionalPlaceholder':'選填，可直接下一步','chat.askAnswerPlaceholder':'輸入你的回答…',
    'chat.askChoose':'請先選擇一個選項','chat.askRequired':'請填寫回答','chat.askCancelled':'Mock Ask 已取消；未提交任何答案。',
    'task.createTask':'Task','task.createTaskDesc':'建立一個 Task，使用共用 Task Editor。',
    'task.createList':'Task List','task.createListDesc':'建立 Task List 草稿，再加入其中的 Tasks。','taskList.empty':'目前沒有 Task','taskList.addFirst':'+ 加入第一個 Task','taskList.add':'加入 Task','taskList.back':'返回','taskList.backInfo':'返回 Info',
    'taskListDraft.cancel':'取消','taskListDraft.create':'建立 Task List','taskListDraft.meta':'草稿 · 尚未建立','taskListDraft.draft':'草稿',
    'taskListDraft.info':'草稿資訊','taskListDraft.noTasks':'目前沒有 Task','taskListDraft.addFirst':'+ 加入第一個 Task',
    'taskListDraft.title':'標題','taskListDraft.project':'Project','taskListDraft.tasks':'Tasks','taskListDraft.state':'狀態',
    'taskListDraft.notCreated':'尚未建立','taskListDraft.defaultTitle':'新增 Task List','taskListDraft.listInfo':'List 資訊','taskListDraft.needTask':'建立 Task List 前至少要加入一個 Task',
    'taskListDraft.titleRequired':'Task List 標題不可空白','taskListDraft.created':'Task List 已建立 · 可繼續加入 Task',
    'taskListDraft.added':'已加入草稿 Task','taskListDraft.updated':'已更新草稿 Task','taskListDraft.removed':'已移除草稿 Task',
    'taskListDraft.edit':'編輯','taskListDraft.moveUp':'上移','taskListDraft.moveDown':'下移','taskListDraft.remove':'移除',
    'taskListDraft.discardTitle':'捨棄 Task List 草稿？','taskListDraft.discardHelp':'這個草稿尚未建立，捨棄後不會出現在 Board。','taskListDraft.discardBody':'目前有尚未建立的變更。確定要捨棄這份 Task List 草稿嗎？','taskListDraft.keepEditing':'繼續編輯','taskListDraft.discard':'捨棄草稿',
    'taskListDraft.creating':'建立中…','taskEditor.discardTitle':'捨棄 Task 修改？','taskEditor.discardHelp':'Task Editor 中尚未儲存的修改會遺失。','taskEditor.discardBody':'確定要捨棄尚未儲存的修改並離開編輯器嗎？','taskEditor.keepEditing':'繼續編輯','taskEditor.discard':'捨棄修改','yaml.discardTitle':'捨棄 YAML 修改？','yaml.discardHelp':'尚未套用的 YAML 修改會遺失。','yaml.discardBody':'確定要捨棄 YAML 修改並離開編輯器嗎？','yaml.keepEditing':'繼續編輯','yaml.discard':'捨棄修改',
    'common.save':'儲存','common.cancel':'取消','common.edit':'編輯','common.delete':'刪除','common.dismiss':'關閉','common.openTask':'開啟 Task',
    'chat.you':'你','chat.assistant':'Assistant','chat.working':'Agent 正在處理…','chat.emptyTitle':'新對話','chat.emptyDesc':'這個 session 只屬於目前 Project。',
    'chat.draft.created':'已建立','chat.draft.mock':'MOCK AI · TASK 草稿','chat.draft.task':'Task','chat.draft.taskList':'Task List',
    'chat.draft.newNotRunning':'New · 尚未執行','chat.draft.review':'建立前請先確認','chat.draft.count':'{count} 個 Task',
    'chat.draft.create':'建立 Task',
    'chat.cmd.goal.title':'執行 Goal','chat.cmd.goal.desc':'建立一個 Ongoing Task，並使用 Chat 設定中的 Workflow 立即開始。',
    'chat.cmd.task.title':'AI 決定 Task 或 Task List','chat.cmd.task.desc':'產生一個 Task 或多個有序 Tasks；Mock 會隨機選擇以供測試。',
    'chat.cmd.single.title':'建立單一 Task','chat.cmd.single.desc':'強制產生的 TaskDraft 只包含一個 Task。',
    'chat.cmd.list.title':'建立 Task List','chat.cmd.list.desc':'強制產生的 TaskDraft 包含兩個以上有序 Tasks。',
    'chat.cmd.workflow.title':'產生 Workflow','chat.cmd.workflow.desc':'模擬既有 Generate Workflow 類型的 system prompt。',
    'chat.cmd.project.title':'Project context','chat.cmd.project.desc':'顯示綁定到此 Chat 的 Project context。',
    'chat.cmd.ask.title':'Mock AI 反問','chat.cmd.ask.desc':'強制觸發多題 AI clarification 流程。',
    'chat.ask.scopeHeader':'實作範圍','chat.ask.scopeQuestion':'針對「{context}」你希望優先採用哪種處理方式？','chat.ask.scopeQuestionPlain':'你希望優先採用哪種處理方式？',
    'chat.ask.minimal':'最小修改','chat.ask.minimalDesc':'只改必要範圍，降低 regression',
    'chat.ask.full':'完整優化','chat.ask.fullDesc':'連同鄰近 UX / code ownership 一起整理',
    'chat.ask.analyze':'先分析','chat.ask.analyzeDesc':'先確認設計與風險，再進行修改',
    'chat.ask.mockFirst':'先做 UI Mock','chat.ask.mockFirstDesc':'先完成可操作 prototype，再接正式 backend',
    'chat.ask.verifyHeader':'驗證','chat.ask.verifyQuestion':'這次驗證希望做到什麼程度？',
    'chat.ask.focused':'Focused tests','chat.ask.focusedDesc':'只跑直接相關測試',
    'chat.ask.regression':'Regression tests','chat.ask.regressionDesc':'包含鄰近功能 regression',
    'chat.ask.mockVerify':'Mock first','chat.ask.mockVerifyDesc':'先完成 Mock / prototype 驗證',
    'chat.ask.live':'Live integration','chat.ask.liveDesc':'接真實 Agent / backend 驗證',
    'chat.ask.extraHeader':'補充資訊','chat.ask.extraQuestion':'還有沒有需要 Agent 特別注意的限制或補充？'
  },
  en:{
    'chat.rename':'Rename','chat.delete':'Delete','chat.newChat':'+ New Chat','chat.deleteTitle':'Delete Chat?','chat.deleteHelp':'This removes only this Chat from the current Project. Tasks are unchanged.','chat.deleteCancel':'Cancel','chat.deleteConfirm':'Delete Chat','chat.commands':'Commands','chat.typeToFilter':'Type to filter',
    'chat.project':'PROJECT','chat.runSettings':'Run settings','chat.workflow':'Workflow','chat.workflowHelp':'Used by @goal and new Chat tasks',
    'chat.agent':'Agent','chat.savedProject':'Saved for this Project','chat.model':'Model','chat.reasoning':'Reasoning','chat.reasoningHelp':'Reasoning effort saved for this Project',
    'chat.turnRunning':'Agent is working; new messages are queued automatically','chat.turnWaiting':'Agent is waiting for Ask answers; new messages are queued',
    'chat.pending':'pending','chat.queueHint':'Messages are queued automatically while the Agent is busy',
    'chat.inputPlaceholder':'Message AI…  @ = Runner command · / = Agent Skill / Command',
    'chat.settingsTitle':'Chat run settings','chat.modeTitle':'Permission / approval mode','chat.mode':'Mode',
    'chat.newTask':'+ New Task','chat.newTaskTitle':'Create a Task or Task List for this Project',
    'chat.send':'Send',
    'chat.runnerPrompts':'Runner prompts','chat.agentCommands':'{agent} · Skills / Commands',
    'chat.runnerHint':'@ = AI Task Runner','chat.agentHint':'/ = selected Agent · MOCK {agent}',
    'chat.queueSave':'Save','chat.queueCancel':'Cancel','chat.queueEdit':'Edit','chat.queueDelete':'Delete',
    'chat.queueEmpty':'Queued prompt cannot be empty','chat.queueUpdated':'Queue updated','chat.addedQueue':'Added to Queue',
    'chat.askOptional':'Optional','chat.askClarification':'Clarification','chat.askQuestion':'Question {current} of {total}',
    'chat.askCancel':'Cancel','chat.askNext':'Next','chat.askSubmit':'Submit',
    'chat.askOther':'Other (type your own)','chat.askOtherDesc':'Enter your own answer',
    'chat.askCustomPlaceholder':'Enter a custom answer…','chat.askOptionalPlaceholder':'Optional; you can go directly to Next','chat.askAnswerPlaceholder':'Enter your answer…',
    'chat.askChoose':'Choose an option first','chat.askRequired':'Enter an answer','chat.askCancelled':'Mock Ask cancelled; no answers were submitted.',
    'task.createTask':'Task','task.createTaskDesc':'Create one Task using the shared Task Editor.',
    'task.createList':'Task List','task.createListDesc':'Create a Task List draft, then add Tasks inside it.','taskList.empty':'No tasks yet','taskList.addFirst':'+ Add first task','taskList.add':'Add task','taskList.back':'Back','taskList.backInfo':'Back to Info',
    'taskListDraft.cancel':'Cancel','taskListDraft.create':'Create Task List','taskListDraft.meta':'Draft · not created yet','taskListDraft.draft':'Draft',
    'taskListDraft.info':'Draft info','taskListDraft.noTasks':'No tasks yet','taskListDraft.addFirst':'+ Add first task',
    'taskListDraft.title':'Title','taskListDraft.project':'Project','taskListDraft.tasks':'Tasks','taskListDraft.state':'State',
    'taskListDraft.notCreated':'Not created','taskListDraft.defaultTitle':'New Task List','taskListDraft.listInfo':'List info','taskListDraft.needTask':'Add at least one task before creating the Task List',
    'taskListDraft.titleRequired':'Task List title cannot be empty','taskListDraft.created':'Task List created · add tasks when ready',
    'taskListDraft.added':'Draft task added','taskListDraft.updated':'Draft task updated','taskListDraft.removed':'Draft task removed',
    'taskListDraft.edit':'Edit','taskListDraft.moveUp':'Move up','taskListDraft.moveDown':'Move down','taskListDraft.remove':'Remove',
    'taskListDraft.discardTitle':'Discard Task List draft?','taskListDraft.discardHelp':'This draft has not been created and will not appear on the Board if discarded.','taskListDraft.discardBody':'There are uncreated changes in this Task List draft. Discard them?','taskListDraft.keepEditing':'Keep editing','taskListDraft.discard':'Discard draft',
    'taskListDraft.creating':'Creating…','taskEditor.discardTitle':'Discard task changes?','taskEditor.discardHelp':'Unsaved changes in this Task Editor will be lost.','taskEditor.discardBody':'Discard the unsaved changes and leave this editor?','taskEditor.keepEditing':'Keep editing','taskEditor.discard':'Discard changes','yaml.discardTitle':'Discard YAML changes?','yaml.discardHelp':'Unsaved YAML changes will be lost.','yaml.discardBody':'Discard the unsaved YAML changes and leave this editor?','yaml.keepEditing':'Keep editing','yaml.discard':'Discard changes',
    'common.save':'Save','common.cancel':'Cancel','common.edit':'Edit','common.delete':'Delete','common.dismiss':'Dismiss','common.openTask':'Open Task',
    'chat.you':'You','chat.assistant':'Assistant','chat.working':'Agent is working…','chat.emptyTitle':'New Chat','chat.emptyDesc':'This session belongs only to the current Project.',
    'chat.draft.created':'CREATED','chat.draft.mock':'MOCK AI · TASK DRAFT','chat.draft.task':'Task','chat.draft.taskList':'Task List',
    'chat.draft.newNotRunning':'New · not running','chat.draft.review':'Review before Create','chat.draft.count':'{count} task(s)',
    'chat.draft.create':'Create Task',
    'chat.cmd.goal.title':'Run goal','chat.cmd.goal.desc':'Create one Task in Ongoing and start immediately with the Workflow selected in Chat settings.',
    'chat.cmd.task.title':'AI decides Task or Task List','chat.cmd.task.desc':'Create one Task or multiple ordered Tasks; Mock randomly chooses for testing.',
    'chat.cmd.single.title':'Create one Task','chat.cmd.single.desc':'Force the generated TaskDraft to contain exactly one Task.',
    'chat.cmd.list.title':'Create Task List','chat.cmd.list.desc':'Force the generated TaskDraft to contain two or more ordered Tasks.',
    'chat.cmd.workflow.title':'Generate Workflow','chat.cmd.workflow.desc':'Mock the existing Generate Workflow-style system prompt.',
    'chat.cmd.project.title':'Project context','chat.cmd.project.desc':'Show the Project context bound to this Chat.',
    'chat.cmd.ask.title':'Mock AI clarification','chat.cmd.ask.desc':'Force a multi-question AI clarification flow.',
    'chat.ask.scopeHeader':'Implementation scope','chat.ask.scopeQuestion':'For “{context}”, which approach should be prioritized?','chat.ask.scopeQuestionPlain':'Which approach should be prioritized?',
    'chat.ask.minimal':'Minimal change','chat.ask.minimalDesc':'Change only what is necessary to reduce regression risk',
    'chat.ask.full':'Full optimization','chat.ask.fullDesc':'Also clean up nearby UX and code ownership',
    'chat.ask.analyze':'Analyze first','chat.ask.analyzeDesc':'Confirm design and risks before making changes',
    'chat.ask.mockFirst':'UI Mock first','chat.ask.mockFirstDesc':'Finish an interactive prototype before wiring the real backend',
    'chat.ask.verifyHeader':'Verification','chat.ask.verifyQuestion':'How much verification should this change receive?',
    'chat.ask.focused':'Focused tests','chat.ask.focusedDesc':'Run only directly related tests',
    'chat.ask.regression':'Regression tests','chat.ask.regressionDesc':'Include nearby regression coverage',
    'chat.ask.mockVerify':'Mock first','chat.ask.mockVerifyDesc':'Validate the Mock / prototype first',
    'chat.ask.live':'Live integration','chat.ask.liveDesc':'Verify against the real Agent / backend',
    'chat.ask.extraHeader':'Extra context','chat.ask.extraQuestion':'Any constraints or extra context the Agent should pay special attention to?'
  }
};
function uiText(key,vars={}){
  const language=globalInterfaceSettings?.language||'zh-TW';
  let value=UI_TEXT[language]?.[key]??UI_TEXT.en[key]??key;
  return String(value).replace(/\{(\w+)\}/g,(_,name)=>vars[name]??'');
}
function applyUiTranslations(root=document){
  root.querySelectorAll('[data-i18n]').forEach(el=>el.textContent=uiText(el.dataset.i18n));
  root.querySelectorAll('[data-i18n-placeholder]').forEach(el=>el.setAttribute('placeholder',uiText(el.dataset.i18nPlaceholder)));
  root.querySelectorAll('[data-i18n-title]').forEach(el=>el.setAttribute('title',uiText(el.dataset.i18nTitle)));
  root.querySelectorAll('[data-i18n-aria-label]').forEach(el=>el.setAttribute('aria-label',uiText(el.dataset.i18nAriaLabel)));
}
window.uiText=uiText;
window.applyUiTranslations=applyUiTranslations;
function loadAutoWorkspacePolicy(){
  try{const value=localStorage.getItem(AUTO_WORKSPACE_POLICY_KEY);if(AUTO_WORKSPACE_POLICIES.has(value))return value}catch(_){}
  return 'busy_worktree';
}
function loadInterfaceSettings(){
  const boot=window.UiBootstrap?.state?.interfaceSettings;
  if(boot)return {...boot};
  try{
    const raw=JSON.parse(localStorage.getItem(INTERFACE_SETTINGS_KEY)||'{}'),legacyAppearance=APPEARANCES.has(raw.theme)?raw.theme:null;
    return {theme:THEME_PALETTES.has(raw.theme)?raw.theme:'teal',appearance:APPEARANCES.has(raw.appearance)?raw.appearance:(legacyAppearance||'system'),language:LANGUAGES.has(raw.language)?raw.language:'zh-TW'};
  }catch(_){return {theme:'teal',appearance:'system',language:'zh-TW'}}
}
const globalExecutionSettings={autoWorkspacePolicy:loadAutoWorkspacePolicy()};
const globalInterfaceSettings=loadInterfaceSettings();
function saveAutoWorkspacePolicy(){try{localStorage.setItem(AUTO_WORKSPACE_POLICY_KEY,globalExecutionSettings.autoWorkspacePolicy)}catch(_){}}
function saveInterfaceSettings(){try{localStorage.setItem(INTERFACE_SETTINGS_KEY,JSON.stringify(globalInterfaceSettings))}catch(_){}}
function resolvedAppearance(){return globalInterfaceSettings.appearance==='system'?(window.matchMedia?.('(prefers-color-scheme: dark)').matches?'dark':'light'):globalInterfaceSettings.appearance}
function applyInterfaceSettings(){document.documentElement.dataset.theme=globalInterfaceSettings.theme;document.documentElement.dataset.appearancePreference=globalInterfaceSettings.appearance;document.documentElement.dataset.appearance=resolvedAppearance();document.documentElement.lang=globalInterfaceSettings.language;applyUiTranslations()}
applyInterfaceSettings();
function autoWorkspaceKind(busy){
  if(globalExecutionSettings.autoWorkspacePolicy==='always_worktree')return 'worktree';
  if(globalExecutionSettings.autoWorkspacePolicy==='main_only')return 'main';
  return busy?'worktree':'main';
}
function autoWorkspacePolicyDescription(){
  return globalExecutionSettings.autoWorkspacePolicy==='always_worktree'
    ?'Auto always creates an isolated Worktree.'
    :globalExecutionSettings.autoWorkspacePolicy==='main_only'
      ?'Auto always uses Main; if Main is busy, the Run is blocked.'
      :'Auto uses Main when idle and switches to Worktree when the project is busy.';
}
function autoWorkspaceStatus(busy,id='Task'){
  const kind=autoWorkspaceKind(!!busy);
  if(kind==='worktree')return globalExecutionSettings.autoWorkspacePolicy==='always_worktree'?`${id} → Worktree`:`${busy?'Main busy → ':''}${id} → Worktree`;
  return busy?'Main busy → Run blocked':'Main available → Main';
}

const projectMeta={
  'ai-task-runner':{path:'C:\\Users\\kevin\\ai-task-runner',branch:'feature/ui'},
  'game-client':{path:'D:\\dev\\game-client',branch:'main'},
  'lab-tools':{path:'D:\\lab\\tools',branch:'dev'},
  'demo-api':{path:'D:\\dev\\demo-api',branch:'main'},
  'web-console':{path:'D:\\dev\\web-console',branch:'feature/dashboard'},
  'sandbox-lab':{path:'D:\\lab\\sandbox-lab',branch:'main'}
};
// Project list behavior is bound after currentProjectKey is initialized.

const chatPresets={
  design:[
    ['assistant','這裡是一般 Chat。你可以討論設計、程式或目前 Project；只有明確建立 Task 才交給 Workflow Runner。'],
    ['user','Task board 要怎樣才不會跟 runtime state 混在一起？'],
    ['assistant','把 Board status 當工作管理狀態；Running / Recovering / Stopped / Completed 則只讀 Runner projection。拖卡片不直接改 process。']
  ],
  debug:[
    ['user','Stage test 偶爾 502，先幫我分析可能是哪一層。'],
    ['assistant','我會先看 backend adapter、StageExecutor technical retry 與 server endpoint；這是互動式除錯，不會自動建立長時間 Task。'],
    ['user','如果確認是 API transient error 呢？'],
    ['assistant','就應沿用 StageExecutor 的 same-session retry / fresh rotation 與 seconds-based backoff，不在 Chat UI 另造 recovery。']
  ],
  review:[
    ['user','幫我 review 這次 UI 修改，先只指出問題。'],
    ['assistant','可以。我會把問題分成 UX、runtime ownership、state consistency 與維護性；若要實際修改，再由你建立 Task 或明確要求執行。']
  ],
  long:[
    ['assistant','這個情境用來測試長對話。'],
    ['user','我希望 Task、Task List、Workflow、Prompt 都能一起用，但不要讓 UI 變得很複雜。'],
    ['assistant','建議把互動責任分清楚：Chat 負責討論；Task 負責工作管理與 runtime projection；Task Lists 負責 batch RunRequest；Workflows / Prompts 維持原本資產管理。'],
    ['user','那從 Chat 轉成 Task 呢？'],
    ['assistant','可以提供「建立 Task」明確動作，把目前輸入帶入 New Task 表單，但不應自動執行。這樣操作快速，也不會讓一般聊天誤觸 Runner。'],
    ['user','如果 Task 正在 Recovering，能直接拖 Closed 嗎？'],
    ['assistant','不建議。Running / Recovering 代表 Runner 還在處理，應先 Stop，再允許 Board 移到 Paused / Closed，避免工作管理狀態和真實 runtime 打架。']
  ],
  empty:[]
};
function renderChat(key){
  const box=document.getElementById('chatMessages');box.innerHTML='';
  (chatPresets[key]||[]).forEach(([who,body])=>{
    const el=document.createElement('div');el.className='msg '+who;
    el.innerHTML=(who==='assistant'?'<div class="msgmeta"><span class="avatar">AI</span>Assistant</div>':'<div class="msgmeta">You</div>')+escapeHtml(body);
    box.appendChild(el);
  });
}
// Chat session change handler is installed by the refined multi-session block.
document.getElementById('newChat').onclick=()=>{document.getElementById('chatMessages').innerHTML='<div class="msg assistant"><div class="msgmeta"><span class="avatar">AI</span>Assistant</div>新的 mock Chat 已建立。這仍然不會建立 Runner Task。</div>';showToast('New Chat')};
document.getElementById('chatSend').onclick=()=>{
  const input=document.getElementById('chatInput');const text=input.value.trim();if(!text)return;
  const box=document.getElementById('chatMessages');
  const u=document.createElement('div');u.className='msg user';u.innerHTML='<div class="msgmeta">You</div>'+escapeHtml(text);box.appendChild(u);
  const a=document.createElement('div');a.className='msg assistant';
  const reply=/task|執行|run/i.test(text)?'這是一般 Chat。若你真的要執行，我會建議把內容送到 New Task，而不是在 Chat 裡偷偷啟動 Runner。':'收到。這個 mock 回覆用來測試一般 Chat 的閱讀密度、輸入體驗與長訊息排列。';
  a.innerHTML='<div class="msgmeta"><span class="avatar">AI</span>Assistant</div>'+reply;box.appendChild(a);
  input.value='';box.scrollTop=box.scrollHeight;
};
document.getElementById('chatInput').addEventListener('keydown',e=>{if(e.key==='Enter'&&!e.shiftKey){e.preventDefault();document.getElementById('chatSend').click()}});
function resizeChatComposer(){
  const input=document.getElementById('chatInput'),wrap=input?.closest('.composerwrap'),messages=document.getElementById('chatMessages');if(!input)return;
  const min=44,max=180;input.style.height='auto';
  const next=Math.min(max,Math.max(min,input.scrollHeight));input.style.height=`${next}px`;input.style.overflowY=input.scrollHeight>max?'auto':'hidden';
  if(wrap&&messages)requestAnimationFrame(()=>messages.style.setProperty('--composer-space',`${wrap.offsetHeight+16}px`));
}
document.getElementById('chatInput').addEventListener('input',resizeChatComposer);
window.addEventListener('resize',resizeChatComposer);
resizeChatComposer();
const taskPresets={
  today:[
    {id:'T-104',status:'new',title:'新增 Task List UI',runtime:'idle',desc:'讓 YAML List 能用 Form / YAML 兩種方式編排與執行。',tags:['ralphy_ai_validate','UI'],workflow:'ralphy_ai_validate.yaml',project:'ai-task-runner',progress:[0,5],elapsed:'—',stage:'Idle',session:'—',goal:'新增 YAML List 的 UI builder，維持同一套 RunRequest / Runner contract。'},
    {id:'T-105',status:'new',title:'重整 README Workflow 說明',runtime:'idle',desc:'文件同步目前 Stage / PASS / FAIL contract。',tags:['docs'],workflow:'mixed.yaml',project:'ai-task-runner',progress:[0,4],elapsed:'—',stage:'Idle',session:'—',goal:'更新文件但不引入 legacy contract。'},
    {id:'T-103',status:'ongoing',title:'完成 feature/ui 新 Task 介面',runtime:'running',desc:'Stage 正在執行 UI implementation；Runtime 不跟 Board 欄位綁死。',tags:['feature/ui','review'],workflow:'ralphy_ai_validate.yaml',project:'ai-task-runner',progress:[3,5],elapsed:'12m',stage:'review',session:'same',goal:'保持目前 UI 風格，加入 Chat、Task Lists 與 Azure-style Task board。'},
    {id:'T-102',status:'ongoing',title:'修正 Studio stage test',runtime:'recover',desc:'API 暫時錯誤，StageExecutor 正在 same-session retry。',tags:['studio','API'],workflow:'mixed.yaml',project:'ai-task-runner',progress:[2,5],elapsed:'4m',stage:'execute',session:'same retry',goal:'修正 Stage Test API 502 並保持正式 runtime contract。'},
    {id:'T-099',status:'paused',title:'24H reliability review',runtime:'stopped',desc:'User stop；可從 Task 詳細頁 Resume / Reset。',tags:['reliability','live'],workflow:'ralphy_ai_validate.yaml',project:'ai-task-runner',progress:[2,6],elapsed:'3h 18m',stage:'execute',session:'role',goal:'跑完整 reliability review；使用者手動停止後保留可 Resume 狀態。'},
    {id:'T-091',status:'closed',title:'移除舊 Discussion 模式',runtime:'done',desc:'舊契約與 UI 已清理，測試通過；worktree result 尚待 merge。',tags:['cleanup'],workflow:'ralphy_ai_validate.yaml',project:'ai-task-runner',progress:[5,5],elapsed:'28m',stage:'Completed',session:'fresh final',goal:'移除 Discussion / legacy runtime paths。',workspaceKind:'worktree',workspacePolicy:'worktree',branch:'task/T-091-discussion',executionRoot:'C:\\Users\\kevin\\ai-task-runner-worktrees\\T-091'}
  ],
  recovery:[
    {id:'T-212',status:'ongoing',title:'Qwen HTTP 503 recovery probe',runtime:'recover',desc:'第 2 次 same-session attempt；下一次將 rotate fresh session。',tags:['Qwen','503'],workflow:'ralphy_ai_validate.yaml',project:'ai-task-runner',progress:[1,4],elapsed:'7m',stage:'execute',session:'same retry',goal:'確認 transient API failure 不會中斷 24H unattended run。'},
    {id:'T-213',status:'ongoing',title:'Runtime heartbeat stale',runtime:'attention',desc:'UI projection 顯示 Needs Attention；等待使用者選 Resume / Reset。',tags:['runtime','attention'],workflow:'mixed.yaml',project:'ai-task-runner',progress:[2,5],elapsed:'16m',stage:'review',session:'role',goal:'驗證 stale heartbeat 時 UI action guard 與 runtime projection 一致。'},
    {id:'T-214',status:'paused',title:'Deterministic config failure',runtime:'failed',desc:'Workflow schema 不合法，fail closed，不做無限 retry。',tags:['schema','fail-closed'],workflow:'invalid-demo.yaml',project:'ai-task-runner',progress:[0,3],elapsed:'1m',stage:'load',session:'—',goal:'確認 deterministic configuration error 不進 technical retry。'},
    {id:'T-208',status:'closed',title:'API disconnect probe',runtime:'done',desc:'Same-session recovery PASS，fresh rotation 未觸發。',tags:['live','PASS'],workflow:'ralphy_ai_validate.yaml',project:'ai-task-runner',progress:[4,4],elapsed:'9m',stage:'Completed',session:'same',goal:'模擬 API disconnect 並驗證 bounded-session recovery。'}
  ],
  history:[
    {id:'T-301',status:'closed',title:'Workflow Studio CRUD browser test',runtime:'done',desc:'Create / rename / duplicate / delete 全部通過。',tags:['UI','PASS'],workflow:'mixed.yaml',project:'ai-task-runner',progress:[5,5],elapsed:'11m',stage:'Completed',session:'fresh final',goal:'Browser CRUD coverage。'},
    {id:'T-302',status:'closed',title:'Dynamic Handoff regression',runtime:'done',desc:'Role session reuse 與 Final Review PASS。',tags:['handoff','PASS'],workflow:'dynamic_handoff.yaml',project:'ai-task-runner',progress:[7,7],elapsed:'34m',stage:'Completed',session:'role + fresh',goal:'驗證 Dynamic Handoff 不建立第二個 orchestrator。'},
    {id:'T-303',status:'closed',title:'YAML list endurance 8 items',runtime:'done',desc:'8 個 child RunRequests 依序完成。',tags:['YAML','PASS'],workflow:'ralphy_ai_validate.yaml',project:'ai-task-runner',progress:[8,8],elapsed:'2h 6m',stage:'Completed',session:'mixed',goal:'驗證 YAML List sequential execution 與 durable resume。'},
    {id:'T-304',status:'closed',title:'Final AI quorum 3/2',runtime:'done',desc:'3 fresh votes，2 PASS，quorum satisfied。',tags:['validator','PASS'],workflow:'ralphy_ai_validate.yaml',project:'ai-task-runner',progress:[3,3],elapsed:'8m',stage:'Completed',session:'fresh votes',goal:'驗證 Final AI 每票獨立 Fresh Session。'}
  ],
  empty:[]
};
let currentPreset='today';
let taskMap={};
function productTaskRecords(){return Object.values(taskMap).filter(t=>!t._chatDraft)}
let runningOnly=false;
let dragged=null;
let listMode=false;

function runtimeLabel(rt){return {running:'Running',recover:'Recovering',stopped:'Stopped',done:'Completed',idle:'Idle',failed:'Failed',attention:'Needs Attention'}[rt]||rt}
function statusLabel(st){return {new:'New',ongoing:'Ongoing',paused:'Paused',closed:'Closed'}[st]||st}
function runtimeClass(rt){return ['running','recover','stopped','done','failed','attention'].includes(rt)?rt:''}
function progressPct(t){return t.progress[1]?Math.round(t.progress[0]/t.progress[1]*100):0}
function workspaceName(t){
  if(t.workspaceKind==='worktree')return `Worktree · ${t.branch||('task/'+t.id)}`;
  if(t.workspaceKind==='batch')return 'Multi-step';
  return 'Main workspace';
}
function worktreeRootFor(project,id){
  const root=projectMeta[project]?.path||project||'C:\\project';
  const parts=root.split('\\'),name=parts.pop()||'project';
  return [...parts,name+'-worktrees',id].join('\\');
}
function hydrateTaskWorkspace(t,mainOwners){
  if(!t.workspacePolicy)t.workspacePolicy='auto';
  if(t.workspaceKind)return t;
  const active=['running','recover'].includes(t.runtime);
  if(active&&mainOwners.has(t.project)){
    t.workspaceKind='worktree';t.branch=`task/${t.id}`;t.executionRoot=worktreeRootFor(t.project,t.id);
  }else{
    t.workspaceKind='main';t.branch=projectMeta[t.project]?.branch||'main';t.executionRoot=projectMeta[t.project]?.path||t.project;
    if(active)mainOwners.add(t.project);
  }
  return t;
}
function taskProjectKeys(t){
  const refs=[];
  if(t?.project)refs.push(t.project);
  if(t?.projectContext)refs.push(t.projectContext);
  const items=Array.isArray(t?.items)&&t.items.length?t.items:(Array.isArray(t?.listItems)?t.listItems:[]);
  items.forEach(x=>{if(x?.project)refs.push(x.project)});
  const keys=[];
  refs.forEach(ref=>{
    const key=projectMeta[ref]?ref:Object.keys(projectMeta).find(k=>projectRefMatches(ref,k));
    const value=key||String(ref||'').trim();
    if(value&&!keys.includes(value))keys.push(value);
  });
  return keys;
}
function taskCardHtml(t){
  const progress=t.progress[1]?`<span class="progress"><span class="bar"><i style="width:${progressPct(t)}%"></i></span>${t.progress[0]} / ${t.progress[1]}</span>`:`<span>#${t.id}</span>`;
  const workspaceClass=t.workspaceKind==='batch'?'batch-tag':'workspace-tag';
  const projectKeys=taskProjectKeys(t),projectTag=projectKeys.length>1?`<span class="tag multi-project-tag" title="${escapeAttr(projectKeys.join(' · '))}">${projectKeys.length} Projects</span>`:'';
  return `<article class="taskcard ${t.runtime==='attention'?'attention':''} ${t.runtime==='failed'?'failed':''}" draggable="true" data-id="${t.id}" data-title="${escapeHtml(t.title)}" data-runtime="${t.runtime}">
    <div class="cardtop"><span class="handle">⠿</span><div class="tasktitle">${escapeHtml(t.title)}</div><span class="runtime ${runtimeClass(t.runtime)}">${runtimeLabel(t.runtime)}</span></div>
    <div class="carddesc" title="${escapeAttr(t.desc||'')}">${escapeHtml(t.desc)}</div><div class="cardmeta"><span class="tag ${workspaceClass}">${escapeHtml(workspaceName(t))}</span>${projectTag}${t.tags.map(x=>`<span class="tag">${escapeHtml(x)}</span>`).join('')}</div>
    <div class="cardfoot">${progress}<span>${escapeHtml(t.elapsed)}</span></div></article>`;
}
function renderBoard(preset=currentPreset){
  currentPreset=preset;taskMap={};
  document.querySelectorAll('.dropzone').forEach(z=>z.innerHTML='');
  const mainOwners=new Set();
  (taskPresets[preset]||[]).forEach(source=>{
    const t=hydrateTaskWorkspace({...source,tags:[...(source.tags||[])]},mainOwners);
    taskMap[t.id]=t;
    const z=document.querySelector(`.col[data-status="${t.status}"] .dropzone`);
    if(z)z.insertAdjacentHTML('beforeend',taskCardHtml(t));
  });
  bindTaskCards();renderTaskList();applyTaskFilter();updateCounts();
}
const BOARD_TRANSITIONS={
  new:new Set(['ongoing','closed']),
  ongoing:new Set(['paused','closed']),
  paused:new Set(['new','ongoing','closed']),
  closed:new Set(['new'])
};
function boardMoveAllowed(t,target){
  if(!t||!target)return {ok:false,reason:'Unknown target'};
  if(t.status===target)return {ok:true,reason:'Same status'};
  if(!BOARD_TRANSITIONS[t.status]?.has(target)){
    return {ok:false,reason:`${statusLabel(t.status)} 不允許直接移到 ${statusLabel(target)}`};
  }
  if(target==='closed'&&['running','recover'].includes(t.runtime)){
    return {ok:false,reason:'執行中的 Task 不直接 Closed；先移到 Paused（會 Stop）或從詳細頁 Stop'};
  }
  return {ok:true,reason:''};
}
function syncRuntimeForBoardMove(t,oldStatus,newStatus){
  if(t.workspaceKind==='batch'&&t.id===batchParentTaskId){
    if(newStatus==='paused'&&batchState.status==='running'){
      clearInterval(batchRunTimer);batchRunTimer=null;batchState.status='stopped';setBatchControls();
      const item=document.querySelector(`.previewitem[data-step="${batchState.index}"]`);if(item)item.querySelector('.orderchip').textContent='Stopped';
      t.runtime='stopped';pushTaskHistory(t,'Board pause · Task List stopped · child state preserved');return;
    }
    if(oldStatus==='paused'&&newStatus==='ongoing'&&batchState.status==='stopped'){
      batchState.status='running';setBatchControls();batchRunTimer=setInterval(batchTick,900);
      t.runtime='running';pushTaskHistory(t,'Board resume · Task List continued');return;
    }
  }
  if(newStatus==='paused'&&['running','recover'].includes(t.runtime)){
    t.runtime='stopped';
    t.desc='由 Board 移到 Paused；mock Stop 已送出，durable state 保留。';
    pushTaskHistory(t,'Board Ongoing → Paused · Stop accepted · resumable');
  }else if(oldStatus==='paused'&&newStatus==='ongoing'&&['stopped','attention'].includes(t.runtime)){
    t.runtime='running';
    t.desc='由 Board Paused → Ongoing；mock Resume 從 durable state 繼續。';
    pushTaskHistory(t,'Board Paused → Ongoing · Resume accepted');
  }else{
    pushTaskHistory(t,`Board ${statusLabel(oldStatus)} → ${statusLabel(newStatus)}`);
  }
}
function clearDropHints(){
  document.querySelectorAll('.dropzone').forEach(z=>z.classList.remove('over','allowed','blocked'));
}
function paintDropHints(t){
  document.querySelectorAll('.dropzone').forEach(zone=>{
    const target=zone.closest('.col')?.dataset.status;
    const rule=boardMoveAllowed(t,target);
    zone.classList.toggle('allowed',rule.ok&&target!==t.status);
    zone.classList.toggle('blocked',!rule.ok);
  });
}
function bindTaskCards(){
  document.querySelectorAll('.taskcard').forEach(card=>{
    card.onclick=()=>{if(!card.classList.contains('dragging'))openTask(card)};
    card.addEventListener('dragstart',e=>{
      dragged=card;card.classList.add('dragging');e.dataTransfer.effectAllowed='move';
      paintDropHints(taskMap[card.dataset.id]);
    });
    card.addEventListener('dragend',()=>{
      card.classList.remove('dragging');dragged=null;clearDropHints();updateCounts();renderTaskList();
    });
  });
}
document.querySelectorAll('.dropzone').forEach(zone=>{
  zone.addEventListener('dragover',e=>{
    if(!dragged)return;
    const t=taskMap[dragged.dataset.id],target=zone.closest('.col')?.dataset.status,rule=boardMoveAllowed(t,target);
    if(rule.ok){e.preventDefault();zone.classList.add('over');e.dataTransfer.dropEffect='move'}
    else{e.dataTransfer.dropEffect='none'}
  });
  zone.addEventListener('dragleave',()=>zone.classList.remove('over'));
  zone.addEventListener('drop',e=>{
    e.preventDefault();zone.classList.remove('over');
    if(!dragged)return;
    const id=dragged.dataset.id,t=taskMap[id],old=t?.status,now=zone.closest('.col')?.dataset.status;
    const rule=boardMoveAllowed(t,now);
    if(!rule.ok){showToast(`不可移動：${rule.reason}`);return}
    if(old===now){showToast(`Task 已在 ${statusLabel(now)}`);return}
    syncRuntimeForBoardMove(t,old,now);t.status=now;
    renderBoardFromMap();
    showToast(`Task: ${statusLabel(old)} → ${statusLabel(now)} · Runtime ${runtimeLabel(t.runtime)}`);
  });
});
function updateCounts(){
  document.querySelectorAll('.col').forEach(c=>c.querySelector('.count').textContent=c.querySelectorAll('.taskcard:not([hidden])').length);
  document.getElementById('taskNavCount').textContent=productTaskRecords().length;
  const n=productTaskRecords().filter(t=>['running','recover'].includes(t.runtime)).length;
  document.getElementById('runningCount').textContent=`${n} Running`;
}
function applyTaskFilter(){
  const q=document.getElementById('taskSearch').value.trim().toLowerCase();
  document.querySelectorAll('.taskcard').forEach(c=>{
    const t=taskMap[c.dataset.id];c.hidden=!!((q&&!c.textContent.toLowerCase().includes(q))||(runningOnly&&!['running','recover'].includes(t?.runtime)));
  });updateCounts();
}
document.getElementById('taskSearch').addEventListener('input',applyTaskFilter);
document.getElementById('filterBtn').addEventListener('click',e=>{runningOnly=!runningOnly;e.currentTarget.textContent=runningOnly?'顯示全部':'只看執行中';applyTaskFilter()});
document.getElementById('boardPreset').addEventListener('change',e=>{runningOnly=false;document.getElementById('filterBtn').textContent='只看執行中';document.getElementById('taskSearch').value='';renderBoard(e.target.value);showToast(`載入 mock board：${e.target.options[e.target.selectedIndex].text}`)});
document.querySelectorAll('.coladd').forEach(b=>b.onclick=()=>document.getElementById('newTask').click());
let taskSequence=420;
function openModal(id){document.getElementById(id)?.classList.add('open')}
function closeModal(id){document.getElementById(id)?.classList.remove('open')}
document.querySelectorAll('[data-close-modal]').forEach(b=>b.onclick=()=>closeModal(b.dataset.closeModal));
function renderGlobalExecutionSettings(){
  const select=document.getElementById('autoWorkspacePolicy'),hint=document.getElementById('autoWorkspacePolicyHint'),preview=document.getElementById('autoWorkspacePolicyPreview');if(!select)return;
  select.value=globalExecutionSettings.autoWorkspacePolicy;if(hint)hint.textContent=autoWorkspacePolicyDescription();
  if(preview){
    const rows=globalExecutionSettings.autoWorkspacePolicy==='busy_worktree'
      ?'<strong>Auto</strong> · Idle → Main · Busy → Worktree'
      :globalExecutionSettings.autoWorkspacePolicy==='main_only'
        ?'<strong>Auto</strong> · Always Main · Busy → Block Run'
        :'<strong>Auto</strong> · Always Worktree';
    preview.innerHTML=rows+'<br>Task-level Main / Worktree always overrides this setting.';
  }
}
function renderGlobalInterfaceSettings(){
  const appearance=document.getElementById('globalAppearance'),preview=document.getElementById('interfaceSettingsPreview');
  if(appearance)appearance.value=globalInterfaceSettings.appearance;
  document.querySelectorAll('[data-prototype-theme]').forEach(button=>{const active=button.dataset.prototypeTheme===globalInterfaceSettings.theme;button.classList.toggle('active',active);button.setAttribute('aria-pressed',String(active))});
  if(preview)preview.innerHTML=`<strong>Appearance</strong> · ${globalInterfaceSettings.appearance==='system'?`System → ${resolvedAppearance()}`:globalInterfaceSettings.appearance}<br><strong>Theme</strong> · ${globalInterfaceSettings.theme}`;
}
function renderGlobalLanguageSettings(){
  const language=document.getElementById('globalLanguage'),preview=document.getElementById('languageSettingsPreview');
  if(language)language.value=globalInterfaceSettings.language;
  if(preview)preview.innerHTML=`<strong>Language</strong> · ${globalInterfaceSettings.language==='zh-TW'?'繁體中文':'English'}<br>Global across all Projects and Chat sessions.`;
}
function showGlobalSettingsTab(name='execution'){
  document.querySelectorAll('[data-settings-tab]').forEach(b=>b.classList.toggle('active',b.dataset.settingsTab===name));
  document.querySelectorAll('[data-settings-panel]').forEach(p=>p.hidden=p.dataset.settingsPanel!==name);
  if(name==='execution')renderGlobalExecutionSettings();
  else if(name==='defaults'&&typeof renderGlobalDefaultSettings==='function')renderGlobalDefaultSettings();
  else if(name==='interface')renderGlobalInterfaceSettings();
  else if(name==='language')renderGlobalLanguageSettings();
}
document.querySelectorAll('[data-settings-tab]').forEach(b=>b.addEventListener('click',()=>showGlobalSettingsTab(b.dataset.settingsTab)));
document.getElementById('globalSettingsButton')?.addEventListener('click',()=>{showGlobalSettingsTab('execution');openModal('globalSettingsModal')});
document.getElementById('autoWorkspacePolicy')?.addEventListener('change',e=>{
  globalExecutionSettings.autoWorkspacePolicy=AUTO_WORKSPACE_POLICIES.has(e.target.value)?e.target.value:'busy_worktree';saveAutoWorkspacePolicy();renderGlobalExecutionSettings();
  if(typeof renderNewTaskWorkspace==='function')renderNewTaskWorkspace();
  showToast('Auto workspace policy updated');
});
document.getElementById('globalAppearance')?.addEventListener('change',e=>{
  globalInterfaceSettings.appearance=APPEARANCES.has(e.target.value)?e.target.value:'system';saveInterfaceSettings();applyInterfaceSettings();renderGlobalInterfaceSettings();showToast('Appearance updated');
});
document.querySelectorAll('[data-prototype-theme]').forEach(button=>button.addEventListener('click',()=>{
  globalInterfaceSettings.theme=THEME_PALETTES.has(button.dataset.prototypeTheme)?button.dataset.prototypeTheme:'teal';saveInterfaceSettings();applyInterfaceSettings();renderGlobalInterfaceSettings();showToast(`Theme · ${globalInterfaceSettings.theme}`);
}));
document.getElementById('globalLanguage')?.addEventListener('change',e=>{
  globalInterfaceSettings.language=LANGUAGES.has(e.target.value)?e.target.value:'zh-TW';saveInterfaceSettings();applyInterfaceSettings();renderGlobalLanguageSettings();if(typeof renderChatSession==='function')renderChatSession();if(typeof renderChatQueue==='function')renderChatQueue();if(typeof renderChatTurnStatus==='function')renderChatTurnStatus();if(typeof renderComposerSuggestions==='function')renderComposerSuggestions();if(typeof newTaskListDraft!=='undefined'&&newTaskListDraft&&typeof renderNewTaskListDraftWorkspace==='function')renderNewTaskListDraftWorkspace();showToast(globalInterfaceSettings.language==='zh-TW'?'語言偏好已更新':'Language preference updated');
});
window.matchMedia?.('(prefers-color-scheme: dark)').addEventListener?.('change',()=>{if(globalInterfaceSettings.appearance==='system'){applyInterfaceSettings();renderGlobalInterfaceSettings()}});
document.querySelectorAll('.modal-overlay').forEach(m=>m.addEventListener('click',e=>{if(e.target===m)closeModal(m.id)}));
document.getElementById('newTask').addEventListener('click',()=>{
  document.getElementById('newTaskTitle').value='New Task';
  document.getElementById('newTaskGoal').value='Implement the requested change and run focused verification.';
  openModal('newTaskModal');
});
document.getElementById('createTaskConfirm').onclick=()=>{
  const title=document.getElementById('newTaskTitle').value.trim(),goal=document.getElementById('newTaskGoal').value.trim();
  if(!title||!goal){showToast('Task title / Goal 不可空白');return}
  const id='T-'+(++taskSequence);
  const project=document.getElementById('newTaskProject').value,workflow=document.getElementById('newTaskWorkflow').value;
  const t={id,status:'new',title,runtime:'idle',desc:'尚未開始；Board 狀態與 Runner runtime 分開。',tags:['workflow'],workflow,project,progress:[0,4],elapsed:'—',stage:'Idle',session:'—',goal};
  taskMap[id]=t;
  document.querySelector('.col[data-status="new"] .dropzone').insertAdjacentHTML('afterbegin',taskCardHtml(t));
  bindTaskCards();renderTaskList();updateCounts();closeModal('newTaskModal');showToast('已建立 mock Task · 尚未執行');
  openTaskById(id);
};
function renderTaskList(){
  const host=document.getElementById('taskListView');
  host.innerHTML=productTaskRecords().map(t=>`<div class="taskrow" data-taskrow="${t.id}"><span class="pill">${statusLabel(t.status)}</span><strong>${escapeHtml(t.title)}</strong><span class="runtime ${runtimeClass(t.runtime)}">${runtimeLabel(t.runtime)}</span><span>${escapeHtml(t.workflow)}</span><span>${t.progress[0]} / ${t.progress[1]}</span></div>`).join('');
  host.querySelectorAll('[data-taskrow]').forEach(r=>r.onclick=()=>openTaskById(r.dataset.taskrow));
}
document.getElementById('listMode').onclick=e=>{
  listMode=!listMode;document.getElementById('board').classList.toggle('hiddenboard',listMode);document.getElementById('taskListView').classList.toggle('active',listMode);
  e.currentTarget.classList.toggle('active',listMode);e.currentTarget.previousElementSibling.classList.toggle('active',!listMode);
};

function renderBoardFromMap(){
  document.querySelectorAll('.dropzone').forEach(z=>z.innerHTML='');
  productTaskRecords().forEach(t=>{    const z=document.querySelector(`.col[data-status="${t.status}"] .dropzone`);
    if(z)z.insertAdjacentHTML('beforeend',taskCardHtml(t));
  });
  bindTaskCards();renderTaskList();applyTaskFilter();updateCounts();
}
function pushTaskHistory(t,message){
  if(!t.history)t.history=[['20:01','Task created'],['20:02','Workflow snapshot frozen']];
  const now=new Date(),hh=String(now.getHours()).padStart(2,'0'),mm=String(now.getMinutes()).padStart(2,'0');
  t.history.push([`${hh}:${mm}`,message]);
}
let currentTaskId='';
function renderDrawerActions(t){
  const primary=document.getElementById('taskPrimaryDemo');
  const reset=document.getElementById('taskResetDemo');
  const rerun=document.getElementById('taskSecondaryDemo');
  primary.hidden=false;reset.hidden=true;rerun.hidden=true;
  primary.className='btn primary';
  if(t.runtime==='idle'){primary.textContent='Run'}
  else if(['running','recover'].includes(t.runtime)){primary.textContent='Stop';primary.className='btn danger'}
  else if(['stopped','attention'].includes(t.runtime)){primary.textContent='Resume';reset.hidden=false}
  else{primary.hidden=true}
  if(['failed','done'].includes(t.runtime)){rerun.hidden=false;rerun.textContent='Rerun'}
  if(t.runtime==='failed')reset.hidden=false;
}
function taskDetails(t){
  const generic=(t.history&&t.history.length?t.history:[
    ['20:01','Task created'],['20:02','Workflow snapshot frozen'],['20:07',`${t.stage} · ${runtimeLabel(t.runtime)}`]
  ]);
  const timeline=t.runtime==='done'
    ?[['planning','PASS · 20:01','done'],['execute','PASS · 20:07','done'],['review','PASS · 20:12','done'],['final_validate','PASS · 20:15','done']]
    :t.runtime==='failed'
    ?[['load','FAIL CLOSED · schema error','now'],['execute','Not started','']]
    :t.runtime==='attention'
    ?[['planning','PASS · 20:01','done'],['execute','PASS · 20:06','done'],['review','Heartbeat stale · Needs Attention','now'],['final_validate','Waiting','']]
    :t.runtime==='recover'
    ?[['planning','PASS · 20:01','done'],['execute','HTTP 503 · retrying same session','now'],['review','Waiting',''],['final_validate','Waiting','']]
    :t.runtime==='stopped'
    ?[['planning','PASS · 18:01','done'],['execute','Stopped by user · resumable','now'],['review','Waiting','']]
    :[['planning','PASS · 20:01','done'],['execute','PASS · 20:07','done'],[t.stage||'review',`${runtimeLabel(t.runtime)} · ${t.session}`,'now'],['final_validate','Waiting','']];
  const output=t.runtime==='recover'
    ?'[20:07:11] backend: HTTP 503 service unavailable\n[20:07:16] StageExecutor: retry delay 5s\n[20:07:21] same-session attempt 2/2\n[20:07:22] next failure will rotate only this Stage session'
    :t.runtime==='failed'
    ?'[20:07:11] workflow loader: invalid target "repair"\n[20:07:11] deterministic configuration error\n[20:07:11] fail closed · technical retry disabled for this error'
    :t.runtime==='attention'
    ?'[20:07:11] runtime projection: heartbeat stale\n[20:07:11] allowed actions: Resume / Reset\n[20:07:11] UI must not infer Running from stale browser flags'
    :t.runtime==='done'
    ?'[20:15:03] final_validate vote 1 PASS\n[20:15:08] final_validate vote 2 PASS\n[20:15:08] quorum satisfied\n[20:15:09] run completed'
    :'[20:07:11] stage: inspecting modified files\n[20:07:12] checking runtime ownership\n[20:07:15] validating UI interactions\n[20:07:19] bounded live output continues...';
  return {timeline,output,history:generic};
}
function renderTaskLiveOutput(t){
  const dot=document.getElementById('drawerLiveDot'),indicator=document.getElementById('drawerLiveIndicator');
  const cls=t.runtime==='running'?'running':t.runtime==='recover'?'recover':t.runtime==='done'?'done':t.runtime==='failed'?'failed':'';
  dot.className='task-live-dot '+cls;
  indicator.textContent=runtimeLabel(t.runtime);
  indicator.className='task-live-indicator '+(t.runtime==='stopped'?'stopped':t.runtime==='done'?'done':t.runtime==='recover'?'recover':'');
  document.getElementById('drawerLiveProgress').textContent=`${t.progress[0]} / ${t.progress[1]} TODO · ${t.stage}`;
  document.getElementById('drawerLiveUpdated').textContent='Last update now';
  document.getElementById('drawerLiveElapsed').textContent=t.elapsed==='—'?'00:00:00':t.elapsed;
  const activity=t.runtime==='recover'
    ?['HTTP 503 service unavailable','StageExecutor same-session retry','Next failure rotates only this Stage session']
    :t.runtime==='running'
    ?['Inspecting modified files',`Stage ${t.stage} is active`,'Waiting for structured StageResult']
    :t.runtime==='stopped'
    ?['Stopped by user','Durable state preserved','Resume continues saved Workflow snapshot']
    :t.runtime==='done'
    ?['Final AI validation passed','Workflow completed','State committed']
    :t.runtime==='failed'
    ?['Deterministic error','Fail closed','Technical retry not entered']
    :['Runtime is not active'];
  document.getElementById('drawerLiveActivityList').innerHTML=activity.map(x=>`<div>${escapeHtml(x)}</div>`).join('');
}
function openTask(card){openTaskById(card.dataset.id)}
function openTaskById(id){
  const t=taskMap[id];if(!t)return;
  currentTaskId=id;
  const d=taskDetails(t);
  document.getElementById('drawerTaskId').textContent=t.id;
  document.getElementById('drawerProjectName').textContent=t.project;
  document.getElementById('drawerTitle').textContent=t.title;
  document.getElementById('drawerBoardStatus').textContent=statusLabel(t.status);
  document.getElementById('drawerStatusValue').textContent=statusLabel(t.status);
  document.getElementById('drawerWorkflow').textContent=t.workflow;
  document.getElementById('drawerProject').textContent=projectMeta[t.project]?.path||t.project;
  document.getElementById('drawerWorkspace').textContent=workspaceName(t);
  document.getElementById('drawerBranch').textContent=t.branch||'—';
  document.getElementById('drawerExecutionRoot').textContent=t.executionRoot||projectMeta[t.project]?.path||t.project;
  document.getElementById('drawerBackend').textContent=t.runtime==='recover'?'Qwen · qwen3-coder-plus':'Default backend';
  document.getElementById('drawerGoal').textContent=t.goal;
  document.getElementById('metricProgress').textContent=`${t.progress[0]} / ${t.progress[1]}`;
  document.getElementById('metricElapsed').textContent=t.elapsed;
  document.getElementById('metricSession').textContent=t.session;
  document.getElementById('drawerStage').textContent='Stage: '+t.stage;
  document.getElementById('drawerProgressText').textContent=`${t.progress[0]} / ${t.progress[1]}`;
  document.getElementById('drawerStageProgress').style.width=progressPct(t)+'%';
  const badge=document.getElementById('drawerRuntime'),inline=document.getElementById('drawerRuntimeInline');
  [badge,inline].forEach(x=>{x.textContent=runtimeLabel(t.runtime);x.className=(x===badge?'pill ':'runtime ')+(t.runtime==='done'?'pass':t.runtime==='stopped'||t.runtime==='failed'?'fail':t.runtime==='idle'?'':t.runtime==='attention'||t.runtime==='recover'||t.runtime==='running'?'run':'')});
  document.getElementById('drawerTimeline').innerHTML=d.timeline.map(([n,m,c])=>`<div class="event ${c}"><strong>${escapeHtml(n)}</strong><small>${escapeHtml(m)}</small></div>`).join('');
  document.getElementById('drawerConsole').textContent=d.output;
  renderTaskLiveOutput(t);
  document.getElementById('drawerHistory').innerHTML=d.history.map(([time,msg])=>`<div class="history-row"><time>${time}</time><span>${escapeHtml(msg)}</span></div>`).join('');
  renderDrawerActions(t);
  document.querySelectorAll('.drawertab').forEach((b,i)=>b.classList.toggle('active',i===0));document.querySelectorAll('.drawer-pane').forEach((p,i)=>p.classList.toggle('active',i===0));
  document.getElementById('taskOverlay').classList.add('open');
}
document.querySelectorAll('[data-drawertab]').forEach(b=>b.onclick=()=>{
  document.querySelectorAll('[data-drawertab]').forEach(x=>x.classList.toggle('active',x===b));
  document.querySelectorAll('.drawer-pane').forEach(p=>p.classList.toggle('active',p.id==='drawer-'+b.dataset.drawertab));
});
const taskDrawer=document.querySelector('#taskOverlay .drawer');
const drawerExpand=document.getElementById('drawerExpand');
function syncDrawerExpand(){
  const expanded=taskDrawer.classList.contains('expanded');
  drawerExpand.setAttribute('aria-pressed',String(expanded));
  drawerExpand.setAttribute('aria-label',expanded?'Collapse task workspace':'Expand task workspace');
  drawerExpand.title=expanded?'Collapse task workspace':'Expand task workspace';
  drawerExpand.textContent=expanded?'⤡':'⤢';
}
drawerExpand.onclick=()=>{taskDrawer.classList.toggle('expanded');syncDrawerExpand()};
syncDrawerExpand();
// Task Drawer Close / backdrop / Escape ownership lives in task-workspace.js.
document.getElementById('taskPrimaryDemo').onclick=()=>{
  const t=taskMap[currentTaskId];if(!t)return;
  if(t.kind==='list'||t.workspaceKind==='batch'){
    if(t.runtime==='idle'){openTaskListEditor(t.id);showToast('Open Task List Editor');return}
    if(['running','recover'].includes(t.runtime)){
      if(t.id!==batchParentTaskId)openTaskListEditor(t.id);
      document.getElementById('stopBatch').click();openTaskById(t.id);return;
    }
    if(['stopped','attention','failed'].includes(t.runtime)){
      if(t.id!==batchParentTaskId)openTaskListEditor(t.id);
      document.getElementById('resumeBatch').click();openTaskById(t.id);return;
    }
  }
  if(t.runtime==='idle'){
    const workspace=prepareTaskWorkspaceForRun(t);
    if(!workspace.ok){showToast(workspace.reason);return}
    if(workspace.changed)pushTaskHistory(t,`Auto workspace resolved → ${workspace.kind}`);
    t.runtime='running';t.stage='planning';t.session='main';t.elapsed='0m';t.desc='Runner 已啟動；Board 與 runtime 仍由不同狀態來源顯示。';
    if(t.status==='new')t.status='ongoing';
    pushTaskHistory(t,'Run started · server-side action guard accepted');
    showToast('Mock Run started');
  }else if(['running','recover'].includes(t.runtime)){
    t.runtime='stopped';t.desc='User stop；durable state 保留，可 Resume / Reset。';
    pushTaskHistory(t,'Stopped by user · resumable');
    showToast('Mock Stop · 現在可拖到 Paused / Closed');
  }else if(['stopped','attention'].includes(t.runtime)){
    t.runtime='running';t.desc='Resume from durable state；沿用既有 Workflow snapshot。';
    if(t.status==='paused')t.status='ongoing';
    pushTaskHistory(t,'Resume accepted · continuing saved state');
    showToast('Mock Resume');
  }
  renderBoardFromMap();openTaskById(t.id);
};
// Reset / Rerun lifecycle actions are owned by tasks-page.js so every destructive restart path uses the same confirmation policy.
document.getElementById('deleteTaskDemo').onclick=()=>{
  const t=taskMap[currentTaskId];if(!t)return;
  if(['running','recover'].includes(t.runtime)){showToast('執行中的 Task 不能直接刪除，請先 Stop');return}
  delete taskMap[currentTaskId];document.getElementById('taskOverlay').classList.remove('open');renderBoardFromMap();showToast('Mock Task deleted');
};
document.getElementById('openWorkflowDemo').onclick=()=>showToast('正式版會開啟目前既有 Workflow Editor，不新增第二套編輯器');

const PROMPT_ASSETS=[
  'common/ai_validator.md',
  'common/review.md',
  'ralphy/ralphy.md',
  'workflow/generate.md'
];
const batchPresets={
  ui:[
    {
      prompt:'Fix feature/ui Task board',goalMode:'inline',goalFile:'',goalAsset:'common/review.md',
      project:'C:\\Users\\kevin\\ai-task-runner',workflow:'ralphy_ai_validate.yaml',
      validatorMode:'file',validator:'C:\\Users\\kevin\\ai-task-runner\\ai_task_runner_validator.py',
      aiMode:'asset',aiPrompt:'',aiFile:'',aiAsset:'common/ai_validator.md'
    },
    {
      prompt:'Review UI/UX and tests',goalMode:'asset',goalFile:'',goalAsset:'common/review.md',
      project:'C:\\Users\\kevin\\ai-task-runner',workflow:'ralphy_ai_validate.yaml',
      validatorMode:'none',validator:'',
      aiMode:'inline',aiPrompt:'嚴格檢查 UI/UX、runtime ownership、錯誤狀態與 focused tests；只回傳驗證判斷。',aiFile:'',aiAsset:'common/ai_validator.md'
    }
  ],
  reliability:[
    {
      prompt:'Run API disconnect probe',goalMode:'file',goalFile:'C:\\Users\\kevin\\ai-task-runner\\tool\\prompts\\api-disconnect.md',goalAsset:'common/review.md',
      project:'C:\\Users\\kevin\\ai-task-runner',workflow:'mixed.yaml',
      validatorMode:'file',validator:'C:\\Users\\kevin\\ai-task-runner\\ai_task_runner_validator.py',
      aiMode:'default',aiPrompt:'',aiFile:'',aiAsset:'common/ai_validator.md'
    },
    {
      prompt:'Run HTTP 503 recovery probe',goalMode:'inline',goalFile:'',goalAsset:'common/review.md',
      project:'C:\\Users\\kevin\\ai-task-runner',workflow:'ralphy_ai_validate.yaml',
      validatorMode:'ai',validator:'',
      aiMode:'file',aiPrompt:'',aiFile:'C:\\Users\\kevin\\ai-task-runner\\runner\\assets\\prompts\\common\\ai_validator.md',aiAsset:'common/ai_validator.md'
    },
    {
      prompt:'Run final AI quorum validation',goalMode:'inline',goalFile:'',goalAsset:'common/review.md',
      project:'C:\\Users\\kevin\\ai-task-runner',workflow:'ralphy_ai_validate.yaml',
      validatorMode:'none',validator:'',
      aiMode:'asset',aiPrompt:'',aiFile:'',aiAsset:'common/ai_validator.md'
    }
  ],
  multi:[
    {
      prompt:'Update runner core docs',goalMode:'inline',goalFile:'',goalAsset:'common/review.md',
      project:'C:\\Users\\kevin\\ai-task-runner',workflow:'ralphy_ai_validate.yaml',
      validatorMode:'none',validator:'',
      aiMode:'asset',aiPrompt:'',aiFile:'',aiAsset:'common/ai_validator.md'
    },
    {
      prompt:'Refactor packet parser',goalMode:'file',goalFile:'D:\\dev\\game-client\\tasks\\packet-parser.md',goalAsset:'common/review.md',
      project:'D:\\dev\\game-client',workflow:'mixed.yaml',
      validatorMode:'file',validator:'D:\\dev\\game-client\\validation.py',
      aiMode:'default',aiPrompt:'',aiFile:'',aiAsset:'common/ai_validator.md'
    },
    {
      prompt:'Review automation scripts',goalMode:'asset',goalFile:'',goalAsset:'common/review.md',
      project:'D:\\lab\\tools',workflow:'ralphy_ai_validate.yaml',
      validatorMode:'file',validator:'D:\\lab\\tools\\validator.py',
      aiMode:'inline',aiPrompt:'確認自動化腳本符合驗收條件，禁止修改檔案。',aiFile:'',aiAsset:'common/ai_validator.md'
    }
  ],
  empty:[]
};
let batchDraft=[];
let batchRunTimer=null;
let batchState={status:'idle',index:0,recovered:false};
let batchParentTaskId=null;
let pickerTarget=null;
const taskFileUploadPicker=document.getElementById('taskFileUploadPicker');
const stagedUploadFiles=new Map(),mockManagedFileCopies=new Map();
let stagedUploadSequence=0;
function cloneUploadMeta(value={}){
  return Object.fromEntries(Object.entries(value||{}).map(([field,meta])=>[field,meta?{...meta}:meta]).filter(([,meta])=>meta));
}
function stagedUploadMeta(source,field){return source?._uploads?.[field]||null}
function hasFileSource(source,field){return !!String(source?.[field]||'').trim()||!!stagedUploadMeta(source,field)}
function stagedUploadName(source,field){return stagedUploadMeta(source,field)?.name||''}
function clearStagedUpload(source,field){
  const meta=stagedUploadMeta(source,field);if(meta?.token)stagedUploadFiles.delete(meta.token);
  if(source?._uploads){delete source._uploads[field];if(!Object.keys(source._uploads).length)delete source._uploads}
}
function safeUploadSegment(value,fallback='file'){return String(value||fallback).replace(/[<>:"/\\|?*\x00-\x1f]+/g,'-').replace(/^\.+|\.+$/g,'').trim()||fallback}
function managedUploadPath(item,itemRef,field,meta){
  const root=String(item?.project||projectMeta[currentProjectKey]?.path||'C:\\project').replace(/[\\/]+$/,'');
  const folder=field==='validator'?'validators':field==='aiFile'?'ai-validator-prompts':'task-prompts';
  return `${root}\\.ai-task-runner\\uploads\\${safeUploadSegment(itemRef,'task')}\\${folder}\\${safeUploadSegment(meta?.name,'uploaded-file')}`;
}
function uploadItemRefForTarget(){
  if(pickerTarget?.context==='task'&&typeof editorItemRef==='function')return editorItemRef();
  const owner=taskMap[currentTaskId];
  if((pickerTarget?.context==='plan'||pickerTarget?.context==='batch')&&owner)return `${owner.id}-I${(pickerTarget.index??0)+1}`;
  return `UPLOAD-I${(pickerTarget?.index??0)+1}`;
}
function stagedManagedPath(source,field){return stagedUploadMeta(source,field)?.managedPath||''}
function isStagedManagedValue(source,field,value){
  const managed=stagedManagedPath(source,field);
  return !!managed&&String(value||'').trim()===managed;
}
function materializeItemUploads(item,itemRef){
  if(!item?._uploads)return item;
  for(const field of ['goalFile','validator','aiFile']){
    const meta=stagedUploadMeta(item,field);if(!meta)continue;
    const active=field==='goalFile'?item.goalMode==='file':field==='aiFile'?item.aiMode==='file':item.validatorMode==='file';
    if(!active){if(meta.token)stagedUploadFiles.delete(meta.token);delete item._uploads[field];continue}
    const path=managedUploadPath(item,itemRef,field,meta),file=stagedUploadFiles.get(meta.token)||null;
    mockManagedFileCopies.set(path,{...meta,file,copiedAt:new Date().toISOString()});
    if(meta.token)stagedUploadFiles.delete(meta.token);item[field]=path;delete item._uploads[field];
  }
  if(!Object.keys(item._uploads||{}).length)delete item._uploads;
  return item;
}
function pickerTargetSource(){
  if(pickerTarget?.context==='task')return newTaskDraft;
  if((pickerTarget?.context==='plan'||pickerTarget?.context==='batch')&&batchDraft[pickerTarget.index])return batchDraft[pickerTarget.index];
  return null;
}
function rerenderPickerTarget(){
  if(pickerTarget?.context==='task'){if(typeof renderNewTaskSources==='function')renderNewTaskSources();return}
  const t=taskMap[currentTaskId];
  if(pickerTarget?.context==='plan'&&t){renderFullPlan(t);renderDrawerPlan(t);return}
  if(typeof renderBatchDraft==='function')renderBatchDraft();
}
function openFileUploadPicker(index,field,kind='file',context='batch'){
  pickerTarget=context==='task'?{context:'task',field,kind}:context==='plan'?{context:'plan',index,field,kind}:{context:'batch',index,field,kind};
  if(!taskFileUploadPicker){showToast('File upload picker is unavailable');return}
  taskFileUploadPicker.accept=kind==='validator'?'.py,.pyw,*/*':'';
  taskFileUploadPicker.value='';taskFileUploadPicker.click();
}
taskFileUploadPicker?.addEventListener('change',()=>{
  const file=taskFileUploadPicker.files?.[0],target=pickerTargetSource();if(!file||!target||!pickerTarget)return;
  clearStagedUpload(target,pickerTarget.field);
  const token=`U${++stagedUploadSequence}`,meta={token,name:file.name,size:file.size,type:file.type||'',lastModified:file.lastModified||0};
  const itemRef=uploadItemRefForTarget(),managedPath=managedUploadPath(target,itemRef,pickerTarget.field,meta);
  meta.managedPath=managedPath;
  stagedUploadFiles.set(token,file);
  target._uploads={...(target._uploads||{}),[pickerTarget.field]:meta};
  target[pickerTarget.field]=managedPath;
  const owner=taskMap[currentTaskId];
  if((pickerTarget.context==='plan'||pickerTarget.context==='batch')&&owner){
    if(!owner._chatDraft)materializeItemUploads(target,`${owner.id}-I${pickerTarget.index+1}`);
    if(typeof commitPlanDraft==='function')commitPlanDraft(owner,{markDirty:owner.status==='paused'&&pickerTarget.index===batchState.index});
    if(!owner._chatDraft)renderBoardFromMap();
  }
  rerenderPickerTarget();showToast(`Uploaded · ${file.name}${owner&&!owner._chatDraft&&pickerTarget.context!=='task'?' · copied to managed path':' · copied when Task is created'}`);
});
function cloneBatch(items){return JSON.parse(JSON.stringify(items||[]))}
function basename(path){return String(path||'').split(/[\\/]/).filter(Boolean).pop()||path||'Untitled'}
function managedDraftPath(item,index,kind){
  const root=String(item.project||'C:\\project').replace(/[\\/]+$/,'');
  const suffix=kind==='ai'?`${String(index+1).padStart(3,'0')}-ai-validator.md`:`${String(index+1).padStart(3,'0')}-goal.md`;
  return `${root}\\.ai-task-runner\\drafts\\yaml-tasks\\ui-prototype\\${suffix}`;
}
function promptAssetPath(item,asset){
  const root=String(item.project||'C:\\project').replace(/[\\/]+$/,'');
  return `${root}\\.ai-task-runner\\assets\\prompts\\${String(asset||'common/review.md').replaceAll('/','\\')}`;
}
function effectiveGoalFile(item,index){
  if(item.goalMode==='inline')return managedDraftPath(item,index,'goal');
  if(item.goalMode==='asset')return promptAssetPath(item,item.goalAsset);
  return item.goalFile||'';
}
function effectiveAiPromptFile(item,index){
  if(item.aiMode==='inline')return managedDraftPath(item,index,'ai');
  if(item.aiMode==='asset')return promptAssetPath(item,item.aiAsset);
  if(item.aiMode==='file')return item.aiFile||'';
  return '';
}
function itemTitle(item,index){
  if(item.goalMode==='inline')return item.prompt||`RunRequest ${index+1}`;
  if(item.goalMode==='asset')return `Prompt asset · ${item.goalAsset||'Select asset'}`;
  return `Prompt file · ${basename(item.goalFile)}`;
}
function yamlScalar(value){
  const s=String(value??'');
  if(!s)return '""';
  if(/[\n#]/.test(s))return JSON.stringify(s);
  return s;
}
function batchToYaml(items){
  return items.map((x,i)=>{
    const lines=[`- goal_file: ${yamlScalar(effectiveGoalFile(x,i))}`,`  project_root: ${yamlScalar(x.project)}`,`  workflow_file: ${yamlScalar(x.workflow)}`];
    if(x.validatorMode==='file'&&x.validator)lines.push(`  validator: ${yamlScalar(x.validator)}`);
    else if(x.validatorMode==='ai')lines.push('  validator: ai');
    const aiFile=effectiveAiPromptFile(x,i);
    if(aiFile)lines.push(`  ai_validator_prompt_file: ${yamlScalar(aiFile)}`);
    lines.push('  stage_retries: -1');
    return lines.join('\n');
  }).join('\n\n');
}
function modeOptions(value,options){
  return options.map(([v,label])=>`<option value="${v}" ${value===v?'selected':''}>${label}</option>`).join('');
}
function assetOptions(value){
  return PROMPT_ASSETS.map(x=>`<option value="${escapeAttr(x)}" ${value===x?'selected':''}>${escapeHtml(x)}</option>`).join('');
}
function goalSourceBody(x,i){
  if(x.goalMode==='file')return `<div class="pathrow"><input data-item="${i}" data-field="goalFile" value="${escapeAttr(x.goalFile||'')}" placeholder="Prompt / goal file path"><button class="mini-btn" type="button" data-pick-index="${i}" data-pick-field="goalFile" data-pick-kind="goal">Upload file</button></div><div class="source-note">Runner contract：使用 <strong>goal_file</strong>。可直接貼絕對/相對路徑，正式版由後端驗證檔案是否存在。</div>`;
  if(x.goalMode==='asset')return `<div class="pathrow"><select data-item="${i}" data-field="goalAsset">${assetOptions(x.goalAsset)}</select><button class="mini-btn" type="button" data-view-prompts="1">Open Prompts</button></div><div class="source-note">選擇既有 Prompt asset；執行時解析成檔案路徑，再走 <strong>goal_file</strong>。</div>`;
  return `<textarea data-item="${i}" data-field="prompt" placeholder="輸入本次 Task Prompt">${escapeHtml(x.prompt||'')}</textarea><div class="source-note">Inline 會先存成受管檔案：<strong>${escapeHtml(managedDraftPath(x,i,'goal'))}</strong><br>Runner 最後仍讀 <strong>goal_file</strong>，不另外發明 inline runtime path。</div>`;
}
function validatorSourceBody(x,i){
  if(x.validatorMode==='file')return `<div class="pathrow"><input data-item="${i}" data-field="validator" value="${escapeAttr(x.validator||'')}" placeholder="Python validator path"><button class="mini-btn" type="button" data-pick-index="${i}" data-pick-field="validator" data-pick-kind="validator">Upload file</button></div><div class="source-note">File Validator 使用既有 <strong>validator</strong> 欄位。</div>`;
  if(x.validatorMode==='ai')return `<div class="source-note">使用 <strong>validator: ai</strong>；AI 驗證 Stage 仍由選定 Workflow 決定。</div>`;
  return `<div class="source-note">不額外指定 run-level validator；因為已有明確 <strong>workflow_file</strong>，是否有 File / AI Validator 由 Workflow 本身決定。</div>`;
}
function aiSourceBody(x,i){
  if(x.aiMode==='file')return `<div class="pathrow"><input data-item="${i}" data-field="aiFile" value="${escapeAttr(x.aiFile||'')}" placeholder="AI validator prompt path"><button class="mini-btn" type="button" data-pick-index="${i}" data-pick-field="aiFile" data-pick-kind="ai">Upload file</button></div><div class="source-note">Runner contract：<strong>ai_validator_prompt_file</strong>。</div>`;
  if(x.aiMode==='asset')return `<div class="pathrow"><select data-item="${i}" data-field="aiAsset">${assetOptions(x.aiAsset)}</select><button class="mini-btn" type="button" data-view-prompts="1">Open Prompts</button></div><div class="source-note">選現有 Prompt asset，解析成 <strong>ai_validator_prompt_file</strong>。</div>`;
  if(x.aiMode==='inline')return `<textarea data-item="${i}" data-field="aiPrompt" placeholder="AI Validator instructions">${escapeHtml(x.aiPrompt||'')}</textarea><div class="source-note">Inline 先存成：<strong>${escapeHtml(managedDraftPath(x,i,'ai'))}</strong>，再用 <strong>ai_validator_prompt_file</strong>。</div>`;
  return `<div class="source-note">Default：不覆寫 AI Validator Prompt，沿用 Workflow / Runner 既有預設。</div>`;
}
function renderBatchDraft(){
  clearInterval(batchRunTimer);batchState={status:'idle',index:0,recovered:false};setBatchControls();
  const form=document.getElementById('formList');
  if(!batchDraft.length){
    form.innerHTML='<div class="empty-panel"><div><strong>目前沒有 RunRequest</strong><br><br>按下方按鈕新增第一個 Task List。</div></div><button class="addreq" id="addRequest">+ Add RunRequest</button>';
  }else{
    form.innerHTML=batchDraft.map((x,i)=>`<div class="request" data-req="${i}">
      <div class="reqhead"><span class="reqnum">${i+1}</span><strong>${escapeHtml(itemTitle(x,i))}</strong><div class="req-actions"><button data-moveup="${i}" title="Move up">↑</button><button data-movedown="${i}" title="Move down">↓</button><button data-remove="${i}" title="Remove">×</button></div></div>
      <div class="row2"><div class="field"><label>Project root</label><input data-item="${i}" data-field="project" value="${escapeAttr(x.project)}"></div><div class="field"><label>Workflow</label><select data-item="${i}" data-field="workflow"><option ${x.workflow==='ralphy_ai_validate.yaml'?'selected':''}>ralphy_ai_validate.yaml</option><option ${x.workflow==='mixed.yaml'?'selected':''}>mixed.yaml</option><option ${x.workflow==='dynamic_handoff.yaml'?'selected':''}>dynamic_handoff.yaml</option></select></div></div>
      <div class="source-card"><div class="source-head"><div><strong>Task Prompt</strong><small> prompt / goal_file</small></div><select class="source-mode" data-item="${i}" data-field="goalMode">${modeOptions(x.goalMode,[['inline','Inline · managed file'],['file','File path'],['asset','Prompt asset']])}</select></div><div class="source-body">${goalSourceBody(x,i)}</div></div>
      <div class="validation-grid">
        <div class="source-card"><div class="source-head"><div><strong>File Validator</strong><small> validator</small></div><select class="source-mode" data-item="${i}" data-field="validatorMode">${modeOptions(x.validatorMode,[['none','None / Workflow owns'],['file','File path'],['ai','AI']])}</select></div><div class="source-body">${validatorSourceBody(x,i)}</div></div>
        <div class="source-card"><div class="source-head"><div><strong>AI Validator Prompt</strong><small> ai_validator_prompt_file</small></div><select class="source-mode" data-item="${i}" data-field="aiMode">${modeOptions(x.aiMode,[['default','Default'],['inline','Inline · managed file'],['file','File path'],['asset','Prompt asset']])}</select></div><div class="source-body">${aiSourceBody(x,i)}</div></div>
      </div>
    </div>`).join('')+'<button class="addreq" id="addRequest">+ Add RunRequest</button>';
  }
  bindBatchForm();
  syncBatchViews();
}
function renderBatch(key){
  batchDraft=cloneBatch(batchPresets[key]||[]);
  renderBatchDraft();
  document.getElementById('batchLog').textContent=batchDraft.length?'Mock batch is idle. Edit sources, Validate, then Run Batch.':'Empty batch · add a RunRequest to begin.';
}
function previewSummary(x,i){
  const goal=x.goalMode==='inline'?'Inline → managed goal_file':x.goalMode==='asset'?`Prompt asset: ${x.goalAsset}`:`goal_file: ${basename(x.goalFile)}`;
  const validator=x.validatorMode==='file'?`file validator: ${basename(x.validator)}`:x.validatorMode==='ai'?'validator: ai':'validator: workflow';
  const ai=x.aiMode==='default'?'AI prompt: default':x.aiMode==='asset'?`AI prompt asset: ${x.aiAsset}`:x.aiMode==='file'?`AI prompt file: ${basename(x.aiFile)}`:'AI prompt: inline → managed file';
  return `${goal} · ${validator} · ${ai}`;
}
function syncBatchViews(){
  document.getElementById('yamlEditor').value=batchToYaml(batchDraft);
  const preview=document.getElementById('batchPreview');
  if(!batchDraft.length){preview.innerHTML='<div class="empty-panel">No child RunRequests</div>';return}
  preview.innerHTML=batchDraft.map((x,i)=>`<div class="previewitem" data-step="${i}"><span class="step">${i+1}</span><div><strong>${escapeHtml(itemTitle(x,i))}</strong><small>${escapeHtml(basename(x.project))} · ${escapeHtml(x.workflow)}<br>${escapeHtml(previewSummary(x,i))}</small></div><span class="orderchip">Waiting</span></div>`).join('');
}
function bindBatchForm(){
  document.querySelectorAll('[data-item][data-field]').forEach(el=>{
    const handler=()=>{
      const i=+el.dataset.item,field=el.dataset.field;
      const value=el.value;
      if(['goalFile','validator','aiFile'].includes(field)&&!isStagedManagedValue(batchDraft[i],field,value))clearStagedUpload(batchDraft[i],field);
      batchDraft[i][field]=value;
      if(['goalMode','validatorMode','aiMode'].includes(field))renderBatchDraft();
      else syncBatchViews();
    };
    el.addEventListener(el.tagName==='SELECT'?'change':'input',handler);
  });
  document.querySelectorAll('[data-pick-index]').forEach(b=>b.onclick=()=>openFileUploadPicker(+b.dataset.pickIndex,b.dataset.pickField,b.dataset.pickKind));
  document.querySelectorAll('[data-view-prompts]').forEach(b=>b.onclick=()=>{showView('prompts');showToast('Prompt 管理仍使用原本 Prompts workspace')});
  const add=document.getElementById('addRequest');
  if(add)add.onclick=()=>{
    batchDraft.push({
      prompt:'New child RunRequest',goalMode:'inline',goalFile:'',goalAsset:'common/review.md',
      project:'C:\\Users\\kevin\\ai-task-runner',workflow:'ralphy_ai_validate.yaml',
      validatorMode:'none',validator:'',aiMode:'default',aiPrompt:'',aiFile:'',aiAsset:'common/ai_validator.md'
    });
    renderBatchDraft();showToast('新增 mock child RunRequest');
  };
  document.querySelectorAll('[data-remove]').forEach(b=>b.onclick=()=>{batchDraft.splice(+b.dataset.remove,1);renderBatchDraft()});
  document.querySelectorAll('[data-moveup]').forEach(b=>b.onclick=()=>{const i=+b.dataset.moveup;if(i<1)return;[batchDraft[i-1],batchDraft[i]]=[batchDraft[i],batchDraft[i-1]];renderBatchDraft()});
  document.querySelectorAll('[data-movedown]').forEach(b=>b.onclick=()=>{const i=+b.dataset.movedown;if(i>=batchDraft.length-1)return;[batchDraft[i+1],batchDraft[i]]=[batchDraft[i],batchDraft[i+1]];renderBatchDraft()});
}

function parseSimpleYamlList(source){
  const lines=String(source||'').split(/\r?\n/),items=[];let current=null;
  for(const raw of lines){
    if(!raw.trim()||raw.trimStart().startsWith('#'))continue;
    let m=raw.match(/^\s*-\s+([A-Za-z_][\w]*):\s*(.*)$/);
    if(m){current={};items.push(current);current[m[1]]=m[2].trim().replace(/^["']|["']$/g,'');continue}
    m=raw.match(/^\s+([A-Za-z_][\w]*):\s*(.*)$/);
    if(m&&current)current[m[1]]=m[2].trim().replace(/^["']|["']$/g,'');
  }
  return items.map((raw,i)=>{
    const goalFile=raw.goal_file||'',prompt=raw.prompt||raw.goal||'';
    const aiFile=raw.ai_validator_prompt_file||'';
    return {
      prompt:prompt||`Loaded from ${basename(goalFile)}`,
      goalMode:prompt?'inline':'file',goalFile,goalAsset:'common/review.md',
      project:raw.project_root||'C:\\Users\\kevin\\ai-task-runner',
      workflow:raw.workflow_file||'ralphy_ai_validate.yaml',
      validatorMode:raw.validator?raw.validator==='ai'?'ai':'file':'none',
      validator:raw.validator&&raw.validator!=='ai'?raw.validator:'',
      aiMode:aiFile?'file':'default',aiPrompt:'',aiFile,aiAsset:'common/ai_validator.md'
    };
  });
}
function batchValidationErrors(items){
  const errors=[];
  items.forEach((x,i)=>{
    if(!x.project?.trim())errors.push(`item ${i+1}: project_root is required`);
    if(!x.workflow?.trim())errors.push(`item ${i+1}: workflow_file is required`);
    if(x.goalMode==='inline'&&!x.prompt?.trim())errors.push(`item ${i+1}: inline Task Prompt is empty`);
    if(x.goalMode==='file'&&!x.goalFile?.trim())errors.push(`item ${i+1}: goal_file is empty`);
    if(x.validatorMode==='file'&&!x.validator?.trim())errors.push(`item ${i+1}: validator path is empty`);
    if(x.aiMode==='inline'&&!x.aiPrompt?.trim())errors.push(`item ${i+1}: inline AI Validator Prompt is empty`);
    if(x.aiMode==='file'&&!x.aiFile?.trim())errors.push(`item ${i+1}: ai_validator_prompt_file is empty`);
  });
  return errors;
}
function setBatchControls(){
  const locked=['running','stopped'].includes(batchState.status);
  document.getElementById('stopBatch').hidden=batchState.status!=='running';
  document.getElementById('resumeBatch').hidden=batchState.status!=='stopped';
  document.getElementById('resetBatch').hidden=batchState.status!=='stopped';
  document.getElementById('runBatch').disabled=locked;
  document.querySelectorAll('#formList input,#formList textarea,#formList select,#formList button').forEach(el=>el.disabled=locked);
  document.getElementById('yamlEditor').disabled=locked;
  document.querySelectorAll('[data-yamltab]').forEach(el=>el.disabled=locked);
}
function resetBatchRuntime(){
  clearInterval(batchRunTimer);batchRunTimer=null;batchState={status:'idle',index:0,recovered:false};setBatchControls();
}
// YAML is edited only through yamlPlanModal; no Visual/YAML mode switch remains.
document.getElementById('batchPreset').onchange=e=>{renderBatch(e.target.value);showToast(`載入 ${e.target.options[e.target.selectedIndex].text}`)};
document.getElementById('yamlEditor').addEventListener('input',()=>{
  if(batchState.status==='running')return;
  if(batchState.status==='stopped')batchState.currentDirty=true;
  document.getElementById('batchLog').textContent=batchState.status==='stopped'
    ?'YAML edited while Paused. Validate before Resume; current item will fresh restart.'
    :'YAML edited manually. Press Validate to parse known RunRequest fields back into Form.';
});
document.getElementById('validateYaml').onclick=()=>{
  const current=document.getElementById('yamlEditor').value.trim(),generated=batchToYaml(batchDraft).trim();
  let items=batchDraft;
  if(current!==generated){
    items=parseSimpleYamlList(current);
    if(items.length)batchDraft=items;
  }
  const errors=batchValidationErrors(items);
  if(!items.length)errors.push('batch must contain at least one child RunRequest');
  if(errors.length){
    showToast(`YAML invalid · ${errors.length} issue(s)`);
    document.getElementById('batchLog').textContent='[validate] FAIL\n- '+errors.join('\n- ');
    return;
  }
  if(current!==generated)renderBatchDraft();
  showToast(`YAML List valid · ${items.length} child RunRequests`);
  document.getElementById('batchLog').textContent=`[validate] PASS · ${items.length} child RunRequests\n[validate] goal_file / validator / ai_validator_prompt_file mapped to current RunRequest contract\n[validate] Formal implementation calls the existing backend loader/schema path.`;
};
function ensureBatchParentTask(){
  let t=batchParentTaskId?taskMap[batchParentTaskId]:null;
  if(!t){
    const id='YAML-'+(++taskSequence),preset=document.getElementById('batchPreset');
    batchParentTaskId=id;
    t={id,status:'ongoing',title:`Task List · ${preset.options[preset.selectedIndex]?.text||'Batch'}`,runtime:'running',desc:`Sequential YAML List · ${batchDraft.length} child RunRequests`,tags:['Task List',`${batchDraft.length} items`],workflow:'YAML List',project:currentProjectKey||'ai-task-runner',progress:[0,batchDraft.length],elapsed:'0m',stage:`Item 1 / ${batchDraft.length}`,session:'batch',goal:'Execute the current Task Lists batch through the existing YAML List / RunRequest runtime.',workspaceKind:'batch',branch:'—',executionRoot:`${batchDraft.length} child RunRequest workspaces`};
    taskMap[id]=t;
  }
  return t;
}
function updateBatchParentTask(runtime,status,index=batchState.index){
  const t=ensureBatchParentTask();
  t.runtime=runtime;t.status=status;t.progress=[Math.min(index,batchDraft.length),batchDraft.length];
  t.stage=batchDraft.length?`YAML item ${Math.min(index+1,batchDraft.length)} / ${batchDraft.length}`:'Batch';
  t.desc=`Sequential YAML List · ${batchDraft.length} child RunRequests · ${runtimeLabel(runtime)}`;
  t.tags=['Task List',`${batchDraft.length} items`];
  t.executionRoot=`${batchDraft.length} child RunRequest workspaces`;
  renderBoardFromMap();
  return t;
}
function finishBatch(status,message){
  clearInterval(batchRunTimer);batchRunTimer=null;batchState.status=status;setBatchControls();
  if(status==='completed')updateBatchParentTask('done','closed',batchDraft.length);
  else if(status==='failed')updateBatchParentTask('failed','paused',batchState.index);
  if(message)document.getElementById('batchLog').textContent+=`\n${message}`;
}
function batchTick(){
  if(batchState.status!=='running')return;
  const items=[...document.querySelectorAll('.previewitem')],log=document.getElementById('batchLog');
  if(batchState.index>=items.length){finishBatch('completed','[done] batch completed');showToast('Mock batch completed');return}
  const item=items[batchState.index],outcome=document.getElementById('batchOutcome').value;
  items.forEach((x,n)=>{if(n!==batchState.index)x.classList.remove('active')});
  item.classList.add('active');item.querySelector('.orderchip').textContent='Running';
  if(outcome==='recover'&&batchState.index===0&&!batchState.recovered){
    batchState.recovered=true;item.querySelector('.orderchip').textContent='Recovering';
    updateBatchParentTask('recover','ongoing',batchState.index);
    log.textContent+='\n[00:05] item 1 · HTTP 503\n[00:10] StageExecutor same-session retry';return;
  }
  if(outcome==='fail'&&batchState.index===1){
    item.classList.remove('active');item.querySelector('.orderchip').textContent='Failed';
    finishBatch('failed','[00:12] item 2 · deterministic validation FAIL\n[00:12] batch stopped');
    showToast('Mock batch failed at item 2');return;
  }
  item.classList.remove('active');item.classList.add('done');item.querySelector('.orderchip').textContent='PASS';
  log.textContent+=`\n[00:${String((batchState.index+1)*6).padStart(2,'0')}] item ${batchState.index+1} PASS`;
  batchState.index++;
  updateBatchParentTask('running','ongoing',batchState.index);
}
document.getElementById('runBatch').onclick=()=>{
  const errors=batchValidationErrors(batchDraft);
  if(!batchDraft.length)errors.push('batch is empty');
  if(errors.length){document.getElementById('batchLog').textContent='[run] BLOCKED\n- '+errors.join('\n- ');showToast('請先修正 Batch 設定');return}
  clearInterval(batchRunTimer);
  document.querySelectorAll('.previewitem').forEach(i=>{i.classList.remove('active','done');i.querySelector('.orderchip').textContent='Waiting'});
  batchState={status:'running',index:0,recovered:false};setBatchControls();
  batchParentTaskId=null;
  updateBatchParentTask('running','ongoing',0);
  document.getElementById('batchLog').textContent='[00:00] batch started · sequential child RunRequests\n[00:00] one Task List parent Task created in Tasks\n[00:00] inline sources materialized into .ai-task-runner/drafts/yaml-tasks/...';
  batchTick();batchRunTimer=setInterval(batchTick,900);
};
document.getElementById('stopBatch').onclick=()=>{
  if(batchState.status!=='running')return;
  clearInterval(batchRunTimer);batchRunTimer=null;batchState.status='stopped';setBatchControls();
  const item=document.querySelector(`.previewitem[data-step="${batchState.index}"]`);
  if(item)item.querySelector('.orderchip').textContent='Stopped';
  updateBatchParentTask('stopped','paused',batchState.index);
  document.getElementById('batchLog').textContent+='\n[user] batch stop requested · current child durable state preserved';
  showToast('Mock Batch stopped · Tasks parent moved to Paused');
};
document.getElementById('resumeBatch').onclick=()=>{
  if(batchState.status!=='stopped')return;
  batchState.status='running';setBatchControls();
  const item=document.querySelector(`.previewitem[data-step="${batchState.index}"]`);
  if(item)item.querySelector('.orderchip').textContent='Running';
  updateBatchParentTask('running','ongoing',batchState.index);
  document.getElementById('batchLog').textContent+='\n[user] resume · continue current child RunRequest';
  batchRunTimer=setInterval(batchTick,900);showToast('Mock Batch resumed · Tasks parent Ongoing');
};

document.getElementById('resetBatch').onclick=()=>{
  if(batchState.status!=='stopped')return;
  resetBatchRuntime();
  syncBatchViews();
  if(batchParentTaskId&&taskMap[batchParentTaskId]){
    const t=taskMap[batchParentTaskId];t.runtime='idle';t.status='new';t.progress=[0,batchDraft.length];t.stage='Batch draft';t.desc='Task List reset；draft unlocked for editing.';renderBoardFromMap();
  }
  document.getElementById('batchLog').textContent='[reset] stopped batch abandoned · draft unlocked for editing';
  showToast('Mock Batch reset · parent Task moved to New');
};

function escapeHtml(s){return String(s??'').replace(/[&<>"']/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#039;'}[m]))}
function escapeAttr(s){return escapeHtml(s).replace(/`/g,'&#096;')}

const WORKFLOW_CAPABILITIES={
  'ralphy_ai_validate.yaml':{file:false,ai:true,label:'AI validation'},
  'mixed.yaml':{file:true,ai:true,label:'File + AI validation'},
  'file.yaml':{file:true,ai:false,label:'File validation'},
  'dynamic_handoff.yaml':{file:false,ai:true,label:'AI validation'}
};
function workflowCaps(name){return WORKFLOW_CAPABILITIES[basename(name)]||{file:false,ai:false,label:'Workflow-owned validation'}}
function workflowCapsHtml(name){
  const caps=workflowCaps(name),chips=[];
  if(caps.file)chips.push('<span class="cap-chip">File Validator</span>');
  if(caps.ai)chips.push('<span class="cap-chip">AI Validator</span>');
  if(!chips.length)chips.push('<span class="cap-chip neutral">No extra validation input</span>');
  return chips.join('');
}
function sourceTabs(value,modes,attrs=''){
  return '<div class="source-tabs">'+modes.map(([key,label])=>`<button type="button" class="${value===key?'active':''}" data-source-value="${key}" ${attrs}>${label}</button>`).join('')+'</div>';
}

let newTaskDraft={
  goalMode:'inline',prompt:'Implement the requested change and run focused verification.',goalFile:'',goalAsset:'common/review.md',
  validator:'',aiMode:'default',aiPrompt:'',aiFile:'',aiAsset:'common/ai_validator.md',_uploads:{}
};
function taskGoalBody(){
  if(newTaskDraft.goalMode==='file')return `<div class="pathrow"><input id="taskGoalFile" value="${escapeAttr(newTaskDraft.goalFile)}" placeholder="Prompt / goal file path"><button class="mini-btn" type="button" id="taskPickGoal">Upload file</button></div><div class="source-note">執行時使用既有 <strong>goal_file</strong>。</div>`;
  if(newTaskDraft.goalMode==='asset')return `<div class="pathrow"><select id="taskGoalAsset">${assetOptions(newTaskDraft.goalAsset)}</select><button class="mini-btn" type="button" data-view-prompts-task>Open Prompts</button></div><div class="source-note">Prompt Asset 解析成檔案路徑後交給 Runner。</div>`;
  return `<textarea id="taskPromptInline" placeholder="輸入 Task Prompt">${escapeHtml(newTaskDraft.prompt)}</textarea><div class="source-note">Write 模式會存成受管 draft，再以 <strong>goal_file</strong> 執行。</div>`;
}
function taskAiBody(){
  if(newTaskDraft.aiMode==='file')return `<div class="pathrow"><input id="taskAiFile" value="${escapeAttr(newTaskDraft.aiFile)}" placeholder="AI validator prompt path"><button class="mini-btn" type="button" id="taskPickAi">Upload file</button></div>`;
  if(newTaskDraft.aiMode==='asset')return `<div class="pathrow"><select id="taskAiAsset">${assetOptions(newTaskDraft.aiAsset)}</select><button class="mini-btn" type="button" data-view-prompts-task>Open Prompts</button></div>`;
  if(newTaskDraft.aiMode==='inline')return `<textarea id="taskAiInline" placeholder="AI Validator instructions">${escapeHtml(newTaskDraft.aiPrompt)}</textarea><div class="source-note">Write 模式同樣會先存受管 draft，再交給既有 <strong>ai_validator_prompt_file</strong>。</div>`;
  return '<div class="source-note">Default：沿用 Workflow / Runner 的 AI Validator Prompt。</div>';
}
function captureTaskFileInput(id,field){
  const input=document.getElementById(id);if(!input)return;
  const value=String(input.value||'').trim();
  if(value){
    if(!isStagedManagedValue(newTaskDraft,field,value))clearStagedUpload(newTaskDraft,field);
    newTaskDraft[field]=value;
  }else if(!stagedUploadMeta(newTaskDraft,field))newTaskDraft[field]='';
}
function captureNewTaskSources(){
  if(document.getElementById('taskPromptInline'))newTaskDraft.prompt=document.getElementById('taskPromptInline').value;
  captureTaskFileInput('taskGoalFile','goalFile');
  if(document.getElementById('taskGoalAsset'))newTaskDraft.goalAsset=document.getElementById('taskGoalAsset').value;
  captureTaskFileInput('taskValidatorFile','validator');
  if(document.getElementById('taskAiInline'))newTaskDraft.aiPrompt=document.getElementById('taskAiInline').value;
  captureTaskFileInput('taskAiFile','aiFile');
  if(document.getElementById('taskAiAsset'))newTaskDraft.aiAsset=document.getElementById('taskAiAsset').value;
}
let newTaskWorkspaceMode='auto';
function mainBusyTask(project){
  return productTaskRecords().find(t=>t.project===project&&t.workspaceKind==='main'&&['running','recover'].includes(t.runtime));
}
function resolveTaskWorkspace(project,id,mode=newTaskWorkspaceMode){
  const busy=mainBusyTask(project);
  const chosen=mode==='auto'?autoWorkspaceKind(!!busy):mode;
  if(chosen==='main'&&busy)return {ok:false,reason:`Main workspace 正被 ${busy.id} 使用 · Auto policy 不使用 Worktree`,busy};
  if(chosen==='worktree')return {ok:true,kind:'worktree',branch:`task/${id}`,root:worktreeRootFor(project,id),busy};
  return {ok:true,kind:'main',branch:projectMeta[project]?.branch||'main',root:projectMeta[project]?.path||project,busy};
}
function prepareTaskWorkspaceForRun(t){
  if(!t)return {ok:false,reason:'Task not found'};
  if((t.workspacePolicy||'auto')==='auto'){
    const before=t.workspaceKind||'main',resolved=resolveTaskWorkspace(t.project,t.id,'auto');if(!resolved.ok)return resolved;
    t.workspaceKind=resolved.kind;t.branch=resolved.branch;t.executionRoot=resolved.root;
    return {...resolved,changed:before!==resolved.kind};
  }
  if(t.workspaceKind==='main'||t.workspacePolicy==='main'){
    const busy=mainBusyTask(t.project);
    if(busy&&busy.id!==t.id)return {ok:false,reason:`Main workspace 正被 ${busy.id} 使用；請改用 Worktree`,busy};
  }
  return {ok:true,kind:t.workspaceKind||t.workspacePolicy||'main',branch:t.branch,root:t.executionRoot};
}
function renderNewTaskWorkspace(){
  const host=document.getElementById('newTaskWorkspace');if(!host)return;
  const project=document.getElementById('newTaskProject')?.value||'ai-task-runner';
  const busy=mainBusyTask(project),previewId='T-'+(taskSequence+1);
  const resolved=resolveTaskWorkspace(project,previewId,newTaskWorkspaceMode);
  const option=(mode,title,desc,status,disabled=false)=>`<label class="workspace-option ${newTaskWorkspaceMode===mode?'selected':''} ${disabled?'disabled':''}"><input type="radio" name="workspaceMode" value="${mode}" ${newTaskWorkspaceMode===mode?'checked':''} ${disabled?'disabled':''}><strong>${title}</strong><small>${desc}</small><span class="workspace-status">${status}</span></label>`;
  host.innerHTML=`<div class="workspace-options">
    ${option('auto','Auto',autoWorkspacePolicyDescription(),autoWorkspaceStatus(busy,previewId))}
    ${option('main','Main workspace','直接使用專案目前 working tree；同一路徑只能一個 Running Task。',busy?`Busy · ${busy.id} 正在執行`:'Available',!!busy)}
    ${option('worktree','Isolated worktree','為這個 Task 建立獨立 branch/path，可與同專案其他 Task 同時執行。',`task/${previewId}`)}
  </div><div class="workspace-preview"><strong>Execution preview</strong><br>${resolved.ok?(resolved.kind==='worktree'?`Worktree · ${resolved.branch}<br>${resolved.root}`:`Main · ${resolved.branch}<br>${resolved.root}`):resolved.reason}</div>`;
  host.querySelectorAll('input[name="workspaceMode"]').forEach(r=>r.onchange=()=>{newTaskWorkspaceMode=r.value;renderNewTaskWorkspace()});
}
document.getElementById('newTaskProject').addEventListener('change',renderNewTaskWorkspace);
function renderNewTaskSources(){
  const workflow=document.getElementById('newTaskWorkflow').value,caps=workflowCaps(workflow);
  document.getElementById('newTaskWorkflowCaps').innerHTML=workflowCapsHtml(workflow);
  document.getElementById('newTaskPromptSource').innerHTML=`<div class="source-card task-source-card"><div class="source-head"><div><strong>Task Prompt</strong><small>goal_file</small></div>${sourceTabs(newTaskDraft.goalMode,[['inline','Write'],['file','File'],['asset','Asset']],'data-task-goal-mode')}</div><div class="source-body">${taskGoalBody()}</div></div>`;
  const fields=[];
  if(caps.file)fields.push(`<div class="source-card"><div class="source-head"><div><strong>File Validator</strong><small>validator</small></div><span class="cap-chip">Required</span></div><div class="source-body"><div class="pathrow"><input id="taskValidatorFile" value="${escapeAttr(newTaskDraft.validator)}" placeholder="Python validator path"><button class="mini-btn" type="button" id="taskPickValidator">Upload file</button></div></div></div>`);
  if(caps.ai)fields.push(`<div class="source-card"><div class="source-head"><div><strong>AI Validator Prompt</strong><small>ai_validator_prompt_file</small></div>${sourceTabs(newTaskDraft.aiMode,[['default','Default'],['inline','Write'],['file','File'],['asset','Asset']],'data-task-ai-mode')}</div><div class="source-body">${taskAiBody()}</div></div>`);
  document.getElementById('newTaskValidationSource').innerHTML=fields.length?`<div class="validation-grid ${fields.length===1?'one':''}">${fields.join('')}</div>`:'<div class="validation-empty">這個 Workflow 不需要額外 Validator 輸入。</div>';
  document.querySelectorAll('[data-task-goal-mode]').forEach(b=>b.onclick=()=>{captureNewTaskSources();newTaskDraft.goalMode=b.dataset.sourceValue;renderNewTaskSources()});
  document.querySelectorAll('[data-task-ai-mode]').forEach(b=>b.onclick=()=>{captureNewTaskSources();newTaskDraft.aiMode=b.dataset.sourceValue;renderNewTaskSources()});
  document.getElementById('taskPickGoal')?.addEventListener('click',()=>openFileUploadPicker(-1,'goalFile','goal','task'));
  document.getElementById('taskPickValidator')?.addEventListener('click',()=>openFileUploadPicker(-1,'validator','validator','task'));
  document.getElementById('taskPickAi')?.addEventListener('click',()=>openFileUploadPicker(-1,'aiFile','ai','task'));
  document.querySelectorAll('[data-view-prompts-task]').forEach(b=>b.onclick=()=>{closeModal('newTaskModal');showView('prompts');showToast('Prompt Asset 仍由原本 Prompts workspace 管理')});
  renderNewTaskWorkspace();
}
document.getElementById('newTaskWorkflow').addEventListener('change',()=>{captureNewTaskSources();renderNewTaskSources()});
document.getElementById('newTask').addEventListener('click',()=>{
  newTaskDraft={goalMode:'inline',prompt:'Implement the requested change and run focused verification.',goalFile:'',goalAsset:'common/review.md',validator:'',aiMode:'default',aiPrompt:'',aiFile:'',aiAsset:'common/ai_validator.md'};
  newTaskWorkspaceMode='auto';
  document.getElementById('newTaskProject').value=currentProjectKey;renderNewTaskSources();renderNewTaskWorkspace();
});
document.getElementById('createTaskConfirm').onclick=()=>{
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
  const t={id,status:'new',title,runtime:'idle',desc:workspace.kind==='worktree'?'尚未開始；Run 時會使用 isolated worktree。':'尚未開始；Run 時使用 Main workspace。',tags,workflow,project,progress:[0,4],elapsed:'—',stage:'Idle',session:'—',goal,promptSource:{...newTaskDraft},workspacePolicy:newTaskWorkspaceMode,workspaceKind:workspace.kind,branch:workspace.branch,executionRoot:workspace.root};
  taskMap[id]=t;renderBoardFromMap();closeModal('newTaskModal');showToast(`已建立 mock Task · ${workspaceName(t)}`);openTaskById(id);
};

function batchToYaml(items){
  return items.map((x,i)=>{
    const caps=workflowCaps(x.workflow);
    const lines=[`- goal_file: ${yamlScalar(effectiveGoalFile(x,i))}`,`  project_root: ${yamlScalar(x.project)}`,`  workflow_file: ${yamlScalar(x.workflow)}`];
    if(caps.file&&x.validator)lines.push(`  validator: ${yamlScalar(x.validator)}`);
    if(caps.ai){const aiFile=effectiveAiPromptFile(x,i);if(aiFile)lines.push(`  ai_validator_prompt_file: ${yamlScalar(aiFile)}`)}
    lines.push('  stage_retries: -1');
    return lines.join('\n');
  }).join('\n\n');
}
function yamlSourceTabs(i,field,value,modes){
  return sourceTabs(value,modes,`data-yaml-source data-item="${i}" data-field="${field}"`);
}
function renderBatchDraft(){
  const form=document.getElementById('formList');
  if(!batchDraft.length){
    form.innerHTML='<div class="empty-panel"><div><strong>目前沒有 RunRequest</strong><br><br>按下方按鈕新增第一個 Task List。</div></div><button class="addreq" id="addRequest">+ Add RunRequest</button>';
  }else{
    form.innerHTML=batchDraft.map((x,i)=>{
      const caps=workflowCaps(x.workflow),validation=[];
      if(caps.file)validation.push(`<div class="source-card"><div class="source-head"><div><strong>File Validator</strong><small>validator</small></div><span class="cap-chip">Required</span></div><div class="source-body"><div class="pathrow"><input data-item="${i}" data-field="validator" value="${escapeAttr(x.validator||'')}" placeholder="Python validator path"><button class="mini-btn" type="button" data-pick-index="${i}" data-pick-field="validator" data-pick-kind="validator">Upload file</button></div></div></div>`);
      if(caps.ai)validation.push(`<div class="source-card"><div class="source-head"><div><strong>AI Validator Prompt</strong><small>ai_validator_prompt_file</small></div>${yamlSourceTabs(i,'aiMode',x.aiMode,[['default','Default'],['inline','Write'],['file','File'],['asset','Asset']])}</div><div class="source-body">${planizeSourceHtml(aiSourceBody(x,i),i)}</div></div>`);
      return `<div class="request" data-req="${i}"><div class="reqhead"><span class="reqnum">${i+1}</span><strong>${escapeHtml(itemTitle(x,i))}</strong><div class="req-actions"><button data-moveup="${i}" title="Move up">↑</button><button data-movedown="${i}" title="Move down">↓</button><button data-remove="${i}" title="Remove">×</button></div></div><div class="request-body"><div class="workflow-row"><div class="field"><label>Project root</label><input data-item="${i}" data-field="project" value="${escapeAttr(x.project)}"></div><div class="field"><label>Workflow</label><select data-item="${i}" data-field="workflow"><option ${x.workflow==='ralphy_ai_validate.yaml'?'selected':''}>ralphy_ai_validate.yaml</option><option ${x.workflow==='mixed.yaml'?'selected':''}>mixed.yaml</option><option ${x.workflow==='file.yaml'?'selected':''}>file.yaml</option><option ${x.workflow==='dynamic_handoff.yaml'?'selected':''}>dynamic_handoff.yaml</option></select></div></div><div class="workflow-caps">${workflowCapsHtml(x.workflow)}</div><div class="source-card"><div class="source-head"><div><strong>Task Prompt</strong><small>goal_file</small></div>${yamlSourceTabs(i,'goalMode',x.goalMode,[['inline','Write'],['file','File'],['asset','Asset']])}</div><div class="source-body">${planizeSourceHtml(goalSourceBody(x,i),i)}</div></div>${validation.length?`<div class="validation-grid ${validation.length===1?'one':''}">${validation.join('')}</div>`:'<div class="validation-empty">這個 Workflow 不需要額外 Validator 輸入。</div>'}</div></div>`;
    }).join('')+'<button class="addreq" id="addRequest">+ Add RunRequest</button>';
  }
  bindBatchForm();syncBatchViews();
}
function bindBatchForm(){
  document.querySelectorAll('[data-item][data-field]:not([data-yaml-source])').forEach(el=>{
    const handler=()=>{
      const i=+el.dataset.item,field=el.dataset.field;batchDraft[i][field]=el.value;
      if(field==='workflow')renderBatchDraft();else syncBatchViews();
    };
    el.addEventListener(el.tagName==='SELECT'?'change':'input',handler);
  });
  document.querySelectorAll('[data-yaml-source]').forEach(b=>b.onclick=()=>{const i=+b.dataset.item,field=b.dataset.field;if(batchState.status==='stopped'&&i===batchState.index)batchState.currentDirty=true;batchDraft[i][field]=b.dataset.sourceValue;renderBatchDraft()});
  document.querySelectorAll('[data-pick-index]').forEach(b=>b.onclick=()=>openFileUploadPicker(+b.dataset.pickIndex,b.dataset.pickField,b.dataset.pickKind,'batch'));
  document.querySelectorAll('[data-view-prompts]').forEach(b=>b.onclick=()=>{showView('prompts');showToast('Prompt 管理仍使用原本 Prompts workspace')});
  const add=document.getElementById('addRequest');
  if(add)add.onclick=()=>{batchDraft.push({prompt:'New child RunRequest',goalMode:'inline',goalFile:'',goalAsset:'common/review.md',project:'C:\\Users\\kevin\\ai-task-runner',workflow:'ralphy_ai_validate.yaml',validatorMode:'file',validator:'',aiMode:'default',aiPrompt:'',aiFile:'',aiAsset:'common/ai_validator.md'});renderBatchDraft();showToast('新增 mock child RunRequest')};
  document.querySelectorAll('[data-remove]').forEach(b=>b.onclick=()=>{batchDraft.splice(+b.dataset.remove,1);renderBatchDraft()});
  document.querySelectorAll('[data-moveup]').forEach(b=>b.onclick=()=>{const i=+b.dataset.moveup;if(i<1)return;[batchDraft[i-1],batchDraft[i]]=[batchDraft[i],batchDraft[i-1]];renderBatchDraft()});
  document.querySelectorAll('[data-movedown]').forEach(b=>b.onclick=()=>{const i=+b.dataset.movedown;if(i>=batchDraft.length-1)return;[batchDraft[i+1],batchDraft[i]]=[batchDraft[i],batchDraft[i+1]];renderBatchDraft()});
}
function batchValidationErrors(items){
  const errors=[];
  items.forEach((x,i)=>{
    const caps=workflowCaps(x.workflow);
    if(!x.project?.trim())errors.push(`item ${i+1}: project_root is required`);
    if(!x.workflow?.trim())errors.push(`item ${i+1}: workflow_file is required`);
    if(x.goalMode==='inline'&&!x.prompt?.trim())errors.push(`item ${i+1}: Task Prompt is empty`);
    if(x.goalMode==='file'&&!x.goalFile?.trim())errors.push(`item ${i+1}: goal_file is empty`);
    if(caps.file&&!x.validator?.trim())errors.push(`item ${i+1}: selected Workflow requires File Validator`);
    if(caps.ai&&x.aiMode==='inline'&&!x.aiPrompt?.trim())errors.push(`item ${i+1}: AI Validator Prompt is empty`);
    if(caps.ai&&x.aiMode==='file'&&!x.aiFile?.trim())errors.push(`item ${i+1}: ai_validator_prompt_file is empty`);
  });
  return errors;
}
function previewSummary(x,i){
  const caps=workflowCaps(x.workflow);
  const goal=x.goalMode==='inline'?'Write → managed goal_file':x.goalMode==='asset'?`Prompt asset: ${x.goalAsset}`:`goal_file: ${basename(x.goalFile)}`;
  const validator=caps.file?`file validator: ${basename(x.validator)||'required'}`:'no file validator input';
  const ai=caps.ai?(x.aiMode==='default'?'AI prompt: default':x.aiMode==='asset'?`AI prompt asset: ${x.aiAsset}`:x.aiMode==='file'?`AI prompt file: ${basename(x.aiFile)}`:'AI prompt: Write → managed file'):'no AI validator input';
  return `${goal} · ${validator} · ${ai}`;
}

renderNewTaskSources();
let currentProjectKey=projectMeta[window.UiBootstrap?.state?.currentProjectKey]?window.UiBootstrap.state.currentProjectKey:'ai-task-runner';
function selectProject(key){
  if(!projectMeta[key])return;
  currentProjectKey=key;
  try{localStorage.setItem(window.UiBootstrap?.keys?.currentProject||'ai-task-runner.prototype.currentProject',key)}catch(_){};
  const meta=projectMeta[key];
  document.querySelectorAll('.project[data-project]').forEach(x=>x.classList.toggle('active',x.dataset.project===key));
  document.getElementById('projectSwitcherPath').textContent=meta.path;
  document.getElementById('chatProjectLine').textContent=`${meta.path} · 一般對話，不建立 Runner Task`;
  if(document.getElementById('newTaskProject'))document.getElementById('newTaskProject').value=key;
  if(typeof renderNewTaskWorkspace==='function')renderNewTaskWorkspace();
}
// Project click navigation is bound once by the final Project→Chat block.
document.getElementById('newProjectDemo').onclick=()=>showToast('Mock: New Project 固定在 sidebar 上方；正式版沿用既有 Open/Add Project 流程');

const chatSessions=[
  {id:'design',name:'UI 設計討論',messages:chatPresets.design.slice()},
  {id:'debug',name:'Bug investigation',messages:chatPresets.debug.slice()},
  {id:'review',name:'Code review',messages:chatPresets.review.slice()},
  {id:'long',name:'Long conversation',messages:chatPresets.long.slice()}
];
let activeChatId='design',chatSequence=4;
function activeChat(){return chatSessions.find(x=>x.id===activeChatId)||chatSessions[0]}
function syncChatSessionSelect(){
  const select=document.getElementById('chatPreset');
  select.innerHTML=chatSessions.map(x=>`<option value="${x.id}" ${x.id===activeChatId?'selected':''}>${escapeHtml(x.name)}</option>`).join('');
}
function renderChatSession(){
  syncChatSessionSelect();
  const session=activeChat(),box=document.getElementById('chatMessages');box.innerHTML='';
  (session?.messages||[]).forEach(([who,body])=>{
    const el=document.createElement('div');el.className='msg '+who;
    el.innerHTML=(who==='assistant'?'<div class="msgmeta"><span class="avatar">AI</span>Assistant</div>':'<div class="msgmeta">You</div>')+escapeHtml(body);
    box.appendChild(el);
  });
  if(!(session?.messages||[]).length){
    box.innerHTML='<div class="empty-panel"><div><strong>New Chat</strong><br><br>這是一個新的獨立 mock session。輸入訊息後只會寫進這個 Chat。</div></div>';
  }
  box.scrollTop=box.scrollHeight;
}
function renderChat(key){if(chatSessions.some(x=>x.id===key))activeChatId=key;renderChatSession()}
document.getElementById('chatPreset').onchange=e=>{activeChatId=e.target.value;renderChatSession()};
document.getElementById('newChat').onclick=()=>{
  const id='chat-'+(++chatSequence);
  chatSessions.unshift({id,name:`New Chat ${chatSequence}`,messages:[]});
  activeChatId=id;renderChatSession();document.getElementById('chatInput').focus();showToast('已建立新的 mock Chat session');
};
document.getElementById('renameChat').onclick=()=>{
  document.getElementById('renameChatInput').value=activeChat()?.name||'';
  openModal('renameChatModal');setTimeout(()=>document.getElementById('renameChatInput').select(),0);
};
document.getElementById('renameChatConfirm').onclick=()=>{
  const value=document.getElementById('renameChatInput').value.trim();
  if(!value){showToast('Chat name 不可空白');return}
  activeChat().name=value;closeModal('renameChatModal');renderChatSession();showToast('Chat renamed');
};
document.getElementById('chatSend').onclick=()=>{
  const input=document.getElementById('chatInput'),text=input.value.trim();if(!text)return;
  const session=activeChat();session.messages.push(['user',text]);
  const reply=/task|執行|run/i.test(text)?'這是一般 Chat。若要長時間執行，可用「建立 Task」帶到 Task 表單。':'收到。這則回覆只屬於目前 Chat session；切換其他 Chat 後會保留各自歷史。';
  session.messages.push(['assistant',reply]);input.value='';resizeChatComposer();renderChatSession();
};

// Task List is the only batch-facing UI concept; YAML is an editor mode only.
ensureBatchParentTask=function(){
  let t=batchParentTaskId?taskMap[batchParentTaskId]:null;
  if(!t){
    const id='T-'+(++taskSequence),items=cloneBatch(batchDraft.length?batchDraft:defaultTaskListItems(currentProjectKey));
    batchParentTaskId=id;
    t={id,kind:'list',status:'new',title:'New Task List',runtime:'idle',desc:`Task List · ${items.length} child RunRequests`,tags:[`${items.length} items`],workflow:'Task List',project:currentProjectKey,progress:[0,items.length],elapsed:'—',stage:'Draft',session:'batch',goal:'Execute an ordered Task List using existing RunRequest runtime.',workspaceKind:'batch',branch:'—',executionRoot:`${items.length} child workspaces`,listItems:items};
    taskMap[id]=t;
  }
  return t;
};
updateBatchParentTask=function(runtime,status,index=batchState.index){
  const t=ensureBatchParentTask();
  t.kind='list';t.runtime=runtime;t.status=status;t.progress=[Math.min(index,batchDraft.length),batchDraft.length];
  t.stage=batchDraft.length?`Item ${Math.min(index+1,batchDraft.length)} / ${batchDraft.length}`:'Task List';
  t.desc=`Task List · ${batchDraft.length} child RunRequests · ${runtimeLabel(runtime)}`;
  t.tags=[`${batchDraft.length} items`];t.workflow='Task List';t.listItems=cloneBatch(batchDraft);t.executionRoot=`${batchDraft.length} child workspaces`;
  renderBoardFromMap();return t;
};
