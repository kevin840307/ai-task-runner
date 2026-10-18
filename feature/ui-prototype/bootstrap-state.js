// Pre-paint UI bootstrap only. No Runner / Task runtime state belongs here.
(function(){
  const root=document.documentElement;
  const INTERFACE_KEY='ai-task-runner.prototype.interfaceSettings';
  const CURRENT_PROJECT_KEY='ai-task-runner.prototype.currentProject';
  const TASK_PROJECT_FILTER_KEY='ai-task-runner.prototype.taskProjectFilters';
  const themes=new Set(['teal','blue','violet','amber','rose']);
  const appearances=new Set(['system','light','dark']);
  const languages=new Set(['zh-TW','en']);

  function readJson(key,fallback){
    try{const value=JSON.parse(localStorage.getItem(key)||'null');return value??fallback}catch(_){return fallback}
  }
  const raw=readJson(INTERFACE_KEY,{});
  const legacyAppearance=appearances.has(raw.theme)?raw.theme:null;
  const interfaceSettings={
    theme:themes.has(raw.theme)?raw.theme:'teal',
    appearance:appearances.has(raw.appearance)?raw.appearance:(legacyAppearance||'system'),
    language:languages.has(raw.language)?raw.language:'zh-TW'
  };
  const resolvedAppearance=interfaceSettings.appearance==='system'
    ?(window.matchMedia?.('(prefers-color-scheme: dark)').matches?'dark':'light')
    :interfaceSettings.appearance;
  const currentProjectKey=localStorage.getItem(CURRENT_PROJECT_KEY)||'';
  const taskProjectKeys=readJson(TASK_PROJECT_FILTER_KEY,null);

  root.classList.add('ui-booting');
  root.dataset.theme=interfaceSettings.theme;
  root.dataset.appearancePreference=interfaceSettings.appearance;
  root.dataset.appearance=resolvedAppearance;
  root.lang=interfaceSettings.language;

  const startedAt=performance.now();
  let finished=false;
  function finish(){
    if(finished)return;finished=true;
    const reveal=()=>requestAnimationFrame(()=>requestAnimationFrame(()=>{
      root.classList.add('ui-ready');
      root.classList.remove('ui-booting');
      document.getElementById('appBootstrapLoader')?.setAttribute('aria-hidden','true');
    }));
    const remaining=Math.max(0,120-(performance.now()-startedAt));
    remaining?window.setTimeout(reveal,remaining):reveal();
  }

  window.UiBootstrap=Object.freeze({
    state:Object.freeze({interfaceSettings,currentProjectKey,taskProjectKeys}),
    keys:Object.freeze({currentProject:CURRENT_PROJECT_KEY,taskProjectFilters:TASK_PROJECT_FILTER_KEY}),
    finish
  });

  // Fail open if a later prototype script throws before normal completion.
  window.setTimeout(finish,1800);
})();