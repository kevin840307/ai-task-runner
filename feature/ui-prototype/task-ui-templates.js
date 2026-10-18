// Shared Task UI templates for the static prototype.
// Keep one DOM definition per surface so Chat / Board / Task List reuse the same markup.
// These boundaries intentionally map to future React components: TaskEditor, TaskListWorkspace,
// TaskSourceCard, TaskListEmptyState and TaskListAddFooter.
(function(){
  const esc=value=>String(value??'').replace(/[&<>"']/g,ch=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));

  const taskEditor=()=>`
<section class="task-create-modal task-workspace-view" id="newTaskModal" data-task-surface="editor">
    <div class="modal-head"><div><h2 id="taskFormTitle">New task</h2><p id="taskFormHelp">Configure this task only.</p></div><button class="close" data-close-modal="newTaskModal">×</button></div>
    <div class="modal-body">
      <div class="modal-grid task-basics">
        <div class="field full" id="taskEditorTitleField"><label>Title <span class="field-optional">optional</span></label><input id="newTaskTitle" placeholder="Auto from task prompt" value=""></div>
        <div class="field full"><label>Project</label><div class="project-combobox"><input id="newTaskProject" autocomplete="off" placeholder="Select a project or type a path"><button type="button" id="projectDropdownToggle" aria-label="Show all projects" aria-expanded="false"><span class="project-dropdown-chevron" aria-hidden="true"></span></button><div class="project-dropdown" id="projectDropdown" hidden></div></div><small class="field-help" id="projectFieldHelp">Current Project is the default. You can also type a new local path.</small><datalist id="projectOptions" hidden></datalist></div>
        <div class="field full" id="newTaskWorkflowField"><label>Workflow</label><select id="newTaskWorkflow"><option>ralphy_ai_validate.yaml</option><option>mixed.yaml</option><option>file.yaml</option><option>dynamic_handoff.yaml</option></select></div>
      </div>
      <div id="newTaskWorkflowCaps" class="workflow-caps"></div>
      <div id="editTaskScopeNote" class="edit-task-scope-note" hidden></div>
      <div id="newTaskListSetup" hidden></div>
      <div id="newTaskPromptSource"></div>
      <div id="newTaskValidationSource"></div>
      <div class="workspace-selector-wrap">
        <div class="workspace-selector-title"><div><strong>Workspace</strong><small>Auto / Main / isolated Worktree</small></div><span class="workspace-recommended">Auto recommended</span></div>
        <div id="newTaskWorkspace"></div>
      </div>
      <div hidden><button type="button" id="addNextTaskFromNew"></button><button type="button" id="addExistingTaskFromNew"></button></div>
      <textarea id="newTaskGoal" hidden>Implement the requested change and run focused verification.</textarea>
      <div class="state-hint">Task settings belong to this task only. Workflow capabilities decide which validation fields appear.</div>
    </div>
    <div class="modal-foot"><button class="btn" data-close-modal="newTaskModal">Cancel</button><button class="btn primary" id="createTaskConfirm">Create Task</button></div>
</section>`;

  const taskListWorkspace=()=>`
<div class="modal-overlay" id="planModal" data-task-surface="list-workspace">
  <div class="modal-card plan-modal-card">
    <div class="modal-head plan-modal-head">
      <div class="plan-title-block"><div class="plan-title-row"><h2 id="planPageTitle">Tasks</h2><button class="plan-title-edit" id="planRenameList" type="button" title="Rename list">✎</button></div><p id="planPageMeta">T-000 · New · 1 task</p></div>
      <div class="plan-modal-head-actions"><button class="btn" id="planOpenWorkflow" type="button" hidden>Open Workflow</button><button class="btn" id="planAddTask" type="button">+ Add task</button><button class="btn ghost" id="planAddExisting" type="button">Move existing</button><button class="btn" id="planEditYaml" type="button">Edit YAML</button><button class="close" id="planBackToTask" type="button">×</button></div>
    </div>
    <div class="plan-page-body">
      <main class="plan-main">
        <div class="plan-intro"><div><strong>Task order</strong><span>Tasks run from top to bottom inside this Task List.</span></div><span class="pill" id="planStatePill">Editable</span></div>
        <div class="plan-list" id="planFormList"></div>
      </main>
      <aside class="plan-side">
        <section class="plan-side-card"><h3 id="planInfoHeading">List info</h3><div class="plan-side-kv" id="planTaskSummary"></div></section>
        <section class="plan-side-card workspace-help-card"><h3>Quick use</h3><p><strong>Click</strong> selects a task · <strong>Double-click</strong> edits it.</p><p>Drag the grip to reorder. Right-click or <strong>⋯</strong> for Info / Workflow / Remove.</p></section>
      </aside>
    </div>
  </div>
  <div class="plan-subview-mount" id="planSubviewMount" hidden></div>
</div>`;

  const sourceCard=({title,subtitle='',control='',body='',classes='simple-source-card'}={})=>`
<div class="source-card ${classes}">
  <div class="source-head simple-source-head"><div><strong>${esc(title)}</strong><small>${esc(subtitle)}</small></div>${control}</div>
  <div class="source-body">${body}</div>
</div>`;

  const emptyTaskList=({large=false,id='planEmptyAddTask'}={})=>`
<button class="empty-plan-cta${large?' large':''}" id="${esc(id)}" type="button"><strong>No tasks yet</strong><span>${large?'+ Add first task':'Add the first task →'}</span></button>`;

  const addTaskFooter=()=>'<button type="button" class="plan-add-task-footer"><span class="plan-add-task-plus">＋</span><strong>Add task</strong></button>';

  function mount(id,html){
    const host=document.getElementById(id);if(!host)return;
    host.innerHTML=html;
  }

  window.TaskUiTemplates=Object.freeze({taskEditor,taskListWorkspace,sourceCard,emptyTaskList,addTaskFooter});
  mount('taskListWorkspaceRoot',taskListWorkspace());
  mount('planSubviewMount',taskEditor());
})();