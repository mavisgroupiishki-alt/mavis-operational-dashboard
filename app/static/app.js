let state=null;
const selectedPeriodType="total";
let drillRows=[];
let loadTimer=null;
let loadController=null;
let drillOffset=0;
let drillMeta=null;
let drillTotal=0;
let commentTarget=null;
let teamTargetRole="expert";
let npsTarget=null;
let crmAuditData=null;
let activeSnapshotKey="";
let salesDetailsRequest=null;
let salesDetailsRetry=null;
const BROWSER_CACHE_PREFIX="mavis-dashboard-snapshot:v3:";
const INSTALL_HINT_DISMISSED_KEY="mavis-dashboard-install-hint-dismissed:v1";
const DASHBOARD_CHAT_STATE_KEY="mavis-dashboard-chat:v1";
const OPERATION_CACHE_TTL=5*60*1000;
const operationsCache=new Map();
const operationsRequests=new Map();
let deferredInstallPrompt=null;
function browserCacheKey(month,period){
  const custom=period==="custom"?`${$("#customStart")?.value||""}:${$("#customEnd")?.value||""}`:"";
  return `${BROWSER_CACHE_PREFIX}${month}|${period}|${custom}`;
}
function saveBrowserSnapshot(snap){
  try{
    if(!snap?.ok||!snap?.month_key)return;
    localStorage.setItem(browserCacheKey(snap.month_key,snap.period||"month"),JSON.stringify({saved_at:Date.now(),snapshot:snap}));
  }catch(e){}
}
function readBrowserSnapshot(month,period){
  try{
    const raw=localStorage.getItem(browserCacheKey(month,period));
    if(!raw)return null;
    const x=JSON.parse(raw);
    const snap=x?.snapshot;
    if(!snap?.ok||snap.month_key!==month||(snap.period||"month")!==period)return null;
    return {snapshot:snap,saved_at:Number(x.saved_at||0)};
  }catch(e){return null}
}
let expandedSalesWeek=null;
let trafficTargetGroup="";
let trafficDraft={};
let keyTasksData=null;
let keyTasksRequest=null;
let taskWorkspaceView="board";
let taskWorkspaceScreen="projects";
let taskWorkspaceProjectId="";
let taskWorkspacePersonId="";
let taskWorkspaceFilters={project:"",executor:"",responsible:"",deadline:"",status:"",search:"",archive:"active"};
let taskEditingId="";
let taskBulkMode=false;
let selectedTaskIds=new Set();
let activeTaskProfileId="";
let taskProfilePrompted=false;
const TASK_PROFILE_KEY="mavis-dashboard-task-profile:v1";
let dashboardChatHistory=[];
let dashboardChatPending=false;
let dashboardChatOpen=false;
let dashboardChatFocusRequested=false;
let dashboardChatDraft="";
let backgroundRefreshTimer=null;
let lastBackgroundRefreshAt=0;
const pendingPlanWrites=new Map();
let planDialogPlans={};
let planDialogRequestId=0;
let actsExpertsData=null;
let actsExpertsLoading=false;
let reactivationData=null;
let reactivationLoading=false;
let salesWorkspaceTab="overview";
let dailySalesTab="leads";
let dailySalesData=null;
let dailySalesDate="";
let dailySalesLoading=false;

const SALES_LABELS={
  leads:["Лиды","num"],qualified:["Квал. лиды","num"],qualified_rate:["Лид → квал.","pct"],lead_to_deal_rate:["Квал. → сделка","pct"],
  lead_to_sale_rate:["Лид → продажа","pct"],qualified_to_sale_rate:["Квал. → продажа","pct"],
  deals:["Сделки","num"],lost_deals:["Слитые сделки","num"],deal_amount:["Сумма созданных сделок","money"],sales:["Продажи","num"],sales_amount:["Сумма продаж","money"],average_check:["Средний чек","money"],
  cohort_sales:["Продажи из созданных сделок","num"],tail_sales:["Продажи из хвоста","num"],
  deal_to_sale_rate:["Сделка → продажа","pct"],closing_flow_deal_to_sale_rate:["Конверсия всех закрытий недели","pct"],tail_deal_to_sale_rate:["Конверсия хвоста","pct"],total_deal_to_sale_rate:["Конверсия с хвостом","pct"],products_per_deal:["Продуктов / сделку","num"],products:["Продукты в сделках","num"],product_amount:["Сумма продуктов в сделках","money"],
  sold_products:["Продано продуктов","num"],sold_product_amount:["Сумма прод. продуктов","money"],average_product_check:["Средний чек продукта","money"],product_sale_rate:["Продукт → продажа","pct"],
  paid_amount:["Платежи (поле CRM)","money"],net_revenue:["Чистая выручка","money"]
};
const SALES_DRILL_LABELS={active_deals:"Незакрытые сделки"};
const PROD_LABELS={
  closed_count:["Закрыто продуктов","num"],closed_amount:["Сумма закрытых","money"],avg_check:["Средний чек","money"],
  new_count:["Пришло за период","num"],new_amount:["Сумма пришедших","money"],period_closed_count:["Закрыто из пришедших","num"],period_closed_amount:["Сумма закрытых из пришедших","money"],new_to_success_pct:["Конверсия периода","pct"],
  capacity_count:["Ёмкость периода, шт","num"],capacity_amount:["Ёмкость периода, BYN","money"],returns_count:["Возвраты","num"],returns_amount:["Сумма возвратов","money"],
  avg_production_days:["Срок производства","days"],avg_deviation_days:["Отклонение от нормы","days"],within_norm_pct:["В нормативе","pct"],
  nps_avg:["NPS за прошлую неделю","num"],dormant_count:["Зависшие по ожидаемой дате","num"],returned_to_production:["Вернулось в производство","num"],dormant_with_reason_pct:["Причина заполнена","pct"],
  stuck_flow_current:["Зависшие сейчас","num"],stuck_flow_returns:["Завершено возвратом","num"],stuck_flow_to_production:["Завершено в производство","num"],
  dormant_all_with_reason_count:["В воронке «Зависшие»","num"],active_stuck_with_reason_count:["Активные зависшие — все","num"],active_stuck_with_reason_expected_month_count:["Активные зависшие — ожидаемое закрытие в месяце","num"]
};

const $=s=>document.querySelector(s);
const $$=s=>[...document.querySelectorAll(s)];
const marketerAccess=()=>state?.access?.role==="marketer";
const maskedValue=n=>marketerAccess()&&(n===null||n===undefined||n==="");
const fmt=n=>maskedValue(n)?"—":new Intl.NumberFormat("ru-RU",{maximumFractionDigits:1}).format(Number(n||0));
const money=n=>maskedValue(n)?"—":new Intl.NumberFormat("ru-RU",{maximumFractionDigits:0}).format(Number(n||0))+" BYN";
const pct=n=>fmt(n)+"%";
const days=n=>fmt(n)+" дн.";
const esc=s=>String(s??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"}[c]));
const attr=s=>esc(String(s??""));
function format(v,type){return type==="money"?money(v):type==="pct"?pct(v):type==="days"?days(v):fmt(v)}

function persistDashboardChatState(){
  try{sessionStorage.setItem(DASHBOARD_CHAT_STATE_KEY,JSON.stringify({open:dashboardChatOpen,draft:dashboardChatDraft,history:dashboardChatHistory.slice(-8)}))}catch(e){}
}
function restoreDashboardChatState(){
  try{
    const saved=JSON.parse(sessionStorage.getItem(DASHBOARD_CHAT_STATE_KEY)||"{}");
    dashboardChatOpen=Boolean(saved.open);
    dashboardChatDraft=typeof saved.draft==="string"?saved.draft:"";
    dashboardChatHistory=Array.isArray(saved.history)?saved.history.slice(-8):[];
  }catch(e){}
}
restoreDashboardChatState();

function selectedManagers(){return state?.team?.managers||["Ирина Богомольцева","Роман Авсеенко"]}
function selectedExperts(){return state?.team?.experts||["Екатерина Николаева","Елизавета Горбатова","Ольга Панькова","Иоланта Кананович"]}
function availableTeamUsers(){
  const detailed=state?.available_user_options||[];
  if(detailed.length)return detailed;
  return (state?.available_users||[]).map(name=>({name,active:true}));
}
function teamUserOptions(){return availableTeamUsers().map(user=>`<option value="${attr(user.name)}">${esc(user.name)}${user.active===false?" · уволен":""}</option>`).join('')}
function managers(){const s=new Set(selectedManagers());return (state?.sales?.managers||[]).filter(x=>s.has(x.name))}
function emptyExpert(name){return {name,new_count:0,active_count:0,returns_count:0,closed_count:0,closed_amount:0,avg_production_days:0,within_norm_pct:0,products:[]}}
function experts(){
  const byName=new Map((state?.production?.experts||[]).map(expert=>[expert.name,expert]));
  return selectedExperts().map(name=>byName.get(name)||emptyExpert(name));
}
function automaticNpsScores(meta){return (meta?.tasks||[]).map(x=>Number(x.score)).filter(Number.isFinite)}
function manualNpsScores(expert){return (state?.manual_nps?.[expert]?.entries||[]).map(x=>Number(x.value)).filter(Number.isFinite)}
function npsMeta(scores,entries=[]){return {value:scores.length?Number((scores.reduce((total,value)=>total+value,0)/scores.length).toFixed(1)):null,count:scores.length,entries}}
function expertNpsMeta(e){if(marketerAccess())return {value:null,count:0,entries:[]};const automatic=state?.automatic_nps_month?.experts?.[e.name]||{};return npsMeta(automaticNpsScores(automatic),automatic.tasks||[])}
function expertNps(e){return expertNpsMeta(e).value}
function overallManualNpsMeta(){if(marketerAccess())return {value:null,count:0,entries:[]};const automatic=Object.values(state?.automatic_nps?.experts||{}).flatMap(automaticNpsScores),manual=Object.keys(state?.manual_nps||{}).flatMap(manualNpsScores);return npsMeta(automatic.concat(manual))}
function overallManualNps(){return overallManualNpsMeta().value}
function npsText(v){return v===null||v===undefined?"Не задан":fmt(v)}
function automaticNpsMonthLabel(nps=state?.automatic_nps_month){
  const start=nps?.month_start||nps?.period_start;
  if(!start)return 'предыдущий месяц';
  const date=new Date(`${start}T12:00:00`);
  return `${date.toLocaleDateString('ru-RU',{month:'long'})} ${date.getFullYear()}`;
}
function getComment(scope,metric){return state?.comments?.[`${scope}|${metric}`]?.comment||""}

function getPlan(scope,metric,contextType="overall",contextKey=""){
  return Number(state?.plans?.[`${scope}|${contextType}|${contextKey}`]?.[metric]||0);
}
function rememberPlanWrite(contextKey,values){
  pendingPlanWrites.set(contextKey,{...values});
}
function reconcilePendingPlans(plans){
  const next={...(plans||{})};
  for(const [contextKey,values] of pendingPlanWrites){
    const received=next[contextKey]||{};
    const confirmed=Object.entries(values).every(([metric,value])=>Number(received[metric]??0)===Number(value??0));
    if(confirmed){
      pendingPlanWrites.delete(contextKey);
    }else{
      next[contextKey]={...received,...values};
    }
  }
  return next;
}
function expertProductPlanKey(expert,product){return `${expert}::${product}`}
function expertProductPlan(expert,product){return getPlan("production","closed_count","expert_product",expertProductPlanKey(expert,product))}
function drillAttrs(scope,metric,extra={}){
  if(marketerAccess())return "";
  let out=`data-drill="1" data-scope="${attr(scope)}" data-metric="${attr(metric)}"`;
  Object.entries(extra).forEach(([k,v])=>{if(v!==undefined&&v!==null&&v!=="") out+=` data-${k.replaceAll("_","-")}="${attr(v)}"`;});
  return out;
}
function progress(scope,metric,fact,ct="overall",ck=""){
  const plan=getPlan(scope,metric,ct,ck); if(!plan)return {plan:0,p:0,cls:""};
  const p=fact/plan*100; return {plan,p,cls:p>=100?"good":p<60?"bad":""};
}
function card(title,value,scope,metric,type="num",extra={},note="",ct="overall",ck=""){
  const pr=progress(scope,metric,Number(value||0),ct,ck);const comment=getComment(scope,metric);
  let pace="";
  if(state?.period==="month"&&state?.pace?.share&&pr.plan&&["sales_amount","sales","closed_amount","closed_count"].includes(metric)){
    const target=pr.plan*state.pace.share,delta=Number(value||0)-target;
    pace=`<div class="kpi-meta"><span>план на сегодня ${format(target,type)}</span><span>${delta>=0?"+":""}${format(delta,type)}</span></div>`;
  }
  return `<div class="card clickable" ${drillAttrs(scope,metric,extra)}><button class="comment-btn" data-comment-scope="${attr(scope)}" data-comment-metric="${attr(metric)}" data-comment-title="${attr(title)}" title="Комментарий">${comment?'●':'+'}</button><div class="kpi-label">${esc(title)}</div><div class="kpi-value">${format(value,type)}</div><div class="kpi-meta plan-line"><span>План: ${pr.plan?format(pr.plan,type):'—'}</span><span>${pr.plan?`Выполнение: ${pct(value/pr.plan*100)}`:'Выполнение: —'}</span></div>${note?`<div class="kpi-note">${esc(note)}</div>`:''}${comment?`<div class="tile-comment">${esc(comment)}</div>`:''}${pr.plan?`<div class="progress"><span class="${pr.cls}" style="width:${Math.min(100,Math.max(0,pr.p))}%"></span></div>`:""}${pace}</div>`;
}
function manualNpsCard(value,count=0){
  const shown=value===null||value===undefined?'—':fmt(value),n=state?.automatic_nps||{};
  const period=n.week_start&&n.week_end?`${new Date(n.week_start+'T00:00:00').toLocaleDateString('ru-RU',{day:'numeric',month:'long'})}–${new Date(n.week_end+'T00:00:00').toLocaleDateString('ru-RU',{day:'numeric',month:'long'})}`:'прошлая неделя';
  const note=n.status==='unavailable'?'Источник временно недоступен':n.status==='updating'?'Загружаем задачи из Bitrix':count?`Среднее по ${fmt(count)} оценкам · ${period}`:'Оценок пока нет';
  const month=state?.automatic_nps_month||{},monthValue=month?.overall?.value,monthCount=Number(month?.overall?.count||0);
  const monthStart=month.month_start||month.period_start,monthEnd=month.month_end||month.period_end;
  const monthLabel=monthStart&&monthEnd?`${new Date(monthStart+'T00:00:00').toLocaleDateString('ru-RU',{month:'long'})} ${new Date(monthStart+'T00:00:00').getFullYear()}`:'предыдущий месяц';
  const monthNote=month.status==='unavailable'?'Источник временно недоступен':month.status==='updating'?'Загружаем задачи из Bitrix':monthCount?`${fmt(monthCount)} оценок · ${new Date(monthStart+'T00:00:00').toLocaleDateString('ru-RU',{day:'numeric',month:'long'})}–${new Date(monthEnd+'T00:00:00').toLocaleDateString('ru-RU',{day:'numeric',month:'long'})}`:'Оценок пока нет';
  return `<div class="card nps-manual-card"><div class="nps-period-values"><section><div class="kpi-label">NPS за прошлую неделю</div><div class="kpi-value">${shown}</div><div class="kpi-meta"><span>${note}</span></div></section><section class="nps-month-total"><div class="kpi-label">Общий NPS за ${esc(monthLabel)}</div><div class="kpi-value">${npsText(monthValue)}</div><div class="kpi-meta"><span>${monthNote}</span></div></section></div><div class="kpi-note">По дате создания завершённых задач</div></div>`;
}
function progressPct(scope,metric,fact,ct="overall",ck=""){const p=getPlan(scope,metric,ct,ck);return p?Math.max(0,Math.min(100,Number(fact||0)/p*100)):0}
function deptHero({kind,title,eyebrow,value,valueType='money',scope,metric,extra={},planMetric=metric,substats=[]}){
  const plan=getPlan(scope,planMetric); const pp=plan?Number(value||0)/plan*100:0;
  return `<div class="department-hero ${kind} clickable" ${drillAttrs(scope,metric,extra)}><div class="dept-hero-top"><div><div class="dept-kicker">${esc(eyebrow)}</div><h2>${esc(title)}</h2></div><div class="dept-ring" style="--ring:${Math.max(0,Math.min(100,pp))*3.6}deg"><span>${plan?Math.round(pp)+'%':'—'}</span></div></div><div class="dept-value">${format(value,valueType)}</div><div class="dept-plan"><span>План ${plan?format(plan,valueType):'—'}</span><span>${plan?`Выполнение ${pct(pp)}`:'Заполни план'}</span></div><div class="dept-substats">${substats.map(s=>`<div><span>${esc(s.label)}</span><strong>${format(s.value,s.type||'num')}</strong></div>`).join('')}</div></div>`;
}
function signalCard(kind,title,value,type,scope,metric,note="",extra={}){return `<div class="signal-card ${kind} clickable" ${drillAttrs(scope,metric,extra)}><div class="signal-top"><span>${esc(title)}</span><span class="signal-arrow">›</span></div><div class="signal-value">${format(value,type)}</div><div class="signal-note">${esc(note)}</div></div>`;}
function panel(title,body,note="",action=""){return `<div class="panel"><div class="panel-head"><div class="panel-title">${esc(title)}</div>${action||`<div class="muted">${esc(note)}</div>`}</div>${body}</div>`}
function tdLink(value,scope,metric,type,extra={}){return `<span class="cell-link" ${drillAttrs(scope,metric,extra)}>${format(value,type)}</span>`}

function usesDealAmountRevenue(){return state?.sales?.financial_source==="deal_amount"}
function salesRevenueLabel(){return usesDealAmountRevenue()?"Сумма продаж":"Чистая выручка"}
function financeIsAvailable(finance=state?.clean_revenue||{}){return ["online","stale","deal_amount"].includes(finance.status)}
function cleanRevenueCaption(){
  const finance=state?.clean_revenue||{};
  if(finance.status==="deal_amount")return "Сумма успешных сделок Bitrix (OPPORTUNITY)";
  if(finance.status==="online")return "Чистая выручка из «Графика платежей»";
  if(finance.status==="stale")return "Последняя подтверждённая чистая выручка; источник обновляется";
  if(finance.status==="not_configured")return "Источник чистой выручки ещё не подключён";
  return "Чистая выручка временно недоступна";
}
function financeAmount(key){
  const finance=state?.clean_revenue||{},value=Number(finance[key]);
  return financeIsAvailable(finance)&&Number.isFinite(value)?money(value):"—";
}
function financeValue(key){
  const finance=state?.clean_revenue||{},value=Number(finance[key]);
  return financeIsAvailable(finance)&&Number.isFinite(value)?value:null;
}
function financialIncomingValue(){
  const finance=state?.clean_revenue||{},value=Number(finance.incoming_amount);
  return financeIsAvailable(finance)&&Number.isFinite(value)?value:null;
}
function financialIncomingAmount(fallback=0){
  const value=financialIncomingValue();
  return value===null?Number(fallback||0):value;
}
function financialSalesMetrics(s){
  if(marketerAccess())return {incoming:null,averageCheck:null};
  const incoming=financialIncomingAmount(s?.sales_amount),sales=Number(s?.sales||0);
  return {incoming,averageCheck:sales?incoming/sales:0};
}
function incomingRevenueCaption(){
  const finance=state?.clean_revenue||{};
  if(finance.status==="deal_amount")return "Сумма успешных сделок Bitrix (OPPORTUNITY)";
  if(finance.status==="online")return "Чистая выручка + подрядчики из «Графика платежей»";
  if(finance.status==="stale")return "Последняя подтверждённая сумма: чистая выручка + подрядчики";
  return "Сумма CRM до восстановления финансового источника";
}
function contractorCaption(){
  const finance=state?.clean_revenue||{};
  if(finance.status==="deal_amount")return "В историческом периоде подрядчики не выделялись";
  if(finance.status==="online")return "Учтено в чистой выручке";
  if(finance.status==="stale")return "Последнее подтверждённое значение";
  return cleanRevenueCaption();
}
function salesSummaryMetric(title,value,type,plan,note="",showPlan=true,financeDrill=""){
  const hasFact=value!==null&&value!==undefined&&Number.isFinite(Number(value));
  const hasPlan=Number(plan)>0;
  const completion=hasFact&&hasPlan?`Выполнение ${pct(Number(value)/Number(plan)*100)}`:"Выполнение —";
  const drill=financeDrill?` class="clickable" data-finance-drill="${attr(financeDrill)}" role="button" tabindex="0" title="Открыть список сделок"`:"";
  return `<div${drill}><span>${esc(title)}</span><strong>${hasFact?format(value,type):"—"}</strong>${note?`<small>${esc(note)}</small>`:""}${showPlan?`<small class="rnp-summary-plan">План ${hasPlan?format(plan,type):"—"} · ${completion}</small>`:""}</div>`;
}
function salesRevenueHero(s){
  const plan=getPlan("sales","sales_amount"),financial=financialSalesMetrics(s),percent=plan?financial.incoming/plan*100:0;
  return `<div class="department-hero sales"><div class="dept-hero-top"><div><h2>Продажи</h2><div class="dept-kicker">${usesDealAmountRevenue()?"СУММА ПРОДАЖ BITRIX":"ОБЩАЯ СУММА ПОСТУПЛЕНИЙ"}</div></div><div class="dept-ring" style="--ring:${Math.max(0,Math.min(100,percent))*3.6}deg"><span>${plan?Math.round(percent)+"%":"—"}</span></div></div><div class="dept-value">${money(financial.incoming)}</div><div class="dept-plan"><span>План ${plan?money(plan):"—"}</span><span>${plan?`Выполнение ${pct(percent)}`:"Заполни план"}</span></div><div class="dept-substats"><div><span>Продажи</span><strong>${fmt(s.sales)}</strong></div><div><span>Сделки</span><strong>${fmt(s.deals)}</strong></div><div><span>Средний чек</span><strong>${money(financial.averageCheck)}</strong></div></div></div>`;
}
function renderHub(){
  const s=state.sales.overall.total.metrics,p=state.production.kpi,financial=financialSalesMetrics(s);
  $("#hub").innerHTML=`<section class="department-directory" aria-label="Разделы операционного дашборда">
    <header class="operations-hero">
      <div class="operations-hero-copy"><div class="eyebrow">MAVIS GROUP · ОПЕРАЦИОННЫЙ ЦЕНТР</div><h2>Пульс бизнеса</h2><p>Главные результаты месяца и быстрый вход в рабочие контуры команды.</p></div>
      <div class="operations-hero-stats"><div><span>${usesDealAmountRevenue()?"Сумма продаж":"Поступления"}</span><strong>${money(financial.incoming)}</strong><small>${esc(incomingRevenueCaption())}</small></div><div><span>Производство</span><strong>${money(p.closed_amount)}</strong><small>${fmt(p.closed_count)} закрыто</small></div><div><span>${salesRevenueLabel()}</span><strong>${financeAmount("value")}</strong><small>${esc(cleanRevenueCaption())}</small></div></div>
    </header>
    <div class="directory-heading"><div><div class="eyebrow">КОНТУРЫ УПРАВЛЕНИЯ</div><h3>Работа отделов</h3></div><p>Открывайте раздел — показатели, первичные данные и расшифровки остаются внутри одного контура.</p></div>
    <div class="department-directory-grid">
      <button type="button" class="department-entry sales-entry" data-open-view="sales"><span class="entry-kicker">01 · Коммерция</span><strong>Продажи</strong><b>${money(financial.incoming)}</b><small>Общая сумма поступлений · ${fmt(s.sales)} продаж</small><i>Открыть →</i></button>
      <button type="button" class="department-entry experts-entry" data-open-view="department-experts"><span class="entry-kicker">02 · Исполнение</span><strong>Эксперты</strong><b>${money(p.closed_amount)}</b><small>${fmt(p.closed_count)} закрыто · производство и эксперты</small><i>Открыть →</i></button>
      <button type="button" class="department-entry calls-entry" data-open-view="sales-calls"><span class="entry-kicker">03 · Контроль качества</span><strong>Звонки продаж</strong><b>Jarvis</b><small>Записи, расшифровки, оценка и рекомендации РОПу</small><i>Открыть →</i></button>
      <button type="button" class="department-entry overview-entry" data-open-view="overview"><span class="entry-kicker">04 · Руководителю</span><strong>Общий краткий свод</strong><b>${fmt(s.sales)} продаж</b><small>Продажи, производство, риски и оперативные сигналы</small><i>Открыть →</i></button>
      <button type="button" class="department-entry marketing-entry" data-open-view="marketing"><span class="entry-kicker">05 · Привлечение</span><strong>Маркетинг</strong><b>Bitrix24</b><small>Лиды, источники, конверсия и экономика кампаний</small><i>Открыть →</i></button>
      <button type="button" class="department-entry audit-entry" data-open-view="crm-audit"><span class="entry-kicker">06 · Качество данных</span><strong>Аудит CRM</strong><b>Контроль</b><small>Ежедневный свод и карточки сделок для разбора</small><i>Открыть →</i></button>
      <button type="button" class="department-entry tasks-entry" data-open-view="key-tasks"><span class="entry-kicker">07 · Фокус команды</span><strong>Задачи</strong><b>Команда</b><small>Проекты, сроки, исполнители и статусы</small><i>Открыть →</i></button>
      <button type="button" class="department-entry muted-entry" data-open-view="expert-calls"><span class="entry-kicker">08 · В разработке</span><strong>Звонки экспертов</strong><b>Скоро</b><small>Контур оставлен пустым до подключения данных</small><i>Открыть →</i></button>
    </div>
  </section>`;
}

function taskDate(iso){return iso?new Date(`${iso.slice(0,10)}T12:00:00`):null}
function taskFormatDeadline(raw){const date=taskDate(raw);return date?date.toLocaleDateString("ru-RU",{day:"numeric",month:"long",year:"numeric"}):"Без дедлайна"}
function taskProfileName(person){if(!person)return "Не назначен";return `${person.label||person.role||person.name}${person.dismissed?" · Уволен":""}`}
function activeTaskProfiles(){return (keyTasksData?.profiles||[]).filter(row=>row.active)}
function currentTaskProfile(){return activeTaskProfiles().find(row=>row.id===activeTaskProfileId)||null}
function saveTaskProfile(id){activeTaskProfileId=id||"";try{localStorage.setItem(TASK_PROFILE_KEY,activeTaskProfileId)}catch(e){}}
function taskOptions(rows,selected,label="Все") {return `<option value="">${esc(label)}</option>${rows.map(row=>`<option value="${attr(row.id)}" ${row.id===selected?"selected":""}>${esc(row.role||row.name)}${row.archived?" · архив":""}</option>`).join("")}`}
function filteredWorkspaceTasks(rows=keyTasksData?.tasks||[]){const f=taskWorkspaceFilters;const today=new Date().toISOString().slice(0,10);return rows.filter(task=>{
  if((f.archive||"active")==="active"&&task.archived)return false;
  if((f.archive||"active")==="archive"&&!task.archived)return false;
  if(f.project!==""&&(task.project_id||"")!==f.project)return false;
  if(f.executor!==""&&!(task.executors||[]).some(person=>person.id===f.executor))return false;
  if(f.responsible!==""&&(task.responsible?.id||"")!==f.responsible)return false;
  if(f.status!==""&&task.status!==f.status)return false;
  if(f.search!==""&&!`${task.title||""} ${task.description||""}`.toLocaleLowerCase("ru").includes(f.search.toLocaleLowerCase("ru").trim()))return false;
  if(f.deadline==="overdue"&&!(task.is_overdue))return false;
  if(f.deadline==="today"&&task.deadline!==today)return false;
  if(f.deadline==="week"){const end=new Date();end.setDate(end.getDate()+7);if(!task.deadline||task.deadline<today||task.deadline>end.toISOString().slice(0,10))return false}
  if(f.deadline==="none"&&task.deadline)return false;
  return true;
})}
function taskHours(value){const hours=Number(value||0);return Number.isFinite(hours)?hours.toLocaleString("ru-RU",{maximumFractionDigits:2}):"0"}
function taskSlaLabel(task){if(task.sla_state==="breached")return `SLA нарушен · ${fmt(task.stage_age_days||0)} дн.`;if(task.sla_state==="near")return `SLA скоро · ${fmt(task.stage_age_days||0)} дн.`;return ""}
function taskCard(task){const people=(task.executors||[]).map(taskProfileName).join(", ")||"Не назначен",watchers=(task.watchers||[]).map(taskProfileName).join(", "),planned=Number(task.planned_hours||0),actual=Number(task.actual_hours||0),sla=taskSlaLabel(task),selected=selectedTaskIds.has(task.id);const effort=planned||actual?`<span class="task-effort-badge">${planned?`План ${taskHours(planned)} ч`:""}${planned&&actual?" · ":""}${actual?`Факт ${taskHours(actual)} ч`:""}</span>`:"";return `<article class="task-card-wrap ${taskBulkMode?"is-selecting":""}">${taskBulkMode?`<button type="button" class="task-card-select ${selected?"selected":""}" data-task-select="${attr(task.id)}" aria-pressed="${selected}" aria-label="${selected?"Снять выбор":"Выбрать"} задачи: ${attr(task.title)}">${selected?"✓":""}</button>`:""}<button type="button" draggable="true" class="task-card ${task.is_overdue?"is-overdue":""} ${task.backlog?"is-backlog":""} ${task.sla_state==="breached"?"is-sla-breached":""}" data-task-open="${attr(task.id)}" data-task-drag="${attr(task.id)}" aria-label="Открыть задачу: ${attr(task.title)}"><span class="task-card-top"><span class="task-status-dot ${attr(task.status)}"></span><span>${esc(task.project?.name||"Без проекта")}</span>${task.priority==="high"?"<b>Высокий</b>":""}</span><strong>${esc(task.title)}</strong>${task.description?`<span class="task-card-description">${esc(task.description)}</span>`:""}<span class="task-card-footer"><span>${esc(people)}</span><time datetime="${attr(task.deadline||"")}">${task.backlog?"Бэклог":esc(taskFormatDeadline(task.deadline))}</time></span>${sla?`<span class="task-sla-badge ${attr(task.sla_state)}">${esc(sla)}</span>`:""}${watchers?`<span class="task-watchers">Наблюдают: ${esc(watchers)}</span>`:""}${effort}${task.recurrence!=="none"?`<span class="task-repeat-badge">↻ ${esc(task.recurrence_label||"Повторяется")}</span>`:""}</button></article>`}
function taskBoard(tasks){const statuses=keyTasksData?.statuses||[];return `<div class="task-board-hint">Перетяните карточку в другой этап — изменение сохранится сразу.</div><div class="task-kanban task-status-board">${statuses.map(status=>{const rows=tasks.filter(task=>task.status===status.id);return `<section class="task-column status-${attr(status.id)}" data-task-drop="${attr(status.id)}"><header><span class="task-status-dot ${attr(status.id)}"></span><h3>${esc(status.name)}</h3><b>${fmt(rows.length)}</b></header><div class="task-column-list">${rows.map(taskCard).join("")||'<div class="task-column-empty">Перетащите сюда задачу</div>'}</div></section>`}).join("")}</div>`}
function taskProjectBoard(tasks){const summaries=(keyTasksData?.project_summaries||[]).filter(project=>taskWorkspaceScreen==="archive"||!project.archived);return `<div class="task-board-hint">Общий вид: каждая колонка — проект. Откройте карточку, чтобы изменить этап или детали.</div><div class="task-kanban task-project-board">${summaries.map(project=>{const rows=tasks.filter(task=>(task.project_id||"")===project.id);return `<section class="task-column ${taskProjectTone(project.id)}"><header><h3>${esc(project.name)}</h3><b>${fmt(rows.length)}</b></header><div class="task-column-list">${rows.map(taskCard).join("")||'<div class="task-column-empty">Нет задач</div>'}</div></section>`}).join("")}</div>`}
function taskSearchControl(){const bulk=["all","archive","person"].includes(taskWorkspaceScreen)?`<span class="task-inline-bulk">${taskBulkControls()}</span>`:"";return `<label class="task-search-control"><span>Поиск</span><input type="search" data-task-search="1" value="${attr(taskWorkspaceFilters.search||"")}" maxlength="180" autocomplete="off" placeholder="Название или описание задачи"></label>${bulk}`}
function taskList(tasks){return `<div class="task-table-wrap"><table class="task-table"><thead><tr>${taskBulkMode?"<th>Выбрать</th>":""}<th>Задача</th><th>Проект</th><th>Исполнители</th><th>Ответственный</th><th>Статус</th><th>Часы</th><th>Срок</th></tr></thead><tbody>${tasks.map(task=>`<tr>${taskBulkMode?`<td><button type="button" class="task-table-select ${selectedTaskIds.has(task.id)?"selected":""}" data-task-select="${attr(task.id)}" aria-pressed="${selectedTaskIds.has(task.id)}" aria-label="Выбрать задачу: ${attr(task.title)}">${selectedTaskIds.has(task.id)?"✓":""}</button></td>`:""}<td><button type="button" class="task-list-open" data-task-open="${attr(task.id)}">${esc(task.title)}</button>${task.priority==="high"?'<span class="task-priority">Высокий</span>':""}${taskSlaLabel(task)?`<small class="task-sla-list ${attr(task.sla_state)}">${esc(taskSlaLabel(task))}</small>`:""}</td><td>${esc(task.project?.name||"Без проекта")}</td><td>${esc((task.executors||[]).map(taskProfileName).join(", ")||"—")}</td><td>${esc(taskProfileName(task.responsible))}</td><td><span class="task-status-chip ${attr(task.status)}">${esc(task.status_label)}</span></td><td class="task-hours-cell">${Number(task.planned_hours||0)?`План ${taskHours(task.planned_hours)} ч`:"—"}${Number(task.actual_hours||0)?`<small>Факт ${taskHours(task.actual_hours)} ч</small>`:""}</td><td class="${task.is_overdue?"task-overdue":""}">${esc(taskFormatDeadline(task.deadline))}</td></tr>`).join("")||`<tr><td colspan="${taskBulkMode?8:7}" class="empty">По этим фильтрам задач нет.</td></tr>`}</tbody></table></div>`}
function taskGantt(tasks){const dated=tasks.filter(task=>task.deadline&&!task.backlog),without=tasks.filter(task=>!task.deadline&&!task.backlog),backlog=tasks.filter(task=>task.backlog);const dates=dated.map(task=>task.deadline).sort();const start=dates[0]||new Date().toISOString().slice(0,10),end=dates.at(-1)||start;const days=Math.max(1,Math.min(45,Math.round((taskDate(end)-taskDate(start))/86400000)+1));const dayLabels=Array.from({length:days},(_,index)=>{const date=taskDate(start);date.setDate(date.getDate()+index);return `<span>${date.getDate()}</span>`}).join("");return `<div class="task-gantt"><div class="task-gantt-grid" style="--task-days:${days}"><div class="task-gantt-head"><span>Задача</span><div>${dayLabels}</div></div>${dated.map(task=>{const offset=Math.max(0,Math.round((taskDate(task.deadline)-taskDate(start))/86400000));return `<div class="task-gantt-row" data-task-open="${attr(task.id)}"><strong>${esc(task.title)}</strong><div class="task-gantt-line"><i class="${attr(task.status)}" style="--task-offset:${offset}">${esc(taskFormatDeadline(task.deadline))}</i></div></div>`}).join("")}</div>${without.length?`<section class="task-no-deadline"><h3>Без срока</h3><div>${without.map(taskCard).join("")}</div></section>`:""}${backlog.length?`<section class="task-backlog-panel"><h3>Бэклог</h3><p>Идеи и несрочные задачи не попадают на временную шкалу.</p><div>${backlog.map(taskCard).join("")}</div></section>`:""}</div>`}
function taskSavedViews(){return (keyTasksData?.saved_views||[]).filter(view=>view.profile_id===activeTaskProfileId)}
function taskBulkControls(){return `<button class="btn ghost" type="button" data-task-bulk-mode="1">${taskBulkMode?"Отменить выбор":"Выбрать задачи"}</button>${taskBulkMode&&selectedTaskIds.size?`<button class="btn primary" type="button" data-task-bulk-open="1">Изменить ${fmt(selectedTaskIds.size)}</button>`:""}`}
function taskWorkspaceControls(tasks,project){const profiles=activeTaskProfiles(),statuses=keyTasksData?.statuses||[];const profile=currentTaskProfile(),overdue=(tasks||[]).filter(task=>task.is_overdue),saved=taskSavedViews();const reminder=overdue.length?`<button type="button" class="task-overdue-reminder" data-task-overdue-filter="1"><span>Просроченные задачи проекта</span><strong>${fmt(overdue.length)}</strong><small>Показать список →</small></button>`:"";const savedBar=`<div class="task-saved-views" aria-label="Быстрые представления"><span>Быстрый вид</span><button type="button" data-task-view-preset="mine">Мои</button><button type="button" data-task-view-preset="overdue">Просроченные</button><button type="button" data-task-view-preset="week">На этой неделе</button>${saved.map(view=>`<span class="task-saved-view-chip"><button type="button" data-task-view-apply="${attr(view.id)}">${esc(view.name)}</button><button type="button" aria-label="Удалить представление ${attr(view.name)}" data-task-view-delete="${attr(view.id)}">×</button></span>`).join("")}<button type="button" class="task-save-view" data-task-view-save="1">+ Сохранить вид</button></div>`;return `<header class="task-workspace-head task-project-banner"><div><button class="task-back-link task-back-button" type="button" data-task-project-back="1">← К проектам и сводке</button><div class="eyebrow">ПРОЕКТ КОМАНДЫ</div><h2>${esc(project?.name||"Без проекта")}</h2><p>Задачи проекта: сроки, исполнители, этапы и история изменений.</p></div><div class="task-workspace-actions"><button class="btn ghost" data-task-profile-open="1">${profile?`Роль: ${esc(taskProfileName(profile))}`:"Выбрать роль"}</button><button class="btn ghost" data-task-stages-open="1">Этапы</button><button class="btn ghost" data-task-templates-open="1">Шаблоны</button>${taskBulkControls()}<button class="btn meeting-action" data-task-meeting-open="1">Итог встречи</button><button class="btn primary" data-key-task-add="1">+ Задача</button></div></header>${reminder}${savedBar}<div class="task-filterbar">${taskSearchControl()}<select data-task-filter="executor">${taskOptions(profiles,taskWorkspaceFilters.executor,"Все исполнители")}</select><select data-task-filter="responsible">${taskOptions(profiles,taskWorkspaceFilters.responsible,"Все ответственные")}</select><select data-task-filter="deadline"><option value="">Все сроки</option><option value="overdue" ${taskWorkspaceFilters.deadline==="overdue"?"selected":""}>Просроченные</option><option value="today" ${taskWorkspaceFilters.deadline==="today"?"selected":""}>Сегодня</option><option value="week" ${taskWorkspaceFilters.deadline==="week"?"selected":""}>Ближайшие 7 дней</option><option value="none" ${taskWorkspaceFilters.deadline==="none"?"selected":""}>Без срока</option></select><select data-task-filter="status"><option value="">Все этапы</option>${statuses.map(row=>`<option value="${attr(row.id)}" ${taskWorkspaceFilters.status===row.id?"selected":""}>${esc(row.name)}</option>`).join("")}</select><button class="task-filter-reset" type="button" data-task-filter-reset="1">Сбросить</button></div><div class="task-view-tabs" role="tablist"><button class="${taskWorkspaceView==="board"?"active":""}" data-task-view="board" role="tab">Канбан <b>${fmt(tasks.length)}</b></button><button class="${taskWorkspaceView==="list"?"active":""}" data-task-view="list">Список</button><button class="${taskWorkspaceView==="gantt"?"active":""}" data-task-view="gantt">Гант</button></div>`}
function dashboardChatMarkup(){
  if(marketerAccess())return "";
  const entries=dashboardChatHistory.map(item=>`<div class="dashboard-chat-message ${item.role==='user'?'user':'assistant'}"><span>${item.role==='user'?'Вы':'Mavis AI'}</span><p>${esc(item.content||'').replaceAll('\n','<br>')}</p>${item.facts?.length?`<ul>${item.facts.map(x=>`<li>${esc(x)}</li>`).join('')}</ul>`:''}${item.recommendations?.length?`<div class="dashboard-chat-recommendations"><strong>Рекомендую</strong><ul>${item.recommendations.map(x=>`<li>${esc(x)}</li>`).join('')}</ul></div>`:''}${item.links?.length?`<div class="dashboard-chat-links">${item.links.map(link=>`<a href="${attr(link.url)}" target="_blank" rel="noopener">${esc(link.label)} →</a>`).join('')}</div>`:''}</div>`).join('');
  const panel=dashboardChatOpen?`<aside id="dashboardChatPanel" class="bitrix-chat-panel" aria-label="Чат с Bitrix"><header class="bitrix-chat-head"><div><h2>Mavis AI-помощник</h2><p>Спросите о данных Bitrix. Чат только анализирует и ничего не меняет в CRM.</p></div><button class="bitrix-chat-close" type="button" data-dashboard-chat-close="1" aria-label="Закрыть чат">×</button></header><div class="dashboard-chat-messages" aria-live="polite">${entries||'<div class="dashboard-chat-empty">Например: «сколько сделок в зависших сейчас?» или «какие сделки можно вернуть?»</div>'}${dashboardChatPending?'<div class="dashboard-chat-message assistant pending"><span>Mavis AI</span><p>Собираю ответ…</p></div>':''}</div><div class="dashboard-chat-compose"><input id="dashboardChatQuestion" name="dashboard_chat_question" maxlength="900" autocomplete="off" aria-label="Вопрос про Bitrix" placeholder="Напишите вопрос…"><button class="bitrix-chat-send" type="button" data-dashboard-chat-send="1" ${dashboardChatPending?'disabled':''} aria-label="Отправить вопрос"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="m4 4 16 8-16 8 3-8-3-8Z"/></svg></button></div></aside>`:"";
  return `<div class="bitrix-chat-widget">${panel}<button class="bitrix-chat-trigger" type="button" data-dashboard-chat-toggle="1" aria-expanded="${dashboardChatOpen}" aria-controls="dashboardChatPanel"><span class="bitrix-chat-trigger-icon"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M20 11.2a7.5 7.5 0 0 1-8 7.5 8.8 8.8 0 0 1-3.8-.9L4 19l1.2-3.5A7.2 7.2 0 0 1 4 11.2 7.5 7.5 0 0 1 12 4a7.5 7.5 0 0 1 8 7.2Z"/><path d="M8 11h.01M12 11h.01M16 11h.01"/></svg></span><span><strong>Спросить про Bitrix</strong><small>AI-помощник</small></span></button></div>`;
}
function renderDashboardChat(){const target=$("#dashboardChatWidget");if(!target)return;target.innerHTML=dashboardChatMarkup();const input=$("#dashboardChatQuestion");if(input&&!dashboardChatPending)input.value=dashboardChatDraft;if(dashboardChatFocusRequested&&dashboardChatOpen){dashboardChatFocusRequested=false;requestAnimationFrame(()=>$("#dashboardChatQuestion")?.focus())}}
function setDashboardChatOpen(open,{focus=false}={}){dashboardChatOpen=Boolean(open);dashboardChatFocusRequested=focus;persistDashboardChatState();renderDashboardChat()}
function renderKeyTasksPlaceholder(message="Загружаю задачи…"){const target=$("#key-tasks");if(!target)return;target.innerHTML=`<div class="section-page key-tasks-loading"><div class="eyebrow">ФОКУС КОМАНДЫ</div><h2>Задачи</h2><p class="section-page-lead">${esc(message)}</p><div class="integration-state">Задачи сохраняются в дашборде отдельно от Bitrix.</div></div>`}
function taskProjectTone(id){let value=0;for(const char of String(id||"inbox"))value=(value*31+char.charCodeAt(0))>>>0;return ["sky","mint","violet","amber"][value%4]}
function taskReminderLabel(kind){return ({overdue:"Просрочено",today:"Сегодня",soon:"Ближайшие 2 дня",sla_breached:"SLA нарушен"})[kind]||"Срок"}
function taskReminderKind(task){return task.sla_state==="breached"?"sla_breached":task.reminder_kind||"soon"}
function taskReminderButton(task){const kind=taskReminderKind(task),detail=task.sla_state==="breached"?`В этапе ${esc(task.status_label)} уже ${fmt(task.stage_age_days||0)} дн.`:taskFormatDeadline(task.deadline);return `<button type="button" class="task-reminder ${attr(kind)}" data-task-reminder-open="${attr(task.id)}"><span class="task-reminder-kind">${esc(taskReminderLabel(kind))}</span><strong>${esc(task.title)}</strong><small>${esc(task.project?.name||"Без проекта")} · ${detail}</small><i>Открыть →</i></button>`}
function taskRemindersMarkup(reminders=keyTasksData?.reminders||{}){const items=reminders.items||[],slaCount=reminders.sla_breached_count||0,total=(reminders.overdue_count||0)+(reminders.today_count||0)+(reminders.soon_count||0)+slaCount;if(!total)return `<section class="task-reminders is-clear"><div><div class="eyebrow">ВНИМАНИЕ</div><h3>На ближайшие дни всё под контролем</h3><p>Нет просроченных задач, нарушений SLA и задач со сроком сегодня или в ближайшие два дня.</p></div></section>`;return `<section class="task-reminders"><header><div><div class="eyebrow">ВНИМАНИЕ</div><h3>Что требует действия</h3><p>Напоминания остаются только внутри дашборда.</p></div><div class="task-reminder-totals"><span class="overdue">${fmt(reminders.overdue_count||0)} просрочено</span><span class="sla">${fmt(slaCount)} SLA</span><span>${fmt(reminders.today_count||0)} сегодня</span><span>${fmt(reminders.soon_count||0)} скоро</span></div></header><div class="task-reminder-list">${items.map(taskReminderButton).join("")}</div></section>`}
function taskObserverRemindersMarkup(){const profile=currentTaskProfile();if(!profile)return "";const rows=(keyTasksData?.tasks||[]).filter(task=>!task.archived&&(task.watchers||[]).some(person=>person.id===profile.id)&&(task.is_overdue||task.reminder_kind||task.sla_state==="breached"));if(!rows.length)return "";return `<section class="task-reminders task-observer-reminders"><header><div><div class="eyebrow">НАБЛЮДАЮ</div><h3>Мои уведомления</h3><p>Вы наблюдатель: эти задачи не входят в вашу нагрузку.</p></div><div class="task-reminder-totals"><span>${fmt(rows.length)} требуют внимания</span></div></header><div class="task-reminder-list">${rows.slice(0,8).map(taskReminderButton).join("")}</div></section>`}
function renderTaskProjectHub(){
  const target=$("#key-tasks");if(!target)return;
  const profile=currentTaskProfile(),summaries=(keyTasksData?.project_summaries||[]).filter(project=>!project.archived),workload=(keyTasksData?.workload||[]).filter(row=>row.active),week=keyTasksData?.week||{},activeCount=(keyTasksData?.tasks||[]).filter(task=>!task.archived).length,archivedCount=(keyTasksData?.tasks||[]).filter(task=>task.archived).length;
  const workloadCards=workload.map(row=>`<article class="task-workload-card"><button type="button" class="task-role-open" data-task-role-open="${attr(row.id)}" aria-label="Открыть канбан задач: ${attr(row.label||row.name)}">${esc(row.label||row.name)} <span>Открыть канбан по проектам →</span></button><strong>${fmt(row.open_count)}</strong><small>в работе</small><div class="task-workload-hours"><span>План недели <b>${taskHours(row.week_planned_hours)} ч</b></span><span>Факт недели <b>${taskHours(row.week_actual_hours)} ч</b></span></div><div class="task-role-projects">${(row.project_counts||[]).map(project=>`<button type="button" data-task-role-project="${attr(project.project_id)}" data-task-role="${attr(row.id)}">${esc(project.project_name)} · ${fmt(project.count)}</button>`).join("")||"<small>Нет активных задач</small>"}</div><footer><span>Бэклог ${fmt(row.backlog_count)}</span><span class="${row.overdue_count?"has-overdue":""}">Просрочено ${fmt(row.overdue_count)}</span></footer></article>`).join("")||'<div class="empty">Добавьте сотрудников, чтобы увидеть нагрузку.</div>';
  target.innerHTML=`<section class="key-tasks-page task-project-hub"><header class="task-workspace-head"><div><h2>Задачи</h2><p>Общий канбан, проекты, роли и сроки — всё в одном рабочем пространстве.</p></div><div class="task-workspace-actions"><button class="btn ghost" data-task-profile-open="1">${profile?`Роль: ${esc(profile.role||profile.name)}`:"Выбрать роль"}</button><button class="btn ghost" data-task-stages-open="1">Этапы</button><button class="btn ghost" data-task-templates-open="1">Шаблоны</button><button class="btn ghost" data-task-projects-open="1">Проекты</button><button class="btn primary" data-key-task-add="1">+ Задача</button></div></header>${taskRemindersMarkup()}<section class="task-project-directory"><div class="task-directory-heading"><div><h3>Работа команды</h3><p>Откройте общий канбан или конкретный проект.</p></div><button type="button" class="task-all-tasks-button" data-task-all-open="1"><span>Все задачи</span><strong>${fmt(activeCount)}</strong><small>по проектам →</small></button></div><div class="task-project-grid">${summaries.map(project=>`<button type="button" class="task-project-tile ${taskProjectTone(project.id)}" data-task-project-open="${attr(project.id)}"><span>${project.id?"Проект":"Без привязки"}</span><strong>${esc(project.name)}</strong><div><b>${fmt(project.active_count)}</b><small>в работе</small></div><footer><span>Бэклог ${fmt(project.backlog_count)}</span><span class="${project.overdue_count?"has-overdue":""}">${project.overdue_count?`Просрочено ${fmt(project.overdue_count)}`:"Без просрочек"}</span></footer><i>Открыть →</i></button>`).join("")||'<div class="tasks-empty-state"><strong>Добавьте первую задачу</strong><span>Её можно сохранить и без проекта.</span></div>'}</div></section><section class="task-workload"><div class="task-directory-heading"><div><h3>Нагрузка по ролям</h3><p>Нажмите на проект под ролью, чтобы открыть задачи этого человека.</p></div><button type="button" class="task-archive-link" data-task-archive-open="1">Архив задач · ${fmt(archivedCount)}</button></div><div class="task-workload-grid">${workloadCards}</div></section></section>`;
  const observerReminders=taskObserverRemindersMarkup();if(observerReminders)target.querySelector(".task-project-hub .task-workspace-head")?.insertAdjacentHTML("afterend",observerReminders);
  if(!currentTaskProfile()&&!taskProfilePrompted){taskProfilePrompted=true;requestAnimationFrame(openTaskProfileDialog)}
}
function renderKeyTasks(){
  if(!activeTaskProfileId){try{activeTaskProfileId=localStorage.getItem(TASK_PROFILE_KEY)||""}catch(e){}}
  if(taskWorkspaceScreen!=="project"&&taskWorkspaceScreen!=="all"&&taskWorkspaceScreen!=="archive"&&taskWorkspaceScreen!=="person"){renderTaskProjectHub();return}
  if(taskWorkspaceScreen==="all"||taskWorkspaceScreen==="archive"){const target=$("#key-tasks");if(!target)return;taskWorkspaceFilters.archive=taskWorkspaceScreen==="archive"?"archive":"active";const tasks=filteredWorkspaceTasks(keyTasksData?.tasks||[]);const title=taskWorkspaceScreen==="archive"?"Архив задач":"Все задачи";const body=taskWorkspaceView==="list"?taskList(tasks):taskWorkspaceView==="gantt"?taskGantt(tasks):taskProjectBoard(tasks);target.innerHTML=`<section class="key-tasks-page task-workspace"><header class="task-workspace-head task-project-banner"><div><button class="task-back-link task-back-button" type="button" data-task-project-back="1">← К проектам и сводке</button><h2>${title}</h2><p>${taskWorkspaceScreen==="archive"?"Архивные задачи не входят в текущую нагрузку. Откройте задачу, чтобы вернуть её в работу.":"Колонки — проекты. Задачи без привязки находятся в отдельной колонке."}</p></div><div class="task-workspace-actions"><button class="btn ghost" data-task-stages-open="1">Этапы</button><button class="btn ghost" data-task-archive-toggle="1">${taskWorkspaceScreen==="archive"?"К активным задачам":"Открыть архив"}</button><button class="btn primary" data-key-task-add="1">+ Задача</button></div></header>${taskSearchControl()}<div class="task-view-tabs" role="tablist"><button class="${taskWorkspaceView==="board"?"active":""}" data-task-view="board">Канбан <b>${fmt(tasks.length)}</b></button><button class="${taskWorkspaceView==="list"?"active":""}" data-task-view="list">Список</button><button class="${taskWorkspaceView==="gantt"?"active":""}" data-task-view="gantt">Гант</button></div>${body}</section>`;return}
  if(taskWorkspaceScreen==="person"){const target=$("#key-tasks"),person=(keyTasksData?.workload||[]).find(row=>row.id===taskWorkspacePersonId);if(!target||!person){taskWorkspaceScreen="projects";renderTaskProjectHub();return}taskWorkspaceFilters.archive="active";const tasks=filteredWorkspaceTasks(keyTasksData?.tasks||[]),title=person.label||person.name,body=taskWorkspaceView==="list"?taskList(tasks):taskWorkspaceView==="gantt"?taskGantt(tasks):taskProjectBoard(tasks);target.innerHTML=`<section class="key-tasks-page task-workspace"><header class="task-workspace-head task-project-banner"><div><button class="task-back-link task-back-button" type="button" data-task-project-back="1">← К проектам и сводке</button><div class="eyebrow">ЗАДАЧИ РОЛИ</div><h2>${esc(title)}</h2><p>Все активные задачи этой роли. Колонки канбана — проекты, задачи внутри них отфильтрованы по роли.</p></div><div class="task-workspace-actions"><button class="btn ghost" data-task-stages-open="1">Этапы</button><button class="btn primary" data-key-task-add="1">+ Задача</button></div></header>${taskSearchControl()}<div class="task-view-tabs" role="tablist"><button class="${taskWorkspaceView==="board"?"active":""}" data-task-view="board">Проекты <b>${fmt(tasks.length)}</b></button><button class="${taskWorkspaceView==="list"?"active":""}" data-task-view="list">Список</button><button class="${taskWorkspaceView==="gantt"?"active":""}" data-task-view="gantt">Гант</button></div>${body}</section>`;return}
  const target=$("#key-tasks");if(!target)return;const project=(keyTasksData?.project_summaries||[]).find(row=>row.id===taskWorkspaceProjectId);if(!project){taskWorkspaceScreen="projects";renderTaskProjectHub();return}const all=(keyTasksData?.tasks||[]).filter(task=>(task.project_id||"")===taskWorkspaceProjectId);const tasks=filteredWorkspaceTasks(all);const workspace=taskWorkspaceControls(tasks,project);const body=taskWorkspaceView==="list"?taskList(tasks):taskWorkspaceView==="gantt"?taskGantt(tasks):taskBoard(tasks);target.innerHTML=`<section class="key-tasks-page task-workspace">${workspace}${body}</section>`;if(!currentTaskProfile()&&!taskProfilePrompted){taskProfilePrompted=true;requestAnimationFrame(openTaskProfileDialog)}
}
async function loadKeyTasks(force=false){
  if(keyTasksRequest)return keyTasksRequest;if(!force&&keyTasksData){renderKeyTasks();return}if(!keyTasksData)renderKeyTasksPlaceholder();
  keyTasksRequest=(async()=>{try{const response=await fetch('/api/key-tasks',{cache:'no-store'}),payload=await response.json().catch(()=>({detail:'Сервис задач временно недоступен'}));if(!response.ok||!payload.ok)throw new Error(payload.detail||payload.error||'Не удалось загрузить задачи');keyTasksData=payload;if(activeTaskProfileId&&!activeTaskProfiles().some(row=>row.id===activeTaskProfileId))saveTaskProfile("");renderKeyTasks()}catch(error){renderKeyTasksPlaceholder(error.message||'Задачи временно недоступны')}finally{keyTasksRequest=null}})();return keyTasksRequest;
}
function openTaskProfileDialog(){const profiles=activeTaskProfiles();$("#taskProfileChoices").innerHTML=profiles.map(row=>`<span class="task-profile-choice ${row.id===activeTaskProfileId?"active":""}"><button data-task-profile-select="${attr(row.id)}">${esc(row.role||row.name)}<small>${esc(row.name)}</small></button><button class="task-profile-edit" data-task-profile-edit="${attr(row.id)}" aria-label="Изменить роль ${attr(row.name)}">Роль</button><button class="task-profile-delete" data-task-profile-delete="${attr(row.id)}" aria-label="Удалить ${attr(row.name)}">×</button></span>`).join("")||'<span class="muted">Добавьте первого сотрудника.</span>';$("#taskProfileName").value="";$("#taskProfileRole").value="";$("#taskProfileDialog").showModal()}
function openTaskProjectsDialog(){const projects=keyTasksData?.projects||[];$("#taskProjectList").innerHTML=projects.length?projects.map(row=>`<div><span>${esc(row.name)}${row.archived?" · архив":""}</span><button class="mini-edit" data-task-project-archive="${attr(row.id)}" data-task-project-archived="${row.archived?"0":"1"}">${row.archived?"Вернуть":"В архив"}</button></div>`).join(""):'<span class="muted">Проектов ещё нет.</span>';$("#taskProjectName").value="";$("#taskProjectDialog").showModal()}
function openTaskStagesDialog(){const statuses=keyTasksData?.statuses||[],profiles=activeTaskProfiles();$("#taskStageList").innerHTML=statuses.map(status=>{const targets=statuses.filter(row=>row.id!==status.id);return `<article class="task-stage-row" data-task-stage-row="${attr(status.id)}"><div class="task-stage-main"><input data-task-stage-name value="${attr(status.name)}" maxlength="120" aria-label="Название этапа"><small>${status.protected?"Системный этап: его нельзя удалить.":"Общий этап для всех проектов."}</small></div><label class="task-stage-rule">Автодействие<select data-task-stage-assignee><option value="">Не менять ответственного</option>${profiles.map(profile=>`<option value="${attr(profile.id)}" ${status.auto_assign_profile_id===profile.id?"selected":""}>Назначить: ${esc(profile.role||profile.name)}</option>`).join("")}</select></label><label class="task-stage-rule">SLA, дней<input type="number" min="0" max="365" step="1" data-task-stage-sla value="${attr(status.sla_days||0)}" inputmode="numeric"><small>0 — не контролировать</small></label><div class="task-stage-actions"><button type="button" class="btn ghost" data-task-stage-save="${attr(status.id)}">Сохранить</button>${status.protected?"":`<label class="task-stage-move">Перенести в<select data-task-stage-target>${targets.map(target=>`<option value="${attr(target.id)}">${esc(target.name)}</option>`).join("")}</select></label><button type="button" class="btn danger" data-task-stage-delete="${attr(status.id)}">Удалить</button>`}</div></article>`}).join("");$("#taskStageName").value="";$("#taskStageDialog").showModal()}
function openTaskTemplatesDialog(){const templates=keyTasksData?.templates||[];$("#taskTemplateList").innerHTML=templates.length?templates.map(row=>`<div><span><strong>${esc(row.name)}</strong><small>${esc(row.title)}</small></span><button class="mini-edit danger" data-task-template-delete="${attr(row.id)}">Удалить</button></div>`).join(""):'<span class="muted">Шаблонов пока нет.</span>';$("#taskTemplateName").value="";$("#taskTemplateTitle").value="";$("#taskTemplateDescription").value="";$("#taskTemplatePriority").value="normal";$("#taskTemplateDialog").showModal()}
function taskActivityDate(raw){const date=raw?new Date(raw):null;return date&&!Number.isNaN(date.getTime())?date.toLocaleString("ru-RU",{dateStyle:"medium",timeStyle:"short"}):"сейчас"}
function renderTaskActivity(payload){const panel=$("#taskActivityPanel");if(!panel)return;const comments=payload.comments||[],events=payload.activity||[];panel.hidden=false;panel.innerHTML=`<div class="task-activity-section"><header><div><div class="eyebrow">ОБСУЖДЕНИЕ</div><h3>Комментарии</h3></div><span>${fmt(comments.length)}</span></header><div class="task-comment-compose"><textarea id="taskCommentText" rows="3" maxlength="3000" aria-label="Комментарий к задаче" placeholder="Напишите комментарий для команды"></textarea><button class="btn ghost" type="button" data-task-comment-add="${attr(taskEditingId)}">Добавить</button></div><div class="task-activity-list">${comments.map(row=>`<article class="task-comment"><header><strong>${esc(row.author_name||"Команда")}</strong><time>${esc(taskActivityDate(row.created_at))}</time></header><p>${esc(row.text).replaceAll("\n","<br>")}</p></article>`).join("")||'<div class="task-activity-empty">Комментариев пока нет.</div>'}</div></div><div class="task-activity-section"><header><div><div class="eyebrow">ХРОНОЛОГИЯ</div><h3>История изменений</h3></div><span>${fmt(events.length)}</span></header><div class="task-activity-list">${events.map(row=>`<article class="task-history-row"><i class="${attr(row.kind||"updated")}"></i><div><strong>${esc(row.text)}</strong><span>${esc(row.author_name||"Команда")} · ${esc(taskActivityDate(row.created_at))}</span></div></article>`).join("")||'<div class="task-activity-empty">История появится после сохранения задачи.</div>'}</div></div>`}
async function loadTaskActivity(taskId){const panel=$("#taskActivityPanel");if(!panel||!taskId)return;panel.hidden=false;panel.innerHTML='<div class="task-activity-loading">Загружаю обсуждение и историю…</div>';try{const response=await fetch(`/api/key-tasks/${encodeURIComponent(taskId)}/activity`,{cache:"no-store"}),payload=await response.json().catch(()=>({detail:"Не удалось загрузить историю"}));if(!response.ok||!payload.ok)throw new Error(payload.detail||"Не удалось загрузить историю");if(taskEditingId===taskId)renderTaskActivity(payload)}catch(error){if(taskEditingId===taskId)panel.innerHTML=`<div class="task-activity-empty">${esc(error.message||"История временно недоступна")}</div>`}}
function updateTaskStageDeadlineState(){const status=$("#keyTaskStatus").value,backlog=status==="backlog",done=status==="done",deadline=$("#keyTaskDeadline"),recurrence=$("#keyTaskRecurrence"),actualField=$("#keyTaskActualHoursField"),actual=$("#keyTaskActualHours");deadline.disabled=backlog;deadline.required=!backlog;recurrence.disabled=backlog;actualField.hidden=!done;actual.disabled=!done;actual.required=done;if(backlog){deadline.value="";recurrence.value="none"}}
function applyTaskTemplate(templateId){const template=(keyTasksData?.templates||[]).find(row=>row.id===templateId);if(!template)return;$("#keyTaskTitle").value=template.title||"";$("#keyTaskDescription").value=template.description||"";$("#keyTaskPriority").value=template.priority||"normal"}
function openKeyTaskDialog(taskId=""){const task=(keyTasksData?.tasks||[]).find(row=>row.id===taskId);taskEditingId=task?.id||"";const profiles=activeTaskProfiles(),projects=(keyTasksData?.projects||[]).filter(row=>!row.archived||row.id===task?.project_id),statuses=keyTasksData?.statuses||[],defaultProject=task?.project_id||(taskWorkspaceScreen==="project"?taskWorkspaceProjectId:""),defaultStatus=statuses.find(row=>!['backlog','done'].includes(row.id))?.id||"backlog",status=task?.backlog?"backlog":(task?.status||defaultStatus);$("#taskDialogTitle").textContent=task?"Редактирование задачи":"Новая задача";$("#keyTaskTemplate").innerHTML=`<option value="">Без шаблона</option>${(keyTasksData?.templates||[]).map(row=>`<option value="${attr(row.id)}">${esc(row.name)}</option>`).join("")}`;$("#keyTaskProject").innerHTML=taskOptions(projects,defaultProject,"Без проекта");$("#keyTaskStatus").innerHTML=statuses.map(row=>`<option value="${attr(row.id)}" ${row.id===status?"selected":""}>${esc(row.name)}</option>`).join("");$("#keyTaskResponsible").innerHTML=taskOptions(profiles,task?.responsible?.id||activeTaskProfileId,"Выберите");$("#keyTaskExecutors").innerHTML=profiles.map(row=>`<option value="${attr(row.id)}" ${(task?.executors||[]).some(person=>person.id===row.id)||(!task&&row.id===activeTaskProfileId)?"selected":""}>${esc(row.role||row.name)}</option>`).join("");$("#keyTaskTitle").value=task?.title||"";$("#keyTaskDeadline").value=task?.deadline||"";$("#keyTaskPriority").value=task?.priority||"normal";$("#keyTaskPlannedHours").value=Number(task?.planned_hours||0)||"";$("#keyTaskActualHours").value=Number(task?.actual_hours||0)||"";$("#keyTaskRecurrence").value=task?.recurrence||"none";$("#keyTaskDescription").value=task?.description||"";updateTaskStageDeadlineState();$("#deleteTaskFromDialog").hidden=!task;$("#archiveTaskFromDialog").hidden=!task;$("#archiveTaskFromDialog").textContent=task?.archived?"Вернуть из архива":"В архив";$("#taskActivityPanel").hidden=!task;$("#taskActivityPanel").innerHTML="";$("#keyTaskDialog").showModal();$("#keyTaskTitle").focus();if(task)loadTaskActivity(task.id)}
async function saveKeyTask(){const executor_ids=[...$("#keyTaskExecutors").selectedOptions].map(option=>option.value),status=$("#keyTaskStatus").value,backlog=status==="backlog",planned_hours=Number($("#keyTaskPlannedHours").value||0),actual_hours=Number($("#keyTaskActualHours").value||0);const payload={title:$("#keyTaskTitle").value.trim(),responsible_id:$("#keyTaskResponsible").value,executor_ids,project_id:$("#keyTaskProject").value,deadline:$("#keyTaskDeadline").value,priority:$("#keyTaskPriority").value,status,recurrence:$("#keyTaskRecurrence").value,description:$("#keyTaskDescription").value.trim(),backlog,planned_hours,actual_hours,created_by_profile_id:activeTaskProfileId,changed_by_profile_id:activeTaskProfileId};const missing=!payload.title||!payload.responsible_id||!payload.executor_ids.length||!payload.priority||!payload.description||(!backlog&&!payload.deadline);if(missing){alert(backlog?"Заполните название, ответственного, исполнителя, приоритет и описание.":"Заполните все обязательные поля, включая срок.");return}if(status==="done"&&(!Number.isFinite(actual_hours)||actual_hours<=0)){alert("При завершении укажите, сколько часов фактически заняла задача.");$("#keyTaskActualHours").focus();return}const url=taskEditingId?`/api/key-tasks/${encodeURIComponent(taskEditingId)}`:"/api/key-tasks";const response=await fetch(url,{method:taskEditingId?"PATCH":"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(payload)});if(!response.ok){alert((await response.json().catch(()=>({detail:"Не удалось сохранить задачу"}))).detail||"Не удалось сохранить задачу");return}$("#keyTaskDialog").close();keyTasksData=null;await loadKeyTasks(true)}
function ensureTaskWatcherField(){let field=$("#keyTaskWatchers");if(field)return field;$("#keyTaskRecurrence").closest("label").insertAdjacentHTML("afterend",'<label class="task-editor-wide">Наблюдатели<select id="keyTaskWatchers" multiple size="3" aria-describedby="keyTaskWatchersNote"></select><span class="field-note" id="keyTaskWatchersNote">Видят напоминания в дашборде, но не входят в нагрузку.</span></label>');return $("#keyTaskWatchers")}
function taskLinkInfo(link){const url=String(link?.url||"").trim(),custom=String(link?.label||"").trim();if(custom)return {url,label:custom};try{const parsed=new URL(url),host=parsed.hostname.toLowerCase(),path=parsed.pathname.toLowerCase();if(host.includes("bitrix")&&path.includes("/crm/deal/"))return {url,label:"Сделка Bitrix24"};if(host.includes("bitrix")&&(path.includes("/tasks/")||path.includes("/task/")))return {url,label:"Задача Bitrix24"};if(host==="docs.google.com"&&path.includes("/spreadsheets/"))return {url,label:"Google Таблица"};if(host==="docs.google.com"&&path.includes("/document/"))return {url,label:"Google Документ"};if(host==="drive.google.com")return {url,label:"Google Drive"};return {url,label:parsed.hostname.replace(/^www\./,"")}}catch(error){return {url,label:"Ссылка"}}}
function taskLinksMarkup(links,extraClass=""){const rows=(Array.isArray(links)?links:[]).map(taskLinkInfo).filter(row=>row.url);if(!rows.length)return "";return `<div class="task-link-chips ${extraClass}">${rows.map(row=>`<a href="${attr(row.url)}" target="_blank" rel="noopener noreferrer" title="Открыть: ${attr(row.label)}">↗ ${esc(row.label)}</a>`).join("")}</div>`}
function taskDealPreviewMarkup(links,extraClass=""){const deals=(Array.isArray(links)?links:[]).map(link=>link?.deal).filter(deal=>deal&&deal.id);if(!deals.length)return "";return `<div class="task-deal-previews ${extraClass}">${deals.map(deal=>`<span class="task-deal-preview"><span>Клиент: ${esc(deal.client||"—")}</span><b>${money(deal.amount||0)}</b><small>${esc(deal.stage||"Не указана")}</small></span>`).join("")}</div>`}
function renderTaskLinkInputs(links=[]){const target=$("#keyTaskLinks");if(!target)return;const rows=Array.isArray(links)&&links.length?links:[{url:"",label:""}];target.innerHTML=rows.map((link,index)=>`<div class="task-link-input-row" data-task-link-row="${index}"><input type="url" data-task-link-url value="${attr(link?.url||"")}" maxlength="2000" placeholder="https://…"><input type="text" data-task-link-label value="${attr(link?.label||"")}" maxlength="160" placeholder="Подпись (необязательно)"><button type="button" class="icon task-link-remove" data-task-link-remove="${index}" aria-label="Удалить ссылку">×</button></div>`).join("")}
function readTaskLinks(){return [...document.querySelectorAll("#keyTaskLinks [data-task-link-row]")].map(row=>({url:row.querySelector("[data-task-link-url]")?.value.trim()||"",label:row.querySelector("[data-task-link-label]")?.value.trim()||""})).filter(row=>row.url||row.label)}
function localTaskDate(){const value=new Date();value.setMinutes(value.getMinutes()-value.getTimezoneOffset());return value.toISOString().slice(0,10)}
function defaultTaskStatus(){return (keyTasksData?.statuses||[]).find(row=>!["backlog","done"].includes(row.id))?.id||"new"}
function openTaskMeetingDialog(){const profiles=activeTaskProfiles(),project=taskWorkspaceScreen==="project"?(keyTasksData?.projects||[]).find(row=>row.id===taskWorkspaceProjectId):null;$("#meetingTaskResponsible").innerHTML=taskOptions(profiles,activeTaskProfileId,"Выберите");$("#meetingTaskSubject").value="";$("#meetingTaskAgreement").value="";$("#meetingTaskDeadline").value=localTaskDate();$("#meetingTaskProjectContext").textContent=project?`Задача будет добавлена в проект «${project.name}».`:"Задача будет добавлена без проекта — проект можно назначить позже.";$("#taskMeetingDialog").showModal();$("#meetingTaskSubject").focus()}
async function saveTaskMeeting(){const subject=$("#meetingTaskSubject").value.trim(),agreement=$("#meetingTaskAgreement").value.trim(),responsible_id=$("#meetingTaskResponsible").value,deadline=$("#meetingTaskDeadline").value,project_id=taskWorkspaceScreen==="project"?taskWorkspaceProjectId:"";if(!subject||!agreement||!responsible_id||!deadline){alert("Укажите тему, договорённость, ответственного и срок.");return}const response=await fetch("/api/key-tasks",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({title:`Итог встречи: ${subject}`,description:`Договорённость: ${agreement}`,responsible_id,executor_ids:[responsible_id],watcher_ids:[],deadline,project_id,status:defaultTaskStatus(),priority:"normal",recurrence:"none",backlog:false,planned_hours:0,actual_hours:0,links:[],created_by_profile_id:activeTaskProfileId})});if(!response.ok){alert((await response.json().catch(()=>({detail:"Не удалось создать задачу"}))).detail||"Не удалось создать задачу");return}$("#taskMeetingDialog").close();keyTasksData=null;await loadKeyTasks(true)}
function taskCard(task){const people=(task.executors||[]).map(taskProfileName).join(", ")||"Не назначен",watchers=(task.watchers||[]).map(taskProfileName).join(", "),planned=Number(task.planned_hours||0),actual=Number(task.actual_hours||0),sla=taskSlaLabel(task),selected=selectedTaskIds.has(task.id),links=taskLinksMarkup(task.links,"task-card-links"),dealPreview=taskDealPreviewMarkup(task.links,"task-card-deal-preview");const effort=planned||actual?`<span class="task-effort-badge">${planned?`План ${taskHours(planned)} ч`:""}${planned&&actual?" · ":""}${actual?`Факт ${taskHours(actual)} ч`:""}</span>`:"";return `<article class="task-card-wrap ${taskBulkMode?"is-selecting":""}">${taskBulkMode?`<button type="button" class="task-card-select ${selected?"selected":""}" data-task-select="${attr(task.id)}" aria-pressed="${selected}" aria-label="${selected?"Снять выбор":"Выбрать"} задачи: ${attr(task.title)}">${selected?"✓":""}</button>`:""}<button type="button" draggable="true" class="task-card ${task.is_overdue?"is-overdue":""} ${task.backlog?"is-backlog":""} ${task.sla_state==="breached"?"is-sla-breached":""}" data-task-open="${attr(task.id)}" data-task-drag="${attr(task.id)}" aria-label="Открыть задачу: ${attr(task.title)}"><span class="task-card-top"><span class="task-status-dot ${attr(task.status)}"></span><span>${esc(task.project?.name||"Без проекта")}</span>${task.priority==="high"?"<b>Высокий</b>":""}</span><strong>${esc(task.title)}</strong>${task.description?`<span class="task-card-description">${esc(task.description)}</span>`:""}${dealPreview}<span class="task-card-footer"><span>${esc(people)}</span><time datetime="${attr(task.deadline||"")}">${task.backlog?"Бэклог":esc(taskFormatDeadline(task.deadline))}</time></span>${sla?`<span class="task-sla-badge ${attr(task.sla_state)}">${esc(sla)}</span>`:""}${watchers?`<span class="task-watchers">Наблюдают: ${esc(watchers)}</span>`:""}${effort}${task.recurrence!=="none"?`<span class="task-repeat-badge">↻ ${esc(task.recurrence_label||"Повторяется")}</span>`:""}</button>${links}</article>`}
function taskList(tasks){return `<div class="task-table-wrap"><table class="task-table"><thead><tr>${taskBulkMode?"<th>Выбрать</th>":""}<th>Задача</th><th>Проект</th><th>Исполнители</th><th>Ответственный</th><th>Статус</th><th>Часы</th><th>Срок</th></tr></thead><tbody>${tasks.map(task=>`<tr>${taskBulkMode?`<td><button type="button" class="task-table-select ${selectedTaskIds.has(task.id)?"selected":""}" data-task-select="${attr(task.id)}" aria-pressed="${selectedTaskIds.has(task.id)}" aria-label="Выбрать задачу: ${attr(task.title)}">${selectedTaskIds.has(task.id)?"✓":""}</button></td>`:""}<td><button type="button" class="task-list-open" data-task-open="${attr(task.id)}">${esc(task.title)}</button>${task.priority==="high"?'<span class="task-priority">Высокий</span>':""}${taskSlaLabel(task)?`<small class="task-sla-list ${attr(task.sla_state)}">${esc(taskSlaLabel(task))}</small>`:""}${taskDealPreviewMarkup(task.links,"task-list-deal-preview")}${taskLinksMarkup(task.links,"task-list-links")}</td><td>${esc(task.project?.name||"Без проекта")}</td><td>${esc((task.executors||[]).map(taskProfileName).join(", ")||"—")}</td><td>${esc(taskProfileName(task.responsible))}</td><td><span class="task-status-chip ${attr(task.status)}">${esc(task.status_label)}</span></td><td class="task-hours-cell">${Number(task.planned_hours||0)?`План ${taskHours(task.planned_hours)} ч`:"—"}${Number(task.actual_hours||0)?`<small>Факт ${taskHours(task.actual_hours)} ч</small>`:""}</td><td class="${task.is_overdue?"task-overdue":""}">${esc(taskFormatDeadline(task.deadline))}</td></tr>`).join("")||`<tr><td colspan="${taskBulkMode?8:7}" class="empty">По этим фильтрам задач нет.</td></tr>`}</tbody></table></div>`}
function openKeyTaskDialog(taskId=""){const task=(keyTasksData?.tasks||[]).find(row=>row.id===taskId);taskEditingId=task?.id||"";const profiles=activeTaskProfiles(),projects=(keyTasksData?.projects||[]).filter(row=>!row.archived||row.id===task?.project_id),statuses=keyTasksData?.statuses||[],defaultProject=task?.project_id||(taskWorkspaceScreen==="project"?taskWorkspaceProjectId:""),status=task?.backlog?"backlog":(task?.status||defaultTaskStatus()),watchers=ensureTaskWatcherField();$("#taskDialogTitle").textContent=task?"Редактирование задачи":"Новая задача";$("#keyTaskTemplate").innerHTML=`<option value="">Без шаблона</option>${(keyTasksData?.templates||[]).map(row=>`<option value="${attr(row.id)}">${esc(row.name)}</option>`).join("")}`;$("#keyTaskProject").innerHTML=taskOptions(projects,defaultProject,"Без проекта");$("#keyTaskStatus").innerHTML=statuses.map(row=>`<option value="${attr(row.id)}" ${row.id===status?"selected":""}>${esc(row.name)}</option>`).join("");$("#keyTaskResponsible").innerHTML=taskOptions(profiles,task?.responsible?.id||activeTaskProfileId,"Выберите");$("#keyTaskExecutors").innerHTML=profiles.map(row=>`<option value="${attr(row.id)}" ${(task?.executors||[]).some(person=>person.id===row.id)||(!task&&row.id===activeTaskProfileId)?"selected":""}>${esc(row.role||row.name)}</option>`).join("");watchers.innerHTML=profiles.map(row=>`<option value="${attr(row.id)}" ${(task?.watchers||[]).some(person=>person.id===row.id)?"selected":""}>${esc(row.role||row.name)}</option>`).join("");$("#keyTaskTitle").value=task?.title||"";$("#keyTaskDeadline").value=task?.deadline||"";$("#keyTaskPriority").value=task?.priority||"normal";$("#keyTaskPlannedHours").value=Number(task?.planned_hours||0)||"";$("#keyTaskActualHours").value=Number(task?.actual_hours||0)||"";$("#keyTaskRecurrence").value=task?.recurrence||"none";$("#keyTaskDescription").value=task?.description||"";renderTaskLinkInputs(task?.links||[]);updateTaskStageDeadlineState();$("#deleteTaskFromDialog").hidden=!task;$("#archiveTaskFromDialog").hidden=!task;$("#archiveTaskFromDialog").textContent=task?.archived?"Вернуть из архива":"В архив";$("#taskActivityPanel").hidden=!task;$("#taskActivityPanel").innerHTML="";$("#keyTaskDialog").showModal();$("#keyTaskTitle").focus();if(task)loadTaskActivity(task.id)}
async function saveKeyTask(){const executor_ids=[...$("#keyTaskExecutors").selectedOptions].map(option=>option.value),watcher_ids=[...$("#keyTaskWatchers").selectedOptions].map(option=>option.value),status=$("#keyTaskStatus").value,backlog=status==="backlog",planned_hours=Number($("#keyTaskPlannedHours").value||0),actual_hours=Number($("#keyTaskActualHours").value||0),links=readTaskLinks();const invalidLink=links.find(link=>!link.url||!/^https?:\/\//i.test(link.url));if(invalidLink){alert("Укажите полный адрес ссылки, начиная с http:// или https://.");return}const payload={title:$("#keyTaskTitle").value.trim(),responsible_id:$("#keyTaskResponsible").value,executor_ids,watcher_ids,project_id:$("#keyTaskProject").value,deadline:$("#keyTaskDeadline").value,priority:$("#keyTaskPriority").value,status,recurrence:$("#keyTaskRecurrence").value,description:$("#keyTaskDescription").value.trim(),links,backlog,planned_hours,actual_hours,created_by_profile_id:activeTaskProfileId,changed_by_profile_id:activeTaskProfileId};const missing=!payload.title||!payload.responsible_id||!payload.executor_ids.length||!payload.priority||!payload.description||(!backlog&&!payload.deadline);if(missing){alert(backlog?"Заполните название, ответственного, исполнителя, приоритет и описание.":"Заполните все обязательные поля, включая срок.");return}if(status==="done"&&(!Number.isFinite(actual_hours)||actual_hours<=0)){alert("Перед завершением укажите фактические часы.");$("#keyTaskActualHours").focus();return}const url=taskEditingId?`/api/key-tasks/${encodeURIComponent(taskEditingId)}`:"/api/key-tasks",response=await fetch(url,{method:taskEditingId?"PATCH":"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(payload)});if(!response.ok){alert((await response.json().catch(()=>({detail:"Не удалось сохранить задачу"}))).detail||"Не удалось сохранить задачу");return}$("#keyTaskDialog").close();keyTasksData=null;await loadKeyTasks(true)}
function openKeyTaskDialog(taskId=""){const task=(keyTasksData?.tasks||[]).find(row=>row.id===taskId);taskEditingId=task?.id||"";const profiles=activeTaskProfiles(),projects=(keyTasksData?.projects||[]).filter(row=>!row.archived||row.id===task?.project_id),statuses=keyTasksData?.statuses||[],defaultProject=task?.project_id||(taskWorkspaceScreen==="project"?taskWorkspaceProjectId:""),defaultStatus=statuses.find(row=>!['backlog','done'].includes(row.id))?.id||"backlog",status=task?.backlog?"backlog":(task?.status||defaultStatus),watchers=ensureTaskWatcherField();$("#taskDialogTitle").textContent=task?"Редактирование задачи":"Новая задача";$("#keyTaskTemplate").innerHTML=`<option value="">Без шаблона</option>${(keyTasksData?.templates||[]).map(row=>`<option value="${attr(row.id)}">${esc(row.name)}</option>`).join("")}`;$("#keyTaskProject").innerHTML=taskOptions(projects,defaultProject,"Без проекта");$("#keyTaskStatus").innerHTML=statuses.map(row=>`<option value="${attr(row.id)}" ${row.id===status?"selected":""}>${esc(row.name)}</option>`).join("");$("#keyTaskResponsible").innerHTML=taskOptions(profiles,task?.responsible?.id||activeTaskProfileId,"Выберите");$("#keyTaskExecutors").innerHTML=profiles.map(row=>`<option value="${attr(row.id)}" ${(task?.executors||[]).some(person=>person.id===row.id)||(!task&&row.id===activeTaskProfileId)?"selected":""}>${esc(row.role||row.name)}</option>`).join("");watchers.innerHTML=profiles.map(row=>`<option value="${attr(row.id)}" ${(task?.watchers||[]).some(person=>person.id===row.id)?"selected":""}>${esc(row.role||row.name)}</option>`).join("");$("#keyTaskTitle").value=task?.title||"";$("#keyTaskDeadline").value=task?.deadline||"";$("#keyTaskPriority").value=task?.priority||"normal";$("#keyTaskPlannedHours").value=Number(task?.planned_hours||0)||"";$("#keyTaskActualHours").value=Number(task?.actual_hours||0)||"";$("#keyTaskRecurrence").value=task?.recurrence||"none";$("#keyTaskDescription").value=task?.description||"";updateTaskStageDeadlineState();$("#deleteTaskFromDialog").hidden=!task;$("#archiveTaskFromDialog").hidden=!task;$("#archiveTaskFromDialog").textContent=task?.archived?"Вернуть из архива":"В архив";$("#taskActivityPanel").hidden=!task;$("#taskActivityPanel").innerHTML="";$("#keyTaskDialog").showModal();$("#keyTaskTitle").focus();if(task)loadTaskActivity(task.id)}
async function saveKeyTask(){const executor_ids=[...$("#keyTaskExecutors").selectedOptions].map(option=>option.value),watcher_ids=[...$("#keyTaskWatchers").selectedOptions].map(option=>option.value),status=$("#keyTaskStatus").value,backlog=status==="backlog",planned_hours=Number($("#keyTaskPlannedHours").value||0),actual_hours=Number($("#keyTaskActualHours").value||0);const payload={title:$("#keyTaskTitle").value.trim(),responsible_id:$("#keyTaskResponsible").value,executor_ids,watcher_ids,project_id:$("#keyTaskProject").value,deadline:$("#keyTaskDeadline").value,priority:$("#keyTaskPriority").value,status,recurrence:$("#keyTaskRecurrence").value,description:$("#keyTaskDescription").value.trim(),backlog,planned_hours,actual_hours,created_by_profile_id:activeTaskProfileId,changed_by_profile_id:activeTaskProfileId};const missing=!payload.title||!payload.responsible_id||!payload.executor_ids.length||!payload.priority||!payload.description||(!backlog&&!payload.deadline);if(missing){alert(backlog?"Заполните название, ответственного, исполнителя, приоритет и описание.":"Заполните все обязательные поля, включая срок.");return}if(status==="done"&&(!Number.isFinite(actual_hours)||actual_hours<=0)){alert("Перед завершением укажите фактические часы.");$("#keyTaskActualHours").focus();return}const url=taskEditingId?`/api/key-tasks/${encodeURIComponent(taskEditingId)}`:"/api/key-tasks";const response=await fetch(url,{method:taskEditingId?"PATCH":"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(payload)});if(!response.ok){alert((await response.json().catch(()=>({detail:"Не удалось сохранить задачу"}))).detail||"Не удалось сохранить задачу");return}$("#keyTaskDialog").close();keyTasksData=null;await loadKeyTasks(true)}
function openKeyTaskDialog(taskId=""){
  const task=(keyTasksData?.tasks||[]).find(row=>row.id===taskId),profiles=activeTaskProfiles(),projects=(keyTasksData?.projects||[]).filter(row=>!row.archived||row.id===task?.project_id),statuses=keyTasksData?.statuses||[];
  taskEditingId=task?.id||"";
  const defaultProject=task?.project_id||(taskWorkspaceScreen==="project"?taskWorkspaceProjectId:""),status=task?.backlog?"backlog":(task?.status||defaultTaskStatus()),watchers=ensureTaskWatcherField();
  $("#taskDialogTitle").textContent=task?"Редактирование задачи":"Новая задача";
  $("#keyTaskTemplate").innerHTML=`<option value="">Без шаблона</option>${(keyTasksData?.templates||[]).map(row=>`<option value="${attr(row.id)}">${esc(row.name)}</option>`).join("")}`;
  $("#keyTaskProject").innerHTML=taskOptions(projects,defaultProject,"Без проекта");
  $("#keyTaskStatus").innerHTML=statuses.map(row=>`<option value="${attr(row.id)}" ${row.id===status?"selected":""}>${esc(row.name)}</option>`).join("");
  $("#keyTaskResponsible").innerHTML=taskOptions(profiles,task?.responsible?.id||activeTaskProfileId,"Выберите");
  $("#keyTaskExecutors").innerHTML=profiles.map(row=>`<option value="${attr(row.id)}" ${(task?.executors||[]).some(person=>person.id===row.id)||(!task&&row.id===activeTaskProfileId)?"selected":""}>${esc(row.role||row.name)}</option>`).join("");
  watchers.innerHTML=profiles.map(row=>`<option value="${attr(row.id)}" ${(task?.watchers||[]).some(person=>person.id===row.id)?"selected":""}>${esc(row.role||row.name)}</option>`).join("");
  $("#keyTaskTitle").value=task?.title||"";$("#keyTaskDeadline").value=task?.deadline||"";$("#keyTaskPriority").value=task?.priority||"normal";$("#keyTaskPlannedHours").value=Number(task?.planned_hours||0)||"";$("#keyTaskActualHours").value=Number(task?.actual_hours||0)||"";$("#keyTaskRecurrence").value=task?.recurrence||"none";$("#keyTaskDescription").value=task?.description||"";
  renderTaskLinkInputs(task?.links||[]);updateTaskStageDeadlineState();$("#deleteTaskFromDialog").hidden=!task;$("#archiveTaskFromDialog").hidden=!task;$("#archiveTaskFromDialog").textContent=task?.archived?"Вернуть из архива":"В архив";$("#taskActivityPanel").hidden=!task;$("#taskActivityPanel").innerHTML="";$("#keyTaskDialog").showModal();$("#keyTaskTitle").focus();if(task)loadTaskActivity(task.id);
}
async function saveKeyTask(){
  const executor_ids=[...$("#keyTaskExecutors").selectedOptions].map(option=>option.value),watcher_ids=[...$("#keyTaskWatchers").selectedOptions].map(option=>option.value),status=$("#keyTaskStatus").value,backlog=status==="backlog",planned_hours=Number($("#keyTaskPlannedHours").value||0),actual_hours=Number($("#keyTaskActualHours").value||0),links=readTaskLinks();
  if(links.some(link=>!link.url||!/^https?:\/\//i.test(link.url))){alert("Укажите полный адрес ссылки, начиная с http:// или https://.");return}
  const payload={title:$("#keyTaskTitle").value.trim(),responsible_id:$("#keyTaskResponsible").value,executor_ids,watcher_ids,project_id:$("#keyTaskProject").value,deadline:$("#keyTaskDeadline").value,priority:$("#keyTaskPriority").value,status,recurrence:$("#keyTaskRecurrence").value,description:$("#keyTaskDescription").value.trim(),links,backlog,planned_hours,actual_hours,created_by_profile_id:activeTaskProfileId,changed_by_profile_id:activeTaskProfileId};
  const missing=!payload.title||!payload.responsible_id||!payload.executor_ids.length||!payload.priority||!payload.description||(!backlog&&!payload.deadline);
  if(missing){alert(backlog?"Заполните название, ответственного, исполнителя, приоритет и описание.":"Заполните все обязательные поля, включая срок.");return}
  if(status==="done"&&(!Number.isFinite(actual_hours)||actual_hours<=0)){alert("Перед завершением укажите фактические часы.");$("#keyTaskActualHours").focus();return}
  const url=taskEditingId?`/api/key-tasks/${encodeURIComponent(taskEditingId)}`:"/api/key-tasks",response=await fetch(url,{method:taskEditingId?"PATCH":"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(payload)});
  if(!response.ok){alert((await response.json().catch(()=>({detail:"Не удалось сохранить задачу"}))).detail||"Не удалось сохранить задачу");return}
  $("#keyTaskDialog").close();keyTasksData=null;await loadKeyTasks(true);
}
async function moveTaskToStage(taskId,status){const task=(keyTasksData?.tasks||[]).find(row=>row.id===taskId);if(!task||task.status===status)return;if(status==="done"&&Number(task.actual_hours||0)<=0){openKeyTaskDialog(taskId);$("#keyTaskStatus").value="done";updateTaskStageDeadlineState();$("#keyTaskActualHours").focus();alert("Перед завершением укажите фактические часы.");return}const response=await fetch(`/api/key-tasks/${encodeURIComponent(taskId)}`,{method:"PATCH",headers:{"Content-Type":"application/json"},body:JSON.stringify({status,backlog:status==="backlog",changed_by_profile_id:activeTaskProfileId})});if(!response.ok){alert((await response.json().catch(()=>({detail:"Не удалось изменить этап"}))).detail||"Не удалось изменить этап");return}keyTasksData=null;await loadKeyTasks(true)}
function openTaskBulkDialog(){const profiles=activeTaskProfiles(),statuses=(keyTasksData?.statuses||[]).filter(row=>row.id!=="done");$("#taskBulkCaption").textContent=`Изменения применятся к ${fmt(selectedTaskIds.size)} выбранным задачам. Завершение доступно только по одной задаче.`;$("#taskBulkStatus").innerHTML='<option value="">Не менять этап</option>'+statuses.map(row=>`<option value="${attr(row.id)}">${esc(row.name)}</option>`).join("");$("#taskBulkResponsible").innerHTML=taskOptions(profiles,"","Не менять ответственного");$("#taskBulkExecutor").innerHTML=taskOptions(profiles,"","Не добавлять исполнителя");$("#taskBulkDeadline").value="";$("#taskBulkDialog").showModal()}
async function saveTaskBulk(){const payload={task_ids:[...selectedTaskIds],status:$("#taskBulkStatus").value||null,deadline:$("#taskBulkDeadline").value||null,responsible_id:$("#taskBulkResponsible").value||null,add_executor_id:$("#taskBulkExecutor").value||null,changed_by_profile_id:activeTaskProfileId};const response=await fetch('/api/key-tasks/bulk',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});if(!response.ok){alert((await response.json().catch(()=>({detail:'Не удалось изменить задачи'}))).detail||'Не удалось изменить задачи');return}$("#taskBulkDialog").close();selectedTaskIds.clear();taskBulkMode=false;keyTasksData=null;await loadKeyTasks(true)}
function applyTaskView(filters){taskWorkspaceFilters={project:"",executor:"",responsible:"",deadline:"",status:"",search:"",archive:"active",...filters};renderKeyTasks()}
function saveTaskView(){if(!currentTaskProfile()){openTaskProfileDialog();return}$("#taskSavedViewName").value="";$("#taskSavedViewDialog").showModal();$("#taskSavedViewName").focus()}
async function submitTaskView(){const name=$("#taskSavedViewName").value.trim();if(!name)return;const filters=((({executor,responsible,deadline,status})=>({executor,responsible,deadline,status}))(taskWorkspaceFilters));const response=await fetch('/api/key-tasks/views',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name,profile_id:activeTaskProfileId,filters})});if(!response.ok){alert((await response.json().catch(()=>({detail:'Не удалось сохранить представление'}))).detail||'Не удалось сохранить представление');return}$("#taskSavedViewDialog").close();keyTasksData=null;await loadKeyTasks(true)}
async function addTaskComment(taskId){const input=$("#taskCommentText"),text=(input?.value||"").trim();if(!text)return;if(!currentTaskProfile()){openTaskProfileDialog();return}const button=document.querySelector("[data-task-comment-add]");if(button)button.disabled=true;try{const response=await fetch(`/api/key-tasks/${encodeURIComponent(taskId)}/comments`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({text,author_profile_id:activeTaskProfileId})}),payload=await response.json().catch(()=>({detail:"Не удалось добавить комментарий"}));if(!response.ok||!payload.ok)throw new Error(payload.detail||"Не удалось добавить комментарий");if(input)input.value="";await loadTaskActivity(taskId)}catch(error){alert(error.message||"Не удалось добавить комментарий")}finally{if(button)button.disabled=false}}
async function deleteKeyTask(taskId){if(!window.confirm("Удалить эту задачу из дашборда? Это действие нельзя отменить."))return;const response=await fetch(`/api/key-tasks/${encodeURIComponent(taskId)}`,{method:'DELETE'});if(!response.ok){alert(await response.text());return}keyTasksData=null;await loadKeyTasks(true)}
async function askDashboardChat(){const input=$("#dashboardChatQuestion"),question=(input?.value||dashboardChatDraft).trim();if(!question||dashboardChatPending)return;dashboardChatDraft="";dashboardChatHistory.push({role:'user',content:question});dashboardChatHistory=dashboardChatHistory.slice(-8);dashboardChatPending=true;dashboardChatOpen=true;persistDashboardChatState();renderDashboardChat();try{const response=await fetch('/api/dashboard-chat',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({question,month:$('#month').value,period:$('#period').value,history:dashboardChatHistory.slice(0,-1).map(({role,content})=>({role,content}))})}),payload=await response.json();if(!response.ok||!payload.ok)throw new Error(payload.error||'Не удалось получить ответ');dashboardChatHistory.push({role:'assistant',content:payload.answer||'',facts:payload.facts||[],recommendations:payload.recommendations||[],links:payload.links||[]});dashboardChatHistory=dashboardChatHistory.slice(-8)}catch(error){dashboardChatHistory.push({role:'assistant',content:error.message||'Чат временно недоступен. Попробуйте ещё раз.'})}finally{dashboardChatPending=false;persistDashboardChatState();renderDashboardChat()}}
function integrationState(status){return ({not_configured:"Интеграция ещё не настроена",invalid_configuration:"Некорректная настройка интеграции",unavailable:"Источник временно недоступен",stale:"Показаны последние полученные данные"})[status]||"Данные обновляются"}
function hasJarvisEmbed(){return Boolean($("#sales-calls .jarvis-embed iframe"))}
function renderCallsPlaceholder(){
  if(!hasJarvisEmbed())$("#sales-calls").innerHTML=`<div class="section-page"><h2>Звонки продажи</h2><p class="section-page-lead">Здесь появятся показатели Jarvis по последнему дню звонков.</p><div class="integration-state">Загрузка данных Jarvis…</div></div>`;
  $("#expert-calls").innerHTML=`<div class="section-page"><h2>Звонки эксперты</h2><p class="section-page-lead">Данные и правила оценки ещё не настроены. Раздел оставлен пустым намеренно — показатели появятся после подключения источника.</p><div class="integration-state">Нет подключённых данных</div></div>`;
}
async function loadJarvisExperience(){
  const target=$("#sales-calls");if(!target)return;
  if(hasJarvisEmbed())return;
  target.innerHTML=`<div class="loading-state"><div class="loading-spinner"></div><div><div class="loading-title">Открываю Jarvis</div><div class="muted">Загружаю полный интерфейс звонков: записи, расшифровки и рекомендации.</div></div></div>`;
  try{const response=await fetch("/api/jarvis",{cache:"no-store"});const payload=await response.json();if(!response.ok||!payload.ok){target.innerHTML=`<div class="section-page"><h2>Звонки продажи</h2><p class="section-page-lead">${esc(integrationState(payload.status))}.</p></div>`;return}target.innerHTML=`<section class="jarvis-embed"><header><div><h2>Звонки продаж</h2><p>Карточки звонков, записи, расшифровки, оценка и рекомендации — прямо внутри операционного дашборда.</p></div></header><iframe title="Джарвис — звонки продаж" src="${attr(payload.url)}" allow="autoplay" referrerpolicy="no-referrer"></iframe></section>`}catch(e){target.innerHTML=`<div class="error">Jarvis временно недоступен. Повтори загрузку через несколько секунд.</div>`}}
function callsSummaryCard(label,value,note=""){return `<div class="call-summary-card"><span>${esc(label)}</span><strong>${fmt(value)}</strong>${note?`<small>${esc(note)}</small>`:""}</div>`}
function renderSalesCalls(data){
  const summary=data.summary||{},calls=(data.calls||[]).slice(0,50),managers=(data.managers||[]).slice(0,8);
  $("#sales-calls").innerHTML=`<div class="calls-page"><div class="toolbar"><div><div class="eyebrow">JARVIS · ПРОДАЖИ</div><h2>Звонки продаж</h2><div class="muted">Последний день с данными: ${esc(data.sourceDate||"нет данных")}</div></div></div><div class="call-summary-grid">${callsSummaryCard("Звонки",summary.calls)}${callsSummaryCard("Разобрано",summary.analyzed)}${callsSummaryCard("Критичные",summary.critical)}${callsSummaryCard("Низкая оценка",summary.attention)}${callsSummaryCard("Нужна проверка",summary.review+summary.reanalysis)}</div><div class="grid-2">${panel("Команда",`<div class="scroll-x"><table><thead><tr><th>Менеджер</th><th class="num">Звонки</th><th class="num">Средняя оценка</th><th class="num">Критичные</th><th class="num">Низкая оценка</th></tr></thead><tbody>${managers.map(item=>`<tr><td>${esc(item.name)}</td><td class="num">${fmt(item.calls)}</td><td class="num">${item.average===null?"—":fmt(item.average)}</td><td class="num">${fmt(item.critical)}</td><td class="num">${fmt(item.attention)}</td></tr>`).join("")||"<tr><td colspan='5'>Нет данных</td></tr>"}</tbody></table></div>`)}${panel("Последние звонки",`<div class="scroll-x"><table><thead><tr><th>Время</th><th>Менеджер</th><th>Звонок</th><th>Стадия</th><th class="num">Оценка</th><th>Статус</th></tr></thead><tbody>${calls.map(item=>`<tr><td>${esc(item.created)}</td><td>${esc(item.manager)}</td><td>${esc(item.activityId||"—")}</td><td>${esc(item.stage||"—")}</td><td class="num">${item.score===null?"—":fmt(item.score)}</td><td>${esc(item.reason||item.status||"—")}</td></tr>`).join("")||"<tr><td colspan='6'>Нет звонков за последний день</td></tr>"}</tbody></table></div>`,"Показаны последние 50 из текущего дня")}</div></div>`;
}
const CRM_AUDIT_METRICS=[["activeDeals","Активные сделки"],["missingSource","Без источника"],["missingLastCommunication","Без последней коммуникации"],["stalledFunnelDeals","В воронке «Зависшие»"],["missingClient","Без контакта и компании"],["inactiveOwner","Неактивный владелец"],["openLeadsMissingClient","Открытые лиды без клиента"],["requiredDealFields","Обязательные поля сделок"]];
function auditDate(value){const date=value?new Date(value):null;return date&&!Number.isNaN(date.getTime())?date.toLocaleString("ru-RU",{dateStyle:"medium",timeStyle:"short"}):"нет успешного среза"}
function renderCrmAuditRows(){const target=$("#crmAuditRows");if(!target||!crmAuditData)return;const issue=$("#crmAuditIssue")?.value||"",priority=$("#crmAuditPriority")?.value||"",funnel=$("#crmAuditFunnel")?.value||"",rows=(crmAuditData.details||[]).filter(row=>(!issue||row.issue===issue)&&(!priority||row.priority===priority)&&(!funnel||row.funnel===funnel));$("#crmAuditCount").textContent=`${fmt(rows.length)} из ${fmt((crmAuditData.details||[]).length)} строк`;target.innerHTML=rows.length?rows.map(row=>`<tr><td>${esc(row.observedOn||"—")}</td><td>${esc(row.issue||"—")}</td><td><span class="audit-priority ${attr(String(row.priority||"").toLowerCase())}">${esc(row.priority||"—")}</span></td><td>${esc(row.funnel||"—")}</td><td>${esc(row.entityType||"—")}</td><td>${row.url?`<a href="${attr(row.url)}" target="_blank" rel="noopener noreferrer">${esc(row.entityId||"—")}</a>`:esc(row.entityId||"—")}</td></tr>`).join(""):'<tr><td colspan="6" class="empty">По выбранным фильтрам карточек нет</td></tr>'}
function renderCrmAudit(data){crmAuditData=data||{};const summary=crmAuditData.summary||{},funnels=crmAuditData.funnelBreakdown||[],details=crmAuditData.details||[],values=(key)=>[...new Set(details.map(item=>String(item[key]||"")).filter(Boolean))].sort((a,b)=>a.localeCompare(b,"ru")),options=(items,label)=>`<option value="">${esc(label)}</option>${items.map(item=>`<option value="${attr(item)}">${esc(item)}</option>`).join("")}`;$("#crm-audit").innerHTML=`<section class="audit-workspace"><header class="audit-head"><div><h2>Аудит CRM</h2><p>Ежедневная проверка всех воронок и открытых лидов. Одна строка — одна причина для разбора карточки.</p></div><div class="audit-freshness">Последний срез<strong>${esc(auditDate(crmAuditData.generatedAt))}</strong></div></header><div class="audit-summary-grid">${CRM_AUDIT_METRICS.map(([key,label])=>`<div class="audit-metric"><span>${esc(label)}</span><strong>${fmt(summary[key])}</strong></div>`).join("")}</div><div class="audit-split"><section class="audit-funnels"><h3>Активные сделки по воронкам</h3><div class="audit-funnel-list">${funnels.map(item=>`<div><span>${esc(item.name||"Не указана")}</span><strong>${fmt(item.activeDeals)}</strong></div>`).join("")||'<div class="empty">Нет данных по воронкам</div>'}</div></section><section class="audit-table-panel"><div class="audit-table-head"><div><h3>Карточки для проверки</h3><span id="crmAuditCount" class="muted"></span></div><div class="audit-filters"><select id="crmAuditIssue" data-audit-filter="issue">${options(values("issue"),"Все проблемы")}</select><select id="crmAuditPriority" data-audit-filter="priority">${options(values("priority"),"Все приоритеты")}</select><select id="crmAuditFunnel" data-audit-filter="funnel">${options(values("funnel"),"Все воронки")}</select></div></div><div class="scroll-x"><table><thead><tr><th>Дата среза</th><th>Проблема</th><th>Приоритет</th><th>Воронка</th><th>Тип</th><th>ID</th></tr></thead><tbody id="crmAuditRows"></tbody></table></div></section></div></section>`;renderCrmAuditRows()}
function operationsMonth(){return state?.month_key||$("#month")?.value||""}
function operationsCacheKey(resource){return `${resource}:${resource==="marketing"?operationsMonth():"current"}`}
function operationsEndpoint(resource){return resource==="sales-calls"?"/api/sales-calls":resource==="marketing"?`/api/marketing?month=${encodeURIComponent(operationsMonth())}`:"/api/crm-audit"}
function renderOperationsData(resource,data){if(resource==="sales-calls")renderSalesCalls(data);else if(resource==="marketing")renderMarketing(data);else renderCrmAudit(data)}
function renderOperationsShell(resource){
  const target=resource==="sales-calls"?$("#sales-calls"):resource==="marketing"?$("#marketing"):$("#crm-audit");
  if(!target)return;
  const title=resource==="marketing"?"Маркетинг":"Аудит CRM";
  const description=resource==="marketing"?"Лиды, источники, конверсия и экономика кампаний.":"Ежедневный контроль воронок и карточек сделок.";
  target.innerHTML=`<section class="operations-shell"><div><h2>${title}</h2><p>${description}</p></div><span class="operations-refresh" role="status">Обновляю данные в фоне</span></section>`;
}
function cachedOperations(resource){
  const cached=operationsCache.get(operationsCacheKey(resource));
  return cached&&Date.now()-cached.savedAt<OPERATION_CACHE_TTL?cached.data:null;
}
function requestOperations(resource,force=false){
  const key=operationsCacheKey(resource),cached=operationsCache.get(key);
  if(!force&&cached&&Date.now()-cached.savedAt<OPERATION_CACHE_TTL)return Promise.resolve(cached.data);
  if(operationsRequests.has(key))return operationsRequests.get(key);
  const request=fetch(operationsEndpoint(resource),{cache:"no-store"}).then(async response=>{
    const payload=await response.json();
    if(!response.ok||!payload.ok)throw new Error(payload.status||"unavailable");
    operationsCache.set(key,{data:payload.data,savedAt:Date.now()});
    return payload.data;
  }).finally(()=>operationsRequests.delete(key));
  operationsRequests.set(key,request);
  return request;
}
function warmOperationsSections(){["marketing","crm-audit"].forEach(resource=>requestOperations(resource).catch(()=>{}))}
async function loadOperationsSection(resource){
  const target=resource==="sales-calls"?$("#sales-calls"):resource==="marketing"?$("#marketing"):$("#crm-audit");
  if(!target)return;
  const key=operationsCacheKey(resource);
  const cached=cachedOperations(resource);
  if(cached)renderOperationsData(resource,cached);else renderOperationsShell(resource);
  try{const data=await requestOperations(resource);if(target.classList.contains("active")&&key===operationsCacheKey(resource))renderOperationsData(resource,data)}catch(e){if(!cached&&target.classList.contains("active")&&key===operationsCacheKey(resource)){const title=resource==="sales-calls"?"Звонки продажи":resource==="marketing"?"Маркетинг":"Аудит CRM";target.innerHTML=`<div class="section-page"><h2>${title}</h2><p class="section-page-lead">${esc(integrationState(e.message))}.</p></div>`}}
}
function marketingMetric(label,value,type="num"){return `<div class="marketing-metric"><span>${esc(label)}</span><strong>${format(value,type)}</strong></div>`}
function renderMarketing(data){
  const m=data||{},summary=m.summary||{},segments=m.segments||[],sources=m.sources||[],funnel=m.funnel||[],marketingUrl="https://mavisgroup.bitrix24.by/marketplace/app/122/",sourceRows=sources.map(row=>{const x=row.metrics||{},conversion=x.targetLeads?x.sales/x.targetLeads:0,check=x.sales?x.salesAmount/x.sales:0;return `<tr><td>${esc(row.label||"—")}</td><td>${esc(row.bucket==="existing"?"Действующие":"Новые")}</td><td class="num">${fmt(x.leads)}</td><td class="num">${fmt(x.targetLeads)}</td><td class="num">${fmt(x.sales)}</td><td class="num">${money(x.salesAmount)}</td><td class="num">${pct(conversion*100)}</td><td class="num">${money(check)}</td></tr>`}).join("");
  $("#marketing").innerHTML=`<section class="marketing-workspace"><header class="marketing-head"><div><div class="eyebrow">BITRIX24 · МАРКЕТИНГ</div><h2>Маркетинг</h2><p>Фактические данные пересчитываются по правилам вашего приложения v7: лиды и сделки выбранного месяца, продажи по успешной стадии и дате перехода.</p></div><div class="marketing-head-actions"><div class="audit-freshness">Срез<strong>${esc(auditDate(m.generatedAt))}</strong></div><a class="btn ghost" href="${attr(marketingUrl)}" target="_blank" rel="noopener noreferrer">Планы в Bitrix24</a></div></header><section class="marketing-summary">${marketingMetric("Лиды",summary.leads)}${marketingMetric("Квал. лиды",summary.targetLeads)}${marketingMetric("Продажи",summary.sales)}${marketingMetric("Выручка",summary.salesAmount,"money")}${marketingMetric("Конверсия квал. лид → продажа",(summary.conversion||0)*100,"pct")}${marketingMetric("Средний чек",summary.averageCheck,"money")}</section><div class="marketing-segments">${segments.map(segment=>{const x=segment.metrics||{};return `<article><div class="eyebrow">${esc(segment.label)}</div><div class="segment-revenue">${money(x.salesAmount)}</div><div class="segment-stats"><span>${fmt(x.leads)} лидов</span><span>${fmt(x.targetLeads)} квал.</span><span>${fmt(x.sales)} продаж</span></div></article>`}).join("")}</div><div class="marketing-data-grid"><section class="marketing-funnel"><div class="panel-head"><div class="panel-title">Текущее состояние воронки</div><div class="muted">Сделки, созданные в месяце</div></div><div class="marketing-funnel-list">${funnel.map(item=>`<div><span>${esc(item.label)}</span><strong>${fmt(item.value)}</strong></div>`).join("")}</div></section><section class="marketing-source-panel"><div class="panel-head"><div class="panel-title">Источники и результат</div><div class="muted">Только распознанные каналы</div></div><div class="scroll-x"><table><thead><tr><th>Источник</th><th>Сегмент</th><th class="num">Лиды</th><th class="num">Квал.</th><th class="num">Продажи</th><th class="num">Выручка</th><th class="num">Конверсия</th><th class="num">Средний чек</th></tr></thead><tbody>${sourceRows||'<tr><td colspan="8" class="empty">За выбранный месяц нет распознанных источников</td></tr>'}</tbody></table></div></section></div></section>`;
}
function renderMarketingPlaceholder(){const cached=cachedOperations("marketing");if(cached)renderMarketing(cached);else renderOperationsShell("marketing")}
function renderCrmAuditPlaceholder(){const cached=cachedOperations("crm-audit");if(cached)renderCrmAudit(cached);else renderOperationsShell("crm-audit")}

function renderOverview(){
  const s=state.sales.overall.total.metrics,p=state.production.kpi,npsMeta=overallManualNpsMeta(),nps=npsMeta.value,financial=financialSalesMetrics(s);
  $("#overview").innerHTML=`
  <div class="overview-layout">
    <div class="overview-primary">
      ${salesRevenueHero(s)}
      <div class="department-mini-row">
        <div class="mini-metric"><span>Общая сумма поступлений</span><strong>${money(financial.incoming)}</strong><small>${esc(incomingRevenueCaption())}</small></div>
        <div class="mini-metric"><span>Чистая выручка</span><strong>${financeAmount("value")}</strong></div>
        <div class="mini-metric"><span>Подрядчики</span><strong>${financeAmount("contractor_amount")}</strong></div>
        <div class="mini-metric clickable" ${drillAttrs('sales','sold_products',{period_type:'total'})}><span>Продано продуктов</span><strong>${fmt(s.sold_products)}</strong></div>
      </div>
    </div>
    <div class="overview-signals">
      ${signalCard('green','Производство · закрытые акты',p.closed_amount,'money','production','closed_amount',`${fmt(p.closed_count)} закрытых продуктов`)}
      ${signalCard('coral','Зависшие периода',p.dormant_count,'num','production','dormant_count',money(p.dormant_amount))}
      ${signalCard('blue','Конверсия производства',p.new_to_success_pct,'pct','production','new_to_success_pct',`${fmt(p.period_closed_count)} из ${fmt(p.new_count)} пришедших`)}
      ${`<div class="signal-card violet nps-signal"><div class="signal-top"><span>NPS за прошлую неделю</span></div><div class="signal-value">${npsText(nps)}</div><div class="signal-note">${npsMeta.count?`${fmt(npsMeta.count)} оценок · по дате создания`:'Оценок пока нет'}</div></div>`}
    </div>
  </div>
  <div class="department-split">
    <div class="department-section sales-section">
      <div class="section-accent-head"><div><div class="eyebrow">ПРОДАЖИ</div><h3>Менеджеры и выполнение</h3></div><button class="btn soft-action" data-open-team="manager">+ Менеджер</button></div>
      ${salesManagerTable(true)}
    </div>
    <div class="department-section production-section">
      <div class="section-accent-head"><div><div class="eyebrow">ПРОИЗВОДСТВО</div><h3>Эксперты и результат</h3></div><button class="btn soft-action" data-open-team="expert">+ Эксперт</button></div>
      ${expertTable(true)}
    </div>
  </div><div class="overview-tools"><button type="button" class="btn ghost" data-open-view="risks">Риски</button><button type="button" class="btn ghost" data-open-view="dynamics">Динамика</button><button type="button" class="btn ghost" data-open-view="forecast">Прогноз</button><button type="button" class="btn ghost" data-open-view="plans">Планы и настройки</button></div>`;
}

function salesPeriodSelector(){return ``}
function salesManagerTable(compact=false){
  let rows=managers().map(m=>{const x=m[selectedPeriodType].metrics;return `<tr><td>${esc(m.name)}</td><td class="num">${tdLink(x.deals,"sales","deals","num",{period_type:selectedPeriodType,manager:m.name})}</td><td class="num">${tdLink(x.sales,"sales","sales","num",{period_type:selectedPeriodType,manager:m.name})}</td><td class="num">${tdLink(x.sales_amount,"sales","sales_amount","money",{period_type:selectedPeriodType,manager:m.name})}</td>${compact?"":`<td class="num">${getPlan("sales","sales_amount","manager",m.name)?money(getPlan("sales","sales_amount","manager",m.name)):"—"}</td><td class="num">${getPlan("sales","sales_amount","manager",m.name)?pct(x.sales_amount/getPlan("sales","sales_amount","manager",m.name)*100):"—"}</td><td class="num">${tdLink(x.deal_to_sale_rate,"sales","deal_to_sale_rate","pct",{period_type:selectedPeriodType,manager:m.name})}</td><td class="num">${tdLink(x.sold_products,"sales","sold_products","num",{period_type:selectedPeriodType,manager:m.name})}</td>`}</tr>`}).join("");
  return `<div class="scroll-x"><table><thead><tr><th>Менеджер</th><th class="num">Сделки</th><th class="num">Продажи</th><th class="num">Выручка</th>${compact?"":"<th class='num'>План BYN</th><th class='num'>% плана</th><th class='num'>Конв.</th><th class='num'>Прод. продукты</th>"}</tr></thead><tbody>${rows}</tbody></table></div>`;
}
function sourceTable(exact=false){
  const rows=(exact?state.sales.exact_sources:state.sales.groups).map(r=>{const x=r[selectedPeriodType].metrics;const extra=exact?{period_type:selectedPeriodType,source:r.name}:{period_type:selectedPeriodType,group:r.name};return `<tr><td>${esc(r.name)}</td>${exact?`<td>${esc(r.group)}</td>`:""}<td class="num">${tdLink(x.leads,"sales","leads","num",extra)}</td><td class="num">${tdLink(x.qualified,"sales","qualified","num",extra)}</td><td class="num">${tdLink(x.deals,"sales","deals","num",extra)}</td><td class="num">${tdLink(x.sales,"sales","sales","num",extra)}</td><td class="num">${tdLink(x.sales_amount,"sales","sales_amount","money",extra)}</td><td class="num">${getPlan("sales","sales_amount",exact?"source":"source_group",r.name)?money(getPlan("sales","sales_amount",exact?"source":"source_group",r.name)):"—"}</td><td class="num">${getPlan("sales","sales_amount",exact?"source":"source_group",r.name)?pct(x.sales_amount/getPlan("sales","sales_amount",exact?"source":"source_group",r.name)*100):"—"}</td><td class="num">${tdLink(x.deal_to_sale_rate,"sales","deal_to_sale_rate","pct",extra)}</td><td class="num">${tdLink(x.sold_products,"sales","sold_products","num",extra)}</td></tr>`}).join("");
  return `<div class="scroll-x"><table><thead><tr><th>${exact?"Источник":"Группа"}</th>${exact?"<th>Тип продаж</th>":""}<th class="num">Лиды</th><th class="num">Квал.</th><th class="num">Сделки</th><th class="num">Продажи</th><th class="num">Выручка</th><th class="num">План</th><th class="num">% плана</th><th class="num">Конв.</th><th class="num">Продукты</th></tr></thead><tbody>${rows}</tbody></table></div>`;
}
function salesProductTable(){
  const rows=state.sales.product_categories.map(r=>{const x=r[selectedPeriodType].metrics;const extra={period_type:selectedPeriodType,product:r.name};return `<tr><td>${esc(r.name)}</td><td class="num">${tdLink(x.products,"sales","products","num",extra)}</td><td class="num">${tdLink(x.product_amount,"sales","product_amount","money",extra)}</td><td class="num">${tdLink(x.sold_products,"sales","sold_products","num",extra)}</td><td class="num">${tdLink(x.sold_product_amount,"sales","sold_product_amount","money",extra)}</td><td class="num">${tdLink(x.average_product_check,"sales","average_product_check","money",extra)}</td><td class="num">${tdLink(x.product_sale_rate,"sales","product_sale_rate","pct",extra)}</td></tr>`}).join("");
  return `<div class="scroll-x"><table><thead><tr><th>Категория</th><th class="num">В сделках</th><th class="num">Сумма</th><th class="num">Продано</th><th class="num">Сумма продаж</th><th class="num">Ср чек</th><th class="num">Конв.</th></tr></thead><tbody>${rows}</tbody></table></div>`;
}

function dailyMetricTable(daysMap, defs, startDay=1, endDay=null, extra={}){
  const first=daysMap?.[defs[0]?.[0]]||[];
  const n=first.length||31;
  const last=Math.min(endDay||n,n);
  const rows=[];
  for(let day=startDay;day<=last;day++){
    const hasActivity=defs.some(([k])=>Number(daysMap?.[k]?.[day-1]||0)!==0);
    rows.push(`<tr class="${hasActivity?'':'zero-day'}"><td>${day}</td>${defs.map(([k,label,type])=>`<td class="num">${tdLink(daysMap?.[k]?.[day-1]||0,'sales',k,type,{...extra,day})}</td>`).join('')}</tr>`);
  }
  return `<div class="scroll-x"><table class="daily-table"><thead><tr><th>День</th>${defs.map(d=>`<th class="num">${esc(d[1])}</th>`).join('')}</tr></thead><tbody>${rows.join('')}</tbody></table></div>`;
}

function compactWeekMatrix(defs){
  const w=state.sales.overall.total.weeks||{};
  return `<div class="compact-week-matrix"><div class="compact-week-head"><span>Показатель</span>${[1,2,3,4,5].map(i=>`<span>${i} нед.</span>`).join('')}</div>${defs.map(([k,label,type])=>`<div class="compact-week-row"><strong>${esc(label)}</strong>${[0,1,2,3,4].map(i=>`<span>${format(w[k]?.[i]||0,type)}</span>`).join('')}</div>`).join('')}</div>`;
}

function weekDayBreakdowns(defs){
  const days=state.sales.overall.total.days||{};
  const ranges=[[1,7],[8,14],[15,21],[22,28],[29,(days?.[defs[0]?.[0]]||[]).length||31]];
  return `<div class="week-day-details">${ranges.map(([a,b],i)=>`<details class="day-breakdown"><summary><span>${i+1} неделя · ${a}–${b}</span><span class="muted">раскрыть по дням</span></summary>${dailyMetricTable(days,defs,a,b,{period_type:'total',week:i})}</details>`).join('')}</div>`;
}

function weeklyGrid(){
  const w=state.sales.overall.total.weeks||{};
  const daysMap=state.sales.overall.total.days||{};
  const defs=[
    ["leads","Лиды","num"],["qualified","Квал. лиды","num"],["qualified_rate","% в квал.","pct"],
    ["lead_to_deal_rate","Квал. → сделка","pct"],["deals","Сделки","num"],["deal_amount","Сумма созданных сделок","money"],
    ["sales","Продажи","num"],["sales_amount","Выручка","money"],["products","Продукты","num"],
    ["product_amount","Сумма продуктов","money"],["sold_products","Продано продуктов","num"],
    ["sold_product_amount","Сумма прод. продуктов","money"]
  ];
  const dayCount=(daysMap?.leads||[]).length||31;
  const ranges=[[1,7],[8,14],[15,21],[22,28],[29,dayCount]];

  const head=`<thead><tr><th>Показатель</th>${[0,1,2,3,4].map(i=>`<th class="num week-head-cell"><button type="button" class="week-head-btn ${expandedSalesWeek===i?'active':''}" data-week-toggle="${i}">${i+1} нед. <span>${expandedSalesWeek===i?'▲':'▼'}</span></button></th>`).join('')}</tr></thead>`;
  const body=defs.map(([k,label,type])=>`<tr><td class="weekly-metric-name">${esc(label)}</td>${[0,1,2,3,4].map(i=>`<td class="num"><span class="cell-link" ${drillAttrs("sales",k,{period_type:"total",week:i})}>${format(w[k]?.[i]||0,type)}</span></td>`).join('')}</tr>`).join('');

  let detail='';
  if(expandedSalesWeek!==null){
    const [a,b]=ranges[expandedSalesWeek];
    detail=`<tr class="week-inline-detail-row"><td colspan="6"><div class="week-inline-detail"><div class="week-inline-title"><strong>${expandedSalesWeek+1} неделя · ${a}–${b}</strong><span class="muted">дни раскрыты внутри недельной таблицы</span></div>${dailyMetricTable(daysMap,defs,a,b,{period_type:'total',week:expandedSalesWeek})}</div></td></tr>`;
  }
  return `<div class="scroll-x"><table class="weekly-main-table">${head}<tbody>${body}${detail}</tbody></table></div>`;
}

function periodDailyBlock(agg, periodType, extra={}){
  const m=agg?.metrics||{},d=agg?.days||{};
  if(periodType==='previous'){
    return `<details class="period-row"><summary><span>Предыдущий период · хвост</span><span><b>${fmt(m.deals)} шт</b> · ${money(m.deal_amount)} · продано ${fmt(m.sales)} · ${money(m.sales_amount)}</span></summary><div class="period-body"><div class="opening-balance">Хвост на начало: <strong>${fmt(m.deals)} шт · ${money(m.deal_amount)}</strong></div>${dailyMetricTable(d,[['sales','Продажи','num'],['sales_amount','Выручка','money']],1,null,{...extra,period_type:'previous'})}</div></details>`;
  }
  return `<details class="period-row"><summary><span>Отчётный период</span><span>сделки <b>${fmt(m.deals)}</b> · ${money(m.deal_amount)} · продажи ${fmt(m.sales)} · ${money(m.sales_amount)}</span></summary><div class="period-body">${dailyMetricTable(d,[['leads','Лиды','num'],['qualified','Квал.','num'],['deals','Сделки','num'],['deal_amount','Сумма созданных сделок','money'],['sales','Продажи','num'],['sales_amount','Выручка','money']],1,null,{...extra,period_type:'current'})}</div></details>`;
}

function salesStructuredSection(title,subtitle,keys,weekDefs,kind){
  const x=state.sales.overall.total.metrics;
  return `<div class="sales-structured ${kind}"><div class="sales-structured-head"><div><div class="eyebrow">${esc(title)}</div><h3>${esc(subtitle)}</h3></div></div><div class="kpi-grid structured-grid">${keys.map(k=>{const [label,type]=SALES_LABELS[k];return card(label,x[k],'sales',k,type,{period_type:'total'})}).join('')}</div>${compactWeekMatrix(weekDefs)}</div>`;
}
function salesStages(){
  const rows=state.sales.stages.map(r=>`<tr><td>${esc(r.name)}</td><td class="num">${tdLink(r.count,"sales","deals","num",{period_type:"total",stage:r.name})}</td><td class="num">${tdLink(r.amount,"sales","deal_amount","money",{period_type:"total",stage:r.name})}</td></tr>`).join("");
  return `<table><thead><tr><th>Стадия</th><th class="num">Сделок</th><th class="num">Сумма</th></tr></thead><tbody>${rows}</tbody></table>`;
}

function salesActiveDealsCard(){
  const count=Number(state.sales.active_deals_count||0);
  return `<button type="button" class="sales-active-deals" ${drillAttrs("sales","active_deals",{period_type:"total"})}><span>Незакрытые сделки</span><strong>${fmt(count)}</strong><small>Активные сделки основной воронки на момент обновления · открыть список</small></button>`;
}

function salesOverdueSchedule(){
  if(usesDealAmountRevenue())return "";
  const finance=state?.clean_revenue||{};
  const available=finance.overdue_schedule_available===true;
  const rows=Array.isArray(finance.overdue_schedule_rows)?finance.overdue_schedule_rows:[];
  if(!available){
    return `<section class="sales-overdue-schedule is-pending" aria-labelledby="sales-overdue-title"><header><div><h3 id="sales-overdue-title">Просроченные оплаты по графику</h3><p>Получаю список непогашенных строк из «Графика платежей».</p></div></header></section>`;
  }
  const total=rows.reduce((sum,row)=>sum+Number(row.remaining||0),0);
  const body=rows.map(row=>`<tr><td>${esc(row.date||"—")}</td><td>${row.url?`<a href="${attr(row.url)}" target="_blank" rel="noreferrer">${esc(row.deal_title||`Сделка №${row.deal_id||""}`)}</a>`:esc(row.deal_title||`Сделка №${row.deal_id||""}`)}<small>№${esc(row.deal_id||"—")}</small></td><td>${esc(row.stage||"—")}</td><td class="num">${money(row.planned||0)}</td><td class="num">${money(row.bank_confirmed||0)}</td><td class="num">${money(row.manual_confirmed||0)}</td><td class="num sales-overdue-amount">${money(row.remaining||0)}</td></tr>`).join("");
  return `<details class="sales-overdue-schedule" aria-labelledby="sales-overdue-title"><summary><div><h3 id="sales-overdue-title">Просроченные оплаты по графику <span>${fmt(rows.length)}</span></h3><p>Непогашенные строки с датой оплаты раньше сегодняшней.</p></div><div class="sales-overdue-summary-total"><strong>${money(total)}</strong><span>Открыть список</span><i aria-hidden="true"></i></div></summary><div class="scroll-x"><table><thead><tr><th>Дата</th><th>Сделка</th><th>Стадия</th><th class="num">По графику</th><th class="num">Банк</th><th class="num">Вручную</th><th class="num">Остаток</th></tr></thead><tbody>${body||`<tr><td colspan="7" class="empty">Просроченных оплат по графику нет.</td></tr>`}</tbody></table></div></details>`;
}

function managerCleanRevenue(manager){
  return rnpCleanRevenue({manager}).total;
}

function unclassifiedCleanRevenueRows(){
  const finance=state?.clean_revenue||{};
  if(!["online","stale"].includes(finance.status)||finance.deal_revenue_available!==true||!Array.isArray(finance.deal_revenue_rows))return null;
  return finance.deal_revenue_rows
    .filter(row=>row.group==="Не распределено"||!String(row.manager||"").trim());
}

function salesOperationalManagerTable(){
  if(usesDealAmountRevenue()){
    const rows=managers().map(manager=>{const metrics=manager.total.metrics;return `<tr><td>${esc(manager.name)}</td><td class="num">${tdLink(metrics.deals,"sales","deals","num",{period_type:"total",manager:manager.name})}</td><td class="num">${tdLink(metrics.sales,"sales","sales","num",{period_type:"total",manager:manager.name})}</td><td class="num">${tdLink(metrics.sales_amount,"sales","sales_amount","money",{period_type:"total",manager:manager.name})}</td></tr>`}).join("");
    return `<div class="scroll-x"><table><thead><tr><th>Менеджер</th><th class="num">Сделки</th><th class="num">Продажи</th><th class="num">Сумма продаж Bitrix</th></tr></thead><tbody>${rows||"<tr><td colspan='4'>Нет выбранных менеджеров</td></tr>"}</tbody></table></div>`;
  }
  const team=managers();
  const rows=team.map(manager=>{
    const metrics=manager.total.metrics;
    const cleanRevenue=managerCleanRevenue(manager.name);
    return `<tr><td>${esc(manager.name)}</td><td class="num">${tdLink(metrics.deals,"sales","deals","num",{period_type:"total",manager:manager.name})}</td><td class="num">${tdLink(metrics.sales,"sales","sales","num",{period_type:"total",manager:manager.name})}</td><td class="num">${tdLink(metrics.sales_amount,"sales","sales_amount","money",{period_type:"total",manager:manager.name})}</td><td class="num">${cleanRevenue===null?"—":money(cleanRevenue)}</td></tr>`;
  }).join("");
  const unclassified=typeof unclassifiedCleanRevenueRows==="function"?unclassifiedCleanRevenueRows():null;
  const unclassifiedAmount=unclassified===null?null:unclassified.reduce((sum,row)=>sum+Number(row.clean_revenue||0),0);
  const otherRow=unclassified?.length?`<tr class="sales-manager-other"><td>Не распределено в графике</td><td class="num">—</td><td class="num">—</td><td class="num">—</td><td class="num"><button type="button" class="table-drill-link" data-finance-drill="unclassified">${money(unclassifiedAmount)}</button></td></tr>`:"";
  return `<div class="scroll-x"><table><thead><tr><th>Менеджер</th><th class="num">Сделки</th><th class="num">Продажи</th><th class="num">Сумма продаж CRM</th><th class="num">Чистая выручка*</th></tr></thead><tbody>${rows||"<tr><td colspan='5'>Нет выбранных менеджеров</td></tr>"}${otherRow}</tbody></table></div>`;
}


function sourceRowsByGroup(group){
  return (state.sales.source_blocks||[]).filter(r=>r.group===group);
}
function trafficGroupCurrentSources(group){
  return sourceRowsByGroup(group).map(x=>x.name);
}
function trafficGroupLabel(group){
  return ({
    "Холодные продажи":"Холодные продажи",
    "Входящий трафик продажи":"Входящий трафик",
    "Повторные продажи по базе":"Повторные продажи",
    "Прочее":"Прочее"
  })[group]||group;
}
function openTrafficGroupDialog(group){
  trafficTargetGroup=group;
  trafficDraft={...(state.traffic_config?.assignments||{})};
  $("#trafficGroupTitle").textContent=`Источники · ${trafficGroupLabel(group)}`;
  renderTrafficGroupEditor();
  $("#trafficGroupDialog").showModal();
}
function renderTrafficGroupEditor(){
  const all=state.traffic_config?.available_sources||state.sales.available_sources||[];
  const current=new Set(trafficGroupCurrentSources(trafficTargetGroup));
  // Explicit overrides in draft must be reflected immediately.
  Object.entries(trafficDraft).forEach(([src,g])=>{
    if(g===trafficTargetGroup)current.add(src);
    else if(g==="__ignore__" || (g && g!==trafficTargetGroup))current.delete(src);
  });
  const selected=[...current].sort((a,b)=>a.localeCompare(b,'ru'));
  const candidates=all.filter(s=>!current.has(s)).sort((a,b)=>a.localeCompare(b,'ru'));

  $("#trafficSelected").innerHTML=selected.length?selected.map(src=>`
    <div class="traffic-selected-row">
      <span>${esc(src)}</span>
      <div>
        <button type="button" class="mini-edit" data-traffic-auto="${attr(src)}">Авто</button>
        <button type="button" class="mini-edit danger-lite" data-traffic-remove="${attr(src)}">Удалить</button>
      </div>
    </div>`).join(''):`<div class="empty-inline">В этом типе пока нет источников</div>`;

  $("#trafficAddSource").innerHTML=`<option value="">Выбери источник Bitrix</option>${candidates.map(src=>`<option value="${attr(src)}">${esc(src)}</option>`).join('')}`;
}
function addTrafficSourceToGroup(){
  const src=$("#trafficAddSource").value;
  if(!src)return;
  trafficDraft[src]=trafficTargetGroup;
  renderTrafficGroupEditor();
}
function removeTrafficSourceFromGroup(src){
  // Явное удаление = источник не участвует в типовой разбивке, пока его не добавят
  // в другой тип или не вернут в "Авто".
  trafficDraft[src]="__ignore__";
  renderTrafficGroupEditor();
}
function resetTrafficSourceAuto(src){
  delete trafficDraft[src];
  renderTrafficGroupEditor();
}
async function saveTrafficGroupDialog(){
  const r=await fetch('/api/traffic-config',{
    method:'PUT',
    headers:{'Content-Type':'application/json'},
    body:JSON.stringify({assignments:trafficDraft,admin_key:$("#trafficGroupAdminKey").value||''})
  });
  if(!r.ok){alert(await r.text());return}
  $("#trafficGroupDialog").close();
  state=null;
  load();
}

function trafficDistributionTree(){
  return (state.sales.groups||[]).map(g=>{
    const t=g.total.metrics;
    const sources=sourceRowsByGroup(g.name);
    return `<details class="traffic-group" open><summary><div class="traffic-group-title"><strong>${esc(g.name)}</strong><span class="muted">${sources.length} источн.</span><button type="button" class="traffic-inline-edit" data-edit-traffic-group="${attr(g.name)}">Изменить</button></div><div class="traffic-summary"><span>${fmt(t.sales)} продаж</span><b>${money(t.sales_amount)}</b></div></summary><div class="traffic-group-body">${sources.length?sources.map(r=>`<details class="traffic-source"><summary><span>${esc(r.name)}</span><span>${fmt(r.total.metrics.sales)} продаж · ${money(r.total.metrics.sales_amount)}</span></summary><div class="traffic-source-body">${periodDailyBlock(r.current,'current',{group:g.name,source:r.name})}${periodDailyBlock(r.previous,'previous',{group:g.name,source:r.name})}</div></details>`).join(''):'<div class="empty-inline">Нет источников</div>'}</div></details>`;
  }).join('');
}

function managerSourceTree(){
  return managers().map(m=>{
    const sources=m.sources||[];
    const byGroup=new Map();
    sources.forEach(s=>{if(!byGroup.has(s.group))byGroup.set(s.group,[]);byGroup.get(s.group).push(s)});
    return `<details class="manager-breakdown" open><summary><span>${esc(m.name)}</span><span class="muted">${sources.length} источн. · ${fmt(m.total.metrics.sales)} продаж · ${money(m.total.metrics.sales_amount)}</span></summary><div class="manager-source-tree">${[...byGroup.entries()].map(([group,items])=>`<details class="traffic-group manager-traffic"><summary><strong>${esc(group)}</strong><span>${items.length} источн.</span></summary><div class="traffic-group-body">${items.map(r=>`<details class="traffic-source"><summary><span>${esc(r.name)}</span><span>${fmt(r.total.metrics.sales)} продаж · ${money(r.total.metrics.sales_amount)}</span></summary><div class="traffic-source-body">${periodDailyBlock(r.current,'current',{manager:m.name,group,source:r.name})}${periodDailyBlock(r.previous,'previous',{manager:m.name,group,source:r.name})}</div></details>`).join('')}</div></details>`).join('')}</div></details>`;
  }).join('');
}
function salesManagerBreakdowns(){
  const productMap=new Map((state.sales.product_managers||[]).map(x=>[x.name,x.categories||[]]));
  return managers().map(m=>{
    const groups=(m.groups||[]).map(g=>{const x=g[selectedPeriodType].metrics,extra={period_type:selectedPeriodType,manager:m.name,group:g.name};return `<tr><td>${esc(g.name)}</td><td class="num">${tdLink(x.leads,"sales","leads","num",extra)}</td><td class="num">${tdLink(x.deals,"sales","deals","num",extra)}</td><td class="num">${tdLink(x.sales,"sales","sales","num",extra)}</td><td class="num">${tdLink(x.sales_amount,"sales","sales_amount","money",extra)}</td><td class="num">${tdLink(x.deal_to_sale_rate,"sales","deal_to_sale_rate","pct",extra)}</td></tr>`}).join("");
    const products=(productMap.get(m.name)||[]).map(p=>{const x=p[selectedPeriodType].metrics,extra={period_type:selectedPeriodType,manager:m.name,product:p.name};return `<tr><td>${esc(p.name)}</td><td class="num">${tdLink(x.products,"sales","products","num",extra)}</td><td class="num">${tdLink(x.product_amount,"sales","product_amount","money",extra)}</td><td class="num">${tdLink(x.sold_products,"sales","sold_products","num",extra)}</td><td class="num">${tdLink(x.sold_product_amount,"sales","sold_product_amount","money",extra)}</td><td class="num">${tdLink(x.product_sale_rate,"sales","product_sale_rate","pct",extra)}</td></tr>`}).join("");
    return `<details class="manager-breakdown"><summary><span>${esc(m.name)}</span><span class="muted">типы продаж + продукты</span></summary><div class="manager-breakdown-body"><div><div class="subhead">По типам продаж</div><div class="scroll-x"><table><thead><tr><th>Тип продаж</th><th class="num">Лиды</th><th class="num">Сделки</th><th class="num">Продажи</th><th class="num">Выручка</th><th class="num">Конв.</th></tr></thead><tbody>${groups}</tbody></table></div></div><div><div class="subhead">По продуктовым категориям</div><div class="scroll-x"><table><thead><tr><th>Категория</th><th class="num">В сделках</th><th class="num">Сумма</th><th class="num">Продано</th><th class="num">Выручка</th><th class="num">Конв.</th></tr></thead><tbody>${products}</tbody></table></div></div></div></details>`;
  }).join("");
}


function salesSummaryBlock(kind,title,items){
  const x=state.sales.overall.total.metrics;
  return `<section class="sales-summary-block ${kind}"><div class="sales-summary-head"><div><div class="eyebrow">${esc(title)}</div></div></div><div class="sales-summary-items">${items.map(([key,label,type])=>{const plan=getPlan('sales',key);const fact=x[key]||0;return `<div class="sales-summary-item clickable" ${drillAttrs('sales',key,{period_type:'total'})}><span>${esc(label)}</span><strong>${format(fact,type)}</strong><small>${plan?`План ${format(plan,type)} · ${pct(fact/plan*100)}`:'План —'}</small></div>`}).join('')}</div></section>`;
}

function monthDateLabel(day){
  const mk=state?.month_key||$('#month')?.value||'';
  const parts=mk.split('-');
  const mm=parts[1]||'';
  return `${String(day).padStart(2,'0')}.${mm}`;
}

function periodDayTable(agg,periodType,extra={}){
  const d=agg?.days||{};
  const n=(d.sales||d.deals||d.leads||[]).length||31;
  const current=periodType==='current';
  const defs=current
    ? [['leads','Лиды','num'],['qualified','Квал.','num'],['deals','Сделки','num'],['deal_amount','Сумма созданных сделок','money'],['sales','Продажи','num'],['sales_amount','Выручка','money']]
    : [['sales','Продажи','num'],['sales_amount','Выручка','money']];
  const rows=[];
  for(let day=1;day<=n;day++){
    const active=defs.some(([k])=>Number(d?.[k]?.[day-1]||0)!==0);
    if(!active)continue;
    rows.push(`<tr><td class="date-cell">${monthDateLabel(day)}</td>${defs.map(([k,l,t])=>`<td class="num">${tdLink(d?.[k]?.[day-1]||0,'sales',k,t,{...extra,period_type:periodType,day})}</td>`).join('')}</tr>`);
  }
  return `<div class="inline-days"><div class="scroll-x"><table><thead><tr><th>Дата</th>${defs.map(x=>`<th class="num">${esc(x[1])}</th>`).join('')}</tr></thead><tbody>${rows.join('')||`<tr><td colspan="${defs.length+1}" class="empty-day">Нет движения по дням</td></tr>`}</tbody></table></div></div>`;
}

function sourcePeriodRows(src,manager,group){
  const c=src.current?.metrics||{},p=src.previous?.metrics||{};
  const currentExtra={manager,group,source:src.name,period_type:'current'};
  const prevExtra={manager,group,source:src.name,period_type:'previous'};
  return `<div class="source-period-table">
    <details class="source-period-row current-period-row">
      <summary><span class="period-name">Отчётный период</span><span>${fmt(c.deals)} создано · ${money(c.deal_amount)}</span><span>${fmt(c.sales)} продаж · <b>${money(c.sales_amount)}</b></span><span class="open-days">по дням ›</span></summary>
      ${periodDayTable(src.current,'current',currentExtra)}
    </details>
    <details class="source-period-row previous-period-row">
      <summary><span class="period-name">Предыдущий период</span><span>хвост ${fmt(p.deals)} шт · ${money(p.deal_amount)}</span><span>${fmt(p.sales)} продаж · <b>${money(p.sales_amount)}</b></span><span class="open-days">по дням ›</span></summary>
      ${periodDayTable(src.previous,'previous',prevExtra)}
    </details>
  </div>`;
}

function managerOperationalMatrix(){
  return managers().map(m=>{
    const mt=m.total.metrics;
    const byGroup=new Map();
    (m.sources||[]).forEach(s=>{if(!byGroup.has(s.group))byGroup.set(s.group,[]);byGroup.get(s.group).push(s)});
    const preferred=['Холодные продажи','Входящий трафик продажи','Повторные продажи по базе','Прочее'];
    const groups=preferred.filter(g=>byGroup.has(g)).concat([...byGroup.keys()].filter(g=>!preferred.includes(g)));
    return `<details class="op-manager" open><summary><div class="op-manager-name"><strong>${esc(m.name)}</strong><span>месяц</span></div><div class="op-manager-summary"><span>Сделки <b>${fmt(mt.deals)}</b></span><span>Продажи <b>${fmt(mt.sales)}</b></span><span>Выручка <b>${money(mt.sales_amount)}</b></span></div></summary><div class="op-manager-body">${groups.map(group=>{
      const items=(byGroup.get(group)||[]).sort((a,b)=>(b.total?.metrics?.sales_amount||0)-(a.total?.metrics?.sales_amount||0));
      const gm=(m.groups||[]).find(g=>g.name===group)?.total?.metrics||{};
      return `<details class="op-traffic-group"><summary><div><strong>${esc(trafficGroupLabel(group))}</strong><span class="muted">${items.length} источн.</span></div><div class="op-group-summary"><span>${fmt(gm.sales||0)} продаж</span><b>${money(gm.sales_amount||0)}</b></div></summary><div class="op-source-list">${items.map(src=>`<details class="op-source"><summary><span>${esc(src.name)}</span><span>${fmt(src.total.metrics.sales)} продаж · ${money(src.total.metrics.sales_amount)}</span></summary>${sourcePeriodRows(src,m.name,group)}</details>`).join('')}</div></details>`;
    }).join('')}</div></details>`;
  }).join('');
}

function compactTrafficStrip(){
  return `<div class="traffic-strip">${(state.sales.groups||[]).map(g=>{const x=g.total.metrics;return `<div class="traffic-strip-card"><div><strong>${esc(trafficGroupLabel(g.name))}</strong><span>${fmt(x.sales)} продаж · ${money(x.sales_amount)}</span></div><button type="button" data-edit-traffic-group="${attr(g.name)}">Изменить</button></div>`}).join('')}</div>`;
}

function departmentDailyDynamics(){
  const d=state.sales.overall.total.days||{};
  const defs=[['leads','Лиды','num'],['deals','Сделки','num'],['sales','Продажи','num'],['sales_amount','Выручка','money']];
  const n=(d.leads||[]).length||31;
  const rows=[];
  for(let day=1;day<=n;day++){
    if(!defs.some(([k])=>Number(d?.[k]?.[day-1]||0)!==0))continue;
    rows.push(`<tr><td>${monthDateLabel(day)}</td>${defs.map(([k,l,t])=>`<td class="num">${tdLink(d?.[k]?.[day-1]||0,'sales',k,t,{period_type:'total',day})}</td>`).join('')}</tr>`);
  }
  return `<details class="department-dynamics"><summary><strong>Динамика отдела по дням</strong><span class="muted">открыть только когда нужна</span></summary><div class="scroll-x"><table><thead><tr><th>Дата</th>${defs.map(x=>`<th class="num">${esc(x[1])}</th>`).join('')}</tr></thead><tbody>${rows.join('')}</tbody></table></div></details>`;
}

function compactProductBreakdown(){
  const x=state.sales.overall.total.metrics;
  return `<details class="compact-product-details"><summary><strong>Продукты · детализация</strong><span>${fmt(x.products)} в сделках · ${fmt(x.sold_products)} продано · ${money(x.sold_product_amount)}</span></summary>${salesProductTable()}<div class="product-definition-note"><strong>Сумма продуктов в сделках</strong> = сумма товарных строк Bitrix (цена × количество) в сделках, созданных в выбранном месяце.</div></details>`;
}


const RNP_GROUPS=[
  {
    key:"Холодные продажи", cls:"cold",
    title:"Холодные продажи",
    metrics:[
      ["leads","Число лидов всего","num"],
      ["qualified_rate","% из лида в квал. лид","pct"],
      ["qualified","Число квал. лидов","num"],
      ["lead_to_deal_rate","% из квал. лида в сделку","pct"],
      ["deals","Число созданных сделок","num"],
      ["sales","Продажи, закрытые в периоде","num"],
      ["lead_to_sale_rate","% из лида в продажу","pct"],
      ["deal_to_sale_rate","Конверсия созданных сделок в продажу","pct"],
      ["average_check","Средний чек","money"],
      ["sales_amount","Выручка","money"]
    ]
  },
  {
    key:"Входящий трафик продажи", cls:"incoming",
    title:"Входящие продажи",
    metrics:[
      ["leads","Число лидов всего","num"],
      ["qualified_rate","% из лида в квал. лид","pct"],
      ["qualified","Число квал. лидов","num"],
      ["lead_to_deal_rate","% из квал. лида в сделку","pct"],
      ["deals","Число созданных сделок","num"],
      ["sales","Продажи, закрытые в периоде","num"],
      ["qualified_to_sale_rate","% из квал. лида в продажу","pct"],
      ["deal_to_sale_rate","Конверсия созданных сделок в продажу","pct"],
      ["average_check","Средний чек","money"],
      ["sales_amount","Выручка","money"]
    ]
  },
  {
    key:"Повторные продажи по базе", cls:"repeat",
    title:"Повторные продажи",
    metrics:[
      ["deals","Число созданных сделок","num"],
      ["lost_deals","Число слитых сделок","num"],
      ["sales","Продажи, закрытые в периоде","num"],
      ["deal_to_sale_rate","Конверсия из созданной сделки в продажу","pct"],
      ["average_check","Средний чек","money"],
      ["sales_amount","Выручка","money"]
    ]
  }
];

const RNP_METRIC_LOGIC={
  leads:"Лиды, созданные в выбранном отчётном периоде.",
  qualified:"Лиды выбранного периода, которые отмечены в CRM как квалифицированные.",
  qualified_rate:"Квалифицированные лиды ÷ все лиды выбранного периода.",
  lead_to_deal_rate:"Созданные сделки ÷ квалифицированные лиды выбранного периода.",
  deals:"Сделки, созданные в периоде. В столбце «Хвост» — сделки, созданные раньше, но учитываемые в текущем месяце.",
  lost_deals:"Сделки, переведённые в проигрыш в выбранном периоде.",
  sales:"Успешно закрытые сделки по дате закрытия: отдельно из сделок периода и из более раннего хвоста.",
  lead_to_sale_rate:"Продажи из сделок, созданных из лидов периода ÷ все лиды периода.",
  qualified_to_sale_rate:"Продажи из сделок, созданных из квалифицированных лидов периода ÷ квалифицированные лиды периода.",
  average_check:"Выручка успешных продаж ÷ количество успешных продаж в соответствующей колонке.",
  sales_amount:"Точная чистая выручка по строкам «Графика платежей», связанным со сделками этого блока. Подрядчики вычитаются только у той сделки, к которой относятся.",
};
const RNP_CONVERSION_LOGIC="Отчётный период: продажи из сделок, созданных в периоде ÷ эти сделки. Итого: все успешные продажи периода вместе с хвостом ÷ все сделки периода вместе с хвостом.";

function rnpGroup(name){return (state.sales.groups||[]).find(x=>x.name===name)}
function isPctMetric(k){return ["qualified_rate","lead_to_deal_rate","lead_to_sale_rate","qualified_to_sale_rate","deal_to_sale_rate","closing_flow_deal_to_sale_rate","tail_deal_to_sale_rate","total_deal_to_sale_rate","product_sale_rate"].includes(k)}
function isAvgMetric(k){return ["average_check","average_product_check","products_per_deal"].includes(k)}
function isAdditiveMetric(k){return !isPctMetric(k)&&!isAvgMetric(k)}

function rnpWeekRanges(){
  const [yy,mm]=(state.month_key||"").split("-").map(Number);
  if(!yy||!mm)return [];
  const first=new Date(yy,mm-1,1);
  const mondayOffset=(first.getDay()+6)%7; // Mon=0
  const firstMonday=new Date(yy,mm-1,1-mondayOffset);
  const lastDay=new Date(yy,mm,0).getDate();
  const out=[];
  for(let i=0;i<5;i++){
    const a=new Date(firstMonday);a.setDate(firstMonday.getDate()+i*7);
    const b=new Date(a);b.setDate(a.getDate()+4);
    const clipStart=(a.getMonth()===mm-1)?a.getDate():1;
    const clipEnd=(b.getMonth()===mm-1)?b.getDate():lastDay;
    let workdays=0;
    for(let d=clipStart;d<=clipEnd;d++){
      const dt=new Date(yy,mm-1,d),wd=dt.getDay();
      if(wd!==0&&wd!==6)workdays++;
    }
    out.push({
      index:i,start:clipStart,end:clipEnd,workdays,
      label:`${String(a.getDate()).padStart(2,"0")}.${String(a.getMonth()+1).padStart(2,"0")}–${String(b.getDate()).padStart(2,"0")}.${String(b.getMonth()+1).padStart(2,"0")}`
    });
  }
  return out;
}
function rnpTotalWorkdays(){return rnpWeekRanges().reduce((s,w)=>s+w.workdays,0)||1}
function rnpWeekPlan(groupKey,metric,weekIndex){
  const plan=getPlan("sales",metric,"source_group",groupKey);
  if(!plan)return 0;
  if(!isAdditiveMetric(metric))return plan;
  const w=rnpWeekRanges()[weekIndex];
  return w?plan*w.workdays/rnpTotalWorkdays():0;
}
function rnpCombinedMetric(key,current,previous,total){
  if(isAdditiveMetric(key))return Number(current||0)+Number(previous||0);
  return Number(total||0);
}
function rnpCleanRevenue(filter={}){
  if(usesDealAmountRevenue()){
    let rows=[];
    if(filter.manager)rows=(state.sales.managers||[]).filter(row=>row.name===filter.manager);
    else if(filter.client_type)rows=(state.sales.client_type_blocks||[]).filter(row=>row.group===filter.group&&row.name===filter.client_type);
    else if(filter.source)rows=(state.sales.source_blocks||[]).filter(row=>row.group===filter.group&&row.name===filter.source);
    else if(filter.group)rows=(state.sales.groups||[]).filter(row=>row.name===filter.group);
    else rows=[state.sales.overall||{}];
    const metrics=rows.reduce((out,row)=>{
      for(const period of ["current","previous","total"])out[period]+=Number(row?.[period]?.metrics?.sales_amount||0);
      return out;
    },{current:0,previous:0,total:0});
    return metrics;
  }
  const finance=state?.clean_revenue||{};
  if(!["online","stale"].includes(finance.status)||finance.deal_revenue_available!==true||!Array.isArray(finance.deal_revenue_rows))return {current:null,previous:null,total:null};
  const rows=finance.deal_revenue_rows.filter(row=>Object.entries(filter).every(([key,value])=>row?.[key]===value));
  const current=rows.filter(row=>row.period_type==="current").reduce((sum,row)=>sum+Number(row.clean_revenue||0),0);
  const previous=rows.filter(row=>row.period_type!=="current").reduce((sum,row)=>sum+Number(row.clean_revenue||0),0);
  return {current,previous,total:current+previous};
}
function rnpCleanRevenueWeeks(group){
  const finance=state?.clean_revenue||{};
  if(!["online","stale"].includes(finance.status)||finance.payment_revenue_available!==true||!Array.isArray(finance.payment_revenue_rows))return null;
  return rnpWeekRanges().map(week=>{
    const rows=finance.payment_revenue_rows.filter(row=>{
      const day=Number(String(row.date||"").slice(-2));
      return row.group===group&&Number.isFinite(day)&&day>=week.start&&day<=week.end;
    });
    const clean=rows.reduce((sum,row)=>sum+Number(row.clean_revenue||0),0);
    const incoming=rows.reduce((sum,row)=>sum+Number(row.bank_confirmed||0)+Number(row.manual_confirmed||0),0);
    const contractor=rows.reduce((sum,row)=>sum+Number(row.contractor_applied||0),0);
    return {week,rows,clean,incoming,contractor};
  });
}
function rnpCleanRevenueWeekTable(cfg){
  if(usesDealAmountRevenue()){
    const weeks=rnpGroup(cfg.key)?.total?.weeks||{};
    return `<div class="sales-semantics-note"><strong>Недельная сумма продаж:</strong> суммы успешных сделок Bitrix по дате закрытия; график платежей для этого месяца ещё не вёлся.</div><div class="scroll-x"><table class="rnp-clean-week-table"><thead><tr><th>Неделя</th><th class="num">Сумма продаж</th><th class="num">Продаж</th><th class="num">Средний чек</th></tr></thead><tbody>${rnpWeekRanges().map(week=>{const sales=Number(weeks.sales?.[week.index]||0),amount=Number(weeks.sales_amount?.[week.index]||0);return `<tr><td>${esc(week.label)}</td><td class="num">${money(amount)}</td><td class="num">${fmt(sales)}</td><td class="num">${money(sales?amount/sales:0)}</td></tr>`}).join("")}</tbody></table></div>`;
  }
  const weeks=rnpCleanRevenueWeeks(cfg.key);
  if(!weeks)return `<div class="empty-inline">Недельная чистая выручка готовится из «Графика платежей».</div>`;
  const body=weeks.map(({week,rows,clean,incoming,contractor})=>`<tr>
    <td>${esc(week.label)}</td>
    <td class="num"><button type="button" class="table-drill-link" data-finance-drill="clean" data-finance-group="${attr(cfg.key)}" data-finance-week="${week.index}">${money(clean)}</button></td>
    <td class="num">${money(incoming)}</td>
    <td class="num">${money(contractor)}</td>
    <td class="num">${fmt(new Set(rows.map(row=>row.deal_id)).size)}</td>
  </tr>`).join("");
  return `<div class="sales-semantics-note"><strong>Чистая выручка по неделям:</strong> дата банка — для поступления, дата строки графика — для ручного подтверждения, дата полной оплаты сделки — для удержания подрядчика.</div><div class="scroll-x"><table class="rnp-clean-week-table"><thead><tr><th>Неделя</th><th class="num">Чистая выручка</th><th class="num">Поступления по графику</th><th class="num">Подрядчики</th><th class="num">Сделок</th></tr></thead><tbody>${body}</tbody></table></div>`;
}
function openFinanceDrill(kind,group="",week=""){
  const finance=state?.clean_revenue||{};
  const source=(group||week!=="")&&Array.isArray(finance.payment_revenue_rows)
    ?finance.payment_revenue_rows
    :Array.isArray(finance.deal_revenue_rows)?finance.deal_revenue_rows:[];
  const labels={incoming:"Общая сумма поступлений",clean:"Чистая выручка",contractor:"Подрядчики",unclassified:"Не распределено в графике"};
  const range=week===""?null:rnpWeekRanges()[Number(week)];
  const rows=source.filter(row=>{
    if(group&&row.group!==group)return false;
    if(range){const day=Number(String(row.date||"").slice(-2));if(!Number.isFinite(day)||day<range.start||day>range.end)return false}
    if(kind==="contractor")return Number(row.contractor_applied||0)!==0;
    if(kind==="unclassified")return row.group==="Не распределено"||!String(row.manager||"").trim();
    return true;
  }).map(row=>{
    const amount=kind==="incoming"?Number(row.bank_confirmed||0)+Number(row.manual_confirmed||0):kind==="contractor"?Number(row.contractor_applied||0):Number(row.clean_revenue||0);
    return {...row,title:row.deal_title,amount,stage:kind==="contractor"?"Удержание подрядчика":kind==="incoming"?"Подтверждённое поступление":"Чистая выручка"};
  }).filter(row=>Number(row.amount||0)!==0);
  drillMeta={scope:"finance",metric:kind};drillRows=rows;drillOffset=rows.length;drillTotal=rows.length;
  $("#drillSearch").value="";
  $("#drillTitle").textContent=labels[kind]||"Финансовые строки";
  $("#drillSubtitle").textContent=["Строки «Графика платежей», связанные со сделками",group,range?`${Number(week)+1} неделя`:""].filter(Boolean).join(" · ");
  $("#drillDialog").showModal();
  renderDrillRows();
}
function optionalMoney(value){return value===null?"—":money(value)}
function rnpMetricDetailRow({label,current,previous,total,plan,logic,showPlan=true}){
  return `<details class="rnp-metric-details"><summary class="rnp-month-row"><span class="rnp-metric-label">${esc(label)}<small>Как считаем</small></span><span>${current}</span><span>${previous}</span><strong>${total}</strong>${showPlan?`<span>${plan||"—"}</span>`:""}</summary><div class="rnp-metric-logic">${esc(logic)}</div></details>`;
}
function rnpTotalDealToSaleRate(c,p,t){
  const deals=Number(c.deals||0)+Number(p.deals||0);
  return deals?(Number(c.sales||0)+Number(p.sales||0))/deals*100:0;
}
function rnpConversionRows(c,p,t,{showPlan=true}={}){
  return [
    rnpMetricDetailRow({
      label:"Конверсия периода",
      current:format(c.deal_to_sale_rate||0,"pct"),
      previous:"—",
      total:"—",
      plan:"—",
      logic:"Продажи из сделок, созданных в отчётном периоде ÷ все сделки, созданные в отчётном периоде. Хвост в расчёт не входит.",
      showPlan,
    }),
    rnpMetricDetailRow({
      label:"Конверсия итого с хвостом",
      current:"—",
      previous:"—",
      total:format(rnpTotalDealToSaleRate(c,p,t),"pct"),
      plan:"—",
      logic:RNP_CONVERSION_LOGIC,
      showPlan,
    }),
  ].join("");
}
function rnpMonthlyTable(cfg,g,{showPlan=true,financeFilter={group:cfg.key}}={}){
  const c=g?.current?.metrics||{},p=g?.previous?.metrics||{},t=g?.total?.metrics||{};
  const cleanRevenue=rnpCleanRevenue(financeFilter);
  return `<div class="rnp-month-table${showPlan?"":" no-plan"}">
    <div class="rnp-month-head"><span>Показатель</span><span>Отчётный период</span><span>Хвост</span><span>Итого</span>${showPlan?"<span>План / выполнение</span>":""}</div>
    ${cfg.metrics.filter(([k])=>k!=="deal_to_sale_rate").map(([k,label,type])=>{
      const isRevenue=k==="sales_amount";
      const plan=showPlan?getPlan("sales",k,"source_group",cfg.key):0;
      const current=isRevenue?cleanRevenue.current:c[k],previous=isRevenue?cleanRevenue.previous:p[k],total=isRevenue?cleanRevenue.total:rnpCombinedMetric(k,c[k],p[k],t[k]);
      const hasTail=["deals","lost_deals","deal_amount","sales","sales_amount","average_check"].includes(k);
      return rnpMetricDetailRow({
        label:isRevenue?salesRevenueLabel():label,
        current:isRevenue?optionalMoney(current):format(current||0,type),
        previous:hasTail?(isRevenue?optionalMoney(previous):format(previous||0,type)):"—",
        total:isRevenue?optionalMoney(total):format(total,type),
        plan:plan&&total!==null?`${format(plan,type)} · ${pct(Number(total||0)/plan*100)}`:"—",
        logic:isRevenue?(usesDealAmountRevenue()?"Сумма успешных сделок Bitrix по полю OPPORTUNITY. Отчётный период и хвост определяются датой создания сделки; график платежей для этого месяца ещё не использовался.":"Сумма строк «Графика платежей», у которых указанная сделка относится к этому блоку. Вычтенный подрядчик остаётся у той же сделки. Отчётный период и хвост определяются датой создания сделки; пропорционального распределения нет."):(RNP_METRIC_LOGIC[k]||"Показатель считается по данным выбранного периода из Bitrix24."),
        showPlan,
      });
    }).join("")}
    ${rnpConversionRows(c,p,t,{showPlan})}
  </div>`;
}
function rnpDailyTable(cfg,g,week,periodType="current",metrics=cfg.metrics){
  const d=g?.[periodType]?.days||{};
  const rows=[];
  for(let day=week.start;day<=week.end;day++){
    const active=metrics.some(([k])=>Number(d?.[k]?.[day-1]||0)!==0);
    if(!active)continue;
    rows.push(`<tr><td>${monthDateLabel(day)}</td>${metrics.map(([k,l,t])=>`<td class="num">${tdLink(d?.[k]?.[day-1]||0,"sales",k,t,{group:cfg.key,period_type:periodType,day,week:week.index})}</td>`).join("")}</tr>`);
  }
  return `<div class="scroll-x"><table class="rnp-daily-table"><thead><tr><th>Дата</th>${metrics.map(x=>`<th class="num">${esc(x[1])}</th>`).join("")}</tr></thead><tbody>${rows.join("")||`<tr><td colspan="${metrics.length+1}" class="empty-day">Нет движения</td></tr>`}</tbody></table></div>`;
}
function rnpWeekTable(cfg,g,periodType="current"){
  const metrics=periodType==="total"
    ? [
      ...cfg.metrics.filter(([k])=>!["sales","sales_amount","average_check","deal_to_sale_rate"].includes(k)),
      ["cohort_sales","Продажи из сделок, созданных на этой неделе","num"],
      ["deal_to_sale_rate","Конверсия созданных сделок в продажу в периоде","pct"],
      ["week_tail_deals","Сделки хвоста в работе на начало недели","num"],
      ["sales","Все продажи, закрытые на этой неделе","num"],
      ["week_tail_sales","Из них продажи из хвоста недели","num"],
      ["total_deal_to_sale_rate","Конверсия итого с хвостом","pct"],
      ["sales_amount","Выручка всех закрытий","money"],
      ["average_check","Средний чек по всем закрытиям","money"]
    ]
    : cfg.metrics;
  const weeks=g?.[periodType]?.weeks||{},ranges=rnpWeekRanges();
  return `<div class="rnp-weeks">${ranges.map(w=>{
    const revenue=weeks.sales_amount?.[w.index]||0,sales=weeks.sales?.[w.index]||0;
    return `<details class="rnp-week"><summary><div><strong>${w.index+1} неделя</strong><span>${w.label}</span></div><div><b>${money(revenue)}</b><span>${fmt(sales)} продаж</span></div></summary>
      <div class="rnp-week-body">
        <div class="rnp-week-facts">${metrics.map(([k,label,type])=>{
          const fact=weeks[k]?.[w.index]||0,plan=periodType==="previous"?0:rnpWeekPlan(cfg.key,k,w.index);
          return `<div><span>${esc(label)}</span><strong>${format(fact,type)}</strong>${plan?`<small>план ${format(plan,type)}</small>`:""}</div>`;
        }).join("")}</div>
        <p class="rnp-cohort-note">«Конверсия созданных сделок в продажу в периоде» = продажи из сделок, созданных на этой неделе ÷ сделки, созданные на этой неделе. «Конверсия итого с хвостом» = все продажи, закрытые на неделе ÷ сделки, созданные на неделе + сделки, которые уже были в работе в начале недели. Хвост включает и сделки, созданные раньше в этом же месяце.</p>
        ${rnpDailyTable(cfg,g,w,periodType,metrics.filter(([key])=>!['week_tail_deals','week_tail_sales','total_deal_to_sale_rate'].includes(key)))}
      </div>
    </details>`;
  }).join("")}</div>`;
}
function rnpSourceList(cfg){
  const rows=sourceRowsByGroup(cfg.key).sort((a,b)=>(b.total?.metrics?.sales_amount||0)-(a.total?.metrics?.sales_amount||0));
  return `<details class="rnp-subdetails"><summary><strong>Источники внутри блока</strong><span>${rows.length} источн. · изменить ›</span></summary>
    <div class="rnp-source-toolbar"><button type="button" class="btn soft-action" data-edit-traffic-group="${attr(cfg.key)}">Изменить источники</button></div>
    <div class="rnp-source-list">${rows.map(r=>`<details><summary><span>${esc(r.name)}</span><span>${fmt(r.current.metrics.sales)} продаж · ${money(r.current.metrics.sales_amount)} · хвост ${money(r.previous.metrics.sales_amount)}</span></summary>${sourcePeriodRows(r,"",cfg.key)}</details>`).join("")||'<div class="empty-inline">Источников нет</div>'}</div>
  </details>`;
}
function rnpClientTypeList(cfg){
  const rows=(state.sales.client_type_blocks||[]).filter(r=>r.group===cfg.key).sort((a,b)=>(b.total?.metrics?.sales_amount||0)-(a.total?.metrics?.sales_amount||0));
  return `<details class="rnp-subdetails"><summary><strong>Типы клиентов</strong><span>${rows.length} тип. · отчётный период / хвост / итого</span></summary>
    <div class="rnp-source-list">${rows.map(r=>{
      const c=r.current.metrics||{},p=r.previous.metrics||{},t=r.total.metrics||{};
      return `<details><summary><span>${esc(r.name)}</span><span>${fmt(c.sales)} + ${fmt(p.sales)} = ${fmt(t.sales)} продаж · ${money(t.sales_amount)}</span></summary>${rnpMonthlyTable(cfg,r,{showPlan:false,financeFilter:{group:cfg.key,client_type:r.name}})}</details>`;
    }).join("")||'<div class="empty-inline">Типы клиентов не заполнены</div>'}</div>
  </details>`;
}
function rnpBlock(cfg){
  const g=rnpGroup(cfg.key)||{current:{metrics:{},weeks:{},days:{}},previous:{metrics:{}},total:{metrics:{}}};
  const c=g.current.metrics||{},p=g.previous.metrics||{},t=g.total.metrics||{};
  const revenue=rnpCleanRevenue({group:cfg.key});
  const plan=getPlan("sales","sales_amount","source_group",cfg.key);

  return `<details class="rnp-block ${cfg.cls}">
    <summary class="rnp-block-summary">
      <div class="rnp-summary-head">
        <div>
          <h2>${esc(cfg.title)}</h2>
        </div>
        <div class="rnp-summary-actions">
          <button type="button" class="rnp-plan-btn" data-rnp-plan="${attr(cfg.key)}">Изменить план</button>
          <span class="rnp-chevron">⌄</span>
        </div>
      </div>

      <div class="rnp-result-strip rnp-summary-strip">
        <div>
          <span>${usesDealAmountRevenue()?"Сумма продаж периода":"Чистая выручка периода"}</span>
          <strong>${optionalMoney(revenue.current)}</strong>
          <small>${fmt(c.sales||0)} продаж</small>
        </div>
        <div>
          <span>${usesDealAmountRevenue()?"Сумма продаж / хвост":"Чистая выручка / хвост"}</span>
          <strong>${optionalMoney(revenue.previous)}</strong>
          <small>${fmt(p.sales||0)} продаж</small>
        </div>
        <div class="rnp-total">
          <span>${usesDealAmountRevenue()?"Итого сумма продаж":"Итого чистая выручка"}</span>
          <strong>${optionalMoney(revenue.total)}</strong>
          <small>${fmt(t.sales||0)} продаж</small>
        </div>
        <div>
          <span>${usesDealAmountRevenue()?"План суммы продаж":"План чистой выручки"}</span>
          <strong>${plan?money(plan):"—"}</strong>
          <small>${plan&&revenue.total!==null?pct(revenue.total/plan*100):"не заполнен"}</small>
        </div>
      </div>
    </summary>

    <div class="rnp-block-expanded">
      ${rnpMonthlyTable(cfg,g)}
      <details class="rnp-subdetails">
        <summary><strong>Недельная динамика CRM</strong><span>сумма сделок и закрытия · раскрывается до дней</span></summary>
        ${rnpWeekTable(cfg,g,"total")}
      </details>
      <details class="rnp-subdetails">
        <summary><strong>${usesDealAmountRevenue()?"Сумма продаж по неделям":"Чистая выручка по неделям"}</strong><span>${usesDealAmountRevenue()?"по сумме сделок Bitrix":"по графику платежей"}</span></summary>
        ${rnpCleanRevenueWeekTable(cfg)}
      </details>
      ${rnpClientTypeList(cfg)}
      ${rnpSourceList(cfg)}
    </div>
  </details>`;
}

function salesCleanRevenueReconciliation(){
  if(usesDealAmountRevenue())return "";
  const finance=state?.clean_revenue||{};
  if(!["online","stale"].includes(finance.status)||finance.deal_revenue_available!==true||!Array.isArray(finance.deal_revenue_rows))return "";
  const linked=finance.deal_revenue_rows.reduce((sum,row)=>sum+Number(row.clean_revenue||0),0);
  const classified=RNP_GROUPS.reduce((sum,cfg)=>sum+Number(rnpCleanRevenue({group:cfg.key}).total||0),0);
  const unclassified=linked-classified;
  const ledgerGap=Number(finance.value||0)-linked;
  const notes=[];
  if(Math.abs(unclassified)>0.009)notes.push(`не отнесено к трём блокам ${money(unclassified)}`);
  if(Math.abs(ledgerGap)>0.009)notes.push(`не связано со сделкой ${money(ledgerGap)}`);
  return `<p class="sales-semantics-note"><strong>Сверка чистой выручки:</strong> по сделкам «Графика платежей» ${money(linked)}${notes.length?` · ${notes.join(" · ")}`:" · вся сумма распределена по трём блокам продаж"}.</p>`;
}

function rnpManagerMatrix(){
  return managers().map(m=>{
    const groups=RNP_GROUPS.map(cfg=>({cfg,g:(m.groups||[]).find(x=>x.name===cfg.key)}));
    return `<details class="rnp-manager"><summary><div><strong>${esc(m.name)}</strong><span>разбивка по трём блокам продаж</span></div><div><b>${money(m.total.metrics.sales_amount)}</b><span>${fmt(m.total.metrics.sales)} продаж</span></div></summary>
      <div class="rnp-manager-body">${groups.map(({cfg,g})=>{
        const c=g?.current?.metrics||{},p=g?.previous?.metrics||{};
        const sources=(m.sources||[]).filter(x=>x.group===cfg.key).sort((a,b)=>(b.total.metrics.sales_amount||0)-(a.total.metrics.sales_amount||0));
        const mini=cfg.key==="Повторные продажи по базе"
          ? `Сделки ${fmt(c.deals||0)} · слито ${fmt(c.lost_deals||0)} · продажи ${fmt(c.sales||0)} · ${money(c.sales_amount||0)}`
          : `Лиды ${fmt(c.leads||0)} · квал. ${fmt(c.qualified||0)} · сделки ${fmt(c.deals||0)} · продажи ${fmt(c.sales||0)} · ${money(c.sales_amount||0)}`;
        return `<details class="rnp-manager-group"><summary><strong>${esc(cfg.title)}</strong><span>${mini}</span><small>хвост ${money(p.sales_amount||0)}</small></summary>
          <div class="rnp-manager-sources">${sources.map(s=>`<details><summary><span>${esc(s.name)}</span><span>${fmt(s.current.metrics.sales)} продаж · ${money(s.current.metrics.sales_amount)} · хвост ${money(s.previous.metrics.sales_amount)}</span></summary>${sourcePeriodRows(s,m.name,cfg.key)}</details>`).join("")||'<div class="empty-inline">Нет источников</div>'}</div>
        </details>`;
      }).join("")}</div>
    </details>`;
  }).join("");
}
function reactivationDate(value){const date=value?new Date(value):null;return date&&!Number.isNaN(date.getTime())?date.toLocaleDateString("ru-RU",{day:"numeric",month:"short",year:"numeric"}):"нет данных"}
function reactivationBlock(){
  if(reactivationLoading&&!reactivationData)return `<section class="reactivation-panel"><div class="reactivation-head"><div><div class="eyebrow">JARVIS · РЕАНИМАЦИЯ</div><h3>Реанимируем реанимацию</h3></div><span class="muted">Проверяю сделки, звонки и договорённости…</span></div></section>`;
  if(!reactivationData)return `<section class="reactivation-panel"><div class="reactivation-head"><div><div class="eyebrow">JARVIS · РЕАНИМАЦИЯ</div><h3>Реанимируем реанимацию</h3><p>Очередь временно недоступна. Это не означает, что рекомендаций нет.</p></div><button class="btn ghost" data-reload-reactivation="1">Повторить</button></div></section>`;
  const summary=reactivationData.summary||{},thresholds=reactivationData.thresholds||{},rows=reactivationData.recommendations||[],excluded=reactivationData.excluded||[];
  const evidence=row=>{const context=row.context||{},calls=context.calls||[],stats=context.callStats||{},comments=context.comments||[],fields=context.fields||[],issues=Array.isArray(stats.issues)?stats.issues:[];const total=Number.isFinite(stats.total)?stats.total:calls.length,analyzed=Number.isFinite(stats.analyzed)?stats.analyzed:calls.length,unavailable=Number(stats.unavailable||0),pending=Number(stats.pending||0),notScored=Number(stats.notScored||0);const callCaption=`${fmt(total)} звонков · ИИ разобрал ${fmt(analyzed)}${unavailable?` · недоступны ${fmt(unavailable)}`:""}${notScored?` · короткие ${fmt(notScored)}`:""}${pending?` · ожидают ${fmt(pending)}`:""}`;return `<details class="reactivation-evidence"><summary>${row.analysisMode==="ai"?"Основания ИИ Jarvis":"Основания Jarvis"} · ${callCaption}, ${fmt(comments.length)} комментариев, ${fmt(fields.length)} полей</summary><div class="reactivation-evidence-grid"><div><strong>Звонки сделки</strong><p><b>${esc(callCaption)}</b></p>${calls.length?calls.map(call=>`<p><b>${esc(reactivationDate(call.occurredAt))}</b>${call.summary?` · ${esc(call.summary)}`:""}${call.nextStep?`<br><span>Следующий шаг: ${esc(call.nextStep)}</span>`:""}</p>`).join(""):'<p>Проанализированных ИИ звонков пока нет.</p>'}${issues.length?`<strong>Статус остальных записей</strong>${issues.map(issue=>`<p><b>${esc(reactivationDate(issue.occurredAt))}</b> · ${esc(issue.reason)}</p>`).join("")}`:""}</div><div><strong>Комментарии</strong>${comments.length?comments.map(comment=>`<p>${esc(comment.text)}</p>`).join(""):'<p>Нет доступных комментариев.</p>'}</div><div><strong>Поля сделки</strong>${fields.length?fields.map(field=>`<p><span>${esc(field.label)}:</span> ${esc(field.value)}</p>`).join(""):'<p>Нет доступных полей для объяснения.</p>'}</div></div></details>`};
  return `<details class="reactivation-panel" open><summary><div class="reactivation-head"><div><div class="eyebrow">JARVIS · РЕАНИМАЦИЯ</div><h3>Реанимируем реанимацию</h3><p>${esc(reactivationData.funnel?.name||"Реанимация")} · анализ полей сделки, комментариев, плановых дел и последних звонков.</p></div><div class="reactivation-count"><strong>${fmt(summary.recommended)}</strong><span>к связи</span></div></div></summary><div class="reactivation-rule">Не включает сделки, где контакт был меньше ${fmt(thresholds.recentContactDays||60)} дней назад, или следующая подтверждённая договорённость позже чем через ${fmt(thresholds.farFutureDays||30)} дней.</div><div class="reactivation-queue">${rows.length?rows.map(row=>`<article class="reactivation-row ${attr(row.priorityLevel||"medium")}"><div class="reactivation-row-main"><div class="reactivation-priority ${attr(row.priorityLevel||"medium")}">${esc(row.priorityLabel||"К связи")}</div><div><div class="reactivation-title">${row.url?`<a href="${attr(row.url)}" target="_blank" rel="noopener noreferrer">${esc(row.title||`Сделка ${row.dealId}`)}</a>`:esc(row.title||`Сделка ${row.dealId}`)}</div><div class="reactivation-meta">Последний контакт: ${esc(reactivationDate(row.lastContactAt))}${row.nextContactAt?` · следующее дело: ${esc(reactivationDate(row.nextContactAt))}`:""}</div></div></div><div class="reactivation-reasons"><strong>Почему вернуть в работу</strong><ul>${(row.reasons||[]).map(reason=>`<li>${esc(reason)}</li>`).join("")}</ul><p><b>Следующий шаг:</b> ${esc(row.suggestedNextStep||"Связаться с клиентом")}</p></div>${evidence(row)}<div class="reactivation-actions"><button class="btn primary" data-reactivate-deal="${attr(row.dealId)}">Реанимировали → Новая</button></div></article>`).join(""):`<div class="empty-inline">Сейчас нет сделок, которые можно безопасно рекомендовать к реанимации. Проверено ${fmt(summary.scanned)}; исключено правилами ${fmt(summary.excluded)}.</div>`}</div><details class="reactivation-excluded"><summary>Почему пока не реанимируем · ${fmt(summary.excluded)}</summary>${excluded.length?`<div class="scroll-x"><table><thead><tr><th>Сделка</th><th>Последний контакт</th><th>Причина</th></tr></thead><tbody>${excluded.map(row=>`<tr><td>${row.url?`<a href="${attr(row.url)}" target="_blank" rel="noopener noreferrer">${esc(row.title)}</a>`:esc(row.title)}</td><td>${esc(reactivationDate(row.lastContactAt))}</td><td>${esc((row.exclusions||[]).join(" "))}</td></tr>`).join("")}</tbody></table></div>`:'<p class="muted">Нет исключённых сделок в доступном срезе.</p>'}</details></details>`;
}
async function loadReactivationQueue(force=false){
  if(reactivationLoading)return;
  reactivationLoading=true;
  try{const response=await fetch("/api/reactivation-recommendations",{cache:"no-store"}),payload=await response.json();if(!response.ok||!payload.ok)throw new Error(payload.status||payload.detail||"unavailable");reactivationData=payload.data}catch(error){if(force||!reactivationData)reactivationData=null}finally{reactivationLoading=false;if(requestedView()==="sales"&&state?.sales?.details_loaded)renderSales()}
}
async function reactivateDeal(dealId){
  if(!window.confirm("Вернуть эту сделку в основную воронку продаж на этап «Новая»? Jarvis сначала повторно проверит, что она ещё в реанимации."))return;
  const button=document.querySelector(`[data-reactivate-deal="${CSS.escape(String(dealId))}"]`);if(button){button.disabled=true;button.textContent="Переношу…"}
  try{const response=await fetch(`/api/reactivation-recommendations/${encodeURIComponent(dealId)}/reactivate`,{method:"POST",headers:{"Content-Type":"application/json"}}),payload=await response.json().catch(()=>({detail:"Не удалось подтвердить перенос"}));if(!response.ok||!payload.ok)throw new Error(payload.detail||payload.error||"Не удалось подтвердить перенос");alert("Сделка перенесена в «Новая» основной воронки продаж.");reactivationData=null;await loadReactivationQueue(true)}catch(error){alert(error.message||"Не удалось безопасно перенести сделку");if(button){button.disabled=false;button.textContent="Реанимировали → Новая"}}}

function dailySalesDateValue(){return dailySalesDate||new Date().toISOString().slice(0,10)}
function salesWorkspaceTabs(){return `<div class="sales-workspace-tabs" role="tablist" aria-label="Разделы продаж"><button type="button" class="${salesWorkspaceTab==="overview"?"active":""}" data-sales-workspace-tab="overview" role="tab" aria-selected="${salesWorkspaceTab==="overview"}">Основное</button><button type="button" class="${salesWorkspaceTab==="daily"?"active":""}" data-sales-workspace-tab="daily" role="tab" aria-selected="${salesWorkspaceTab==="daily"}">Ежедневный отчёт</button></div>`}
function dailySalesAvailability(data){const status=data?.availability||{},labels={leads:"лиды",deals:"сделки",calls:"звонки"};const unavailable=Object.entries(status).filter(([,item])=>item?.status!=="online").map(([key,item])=>`${labels[key]}${item?.status==="partial"?" (частично)":""}`);return unavailable.length?`Частично недоступны данные: ${unavailable.join(", ")}. Остальные блоки показаны по Bitrix.`:"Прямые данные Bitrix24 · все блоки доступны."}
function dailySalesCounterRows(rows=[]){return rows.map(row=>`<tr><td>${esc(row.name)}</td><td class="num">${fmt(row.count)}</td></tr>`).join("")||"<tr><td colspan='2' class='empty'>Нет записей за выбранный день</td></tr>"}
function dailySalesNestedRows(rows=[],childKey){return rows.map(row=>`<tr><td><strong>${esc(row.name)}</strong></td><td class="num">${fmt(row.count)}</td><td>${(row[childKey]||[]).map(child=>`${esc(child.name)} · ${fmt(child.count)}`).join("<br>")||"—"}</td></tr>`).join("")||"<tr><td colspan='3' class='empty'>Нет записей за выбранный день</td></tr>"}
function dailySalesLeadsAndDeals(data){const leads=data?.leads||{},deals=data?.deals||{},funnel=data?.funnel||{};return `<div class="daily-sales-kpis"><div><span>Лиды</span><strong>${fmt(leads.total||0)}</strong></div><div><span>Созданные сделки</span><strong>${fmt(deals.total||0)}</strong></div><div><span>Дата</span><strong>${esc(data?.date||dailySalesDateValue())}</strong></div></div><div class="grid-2">${panel("Лиды по источникам",`<div class="scroll-x"><table><thead><tr><th>Источник</th><th class="num">Лиды</th></tr></thead><tbody>${dailySalesCounterRows(leads.by_source)}</tbody></table></div>`)}${panel("Лиды по менеджерам и источникам",`<div class="scroll-x"><table><thead><tr><th>Менеджер</th><th class="num">Лиды</th><th>Источники</th></tr></thead><tbody>${dailySalesNestedRows(leads.by_manager_source,"sources")}</tbody></table></div>`)}</div><div class="grid-2">${panel("Созданные сделки по источникам",`<div class="scroll-x"><table><thead><tr><th>Источник</th><th class="num">Сделки</th></tr></thead><tbody>${dailySalesCounterRows(deals.by_source)}</tbody></table></div>`)}${panel("Созданные сделки по стадиям",`<div class="scroll-x"><table><thead><tr><th>Стадия</th><th class="num">Сделки</th></tr></thead><tbody>${dailySalesCounterRows(deals.by_stage)}</tbody></table></div>`)}</div><div class="grid-2">${panel("Стадии и источники",`<div class="scroll-x"><table><thead><tr><th>Стадия</th><th class="num">Сделки</th><th>Источники</th></tr></thead><tbody>${dailySalesNestedRows(deals.by_stage_source,"sources")}</tbody></table></div>`)}${panel("Сделки по менеджерам и типу клиента",`<div class="scroll-x"><table><thead><tr><th>Менеджер</th><th class="num">Сделки</th><th>Тип клиента</th></tr></thead><tbody>${dailySalesNestedRows(deals.by_manager_client_type,"client_types")}</tbody></table></div>`)}</div>${funnel.note?`<div class="daily-sales-note"><strong>Воронка на конец дня</strong><span>${esc(funnel.note)}</span></div>`:""}`}
function dailySalesCalls(data){const calls=data?.calls||{},rows=calls.by_manager||[];const countRows=rows.map(row=>`<tr><td>${esc(row.name)}</td><td class="num">${fmt(row.incoming_count)}</td><td class="num">${fmt(row.outgoing_count)}</td></tr>`).join("")||"<tr><td colspan='3' class='empty'>Нет звонков за выбранный день</td></tr>";const durationRows=rows.map(row=>`<tr><td>${esc(row.name)}</td><td class="num">${fmt(row.incoming_minutes)}</td><td class="num">${fmt(row.outgoing_minutes)}</td></tr>`).join("")||"<tr><td colspan='3' class='empty'>Нет звонков за выбранный день</td></tr>";return `<div class="daily-sales-kpis"><div><span>CRM-звонки</span><strong>${fmt(calls.total||0)}</strong></div><div><span>Не классифицировано</span><strong>${fmt(calls.unclassified_count||0)}</strong></div><div><span>Без длительности</span><strong>${fmt(calls.without_duration_count||0)}</strong></div></div><div class="grid-2">${panel("Количество звонков по менеджерам",`<div class="scroll-x"><table><thead><tr><th>Менеджер</th><th class="num">Входящие</th><th class="num">Исходящие</th></tr></thead><tbody>${countRows}</tbody></table></div>`,"по CRM-активностям")}${panel("Длительность звонков по менеджерам",`<div class="scroll-x"><table><thead><tr><th>Менеджер</th><th class="num">Входящие, мин</th><th class="num">Исходящие, мин</th></tr></thead><tbody>${durationRows}</tbody></table></div>`,"минуты · только записи с указанной длительностью")}</div><div class="daily-sales-note"><strong>Как считаются звонки</strong><span>${esc(calls.time_basis||"Дата создания CRM-активности")}. Записи без понятного направления не добавляются во входящие или исходящие.</span></div>`}
function renderDailySales(){const data=dailySalesData,tab=dailySalesTab;const body=!data?`<div class="daily-sales-loading">${dailySalesLoading?"Загружаю дневные данные Bitrix…":"Выберите дату, чтобы загрузить прямой дневной отчёт из Bitrix."}</div>`:`<div class="daily-sales-status">${esc(dailySalesAvailability(data))}${data.generated_at?` · обновлено ${esc(new Intl.DateTimeFormat("ru-RU",{hour:"2-digit",minute:"2-digit"}).format(new Date(data.generated_at)))}`:""}</div>${tab==="leads"?dailySalesLeadsAndDeals(data):dailySalesCalls(data)}`;$("#sales").innerHTML=`<div class="toolbar dept-toolbar daily-sales-head"><div><div class="eyebrow">ОТДЕЛ ПРОДАЖ · BITRIX24</div><h2>Ежедневный отчёт</h2><div class="muted">Лиды, сделки и звонки за один день — напрямую из Bitrix, без BI-конструктора.</div></div><div class="toolbar-actions"><label class="daily-sales-date"><span>Дата отчёта</span><input type="date" value="${attr(dailySalesDateValue())}" data-daily-sales-date></label><button type="button" class="btn ghost" data-daily-sales-refresh="1">Обновить</button></div></div>${salesWorkspaceTabs()}<div class="daily-sales-tabs" role="tablist"><button type="button" class="${tab==="leads"?"active":""}" data-daily-sales-tab="leads" role="tab">Лиды и сделки</button><button type="button" class="${tab==="calls"?"active":""}" data-daily-sales-tab="calls" role="tab">Звонки</button></div><section class="daily-sales-report">${body}</section>`}
async function loadDailySales(force=false){const date=dailySalesDateValue();if(dailySalesLoading||(!force&&dailySalesData?.date===date))return;dailySalesLoading=true;if(salesWorkspaceTab==="daily")renderDailySales();try{const response=await fetch(`/api/sales-daily?date=${encodeURIComponent(date)}`,{cache:"no-store"}),payload=await response.json().catch(()=>({detail:"Не удалось прочитать ответ Bitrix"}));if(!response.ok||!payload.ok)throw new Error(payload.detail||"Ежедневный отчёт временно недоступен");if(dailySalesDateValue()===date)dailySalesData=payload}catch(error){if(dailySalesDateValue()===date)dailySalesData={ok:true,date,availability:{leads:{status:"unavailable"},deals:{status:"unavailable"},calls:{status:"unavailable"}},leads:{},deals:{},calls:{},funnel:{note:error.message||"Ежедневный отчёт временно недоступен"}}}finally{dailySalesLoading=false;if(salesWorkspaceTab==="daily")renderDailySales()}}
function renderSales(){
  if(salesWorkspaceTab==="daily"){renderDailySales();return}
  const x=state.sales.overall.total.metrics,financial=financialSalesMetrics(x);
  const cleanRevenuePlan=getPlan("sales","sales_amount"),salesPlan=getPlan("sales","sales"),averageCheckPlan=getPlan("sales","average_check");
  const cleanRevenue=financeValue("value"),contractors=financeValue("contractor_amount");
  const legacy=usesDealAmountRevenue();
  const sf=state.sales.sale_filter||{};
  const stageText=(sf.stage_names||[]).length?(sf.stage_names||[]).join(", "):"Предоплата + успешная продажа";
  $("#sales").innerHTML=`
    <div class="toolbar dept-toolbar rnp-toolbar">
      <div><div class="eyebrow">ОТДЕЛ ПРОДАЖ</div><div class="muted">Три блока продаж → план/факт → недели → дни → источники</div></div>
      <div class="toolbar-actions"><button class="btn soft-action" data-open-team="manager">+ Менеджер</button><button class="btn ghost" id="openPlanSales">Все планы</button></div>
    </div>${salesWorkspaceTabs()}

    <div class="rnp-overall-strip">
      ${legacy?salesSummaryMetric("Сумма продаж",financial.incoming,"money",cleanRevenuePlan,incomingRevenueCaption(),true):`${salesSummaryMetric("Общая сумма поступлений",financial.incoming,"money",0,incomingRevenueCaption(),false,"incoming")}${salesSummaryMetric("Чистая выручка",cleanRevenue,"money",cleanRevenuePlan,cleanRevenueCaption(),true,"clean")}${salesSummaryMetric("Подрядчики",contractors,"money",0,contractorCaption(),false,"contractor")}`}
      ${salesSummaryMetric("Продажи месяца",x.sales,"num",salesPlan)}
      ${salesSummaryMetric("Средний чек",financial.averageCheck,"money",averageCheckPlan)}
    </div>

    <div class="sales-semantics-note"><strong>Финансовая логика:</strong> ${legacy?"июль и август 2026 считаются по сумме успешных сделок Bitrix (OPPORTUNITY): контура «Чистой выручки» тогда ещё не было.":"общая сумма поступлений = чистая выручка + подрядчики из приложения «График платежей». Нажмите на любую из трёх финансовых карточек, чтобы открыть подтверждающие строки сделок."}</div>
    ${salesOverdueSchedule()}
    ${reactivationBlock()}
    <div class="rnp-three-blocks">${RNP_GROUPS.map(rnpBlock).join("")}</div>
    ${salesCleanRevenueReconciliation()}
    <div class="sales-semantics-note"><strong>Логика воронки:</strong> «Созданные сделки» включают все сделки, созданные в месяце. «Продажи» и общая сумма поступлений — только стадии 14. Предоплата получена и 15. Продажа успешна. Отказы и слитые сделки в продажи не входят.</div>

    <section class="sales-operational-grid" aria-label="Оперативная работа отдела продаж">
      ${salesActiveDealsCard()}
      ${panel("Стадии продаж",`<div class="scroll-x">${salesStages()}</div>`,"актуально на момент обновления")}
    </section>
    ${panel("Менеджеры продаж",`${salesOperationalManagerTable()}<p class="sales-manager-note">${legacy?"* Сумма продаж — OPPORTUNITY успешно закрытых сделок Bitrix.":"* Чистая выручка — сумма строк «Графика платежей», связанных со сделками менеджера; подрядчик вычитается из той же сделки. В строке «Не распределено» остаются только нераспознанные строки графика, а не сделки сотрудников вне выбранной команды."}</p>`,legacy?"продажи по сумме сделок Bitrix":"продажи и чистая выручка по графику платежей")}

    <section class="rnp-secondary">
      <details class="rnp-main-details" open><summary><div><strong>Разбивка по менеджерам</strong><span>Роман / Ирина → холодные / входящие / повторные → источник → период → даты</span></div></summary>${rnpManagerMatrix()}</details>
      <details class="rnp-main-details"><summary><div><strong>Разбивка по продуктам</strong><span>${fmt(x.products)} продуктов в сделках · ${fmt(x.sold_products)} продано</span></div></summary>
        ${salesProductTable()}
        <div class="product-definition-note"><strong>Конверсия по продуктам</strong> = количество продуктов из сделок, созданных в выбранном месяце, которые продались в этом же месяце / количество продуктов в сделках, созданных в выбранном месяце. <strong>Хвост в эту конверсию не входит.</strong></div>
      </details>
    </section>
  `;
  $("#openPlanSales")?.addEventListener("click",()=>openPlanDialog("sales"));
  if(!reactivationData&&!reactivationLoading)void loadReactivationQueue();
}

function renderExpertsDepartment(){
  const production=$("#production").innerHTML;
  const expertsView=$("#experts").innerHTML;
  $("#department-experts").innerHTML=`<div class="combined-department"><div class="combined-department-section">${production}</div><div class="combined-department-section">${expertsView}</div></div>`;
  $("#department-experts #openPlanProd")?.addEventListener("click",()=>openPlanDialog("production"));
}
function prodProductTable(){
  const rows=state.production.products.map(r=>{
    const planCount=getPlan("production","closed_count","product",r.name);
    const planAmount=getPlan("production","closed_amount","product",r.name);
    return `<tr>
      <td>${esc(r.name)}</td>
      <td>${esc(r.complexity||r.category)}</td>
      <td class="num">${r.norm_days?days(r.norm_days):"—"}</td>
      <td class="num">${tdLink(r.new_count,"production","new_count","num",{product:r.name})}</td>
      <td class="num">${tdLink(r.new_amount,"production","new_amount","money",{product:r.name})}</td>
      <td class="num">${tdLink(r.period_closed_count,"production","period_closed_count","num",{product:r.name})}</td>
      <td class="num">${tdLink(r.conversion_pct,"production","new_to_success_pct","pct",{product:r.name})}</td>
      <td class="num">${tdLink(r.closed_count,"production","closed_count","num",{product:r.name})}</td>
      <td class="num">${tdLink(r.closed_amount,"production","closed_amount","money",{product:r.name})}</td>
      <td class="num">${planCount?fmt(planCount)+" шт":"—"}</td>
      <td class="num">${planCount?pct(r.closed_count/planCount*100):"—"}</td>
      <td class="num">${planAmount?money(planAmount):"—"}</td>
      <td class="num">${planAmount?pct(r.closed_amount/planAmount*100):"—"}</td>
      <td class="num">${tdLink(r.avg_check,"production","avg_check","money",{product:r.name})}</td>
      <td class="num">${tdLink(r.avg_production_days,"production","avg_production_days","days",{product:r.name})}</td>
      <td class="num">${tdLink(r.avg_deviation_days,"production","avg_deviation_days","days",{product:r.name})}</td>
      <td class="num">${tdLink(r.within_norm_pct,"production","within_norm_pct","pct",{product:r.name})}</td>
      <td class="num">${tdLink(r.capacity_count,"production","capacity_count","num",{product:r.name})}</td>
      <td class="num">${tdLink(r.capacity_amount,"production","capacity_amount","money",{product:r.name})}</td>
      <td class="num">${tdLink(r.returns_count,"production","returns_count","num",{product:r.name})}</td>
      <td class="num">${tdLink(r.returns_amount,"production","returns_amount","money",{product:r.name})}</td>
      <td class="num"><button class="mini-edit" data-edit-product-plan="${attr(r.name)}">Изменить</button></td>
    </tr>`}).join("");
  return `<div class="criteria-box compact-criteria"><strong>Конверсия по продукту</strong> = «Закрыто из новых» / «Новых». Колонка «Закрыто всего» может включать старый хвост и поэтому не участвует в этой конверсии.</div>
  <div class="scroll-x"><table><thead><tr>
    <th>Продукт</th><th>Сложность</th><th class="num">Норма</th>
    <th class="num">Новых</th><th class="num">Новых BYN</th>
    <th class="num">Закрыто из новых</th><th class="num">Конв.</th>
    <th class="num">Закрыто всего</th><th class="num">Закрыто BYN</th>
    <th class="num">План, шт</th><th class="num">% шт</th>
    <th class="num">План, BYN</th><th class="num">% BYN</th>
    <th class="num">Ср чек</th><th class="num">Срок</th><th class="num">Откл.</th><th class="num">В норме</th>
    <th class="num">Ёмкость</th><th class="num">Ёмкость BYN</th><th class="num">Возвраты</th><th class="num">Возвраты BYN</th>
    <th></th>
  </tr></thead><tbody>${rows}</tbody></table></div>`;
}
function expertTable(compact=false){
  const rows=experts().map(r=>`<tr><td>${esc(r.name)}</td><td class="num">${tdLink(r.closed_count,"production","closed_count","num",{expert:r.name})}</td><td class="num">${tdLink(r.closed_amount,"production","closed_amount","money",{expert:r.name})}</td><td class="num">${tdLink(r.avg_production_days,"production","avg_production_days","days",{expert:r.name})}</td><td class="num">${tdLink(r.within_norm_pct,"production","within_norm_pct","pct",{expert:r.name})}</td>${compact?"":`<td class="num">${getPlan("production","closed_amount","expert",r.name)?money(getPlan("production","closed_amount","expert",r.name)):"—"}</td><td class="num">${getPlan("production","closed_amount","expert",r.name)?pct(r.closed_amount/getPlan("production","closed_amount","expert",r.name)*100):"—"}</td><td class="num">${npsText(expertNps(r))}${expertNpsMeta(r).count?` · ${fmt(expertNpsMeta(r).count)} оц.`:''}</td><td class="num">${tdLink(r.active_count,"production","active","num",{expert:r.name})}</td><td class="num">${tdLink(r.returns_count,"production","returns_count","num",{expert:r.name})}</td>`}</tr>`).join("");
  return `<div class="scroll-x"><table><thead><tr><th>Эксперт</th><th class="num">Закрыто</th><th class="num">Сумма</th><th class="num">Срок</th><th class="num">В норме</th>${compact?"":"<th class='num'>План BYN</th><th class='num'>% плана</th><th class='num'>NPS за прошлую неделю</th><th class='num'>Активно</th><th class='num'>Возвраты</th>"}</tr></thead><tbody>${rows}</tbody></table></div>`;
}
function prodStages(){return `<table><thead><tr><th>Стадия</th><th class="num">Кол-во</th><th class="num">Сумма</th></tr></thead><tbody>${state.production.stages.map(r=>`<tr><td>${esc(r.name)}</td><td class="num">${tdLink(r.count,"production","active","num",{stage:r.name})}</td><td class="num">${tdLink(r.amount,"production","active","money",{stage:r.name})}</td></tr>`).join("")}</tbody></table>`}
const PROD_WEEKLY_METRICS=[
  ["closed_count","Закрыто продуктов","num"],
  ["closed_amount","Сумма закрытых","money"],
  ["avg_check","Средний чек","money"],
  ["avg_production_days","Срок производства","days"],
  ["within_norm_pct","В нормативе","pct"]
];
function prodWeekPlan(metric,weekIndex){
  const weeklyPlan=getPlan("production",metric,"week",String(weekIndex));
  if(weeklyPlan)return weeklyPlan;
  const plan=getPlan("production",metric);
  if(!plan||!["closed_count","closed_amount"].includes(metric))return 0;
  const week=rnpWeekRanges()[weekIndex];
  return week?plan*week.workdays/rnpTotalWorkdays():0;
}
function prodDailyTable(week){
  const data=state.production.weekly?.days||{};
  const rows=[];
  for(let day=week.start;day<=week.end;day++){
    if(!PROD_WEEKLY_METRICS.some(([key])=>Number(data?.[key]?.[day-1]||0)!==0))continue;
    rows.push(`<tr><td>${monthDateLabel(day)}</td>${PROD_WEEKLY_METRICS.map(([key,label,type])=>`<td class="num">${tdLink(data?.[key]?.[day-1]||0,"production",key,type,{week:week.index,day})}</td>`).join("")}</tr>`);
  }
  return `<div class="scroll-x"><table class="rnp-daily-table"><thead><tr><th>Дата</th>${PROD_WEEKLY_METRICS.map(([,label])=>`<th class="num">${esc(label)}</th>`).join("")}</tr></thead><tbody>${rows.join("")||`<tr><td colspan="${PROD_WEEKLY_METRICS.length+1}" class="empty-day">Нет закрытых продуктов</td></tr>`}</tbody></table></div>`;
}
function productionWeeklyDynamics(){
  const weeks=state.production.weekly?.weeks||{},ranges=rnpWeekRanges();
  return `<details class="rnp-subdetails production-weekly-dynamics">
    <summary><strong>Недельная динамика</strong><span><button type="button" class="btn ghost" data-production-week-plans="1">Изменить планы</button> план / факт · раскрывается до дней</span></summary>
    <div class="rnp-weeks">${ranges.map(week=>{
      const amount=weeks.closed_amount?.[week.index]||0,count=weeks.closed_count?.[week.index]||0;
      return `<details class="rnp-week"><summary><div><strong>${week.index+1} неделя</strong><span>${week.label}</span></div><div><b>${money(amount)}</b><span>${fmt(count)} закрыто</span></div></summary>
        <div class="rnp-week-body"><div class="rnp-week-facts">${PROD_WEEKLY_METRICS.map(([key,label,type])=>{
          const fact=weeks[key]?.[week.index]||0,plan=prodWeekPlan(key,week.index);
          return `<div><span>${esc(label)}</span><strong>${format(fact,type)}</strong>${plan?`<small>план ${format(plan,type)}</small>`:""}</div>`;
        }).join("")}</div>${prodDailyTable(week)}</div>
      </details>`;
    }).join("")}</div>
  </details>`;
}
function productionSalesIncomingCard(){
  const value=financialIncomingValue();
  const plan=getPlan("production","new_amount");
  const shown=value===null?"—":money(value);
  const completion=value!==null&&plan?pct(value/plan*100):"—";
  const bar=value!==null&&plan?Math.min(100,Math.max(0,value/plan*100)):0;
  const finance=state?.clean_revenue||{};
  const note=finance.status==="online"?"Чистая выручка + подрядчики из «Графика платежей»":finance.status==="stale"?"Последняя подтверждённая сумма: чистая выручка + подрядчики":"Поступления временно недоступны";
  return `<div class="card production-sales-incoming"><div class="kpi-label">Поступления отдела продаж</div><div class="kpi-value">${shown}</div><div class="kpi-meta plan-line"><span>План: ${plan?money(plan):"—"}</span><span>${plan?`Выполнение: ${completion}`:"Выполнение: —"}</span></div><div class="kpi-note">${esc(note)}</div>${plan&&value!==null?`<div class="progress"><span class="${bar>=100?"good":bar<60?"bad":""}" style="width:${bar}%"></span></div>`:""}</div>`;
}
function renderProduction(){
  const weeklyNps=state?.automatic_nps?.overall||{value:null,count:0};
  const p={...state.production.kpi,nps_avg:weeklyNps.value};
  $("#production").innerHTML=`<div class="toolbar dept-toolbar production-toolbar"><div><div class="eyebrow">ПРОИЗВОДСТВО</div><div class="muted">${esc(state.production.period_label)} · результат, поток, воронка и сроки</div></div><div class="toolbar-actions"><button class="btn soft-action" data-open-team="expert">+ Добавить эксперта</button><button class="btn ghost" data-open-team="expert" data-team-former="1">+ Уволенного из Bitrix</button><button class="btn ghost" id="openPlanProd">Изменить планы</button></div></div>
  <div class="department-page-head production-page-head">${deptHero({kind:'production',title:'Результат производства',eyebrow:'ЗАКРЫТЫЕ АКТЫ',value:p.closed_amount,valueType:'money',scope:'production',metric:'closed_amount',substats:[{label:'Закрыто продуктов',value:p.closed_count},{label:'Средний чек',value:p.avg_check,type:'money'},{label:'В нормативе',value:p.within_norm_pct,type:'pct'}]})}${manualNpsCard(p.nps_avg,weeklyNps.count)}</div>
  <div class="section-title">Результат периода</div>
  <div class="kpi-grid compact-cards">${card("Закрыто продуктов",p.closed_count,"production","closed_count","num")}${card("Сумма закрытых",p.closed_amount,"production","closed_amount","money")}${card("Средний чек",p.avg_check,"production","avg_check","money")}</div>
  ${productionWeeklyDynamics()}
  <div class="section-title">Поток выбранного периода</div>
  <div class="kpi-grid dense">${card("Пришло продуктов",p.new_count,"production","new_count","num")}${productionSalesIncomingCard()}${card("Закрыто из пришедших",p.period_closed_count,"production","period_closed_count","num")}${card("Сумма закрытых из пришедших",p.period_closed_amount,"production","period_closed_amount","money")}${card("Конверсия в успех",p.new_to_success_pct,"production","new_to_success_pct","pct",{},`${fmt(p.period_closed_count)} закрыто из ${fmt(p.new_count)} пришедших`)}</div>
  <div class="section-title">Воронка и сроки</div>
  <div class="kpi-grid dense">${card("Ёмкость периода",p.capacity_count,"production","capacity_count","num",{},money(p.capacity_amount))}${card("Возвраты",p.returns_count,"production","returns_count","num",{},money(p.returns_amount))}${card("Средний срок",p.avg_production_days,"production","avg_production_days","days")}${card("Отклонение от нормы",p.avg_deviation_days,"production","avg_deviation_days","days")}${card("В нормативе",p.within_norm_pct,"production","within_norm_pct","pct")}</div>
  <details class="rnp-main-details production-product-breakdown"><summary><div><strong>Разбивка по продуктам</strong><span>нажми на показатель → эксперт → продукт → компания</span></div><button type="button" class="btn ghost" data-production-product-plans="1">Изменить планы</button></summary>${prodProductTable()}</details>
  <div class="grid-2">${panel("Эксперты",expertTable(false),"состав можно менять прямо здесь",'<button type="button" class="btn ghost" data-production-expert-plans="1">Изменить планы</button>')}${panel("Стадии производства",prodStages(),"количество и сумма")}</div>`;
  $("#openPlanProd")?.addEventListener("click",()=>openPlanDialog("production"));
}

function renderExperts(){
  const p=state.production.kpi;
  const flow=state.production?.stuck_flow||{};
  const dateLabel=(value)=>{try{return new Intl.DateTimeFormat('ru-RU',{day:'numeric',month:'long'}).format(new Date(`${value}T12:00:00`))}catch(e){return value||'1 число'}};
  const flowDelta=(delta,baseline=0)=>{
    const value=Number(delta?.value||0),percent=delta?.pct;
    if(!value)return `без изменений · было ${fmt(baseline)}`;
    const sign=value>0?'+':'';
    return `${value>0?'↑':'↓'} ${sign}${fmt(value)}${percent===null||percent===undefined?'':` · ${sign}${pct(percent)}`}`;
  };
  const flowCard=(title,value,metric,delta,baseline,note)=>`<div class="card clickable stuck-flow-card" ${drillAttrs('production',metric)}><div class="kpi-label">${esc(title)}</div><div class="kpi-value">${fmt(value)}</div><div class="stuck-flow-delta ${Number(delta?.value||0)>0?'up':Number(delta?.value||0)<0?'down':''}">${esc(flowDelta(delta,baseline))}</div><div class="kpi-note">${esc(note)}</div></div>`;
  const flowBlock=flow.available?`<div class="stuck-flow-block"><div class="section-title">Зависшие</div><div class="kpi-grid dense">${flowCard('Зависшие сейчас',flow.current_count,'stuck_flow_current',flow.current_delta,flow.baseline_count,`на дату ${dateLabel(flow.as_of)}`)}${flowCard('Завершено возвратом',flow.to_returns_count,'stuck_flow_returns',flow.returns_delta,0,`с ${dateLabel(flow.baseline_date)}`)}${flowCard('Завершено в производство',flow.to_production_count,'stuck_flow_to_production',flow.production_delta,0,`с ${dateLabel(flow.baseline_date)}`)}</div><div class="stuck-flow-summary"><strong>Динамика остатка:</strong> на ${dateLabel(flow.baseline_date)} было ${fmt(flow.baseline_count)} зависших, сейчас ${fmt(flow.current_count)}. ${flowDelta(flow.current_delta,flow.baseline_count)}.${flow.exact_cohort?' Переходы считаются по зафиксированному списку первого дня.':' Для сентября стартовая цифра подтверждена вручную; переходы считаются по завершениям в воронке с 1 сентября.'}</div></div>`:`<div class="stuck-flow-block"><div class="section-title">Зависшие</div><div class="criteria-box">Стартовая база на первое число для этого месяца ещё не зафиксирована.</div></div>`;
  const npsMonth=automaticNpsMonthLabel();
  const cards=experts().map(e=>{const nm=expertNpsMeta(e),nv=nm.value,canOpen=nm.count>0;return `<div class="expert-card"><div class="expert-card-top"><div><div class="expert-name">${esc(e.name)}</div><div class="expert-result">${money(e.closed_amount)}</div></div><button type="button" class="btn nps-button nps-details-trigger" data-open-nps-details="${attr(e.name)}" ${canOpen?'':'disabled'} title="${canOpen?'Открыть оценки NPS':'За этот месяц оценок пока нет'}">${nv===null?`NPS ${esc(npsMonth)} —`:`NPS ${esc(npsMonth)} ${fmt(nv)} · ${fmt(nm.count)} оц.`}${canOpen?'<span aria-hidden="true">›</span>':''}</button></div><div class="expert-stats"><div><span>Закрыто</span><strong>${tdLink(e.closed_count,"production","closed_count","num",{expert:e.name})}</strong></div><div><span>В работе</span><strong>${tdLink(e.active_count,"production","active","num",{expert:e.name})}</strong></div><div><span>В норме</span><strong>${pct(e.within_norm_pct)}</strong></div><div><span>Возвраты</span><strong>${tdLink(e.returns_count,"production","returns_count","num",{expert:e.name})}</strong></div></div><details class="nested"><summary>По продуктам (${e.products.length})</summary><div class="nested-body"><table><thead><tr><th>Продукт</th><th class="num">Закрыто</th><th class="num">План, шт</th><th class="num">% плана</th><th class="num">Сумма</th><th class="num">Срок</th><th class="num">В норме</th><th></th></tr></thead><tbody>${e.products.map(p=>{const plan=expertProductPlan(e.name,p.name);return `<tr><td>${esc(p.name)}</td><td class="num">${tdLink(p.closed_count,"production","closed_count","num",{expert:e.name,product:p.name})}</td><td class="num">${plan?fmt(plan):"—"}</td><td class="num">${plan?pct(p.closed_count/plan*100):"—"}</td><td class="num">${tdLink(p.closed_amount,"production","closed_amount","money",{expert:e.name,product:p.name})}</td><td class="num">${tdLink(p.avg_days,"production","avg_production_days","days",{expert:e.name,product:p.name})}</td><td class="num">${tdLink(p.within_norm_pct,"production","within_norm_pct","pct",{expert:e.name,product:p.name})}</td><td class="num"><button class="mini-edit" data-edit-expert-product-plan="1" data-expert="${attr(e.name)}" data-product="${attr(p.name)}">План</button></td></tr>`}).join("")}</tbody></table></div></details></div>`}).join("");
  const activeStuck=state.production.active_stuck||{},reasonCards=`<div class="kpi-grid compact-cards reason-coverage-cards">${card("Активные зависшие — все",p.active_stuck_with_reason_count||0,"production","active_stuck_with_reason_count","num",{},`${money(p.active_stuck_with_reason_amount||0)} · ${pct(p.active_stuck_with_reason_pct||0)} из ${fmt(activeStuck.all_count||0)}`)}${card("Активные зависшие — ожидаемое закрытие в месяце",p.active_stuck_with_reason_expected_month_count||0,"production","active_stuck_with_reason_expected_month_count","num",{},`${money(p.active_stuck_with_reason_expected_month_amount||0)} · ${pct(p.active_stuck_with_reason_expected_month_pct||0)} из ${fmt(activeStuck.expected_month_count||0)}`)}</div>`;
  const reasonsBlock=`<section class="expert-stuck-reasons"><div class="section-title">Активные зависшие в производстве</div>${reasonCards}${panel("Разбивка по причинам",activeReasonTable(activeStuck.all_reasons||[],activeStuck.expected_month_reasons||[]),activeStuck.expected_month_rule||"Вторая группа: предполагаемая дата закрытия попадает в выбранный месяц.")}</section>`;
  $("#experts").innerHTML=`<div class="toolbar dept-toolbar"><div><div class="eyebrow">ЭКСПЕРТЫ</div><div class="muted">Закрытые продукты, нагрузка, нормативы и общий NPS за ${esc(npsMonth)} по дате создания задачи</div></div><div class="toolbar-actions"><button class="btn primary-light" data-open-team="expert">+ Добавить эксперта из Bitrix</button><button class="btn ghost" data-open-team="expert" data-team-former="1">+ Уволенного из Bitrix</button><button type="button" class="btn ghost" data-open-nps="">+ Добавить NPS вручную</button></div></div><div class="expert-grid">${cards||'<div class="empty">Эксперты не выбраны. Нажми «Добавить эксперта из Bitrix».</div>'}</div>${actsExpertsPanel()}${flowBlock}${reasonsBlock}`;
  void loadActsExperts();
}

function actsExpertsMonth(){return state?.month_key||$("#month")?.value||""}
function actsExpertsPanel(){
  const month=actsExpertsMonth();
  const report=actsExpertsData?.month===month?actsExpertsData:null;
  if(!report)return `<details class="acts-experts-panel" open><summary class="acts-experts-summary"><div class="panel-head"><div><div class="eyebrow">АКТЫ СЧЕТА</div><h3>Отчёт по экспертам</h3><p class="muted">Задачи проекта «Акты Счета» за выбранный месяц: загружаю из Bitrix…</p></div><button type="button" class="acts-panel-toggle" data-acts-experts-toggle="1" aria-expanded="true">Свернуть отчёт</button></div></summary></details>`;
  const refreshed=report.generated_at?new Intl.DateTimeFormat("ru-RU",{hour:"2-digit",minute:"2-digit",second:"2-digit"}).format(new Date(report.generated_at)):"";
  const taskList=(rows,empty)=>rows?.length?`<ol class="acts-pending-list">${rows.map(task=>`<li><a href="${attr(task.url)}" target="_blank" rel="noopener noreferrer">${esc(task.title)}</a><span>${esc(task.stage)}</span></li>`).join("")}</ol>`:`<p class=muted>${esc(empty)}</p>`;
  const crmMismatchList=(rows)=>rows?.length?`<ol class="acts-pending-list">${rows.map(task=>`<li><a href="${attr(task.url)}" target="_blank" rel="noopener noreferrer">${esc(task.title)}</a><span>Дата завершения сделки: ${esc(task.deal_close_date||'не указана')}</span></li>`).join("")}</ol>`:"";
  const cards=(report.experts||[]).map(expert=>`<article class="acts-expert-card"><div class="acts-expert-title">${esc(expert.name)}</div><div class="acts-expert-counts"><div><span>Всего актов</span><strong>${fmt(expert.total)}</strong></div><div><span>Есть скан</span><strong>${fmt(expert.scan)}</strong></div><div><span>Есть оригинал</span><strong>${fmt(expert.archive)}</strong></div><div><span>Нет подтверждения</span><strong>${fmt(expert.no_confirmation)}</strong></div></div><details><summary>Скан есть: ${fmt(expert.scan)}</summary>${taskList(expert.scan_tasks,"Сканов в этом месяце нет.")}</details><details><summary>В архиве: ${fmt(expert.archive)}</summary>${taskList(expert.archive_tasks,"Оригиналов в архиве пока нет.")}</details><details><summary>Нет подтверждения: ${fmt(expert.no_confirmation)}</summary>${taskList(expert.pending,"Все задачи подтверждены.")}</details>${expert.crm_mismatch_count?`<details class="acts-crm-mismatch"><summary>Исключено CRM-сверкой: ${fmt(expert.crm_mismatch_count)}</summary>${crmMismatchList(expert.crm_mismatch)}</details>`:''}</article>`).join("");
  const crmCheck=report.crm_check||{},crmNote=crmCheck.status==='online'?`CRM-сверка: ${fmt(crmCheck.found_count||0)} из ${fmt(crmCheck.linked_count||0)} связанных сделок найдены.`:crmCheck.status==='unavailable'?'CRM-сверка временно недоступна: задачи пока показаны по дате создания.':crmCheck.status==='not_linked'?'Связанных CRM-сделок в задачах не найдено.':'';
  return `<details class="acts-experts-panel" open><summary class="acts-experts-summary"><div class="panel-head"><div><div class="eyebrow">АКТЫ СЧЕТА</div><h3>Отчёт по экспертам</h3><p class="muted">Постановщик задачи · создание за ${esc(month)}. Задачи, где дата завершения связанной сделки относится к другому месяцу, исключены из итогов и показаны отдельно.</p></div><div class="acts-head-meta"><div class="acts-live-status"><span>●</span> Bitrix online${refreshed?` · ${esc(refreshed)}`:""}</div><button type="button" class="acts-panel-toggle" data-acts-experts-toggle="1" aria-expanded="true">Свернуть отчёт</button></div></div></summary><p class="acts-crm-note">${esc(crmNote)}</p><div class="acts-experts-grid">${cards}</div></details>`;
}
async function loadActsExperts(force=false){
  const month=actsExpertsMonth();
  if(!month||actsExpertsLoading||(!force&&actsExpertsData?.month===month))return;
  actsExpertsLoading=true;
  try{
    const response=await fetch(`/api/acts-experts?month=${encodeURIComponent(month)}${force?"&force=true":""}`);
    if(!response.ok)throw new Error("acts_experts_unavailable");
    const report=await response.json();
    if(report?.ok){actsExpertsData=report;if(["experts","department-experts"].includes(requestedView()))renderExperts();}
  }catch(error){console.warn("Acts experts report is unavailable",error)}finally{actsExpertsLoading=false}
}

function reasonTable(rows=state.production.dormant.reasons,metric="dormant_count"){return `<table><thead><tr><th>Причина зависания</th><th class="num">Кол-во</th></tr></thead><tbody>${rows.map(r=>`<tr><td>${esc(r.name)}</td><td class="num">${tdLink(r.count,"production",metric,"num",{reason:r.name})}</td></tr>`).join("")||"<tr><td colspan='2' class='empty'>Причины пока не заполнены</td></tr>"}</tbody></table>`}
function activeReasonTable(allRows=[],expectedRows=[]){const allByReason=new Map(allRows.map(r=>[r.name,r])),expectedByReason=new Map(expectedRows.map(r=>[r.name,r])),names=[...new Set([...allByReason.keys(),...expectedByReason.keys()])].sort((a,b)=>(Number(allByReason.get(b)?.count||0)+Number(expectedByReason.get(b)?.count||0))-(Number(allByReason.get(a)?.count||0)+Number(expectedByReason.get(a)?.count||0))||a.localeCompare(b,"ru"));return `<div class="scroll-x"><table><thead><tr><th>Причина зависания</th><th class="num">Все активные, шт</th><th class="num">Сумма</th><th class="num">%</th><th class="num">Ожидаемое закрытие в месяце, шт</th><th class="num">Сумма</th><th class="num">%</th></tr></thead><tbody>${names.map(name=>{const all=allByReason.get(name)||{},expected=expectedByReason.get(name)||{};return `<tr><td>${esc(name)}</td><td class="num">${tdLink(all.count||0,"production","active_stuck_with_reason_count","num",{reason:name})}</td><td class="num">${money(all.amount||0)}</td><td class="num">${pct(all.pct||0)}</td><td class="num">${tdLink(expected.count||0,"production","active_stuck_with_reason_expected_month_count","num",{reason:name})}</td><td class="num">${money(expected.amount||0)}</td><td class="num">${pct(expected.pct||0)}</td></tr>`}).join("")||"<tr><td colspan='7' class='empty'>Причины пока не заполнены</td></tr>"}</tbody></table></div>`}
function returnReasonTable(){return `<table><thead><tr><th>Причина возврата</th><th class="num">Кол-во</th><th class="num">Сумма</th><th class="num">%</th></tr></thead><tbody>${state.production.return_reasons.map(r=>`<tr><td>${esc(r.name)}</td><td class="num">${tdLink(r.count,"production","returns_count","num",{reason:r.name})}</td><td class="num">${money(r.amount)}</td><td class="num">${pct(r.pct)}</td></tr>`).join("")}</tbody></table>`}
function overdueTable(){return `<table><thead><tr><th>Просрочка</th><th class="num">Кол-во</th></tr></thead><tbody>${Object.entries(state.production.overdue.buckets).map(([k,v])=>`<tr><td>${esc(k)}</td><td class="num">${fmt(v)}</td></tr>`).join("")}</tbody></table>`}
function renderRisks(){
  const p=state.production.kpi;
  const crit=(state.dormant_config?.selected_stages||[]).join(", ")||"все активные стадии";
  $("#risks").innerHTML=`<div class="criteria-box"><strong>Критерий «Зависшие»:</strong> воронка ID 30 + выбранные стадии + <strong>предполагаемая дата закрытия попадает в выбранный период</strong>. Поэтому для сентября считаются только карточки с предполагаемой датой закрытия в сентябре. Стадии: ${esc(crit)}. Всего активных карточек в воронке независимо от даты: ${fmt(p.dormant_all_count||0)}.</div>
  <div class="kpi-grid">
    ${card("Зависшие периода",p.dormant_count,"production","dormant_count","num",{},money(p.dormant_amount))}
    ${card("Вернулось в производство",p.returned_to_production,"production","returned_to_production","num",{},money(p.returned_to_production_amount))}
    ${card("Просрочена ожидаемая дата",state.production.overdue.count,"production","overdue","num",{},money(state.production.overdue.amount))}
  </div>
  <div class="grid-2">${panel("Причины возврата",returnReasonTable())}${panel("Просрочка ожидаемой даты",overdueTable())}</div>`;
}

function contextOptions(scope,type){
  if(type==="overall")return [{value:"",label:"Общий план"}];
  if(scope==="production"&&type==="week")return rnpWeekRanges().map(week=>({value:String(week.index),label:`${week.index+1} неделя · ${week.label}`}));
  if(scope==="sales"&&type==="manager")return managers().map(x=>({value:x.name,label:x.name}));
  if(scope==="sales"&&type==="source_group")return state.sales.groups.map(x=>({value:x.name,label:x.name}));
  if(scope==="sales"&&type==="source")return state.sales.exact_sources.map(x=>({value:x.name,label:x.name}));
  if(scope==="sales"&&type==="product")return state.sales.product_categories.map(x=>({value:x.name,label:x.name}));
  if(scope==="production"&&type==="expert")return experts().map(x=>({value:x.name,label:x.name}));
  if(scope==="production"&&type==="product")return state.production.products.map(x=>({value:x.name,label:x.name}));
  if(scope==="production"&&type==="expert_product")return experts().flatMap(expert=>(expert.products||[]).map(product=>({value:expertProductPlanKey(expert.name,product.name),label:`${expert.name} · ${product.name}`})));
  return [];
}

function teamSettings(){
  const block=(role,title,names)=>`<div class="team-block"><div class="subhead">${esc(title)}</div><div class="team-tags">${names.map(n=>`<span class="team-tag">${esc(n)} <button data-team-remove="1" data-role="${role}" data-name="${attr(n)}">×</button></span>`).join('')}</div><div class="team-add"><select data-team-select="${role}">${teamUserOptions()}</select><button class="btn ghost" data-team-add="${role}">Добавить</button></div></div>`;
  return block('manager','Менеджеры',selectedManagers())+block('expert','Эксперты',selectedExperts())+`<div class="admin-inline"><input id="teamAdminKey" type="password" placeholder="ADMIN_KEY"></div>`;
}
function dormantSettings(){const all=state.dormant_config?.available_stages||[],sel=new Set(state.dormant_config?.selected_stages||[]);return `<div class="dormant-stage-list">${all.map(s=>`<label><input type="checkbox" data-dormant-stage="1" value="${attr(s)}" ${sel.has(s)?'checked':''}> ${esc(s)}</label>`).join('')}</div><div class="admin-inline"><input id="dormantAdminKey" type="password" placeholder="ADMIN_KEY"><button class="btn ghost" id="saveDormant">Сохранить критерий</button></div>`}

function trafficSettings(){
  const cfg=state.traffic_config||{},assign=cfg.assignments||{};
  const sources=cfg.available_sources||state.sales.available_sources||[];
  const groups=[
    ["","Авто · по типу клиента и источнику"],
    ["Холодные продажи","Холодные продажи"],
    ["Входящий трафик продажи","Входящий трафик"],
    ["Повторные продажи по базе","Повторные продажи"],
    ["Прочее","Прочее"],
    ["__ignore__","Не учитывать в этой разбивке"]
  ];
  return `<div class="traffic-config-note">По умолчанию работает согласованная автоматическая логика. Ручная привязка имеет приоритет только для выбранного источника.</div><div class="traffic-config-list">${sources.map(src=>`<div class="traffic-config-row"><span>${esc(src)}</span><select data-traffic-source="${attr(src)}">${groups.map(([v,l])=>`<option value="${attr(v)}" ${(assign[src]||'')===v?'selected':''}>${esc(l)}</option>`).join('')}</select><button class="mini-edit" data-clear-traffic="${attr(src)}">Сбросить</button></div>`).join('')}</div><div class="admin-inline"><input id="trafficAdminKey" type="password" placeholder="ADMIN_KEY"><button class="btn primary-light" id="saveTrafficConfig">Сохранить распределение</button></div>`;
}
async function saveTrafficConfig(){
  const assignments={};
  $$('[data-traffic-source]').forEach(sel=>{if(sel.value)assignments[sel.dataset.trafficSource]=sel.value});
  const r=await fetch('/api/traffic-config',{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({assignments,admin_key:$('#trafficAdminKey')?.value||''})});
  if(!r.ok){alert(await r.text());return}
  state=null;load();
}
async function addTeam(role){const sel=document.querySelector(`[data-team-select="${role}"]`);if(!sel)return;const r=await fetch('/api/team',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({role,name:sel.value,admin_key:$('#teamAdminKey')?.value||''})});if(!r.ok){alert(await r.text());return}state.team=(await r.json()).team;renderAll()}
async function removeTeam(role,name){const q=new URLSearchParams({role,name,admin_key:$('#teamAdminKey')?.value||''});const r=await fetch('/api/team?'+q,{method:'DELETE'});if(!r.ok){alert(await r.text());return}state.team=(await r.json()).team;renderAll()}
async function saveDormant(){const stages=$$('[data-dormant-stage]:checked').map(x=>x.value);const r=await fetch('/api/dormant-config',{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({stages,admin_key:$('#dormantAdminKey')?.value||''})});if(!r.ok){alert(await r.text());return}state=null;load()}
function renderDynamics(){const el=$('#dynamics');el.innerHTML='<div class="loading-state"><div class="loading-spinner"></div><div><div class="loading-title">Загружаю динамику</div><div class="muted">Считаю лёгкий агрегат за 6 месяцев без тяжёлой расшифровки</div></div></div>';fetch(`/api/dynamics?month=${encodeURIComponent($('#month').value)}&months=6`).then(r=>r.json()).then(j=>{const rows=j.rows||[];el.innerHTML=`<div class="toolbar"><div><div class="eyebrow">ДИНАМИКА</div><div class="muted">Ключевые показатели за 6 месяцев</div></div></div>${panel('Продажи',trendTable(rows,'sales'))}${panel('Производство',trendTable(rows,'production'))}`}).catch(e=>el.innerHTML=`<div class="error">${esc(e.message)}</div>`)}
function trendTable(rows,scope){const cols=scope==='sales'?[['sales_amount','Выручка','money'],['sales','Продажи','num'],['avg_check','Средний чек','money'],['deals','Сделки','num'],['leads','Лиды','num']]:[['prod_closed_amount','Сумма закрытых','money'],['prod_closed','Закрытые продукты','num'],['prod_new','Новые','num'],['prod_conversion','Конверсия','pct'],['avg_prod_days','Срок','days'],['returns','Возвраты','num']];return `<div class="scroll-x"><table><thead><tr><th>Месяц</th>${cols.map(c=>`<th class="num">${c[1]}</th>`).join('')}</tr></thead><tbody>${rows.map(r=>`<tr><td>${esc(r.month)}</td>${cols.map(c=>`<td class="num">${format(r[c[0]],c[2])}</td>`).join('')}</tr>`).join('')}</tbody></table></div>`}

function forecastCard(title,fact,plan,type="money"){
  const pace=state?.pace||{};const share=Number(pace.share||0);const total=Number(pace.business_days_total||0),elapsed=Number(pace.business_days_elapsed||0);const remaining=Math.max(0,total-elapsed);
  const projected=share>0?fact/share:fact;const need=Math.max(0,plan-fact);const perDay=remaining>0?need/remaining:0;
  const status=plan?(projected>=plan?"По текущему темпу план выполняется":"По текущему темпу есть риск недовыполнения"):"Заполни план, чтобы увидеть прогноз";
  return `<div class="forecast-card"><div class="kpi-label">${esc(title)}</div><div class="forecast-main"><span>Факт ${format(fact,type)}</span><span>Прогноз ${format(projected,type)}</span></div><div class="kpi-meta"><span>План ${plan?format(plan,type):"—"}</span><span>${plan?status:""}</span></div>${plan?`<div class="forecast-need">До плана: ${format(need,type)} · нужно в рабочий день: ${format(perDay,type)}</div>`:""}</div>`;
}
function qualityCard(title,value,metric,note="") {return `<div class="quality-card clickable" ${drillAttrs("production",metric)}><div class="kpi-label">${esc(title)}</div><div class="quality-value">${fmt(value)}</div><div class="muted">${esc(note)}</div></div>`}
function renderForecast(){
  if(!state)return;const el=$("#forecast");const s=state.sales.overall.total.metrics,p=state.production.kpi,financial=financialSalesMetrics(s);
  const currentMonth=new Date().toISOString().slice(0,7);const isCurrent=$("#month").value===currentMonth && $("#period").value==="month";
  el.innerHTML=`<div class="toolbar"><div><div class="eyebrow">ПРОГНОЗ МЕСЯЦА</div><div class="muted">Прогноз по темпу рабочих дней + контроль качества данных</div></div></div>
  ${!isCurrent?`<div class="criteria-box">Прогноз темпа корректнее смотреть для текущего месяца в режиме «Месяц». Сейчас показан ориентир на основе выбранного месяца.</div>`:""}
  <div class="grid-2">${forecastCard("Поступления",financial.incoming,getPlan("sales","sales_amount"),"money")}${forecastCard("Сумма закрытых",p.closed_amount,getPlan("production","closed_amount"),"money")}${forecastCard("Продажи",s.sales,getPlan("sales","sales"),"num")}${forecastCard("Закрытые продукты",p.closed_count,getPlan("production","closed_count"),"num")}</div>
  <div class="section-title">Контроль качества данных</div>
  <div class="kpi-grid">${qualityCard("Активные без предполагаемой даты",p.active_missing_expected_count||0,"active_missing_expected_count","не попадают в ёмкость")}${qualityCard("Зависшие без причины",p.dormant_without_reason_count||0,"dormant_count","из ожидаемой даты выбранного периода")}${qualityCard("Активные без продукта",p.active_missing_service_count||0,"active_missing_service_count")}${qualityCard("Активные без эксперта",p.active_missing_expert_count||0,"active_missing_expert_count")}</div>`;
}

function productionProductPlanTable(){
  const rows=(state.production?.products||[]).map(r=>{
    const pc=getPlan("production","closed_count","product",r.name);
    const pa=getPlan("production","closed_amount","product",r.name);
    return `<tr>
      <td>${esc(r.name)}</td>
      <td class="num">${fmt(r.closed_count)} шт</td>
      <td class="num">${pc?fmt(pc)+" шт":"—"}</td>
      <td class="num">${pc?pct(r.closed_count/pc*100):"—"}</td>
      <td class="num">${money(r.closed_amount)}</td>
      <td class="num">${pa?money(pa):"—"}</td>
      <td class="num">${pa?pct(r.closed_amount/pa*100):"—"}</td>
      <td class="num"><button class="mini-edit" data-edit-product-plan="${attr(r.name)}">Изменить план</button></td>
    </tr>`;
  }).join("");
  return `<div class="scroll-x"><table><thead><tr>
    <th>Продукт</th><th class="num">Факт, шт</th><th class="num">План, шт</th><th class="num">% шт</th>
    <th class="num">Факт, BYN</th><th class="num">План, BYN</th><th class="num">% BYN</th><th></th>
  </tr></thead><tbody>${rows}</tbody></table></div>`;
}

function renderPlanInline(){
  const statuses=state.metric_status||{};
  $("#plans").innerHTML=`<div class="toolbar"><div><div class="eyebrow">ПЛАНЫ И КАЧЕСТВО ДАННЫХ</div><div class="muted">Планы редактируются без Excel · хранилище: ${esc(state.storage_backend||"локальное")}</div></div><button class="btn primary" id="openPlans">Редактировать планы</button></div>
  <div class="grid-2">${panel("Планы продаж",planSummary("sales"))}${panel("Планы производства",planSummary("production"))}</div>
  ${panel("Планы производства по продуктам",productionProductPlanTable(),"план по каждому продукту: количество и сумма; кнопка открывает все плановые показатели выбранного продукта")}
  <div class="grid-2">${panel("Команда дашборда",teamSettings())}${panel("Критерий зависших",dormantSettings())}</div>
  ${panel("Распределение источников продаж",trafficSettings(),"можно вручную менять, что относится к холодным / входящим / повторным / прочему")}
  ${panel("Статус дополнительных метрик",`<div class="mapping-grid">${Object.entries(statuses).map(([k,v])=>`<div class="mapping-item"><div><div class="name">${esc(k)}</div><div class="note">${esc(v.note)}</div></div><span class="badge ${v.connected?"good":"warn"}">${v.connected?"подключено":"нужен mapping"}</span></div>`).join("")}</div>`,"ничего не выдумываем: неподключенные поля отмечены явно")}`;
  $("#openPlans")?.addEventListener("click",()=>openPlanDialog("sales"));
  $("#saveTrafficConfig")?.addEventListener("click",saveTrafficConfig);
  $$("[data-clear-traffic]").forEach(btn=>btn.addEventListener("click",()=>{const sel=document.querySelector(`[data-traffic-source="${CSS.escape(btn.dataset.clearTraffic)}"]`);if(sel)sel.value=""}));
}
function planSummary(scope){
  const defs=scope==="sales"?SALES_LABELS:PROD_LABELS;
  const key=`${scope}|overall|`,vals=state.plans?.[key]||{};
  return `<table><thead><tr><th>Показатель</th><th class="num">План</th></tr></thead><tbody>${Object.entries(defs).map(([k,[label,type]])=>`<tr><td>${esc(label)}</td><td class="num">${vals[k]?format(vals[k],type):"—"}</td></tr>`).join("")}</tbody></table>`;
}
function renderPlans(){renderPlanInline()}

function captureDashboardInteraction(){
  const view=$("#"+requestedView());
  const fields=view?[...view.querySelectorAll("input,textarea,select")].map((field,index)=>({index,value:field.value,checked:field.checked,selectionStart:field.selectionStart,selectionEnd:field.selectionEnd})):[];
  const chatInput=$("#dashboardChatQuestion");
  if(chatInput)dashboardChatDraft=chatInput.value;
  persistDashboardChatState();
  return {view:requestedView(),scrollY:window.scrollY,openDetails:view?[...view.querySelectorAll("details")].map((detail,index)=>detail.open?index:null).filter(index=>index!==null):[],fields,chatDraft:dashboardChatDraft,chatFocused:document.activeElement?.id==="dashboardChatQuestion"};
}
function restoreDashboardInteraction(saved){
  if(!saved)return;
  const view=$("#"+saved.view);
  saved.openDetails.forEach(index=>{const detail=view?.querySelectorAll("details")[index];if(detail)detail.open=true});
  saved.fields.forEach(item=>{const field=view?.querySelectorAll("input,textarea,select")[item.index];if(!field)return;if(field.type==="checkbox"||field.type==="radio")field.checked=item.checked;else field.value=item.value});
  const chat=$("#dashboardChatQuestion");if(chat&&!dashboardChatPending)chat.value=dashboardChatDraft=saved.chatDraft;
  requestAnimationFrame(()=>{if(saved.chatFocused&&chat){chat.focus();if(typeof chat.setSelectionRange==="function")chat.setSelectionRange(chat.value.length,chat.value.length)}window.scrollTo({top:saved.scrollY,behavior:"auto"})});
}
function renderAll(){
  const interaction=captureDashboardInteraction();
  if(!state?.ok){const e=`<div class="error">${esc(state?.error||"Ошибка загрузки")}</div>`;$$('.view').forEach(x=>x.innerHTML=e);renderDashboardChat();restoreDashboardInteraction(interaction);return}
  renderOverview();
  if(state.sales?.details_loaded&&state.sales?.details_key===snapshotKey())renderSales();else renderSalesPlaceholder("Откройте раздел, чтобы загрузить детальную разбивку продаж.");
  renderProduction();renderExperts();renderExpertsDepartment();renderRisks();renderForecast();renderPlans();renderCallsPlaceholder();renderMarketingPlaceholder();renderCrmAuditPlaceholder();renderHub();keyTasksData?renderKeyTasks():renderKeyTasksPlaceholder("Откройте раздел, чтобы загрузить задачи.");openView(requestedView(),false);
  renderDashboardChat();
  $("#liveDot").className="ok";const d=new Date(state.updated_at);$("#liveText").textContent=`BITRIX ONLINE · ${d.toLocaleTimeString("ru-RU",{hour:"2-digit",minute:"2-digit",second:"2-digit"})}`;
  restoreDashboardInteraction(interaction);
}

const VIEW_TITLES={
  hub:"Все разделы", overview:"Общий краткий свод", sales:"Продажи", "department-experts":"Эксперты",
  "sales-calls":"Звонки продажи", "expert-calls":"Звонки эксперты", marketing:"Маркетинг", "crm-audit":"Аудит CRM", "key-tasks":"Задачи",
  risks:"Риски", dynamics:"Динамика", forecast:"Прогноз", plans:"Планы и настройки"
};
const MARKETER_RESTRICTED_VIEWS=new Set(["sales-calls","expert-calls","crm-audit","key-tasks","plans","dynamics"]);
function renderMarketerRestriction(view){
  const target=$("#"+view);if(!target)return;
  target.innerHTML=`<div class="section-page"><div class="eyebrow">ОГРАНИЧЕННЫЙ ДОСТУП</div><h2>${esc(VIEW_TITLES[view]||"Раздел")}</h2><p class="section-page-lead">Этот раздел содержит операционные данные и недоступен для роли «Маркетолог».</p><div class="integration-state">Фактические показатели доступны в разделе «Маркетинг».</div></div>`;
}
function requestedView(){const value=location.hash.slice(1);return VIEW_TITLES[value]?value:"hub"}
function openView(view,updateHistory=true){
  if(!$("#"+view))return;
  $$(".view").forEach(item=>item.classList.toggle("active",item.id===view));
  const isHub=view==="hub";
  $("#sectionNav").classList.toggle("hidden",isHub);
  $("#sectionNavTitle").textContent=VIEW_TITLES[view]||"";
  if(marketerAccess()&&MARKETER_RESTRICTED_VIEWS.has(view)){
    renderMarketerRestriction(view);
    if(updateHistory){history.pushState(null,"",`#${view}`);window.scrollTo({top:0,behavior:"auto"});}
    return;
  }
  if(view==="dynamics")renderDynamics();
  if(view==="forecast")renderForecast();
  if(view==="sales")loadSalesSection();
  if(view==="sales-calls")loadJarvisExperience();
  if(view==="marketing")loadOperationsSection("marketing");
  if(view==="crm-audit")loadOperationsSection("crm-audit");
  if(view==="key-tasks")loadKeyTasks();
  if(updateHistory){history.pushState(null,"",view==="hub"?location.pathname:`#${view}`);window.scrollTo({top:0,behavior:window.matchMedia("(prefers-reduced-motion: reduce)").matches?"auto":"smooth"});}
}

function loadingView(month){
  const label=periodDisplayLabel()||month;
  return `<div class="loading-state"><div class="loading-spinner"></div><div><div class="loading-title">Синхронизирую ${esc(label)}</div><div class="muted">Интерфейс уже доступен. Первый расчёт Bitrix идёт в фоне; дальше данные будут открываться из кеша сразу.</div></div></div>`;
}

function monthKey(offset=0){
  const d=new Date();
  d.setDate(1);
  d.setMonth(d.getMonth()+offset);
  return `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,"0")}`;
}
function periodDisplayLabel(){
  const active=$("[data-period-preset].active");
  return active?.textContent?.trim()||$("#monthPicker")?.selectedOptions?.[0]?.textContent?.trim()||"Выбранный месяц";
}
function updatePeriodPresets(active){
  $$('[data-period-preset]').forEach(button=>{
    const selected=button.dataset.periodPreset===active;
    button.classList.toggle('active',selected);
    button.setAttribute('aria-pressed',String(selected));
  });
}
function selectPeriodPreset(preset){
  const isCustom=preset==='custom';
  if(preset==='current')$("#month").value=monthKey();
  if(preset==='previous')$("#month").value=monthKey(-1);
  if(preset!=='custom'&&$("#monthPicker"))$("#monthPicker").value=$("#month").value;
  $("#period").value=isCustom?'custom':'month';
  $("#customPeriod").classList.toggle("hidden",!isCustom);
  if(isCustom){
    const month=$("#month").value;
    if(!$("#customStart").value)$("#customStart").value=`${month}-01`;
    if(!$("#customEnd").value){
      const [year,monthNumber]=month.split('-').map(Number);
      $("#customEnd").value=new Date(year,monthNumber,0).toISOString().slice(0,10);
    }
  }
  updatePeriodPresets(preset);
  state=null;
  load();
}
function customQueryParams(){
  if($("#period").value!=="custom")return "";
  const a=$("#customStart").value,b=$("#customEnd").value;
  return `&custom_start=${encodeURIComponent(a)}&custom_end=${encodeURIComponent(b)}`;
}
function snapshotKey(month=$("#month")?.value||"",period=$("#period")?.value||"month"){
  const custom=period==="custom"?`${$("#customStart")?.value||""}:${$("#customEnd")?.value||""}`:"";
  return `${month}|${period}|${custom}`;
}
function preserveSalesDetails(previous,nextSales,key){
  const next={...(nextSales||{})};
  if(previous?.details_loaded&&previous.details_key===key){
    const previousManagers=new Map((previous.managers||[]).map(manager=>[manager.name,manager]));
    const managers=Array.isArray(next.managers)
      ? next.managers.map(manager=>({...previousManagers.get(manager.name),...manager}))
      : previous.managers;
    return {...previous,...next,managers,details_loaded:true,details_key:key};
  }
  return next;
}
function salesDetailsNeedRefresh(sales,snapshotUpdatedAt){
  return Boolean(sales?.details_loaded&&snapshotUpdatedAt&&sales.details_revision!==snapshotUpdatedAt);
}
function renderSalesPlaceholder(message="Загружаю детализацию продаж…",retry=false){
  const target=$("#sales");if(!target)return;
  target.innerHTML=`<div class="section-page sales-loading"><div class="eyebrow">ОТДЕЛ ПРОДАЖ</div><h2>Продажи</h2><p class="section-page-lead">${esc(message)}</p><div class="integration-state">Основные показатели уже доступны на главном экране. Загружаю расшифровку менеджеров, источников и сделок только для этого раздела.</div>${retry?'<button type="button" class="btn primary" data-retry-sales-section="1">Повторить</button>':''}</div>`;
}
async function loadSalesSection({force=false,silent=false}={}){
  if(!state?.ok)return;
  if(marketerAccess()){
    renderSalesPlaceholder("Реальные показатели и детализация продаж скрыты для роли «Маркетолог». В разделе «Маркетинг» доступны фактические данные.");
    return;
  }
  const key=snapshotKey();
  const needsRefresh=force||state.sales?.details_stale;
  if(state.sales?.details_loaded&&state.sales?.details_key===key&&!needsRefresh){renderSales();return}
  if(salesDetailsRequest===key)return;
  if(salesDetailsRetry){clearTimeout(salesDetailsRetry);salesDetailsRetry=null}
  salesDetailsRequest=key;
  if(!silent)renderSalesPlaceholder();
  try{
    const response=await fetch(`/api/sales-section?month=${encodeURIComponent($("#month").value)}&period=${encodeURIComponent($("#period").value)}${customQueryParams()}`,{cache:"no-store"});
    const payload=await response.json();
    if(key!==snapshotKey()||requestedView()!=="sales")return;
    if(response.status===202||payload.loading){
      renderSalesPlaceholder("Детализация готовится в фоне. Повторяю запрос через несколько секунд…");
      salesDetailsRetry=setTimeout(()=>{salesDetailsRetry=null;loadSalesSection()},2500);
      return;
    }
    if(!response.ok||!payload.ok)throw new Error(payload.detail||payload.error||"Не удалось загрузить детализацию продаж");
    state.sales={...(state.sales||{}),...(payload.sales||{}),details_loaded:true,details_key:key,details_stale:false,details_revision:state.updated_at||""};
    // Detailed sales are refreshed in the background.  Do not replace an
    // opened hierarchy while a manager is reading it: the newer data is kept
    // in state and appears on the next deliberate render.
    if(silent&&document.querySelector("#sales details[open]"))return;
    renderSales();
  }catch(error){
    if(key===snapshotKey()&&requestedView()==="sales")renderSalesPlaceholder(error.message||"Детализация продаж временно недоступна",true);
  }finally{if(salesDetailsRequest===key)salesDetailsRequest=null}
}
function scheduleBackgroundLoad(){
  if(backgroundRefreshTimer)return;
  const delay=Math.max(0,15000-(Date.now()-lastBackgroundRefreshAt));
  backgroundRefreshTimer=setTimeout(()=>{backgroundRefreshTimer=null;load({background:true})},delay);
}
async function load({background=false}={}){
  const month=$("#month").value,period=$("#period").value;
  if(loadTimer){clearTimeout(loadTimer);loadTimer=null}
  if(loadController)loadController.abort();
  loadController=new AbortController();

  const requestKey=snapshotKey(month,period);
  const sameState=state&&activeSnapshotKey===requestKey;
  if(!sameState){
    const cached=readBrowserSnapshot(month,period);
    if(cached){
      state=cached.snapshot;
      activeSnapshotKey=requestKey;
      renderAll();
      $("#liveDot").className="";
      const ageMin=Math.max(0,Math.round((Date.now()-cached.saved_at)/60000));
      $("#liveText").textContent=`ПОКАЗАН КЕШ БРАУЗЕРА${ageMin?` · ${ageMin} мин назад`:""} · обновляю Bitrix`;
    }else{
      $("#hub").innerHTML=loadingView(month);
      $("#liveDot").className="";
      $("#liveText").textContent="СИНХРОНИЗАЦИЯ В ФОНЕ";
    }
  }

  try{
    const r=await fetch(`/api/snapshot?month=${encodeURIComponent(month)}&period=${encodeURIComponent(period)}${customQueryParams()}&compact=1`,{cache:"no-store",signal:loadController.signal});
    if(r.status===401){location.href="/login";return}
    const j=await r.json();
    const offlineSnapshot=r.headers.get("X-Mavis-Cache")==="offline";

    if(r.status===202 || j.loading){
      $("#liveDot").className="";
      $("#liveText").textContent=state&&state.month_key===month
        ?"ПОКАЗАНЫ ПОСЛЕДНИЕ ДАННЫЕ · Bitrix обновляется в фоне"
        :"BITRIX · ПЕРВИЧНАЯ СИНХРОНИЗАЦИЯ";
      loadTimer=setTimeout(()=>load({background:true}),2500);
      return;
    }
    if(!r.ok)throw new Error(j.detail||j.error||JSON.stringify(j));

    const sales=preserveSalesDetails(state?.sales,j.sales,requestKey);
    const details_stale=salesDetailsNeedRefresh(sales,j.updated_at);
    state={...j,sales:{...sales,details_stale},plans:reconcilePendingPlans(j.plans)};
    activeSnapshotKey=requestKey;
    saveBrowserSnapshot(state);
    if(background)lastBackgroundRefreshAt=Date.now();
    renderAll();
    if(details_stale&&requestedView()==="sales")void loadSalesSection({force:true,silent:true});
    if(offlineSnapshot){
      $("#liveDot").className="bad";
      $("#liveText").textContent="ПОКАЗАНА ПОСЛЕДНЯЯ ВЕРСИЯ · НЕТ СЕТИ";
    }else if(j.syncing){
      $("#liveText").textContent=j.cached_snapshot
        ?"ПОКАЗАН ПОСЛЕДНИЙ SNAPSHOT · обновляю Bitrix в фоне"
        :"BITRIX ONLINE · обновляю в фоне";
    }
  }catch(e){
    if(e.name==='AbortError')return;
    $("#liveDot").className="bad";
    $("#liveText").textContent=state?"ПОКАЗАН КЕШ · Bitrix временно недоступен":"НЕТ СВЯЗИ";
    if(!state)$("#hub").innerHTML=`<div class="error">${esc(e.message)}</div>`;
  }
}

function sleep(ms){return new Promise(resolve=>setTimeout(resolve,ms))}
async function apiJson(url,opts={}){
  const r=await fetch(url,{cache:"no-store",...opts});
  if(r.status===401){location.href="/login";throw new Error("AUTH_REQUIRED")}
  const ct=(r.headers.get("content-type")||"").toLowerCase();
  if(!ct.includes("application/json")){
    const raw=await r.text();
    const e=new Error(
      r.status>=500
        ?"Сервис сейчас обновляется. Повторяю запрос автоматически…"
        :"Расшифровка временно недоступна. Повтори через несколько секунд."
    );
    e.retryable=r.status>=500 || raw.trim().startsWith("<!DOCTYPE") || raw.trim().startsWith("<html");
    e.status=r.status;
    throw e;
  }
  return {response:r,data:await r.json()};
}
async function fetchDrillJson(params,maxAttempts=5){
  let lastError=null;
  for(let attempt=0;attempt<maxAttempts;attempt++){
    try{
      const out=await apiJson('/api/drilldown?'+params.toString());
      if(out.response.status===202 || out.data?.loading){
        lastError=new Error(out.data?.message||"Расшифровка готовится");
        lastError.retryable=true;
      }else{
        return out;
      }
    }catch(e){
      if(e.message==="AUTH_REQUIRED")throw e;
      lastError=e;
      if(!e.retryable)throw e;
    }
    if(attempt<maxAttempts-1)await sleep(1200+attempt*500);
  }
  throw lastError||new Error("Расшифровка пока не готова");
}

function detailHtml(r){
  const title=r.title||r.deal_title||r.service||r.id;const amount=r.amount!==undefined?money(r.amount):"";
  const meta=[r.kind==='lead'?r.status:r.stage,r.manager||r.expert,r.source,r.service,r.created?new Date(r.created).toLocaleDateString('ru-RU'):null,r.close?`закрыто ${new Date(r.close).toLocaleDateString('ru-RU')}`:null,r.prod_days!==undefined&&r.prod_days!==null?`${r.prod_days} раб.дн.`:null,r.norm_days?`норма ${r.norm_days}`:null,r.return_reason].filter(Boolean);
  const products=(r.products||[]).map(p=>`${p.name} × ${fmt(p.quantity)} · ${money(p.amount)}`).join("; ");
  return `<div class="detail-card" data-search="${attr([title,...meta,products].join(' ').toLowerCase())}"><div class="detail-main"><div><div class="detail-title">${r.url?`<a href="${attr(r.url)}" target="_blank" rel="noreferrer">${esc(title)}</a>`:esc(title)}</div><div class="detail-meta">${meta.map(x=>`<span>${esc(x)}</span>`).join("")}</div>${products?`<div class="detail-products">${esc(products)}</div>`:""}</div><div class="detail-money">${amount}</div></div></div>`;
}
async function openDrill(el){
  const d=el.dataset;drillOffset=0;drillMeta={...d};
  $("#drillSearch").value="";
  const params=new URLSearchParams({scope:d.scope,metric:d.metric,month:$("#month").value,period:$("#period").value,offset:'0',limit:'500'});
  if($("#period").value==="custom"){params.set("custom_start",$("#customStart").value);params.set("custom_end",$("#customEnd").value);}
  ["periodType","manager","group","source","product","expert","stage","reason","week","day"].forEach(k=>{if(d[k]!==undefined)params.set(k.replace(/[A-Z]/g,m=>'_'+m.toLowerCase()),d[k])});
  const label=(d.scope==="sales"?(SALES_LABELS[d.metric]?.[0]||SALES_DRILL_LABELS[d.metric]):PROD_LABELS[d.metric]?.[0])||d.metric;
  $("#drillTitle").textContent=label;$("#drillSubtitle").textContent="Расшифровка из уже загруженного snapshot";$("#drillBody").innerHTML='<div class="loading">Загрузка…</div>';$("#drillDialog").showModal();
  try{
    $("#drillBody").innerHTML='<div class="loading">Готовлю расшифровку…</div>';
    const {response:r,data:j}=await fetchDrillJson(params,5);
    if(!r.ok)throw new Error(j.detail||JSON.stringify(j));
    drillRows=j.rows||[];drillOffset=drillRows.length;drillTotal=Number(j.count||drillRows.length);
    $("#drillCount").textContent=`${drillTotal} записей · показано ${drillRows.length}`;
    $("#drillSubtitle").textContent=[d.manager,d.expert,d.group,d.source,d.product,d.stage,d.reason,d.week!==undefined?`неделя ${Number(d.week)+1}`:null].filter(Boolean).join(' · ');
    renderDrillRows()
  }catch(e){
    if(e.message==="AUTH_REQUIRED")return;
    $("#drillBody").innerHTML=`<div class="error">Расшифровка пока не загрузилась. ${esc(e.message)}</div><div class="drill-retry-wrap"><button class="btn primary-light" id="retryDrill">Повторить</button></div>`;
    $("#retryDrill")?.addEventListener("click",()=>openDrill(el));
  }
}
function groupRows(rows,keyFn){const m=new Map();rows.forEach(r=>{const k=keyFn(r)||"Не указано";if(!m.has(k))m.set(k,[]);m.get(k).push(r)});return [...m.entries()].sort((a,b)=>b[1].reduce((s,x)=>s+Number(x.amount||0),0)-a[1].reduce((s,x)=>s+Number(x.amount||0),0))}
function drillGroupKeys(r){
  if(drillMeta?.scope==="finance"){
    return [r.group||"Не распределено",r.manager||r.source||"Без ответственного"];
  }
  if(drillMeta?.scope==="production"){
    const first=drillMeta.expert? (r.service||r.category||"Прочее") : (r.expert||"Эксперт не указан");
    const second=drillMeta.product? (r.stage||"Стадия не указана") : (r.service||r.stage||"Прочее");
    return [first,second];
  }
  const first=drillMeta?.manager? (r.group||r.source||"Прочее") : (r.manager||"Менеджер не указан");
  const second=drillMeta?.source? (r.stage||"Стадия не указана") : (r.source||r.group||"Прочее");
  return [first,second];
}
function renderDrillRows(){
  const q=normSearch($("#drillSearch").value);const rows=q?drillRows.filter(r=>JSON.stringify(r).toLowerCase().includes(q)):drillRows;
  $("#drillCount").textContent=q?`${drillTotal} всего · найдено ${rows.length}`:`${drillTotal} записей · показано ${drillRows.length}`;
  if(!rows.length){$("#drillBody").innerHTML='<div class="empty">Нет записей</div>';return}
  const firstGroups=groupRows(rows,r=>drillGroupKeys(r)[0]);
  const maxCount=Math.max(1,...firstGroups.map(x=>x[1].length));
  const html=firstGroups.map(([g,items])=>{
    const total=items.reduce((a,r)=>a+Number(r.amount||0),0);const secondGroups=groupRows(items,r=>drillGroupKeys(r)[1]);
    return `<details class="drill-group" open><summary><div class="drill-summary-main"><span>${esc(g)}</span><div class="group-bar"><i style="width:${Math.max(5,items.length/maxCount*100)}%"></i></div></div><span>${fmt(items.length)} шт · ${money(total)}</span></summary><div class="drill-group-body">${secondGroups.map(([sg,sub])=>`<details class="drill-subgroup"><summary><span>${esc(sg)}</span><span>${fmt(sub.length)} шт · ${money(sub.reduce((a,r)=>a+Number(r.amount||0),0))}</span></summary><div>${sub.map(detailHtml).join('')}</div></details>`).join('')}</div></details>`;
  }).join('');
  const more=(!q&&drillOffset<drillTotal)?`<button class="btn primary-light load-more" id="drillMore">Показать ещё <span>${fmt(Math.min(100,drillTotal-drillOffset))}</span></button>`:'';
  $("#drillBody").innerHTML=html+more;
}

function normSearch(s){return String(s||'').trim().toLowerCase()}

async function loadMoreDrill(){
  if(!drillMeta||drillOffset>=drillTotal)return;
  const d=drillMeta;const params=new URLSearchParams({scope:d.scope,metric:d.metric,month:$("#month").value,period:$("#period").value,offset:String(drillOffset),limit:'500'});
  if($("#period").value==="custom"){params.set("custom_start",$("#customStart").value);params.set("custom_end",$("#customEnd").value)}
  ["periodType","manager","group","source","product","expert","stage","reason","week","day"].forEach(k=>{if(d[k]!==undefined)params.set(k.replace(/[A-Z]/g,m=>'_'+m.toLowerCase()),d[k])});
  const btn=$("#drillMore");if(btn){btn.disabled=true;btn.textContent='Загружаю…'}
  try{
    const {response:r,data:j}=await fetchDrillJson(params,4);
    if(!r.ok)throw new Error(j.detail||JSON.stringify(j));
    const add=j.rows||[];
    drillRows=drillRows.concat(add);drillOffset+=add.length;drillTotal=Number(j.count||drillTotal);renderDrillRows()
  }catch(e){
    if(btn){btn.disabled=false;btn.textContent='Повторить загрузку'}
  }
}
function renderNpsHistory(){
  const row=state?.manual_nps?.[npsTarget]||null;
  const entries=row?.entries||[];
  $("#npsTitle").textContent=npsTarget?`NPS · ${npsTarget}`:'NPS вручную';
  const avg=row?fmt(row.value):'—',count=row?Number(row.count||0):0;
  $("#npsHistory").innerHTML=`<div class="nps-summary"><strong>Среднее: ${avg}</strong><span>${fmt(count)} оценок</span></div>${entries.length?entries.map(x=>`<div class="nps-history-row"><div><strong>${fmt(x.value)}</strong>${x.note?`<span>${esc(x.note)}</span>`:''}</div><button class="mini-edit danger" data-delete-nps="${attr(x.id)}">удалить</button></div>`).join(''):'<div class="muted">Оценок пока нет</div>'}`;
}
function openNpsDialog(expert=""){
  const list=selectedExperts();$("#npsExpert").innerHTML=list.map(n=>`<option value="${attr(n)}">${esc(n)}</option>`).join('');
  if(expert&&list.includes(expert))$("#npsExpert").value=expert;
  npsTarget=$("#npsExpert").value||expert||list[0]||"";
  $("#npsValue").value='';$("#npsNote").value='';renderNpsHistory();$("#npsDialog").showModal();
}
function openNpsDetails(expert=""){
  const period=state?.automatic_nps_month||{};
  const details=period?.experts?.[expert]||{};
  const tasks=[...(details.tasks||[])].sort((a,b)=>String(b.created_date||'').localeCompare(String(a.created_date||'')));
  $("#npsDetailsTitle").textContent=`NPS · ${expert}`;
  $("#npsDetailsSubtitle").textContent=`Общий NPS за ${automaticNpsMonthLabel(period)} · ${fmt(details.count||0)} оценок · по дате создания завершённых задач`;
  $("#npsDetailsBody").innerHTML=tasks.map(task=>{
    const deal=task.deal||{},company=deal.client||(task.deal_id?`Сделка #${task.deal_id}`:'Компания не указана');
    const comment=String(task.comment||'').trim();
    return `<article class="nps-task-detail"><header><strong>Оценка ${fmt(task.score)}</strong><time>Создано ${esc(task.created_date||'—')}</time></header><div class="nps-task-company">${esc(company)}${deal.stage?` · ${esc(deal.stage)}`:''}</div><div class="nps-task-title">${esc(task.title||'Задача NPS')}</div><div class="nps-task-comment"><strong>Комментарий:</strong> ${comment?esc(comment).replace(/\n/g,'<br>'):'не указан в задаче NPS'}</div><div class="nps-task-links">${task.deal_url?`<a href="${attr(task.deal_url)}" target="_blank" rel="noopener noreferrer">Открыть сделку</a>`:''}${task.task_url?`<a href="${attr(task.task_url)}" target="_blank" rel="noopener noreferrer">Открыть задачу NPS</a>`:''}</div></article>`;
  }).join('')||'<div class="empty">Оценок за этот месяц пока нет.</div>';
  $("#npsDetailsDialog").showModal();
}
function openTeamDialog(role="expert", formerOnly=false){
  teamTargetRole=role;$("#teamRole").value=role;
  const users=availableTeamUsers().filter(user=>!formerOnly||!user.active);
  const active=users.filter(user=>user.active),former=users.filter(user=>!user.active);
  $("#teamUser").innerHTML=`${active.length?`<optgroup label="Работают сейчас">${active.map(user=>`<option value="${attr(user.name)}">${esc(user.name)}</option>`).join('')}</optgroup>`:''}${former.length?`<optgroup label="Уволенные сотрудники">${former.map(user=>`<option value="${attr(user.name)}">${esc(user.name)} · уволен(а)</option>`).join('')}</optgroup>`:''}`;
  $("#teamDialogTitle").textContent=formerOnly?'Добавить уволенного сотрудника из Bitrix':role==='expert'?'Добавить эксперта из Bitrix':'Добавить менеджера из Bitrix';
  $("#teamDialogHint").textContent=formerOnly?'Выберите уволенного сотрудника: его исторические показатели останутся в отчётах.':'В списке есть работающие и уволенные сотрудники Bitrix. После добавления показатели сотрудника начнут считаться в дашборде.';
  $("#teamDialog").showModal();
}
function openPlanDialog(scope="sales",contextType="overall",contextKey=""){
  fillPlanMonthOptions();
  $("#planScope").value=scope;
  updatePlanContextTypes();
  const typeSel=$("#planContextType");
  const wanted=[...typeSel.options].find(o=>o.value===contextType && !o.disabled);
  typeSel.value=wanted?contextType:"overall";
  const opts=contextOptions(scope,typeSel.value);
  $("#planContextKey").innerHTML=opts.map(o=>`<option value="${attr(o.value)}">${esc(o.label)}</option>`).join('');
  if(opts.some(o=>o.value===contextKey))$("#planContextKey").value=contextKey;
  loadPlanDialogMonth();
  $("#planDialog").showModal();
}
function planMonthLabel(value){const [year,month]=String(value||"").split("-").map(Number);return Number.isInteger(year)&&Number.isInteger(month)?new Intl.DateTimeFormat("ru-RU",{month:"long",year:"numeric"}).format(new Date(year,month-1,1)):value}
function isoMonth(date){return `${date.getFullYear()}-${String(date.getMonth()+1).padStart(2,"0")}`}
function fillPlanMonthOptions(){
  const dashboardMonth=state?.month_key||$("#month").value;
  const now=new Date();now.setDate(1);now.setHours(0,0,0,0);
  const months=[dashboardMonth];
  for(let offset=0;offset<=12;offset++){
    const candidate=new Date(now);candidate.setMonth(candidate.getMonth()+offset);
    const value=isoMonth(candidate);
    if(!months.includes(value))months.push(value);
  }
  $("#planMonth").innerHTML=months.map(value=>`<option value="${attr(value)}">${esc(planMonthLabel(value))}</option>`).join("");
  $("#planMonth").value=dashboardMonth&&months.includes(dashboardMonth)?dashboardMonth:isoMonth(now);
}
async function loadPlanDialogMonth(){
  const month=$("#planMonth").value;
  const requestId=++planDialogRequestId;
  if(month===(state?.month_key||"")){
    planDialogPlans=state?.plans||{};
    buildPlanForm();
    return;
  }
  $("#planForm").innerHTML='<div class="loading">Загружаю планы выбранного месяца…</div>';
  try{
    const response=await fetch(`/api/plans?month=${encodeURIComponent(month)}`);
    const payload=await response.json();
    if(!response.ok)throw new Error(payload.detail||"Не удалось загрузить планы");
    if(requestId!==planDialogRequestId)return;
    planDialogPlans=payload.dict||{};
    buildPlanForm();
  }catch(error){
    if(requestId===planDialogRequestId)$("#planForm").innerHTML=`<div class="error">${esc(error.message)}</div>`;
  }
}
function updatePlanContextTypes(){const scope=$("#planScope").value;const sel=$("#planContextType");[...sel.options].forEach(o=>o.disabled=(scope==="sales"&&["week","expert","expert_product"].includes(o.value))||(scope==="production"&&["manager","source_group","source"].includes(o.value)));if(sel.selectedOptions[0]?.disabled)sel.value="overall"}
function updatePlanKey(){const opts=contextOptions($("#planScope").value,$("#planContextType").value);$("#planContextKey").innerHTML=opts.map(o=>`<option value="${attr(o.value)}">${esc(o.label)}</option>`).join('');buildPlanForm()}
function buildPlanForm(){if(!state)return;const scope=$("#planScope").value,type=$("#planContextType").value,key=$("#planContextKey").value||"",productionResultPlan={closed_count:["План закрытых продуктов, шт","num"],closed_amount:["План суммы закрытых, BYN","money"]},defs=scope==="production"&&["week","expert","product"].includes(type)?productionResultPlan:scope==="production"&&type==="expert_product"?{closed_count:["План продуктов, шт","num"]}:scope==="sales"?SALES_LABELS:PROD_LABELS,vals=planDialogPlans?.[`${scope}|${type}|${key}`]||{};$("#planForm").innerHTML=Object.entries(defs).map(([metric,[label]])=>`<div class="plan-field"><label>${esc(label)}</label><input type="number" min="0" step="0.01" data-plan-metric="${attr(metric)}" value="${vals[metric]??''}"></div>`).join('')}
async function savePlan(){const month=$("#planMonth").value,scope=$("#planScope").value,context_type=$("#planContextType").value,context_key=$("#planContextKey").value||"",values={},context=`${scope}|${context_type}|${context_key}`,button=$("#savePlan");$$('[data-plan-metric]').forEach(i=>values[i.dataset.planMetric]=Number(i.value||0));button.disabled=true;try{const r=await fetch('/api/plans',{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({month,scope,context_type,context_key,values,admin_key:$("#adminKey").value})});if(!r.ok){alert(await r.text());return}const j=await r.json();planDialogPlans=j.dict||{};if(month===state?.month_key){rememberPlanWrite(context,values);state.plans=j.dict;renderAll()}$("#planDialog").close()}finally{button.disabled=false}}

function fillMonths(){
  const sel=$("#month");
  const now=new Date();
  const monthNames=["январь","февраль","март","апрель","май","июнь","июль","август","сентябрь","октябрь","ноябрь","декабрь"];
  const opts=[];
  // История с января 2025 + два будущих месяца для планирования.
  const start=new Date(2025,0,1);
  const finish=new Date(now.getFullYear(),now.getMonth()+2,1);
  for(let d=new Date(start);d<=finish;d.setMonth(d.getMonth()+1)){
    const value=`${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}`;
    opts.push(`<option value="${value}">${monthNames[d.getMonth()]} ${d.getFullYear()}</option>`);
  }
  sel.innerHTML=opts.reverse().join('');
  const cur=`${now.getFullYear()}-${String(now.getMonth()+1).padStart(2,'0')}`;
  sel.value=cur;
  const monthPicker=$("#monthPicker");
  if(monthPicker){
    const year=now.getFullYear();
    monthPicker.innerHTML=monthNames.map((name,index)=>{const value=`${year}-${String(index+1).padStart(2,'0')}`;return `<option value="${value}">${name} ${year}</option>`}).join('');
    monthPicker.value=cur;
  }
}

function isIos(){return /iphone|ipad|ipod/i.test(navigator.userAgent)}
function isStandalone(){return window.matchMedia("(display-mode: standalone)").matches||window.navigator.standalone===true}
function setInstallHint({title,text,actionLabel,action,iosSteps=false}={}){
  const hint=$("#installHint");if(!hint)return;
  $("#installHintTitle").textContent=title||"Установите дашборд";
  $("#installHintText").textContent=text||"";
  $("#installIosSteps").classList.toggle("hidden",!iosSteps);
  const button=$("#installAction");button.textContent=actionLabel||"Установить";
  button.onclick=action||null;
  button.classList.toggle("hidden",!action);
  hint.classList.remove("hidden");
}
function initializeInstallExperience(){
  const hint=$("#installHint");
  if(!hint||isStandalone())return;
  $("#dismissInstallHint").addEventListener("click",()=>{try{localStorage.setItem(INSTALL_HINT_DISMISSED_KEY,"1")}catch(e){}hint.classList.add("hidden")});
  window.addEventListener("beforeinstallprompt",event=>{
    event.preventDefault();deferredInstallPrompt=event;
    let dismissed=false;try{dismissed=localStorage.getItem(INSTALL_HINT_DISMISSED_KEY)==="1"}catch(e){}
    if(!dismissed)setInstallHint({title:"Установите дашборд",text:"Откроется как отдельное приложение.",actionLabel:"Установить",action:async()=>{
      if(!deferredInstallPrompt)return;
      deferredInstallPrompt.prompt();await deferredInstallPrompt.userChoice;deferredInstallPrompt=null;hint.classList.add("hidden");
    }});
  });
  let dismissed=false;try{dismissed=localStorage.getItem(INSTALL_HINT_DISMISSED_KEY)==="1"}catch(e){}
  if(isIos()&&!dismissed)setInstallHint({title:"Добавьте дашборд на экран «Домой»",text:"Это займёт два нажатия — после этого он будет открываться как приложение.",actionLabel:"",action:null,iosSteps:true});
}
function registerServiceWorker(){
  if(!("serviceWorker" in navigator)||!window.isSecureContext)return;
  window.addEventListener("load",()=>navigator.serviceWorker.register("/service-worker.js").catch(()=>{}),{once:true});
}

function init(){
  fillMonths();
  initializeInstallExperience();
  registerServiceWorker();
  $$('[data-period-preset]').forEach(button=>button.addEventListener('click',()=>selectPeriodPreset(button.dataset.periodPreset)));
  $("#monthPicker")?.addEventListener('change',()=>{const selected=$("#monthPicker").value;if(!selected)return;$("#month").value=selected;$("#period").value='month';$("#customPeriod").classList.add('hidden');updatePeriodPresets('selected');state=null;load()});
  $("#customStart").addEventListener('change',()=>{if($("#period").value==="custom"){state=null;load()}});$("#customEnd").addEventListener('change',()=>{if($("#period").value==="custom"){state=null;load()}});$("#refreshBtn").addEventListener('click',load);$("#tvBtn").addEventListener('click',()=>document.body.classList.toggle('tv-mode'));
  window.addEventListener("hashchange",()=>openView(requestedView(),false));
  document.body.addEventListener('click',e=>{
    const view=e.target.closest('[data-open-view],[data-view]');if(view){openView(view.dataset.openView||view.dataset.view);return}
    const chatToggle=e.target.closest('[data-dashboard-chat-toggle]');if(chatToggle){setDashboardChatOpen(!dashboardChatOpen,{focus:!dashboardChatOpen});return}
    if(e.target.closest('[data-dashboard-chat-close]')){setDashboardChatOpen(false);return}
    if(e.target.closest('[data-task-meeting-open]')){if(!currentTaskProfile()){openTaskProfileDialog();return}openTaskMeetingDialog();return}
    if(e.target.closest('[data-key-task-add]')){if(!currentTaskProfile()){openTaskProfileDialog();return}openKeyTaskDialog();return}
    if(e.target.closest('[data-task-all-open],[data-task-archive-open],[data-task-archive-toggle],[data-task-project-open],[data-task-role-open],[data-task-role-project],[data-task-project-back]')){taskBulkMode=false;selectedTaskIds.clear()}
    if(e.target.closest('[data-task-all-open]')){taskWorkspaceScreen="all";taskWorkspaceProjectId="";taskWorkspaceFilters={project:"",executor:"",responsible:"",deadline:"",status:"",search:"",archive:"active"};renderKeyTasks();return}
    if(e.target.closest('[data-task-archive-open]')){taskWorkspaceScreen="archive";taskWorkspaceProjectId="";taskWorkspaceFilters={project:"",executor:"",responsible:"",deadline:"",status:"",search:"",archive:"archive"};renderKeyTasks();return}
    if(e.target.closest('[data-task-archive-toggle]')){taskWorkspaceScreen=taskWorkspaceScreen==="archive"?"all":"archive";taskWorkspaceFilters={...taskWorkspaceFilters,archive:taskWorkspaceScreen==="archive"?"archive":"active"};renderKeyTasks();return}
    const taskProjectOpen=e.target.closest('[data-task-project-open]');if(taskProjectOpen){taskWorkspaceProjectId=taskProjectOpen.dataset.taskProjectOpen||"";taskWorkspaceScreen="project";taskWorkspaceFilters={project:"",executor:"",responsible:"",deadline:"",status:"",search:"",archive:"active"};renderKeyTasks();return}
    const taskRoleOpen=e.target.closest('[data-task-role-open]');if(taskRoleOpen){taskWorkspacePersonId=taskRoleOpen.dataset.taskRoleOpen||"";taskWorkspaceProjectId="";taskWorkspaceScreen="person";taskWorkspaceView="board";taskWorkspaceFilters={project:"",executor:taskWorkspacePersonId,responsible:"",deadline:"",status:"",search:"",archive:"active"};renderKeyTasks();return}
    const taskRoleProject=e.target.closest('[data-task-role-project]');if(taskRoleProject){taskWorkspaceProjectId=taskRoleProject.dataset.taskRoleProject||"";taskWorkspaceScreen="project";taskWorkspaceFilters={project:"",executor:taskRoleProject.dataset.taskRole||"",responsible:"",deadline:"",status:"",search:"",archive:"active"};renderKeyTasks();return}
    if(e.target.closest('[data-task-project-back]')){taskWorkspaceScreen="projects";taskWorkspaceProjectId="";taskWorkspacePersonId="";taskWorkspaceFilters={project:"",executor:"",responsible:"",deadline:"",status:"",search:"",archive:"active"};renderKeyTasks();return}
    if(e.target.closest('[data-task-bulk-mode]')){taskBulkMode=!taskBulkMode;selectedTaskIds.clear();renderKeyTasks();return}
    const taskSelect=e.target.closest('[data-task-select]');if(taskSelect){const id=taskSelect.dataset.taskSelect;if(selectedTaskIds.has(id))selectedTaskIds.delete(id);else selectedTaskIds.add(id);renderKeyTasks();return}
    if(e.target.closest('[data-task-bulk-open]')){openTaskBulkDialog();return}
    const taskReminderOpen=e.target.closest('[data-task-reminder-open]');if(taskReminderOpen){openKeyTaskDialog(taskReminderOpen.dataset.taskReminderOpen);return}
    const taskLinkRemove=e.target.closest('[data-task-link-remove]');if(taskLinkRemove){const links=readTaskLinks();links.splice(Number(taskLinkRemove.dataset.taskLinkRemove),1);renderTaskLinkInputs(links);return}
    const taskOpen=e.target.closest('[data-task-open]');if(taskOpen){openKeyTaskDialog(taskOpen.dataset.taskOpen);return}
    const overdueFilter=e.target.closest('[data-task-overdue-filter]');if(overdueFilter){taskWorkspaceFilters={...taskWorkspaceFilters,deadline:"overdue"};renderKeyTasks();return}
    const taskCommentAdd=e.target.closest('[data-task-comment-add]');if(taskCommentAdd){addTaskComment(taskCommentAdd.dataset.taskCommentAdd);return}
    if(e.target.closest('[data-task-profile-open]')){openTaskProfileDialog();return}
    if(e.target.closest('[data-task-stages-open]')){openTaskStagesDialog();return}
    const taskStageSave=e.target.closest('[data-task-stage-save]');if(taskStageSave){const row=taskStageSave.closest('[data-task-stage-row]'),name=row?.querySelector('[data-task-stage-name]')?.value||"",auto_assign_profile_id=row?.querySelector('[data-task-stage-assignee]')?.value||"",sla_days=Number(row?.querySelector('[data-task-stage-sla]')?.value||0);fetch(`/api/key-tasks/statuses/${encodeURIComponent(taskStageSave.dataset.taskStageSave)}`,{method:'PATCH',headers:{'Content-Type':'application/json'},body:JSON.stringify({name,auto_assign_profile_id,sla_days})}).then(async response=>{if(!response.ok){alert((await response.json().catch(()=>({detail:'Не удалось сохранить этап'}))).detail||'Не удалось сохранить этап');return}keyTasksData=null;await loadKeyTasks(true);openTaskStagesDialog()});return}
    const taskStageDelete=e.target.closest('[data-task-stage-delete]');if(taskStageDelete){const row=taskStageDelete.closest('[data-task-stage-row]'),move_to_status_id=row?.querySelector('[data-task-stage-target]')?.value||"";if(!window.confirm('Удалить этап? Все его задачи перейдут в выбранный этап.'))return;fetch(`/api/key-tasks/statuses/${encodeURIComponent(taskStageDelete.dataset.taskStageDelete)}`,{method:'DELETE',headers:{'Content-Type':'application/json'},body:JSON.stringify({move_to_status_id})}).then(async response=>{if(!response.ok){alert((await response.json().catch(()=>({detail:'Не удалось удалить этап'}))).detail||'Не удалось удалить этап');return}keyTasksData=null;await loadKeyTasks(true);openTaskStagesDialog()});return}
    if(e.target.closest('[data-task-projects-open]')){openTaskProjectsDialog();return}
    if(e.target.closest('[data-task-templates-open]')){openTaskTemplatesDialog();return}
    const taskTemplateDelete=e.target.closest('[data-task-template-delete]');if(taskTemplateDelete){if(!window.confirm("Удалить шаблон? Задачи, созданные по нему, останутся."))return;fetch(`/api/key-tasks/templates/${encodeURIComponent(taskTemplateDelete.dataset.taskTemplateDelete)}`,{method:'DELETE'}).then(async response=>{if(!response.ok){alert(await response.text());return}keyTasksData=null;await loadKeyTasks(true);openTaskTemplatesDialog()});return}
    const taskProfileSelect=e.target.closest('[data-task-profile-select]');if(taskProfileSelect){saveTaskProfile(taskProfileSelect.dataset.taskProfileSelect);$("#taskProfileDialog").close();renderKeyTasks();return}
    const taskProfileEdit=e.target.closest('[data-task-profile-edit]');if(taskProfileEdit){const profile=activeTaskProfiles().find(row=>row.id===taskProfileEdit.dataset.taskProfileEdit),role=window.prompt(`Роль для ${profile?.name||"сотрудника"}`,profile?.role||"");if(role===null)return;fetch(`/api/key-tasks/profiles/${encodeURIComponent(taskProfileEdit.dataset.taskProfileEdit)}`,{method:'PATCH',headers:{'Content-Type':'application/json'},body:JSON.stringify({role})}).then(async response=>{if(!response.ok){alert(await response.text());return}keyTasksData=null;await loadKeyTasks(true);openTaskProfileDialog()});return}
    const taskProfileDelete=e.target.closest('[data-task-profile-delete]');if(taskProfileDelete){if(!window.confirm("Удалить сотрудника из выбора? На старых задачах он останется как «Уволен»."))return;fetch(`/api/key-tasks/profiles/${encodeURIComponent(taskProfileDelete.dataset.taskProfileDelete)}`,{method:'DELETE'}).then(async response=>{if(!response.ok){alert(await response.text());return}if(activeTaskProfileId===taskProfileDelete.dataset.taskProfileDelete)saveTaskProfile("");keyTasksData=null;await loadKeyTasks(true);openTaskProfileDialog()});return}
    const taskProjectArchive=e.target.closest('[data-task-project-archive]');if(taskProjectArchive){fetch(`/api/key-tasks/projects/${encodeURIComponent(taskProjectArchive.dataset.taskProjectArchive)}`,{method:'PATCH',headers:{'Content-Type':'application/json'},body:JSON.stringify({archived:taskProjectArchive.dataset.taskProjectArchived==='1'})}).then(async response=>{if(!response.ok){alert(await response.text());return}keyTasksData=null;await loadKeyTasks(true);openTaskProjectsDialog()});return}
    const taskViewPreset=e.target.closest('[data-task-view-preset]');if(taskViewPreset){const preset=taskViewPreset.dataset.taskViewPreset;if(preset==='mine'){if(!currentTaskProfile()){openTaskProfileDialog();return}applyTaskView({executor:activeTaskProfileId})}else if(preset==='overdue')applyTaskView({deadline:'overdue'});else applyTaskView({deadline:'week'});return}
    const taskViewApply=e.target.closest('[data-task-view-apply]');if(taskViewApply){const saved=taskSavedViews().find(view=>view.id===taskViewApply.dataset.taskViewApply);if(saved)applyTaskView(saved.filters||{});return}
    const taskViewDelete=e.target.closest('[data-task-view-delete]');if(taskViewDelete){const name=taskSavedViews().find(view=>view.id===taskViewDelete.dataset.taskViewDelete)?.name||'это представление';if(!window.confirm(`Удалить «${name}»?`))return;fetch(`/api/key-tasks/views/${encodeURIComponent(taskViewDelete.dataset.taskViewDelete)}?profile_id=${encodeURIComponent(activeTaskProfileId)}`,{method:'DELETE'}).then(async response=>{if(!response.ok){alert(await response.text());return}keyTasksData=null;await loadKeyTasks(true)});return}
    if(e.target.closest('[data-task-view-save]')){saveTaskView();return}
    const reactivationReload=e.target.closest('[data-reload-reactivation]');if(reactivationReload){reactivationData=null;void loadReactivationQueue(true);return}
    const reactivationAction=e.target.closest('[data-reactivate-deal]');if(reactivationAction){e.preventDefault();void reactivateDeal(reactivationAction.dataset.reactivateDeal);return}
    const taskView=e.target.closest('[data-task-view]');if(taskView){taskWorkspaceView=taskView.dataset.taskView;renderKeyTasks();return}
    if(e.target.closest('[data-task-filter-reset]')){taskWorkspaceFilters={project:"",executor:"",responsible:"",deadline:"",status:"",search:"",archive:"active"};renderKeyTasks();return}
    if(e.target.closest('[data-dashboard-chat-send]')){askDashboardChat();return}
    const salesWorkspace=e.target.closest('[data-sales-workspace-tab]');if(salesWorkspace){salesWorkspaceTab=salesWorkspace.dataset.salesWorkspaceTab||"overview";renderSales();if(salesWorkspaceTab==="daily")void loadDailySales();return}
    const dailyTab=e.target.closest('[data-daily-sales-tab]');if(dailyTab){dailySalesTab=dailyTab.dataset.dailySalesTab||"leads";renderDailySales();return}
    if(e.target.closest('[data-daily-sales-refresh]')){void loadDailySales(true);return}
    if(e.target.closest('[data-retry-sales-section]')){loadSalesSection();return}
    const cb=e.target.closest('[data-comment-scope]');if(cb){e.stopPropagation();commentTarget={scope:cb.dataset.commentScope,metric:cb.dataset.commentMetric,title:cb.dataset.commentTitle};$('#commentTitle').textContent=commentTarget.title;$('#commentText').value=getComment(commentTarget.scope,commentTarget.metric);$('#commentDialog').showModal();return}
    const np=e.target.closest('[data-nps-edit]');if(np){e.stopPropagation();openNpsDialog(np.dataset.expert||'');return}
    const openNps=e.target.closest('[data-open-nps]');if(openNps){e.stopPropagation();openNpsDialog(openNps.dataset.expert||'');return}
    const npsDetails=e.target.closest('[data-open-nps-details]');if(npsDetails){e.stopPropagation();openNpsDetails(npsDetails.dataset.openNpsDetails||'');return}
    const openTeam=e.target.closest('[data-open-team]');if(openTeam){e.stopPropagation();openTeamDialog(openTeam.dataset.openTeam||'expert',openTeam.dataset.teamFormer==='1');return}
    const actsToggle=e.target.closest('[data-acts-experts-toggle]');if(actsToggle){e.preventDefault();e.stopPropagation();const panel=actsToggle.closest('.acts-experts-panel');if(!panel)return;panel.open=!panel.open;actsToggle.textContent=panel.open?'Свернуть отчёт':'Развернуть отчёт';actsToggle.setAttribute('aria-expanded',String(panel.open));return}
    if(e.target.closest('[data-production-week-plans]')){e.preventDefault();e.stopPropagation();openPlanDialog("production","week","0");return}
    if(e.target.closest('[data-production-product-plans]')){e.preventDefault();e.stopPropagation();openPlanDialog("production","product");return}
    if(e.target.closest('[data-production-expert-plans]')){e.preventDefault();e.stopPropagation();openPlanDialog("production","expert");return}
    const productPlan=e.target.closest('[data-edit-product-plan]');if(productPlan){e.stopPropagation();openPlanDialog("production","product",productPlan.dataset.editProductPlan||"");return}
    const expertProductPlan=e.target.closest('[data-edit-expert-product-plan]');if(expertProductPlan){e.stopPropagation();openPlanDialog("production","expert_product",expertProductPlanKey(expertProductPlan.dataset.expert||"",expertProductPlan.dataset.product||""));return}
    const rnpPlan=e.target.closest('[data-rnp-plan]');if(rnpPlan){e.preventDefault();e.stopPropagation();openPlanDialog("sales","source_group",rnpPlan.dataset.rnpPlan||"");return}
    const weekToggle=e.target.closest('[data-week-toggle]');if(weekToggle){e.stopPropagation();const i=Number(weekToggle.dataset.weekToggle);expandedSalesWeek=expandedSalesWeek===i?null:i;renderSales();return}
    const editTraffic=e.target.closest('[data-edit-traffic-group]');if(editTraffic){e.preventDefault();e.stopPropagation();openTrafficGroupDialog(editTraffic.dataset.editTrafficGroup||"");return}
    const trafficRemove=e.target.closest('[data-traffic-remove]');if(trafficRemove){e.preventDefault();e.stopPropagation();removeTrafficSourceFromGroup(trafficRemove.dataset.trafficRemove||"");return}
    const trafficAuto=e.target.closest('[data-traffic-auto]');if(trafficAuto){e.preventDefault();e.stopPropagation();resetTrafficSourceAuto(trafficAuto.dataset.trafficAuto||"");return}
    const delNps=e.target.closest('[data-delete-nps]');if(delNps){e.stopPropagation();const q=new URLSearchParams({month:$('#month').value,entry_id:delNps.dataset.deleteNps,admin_key:$('#npsAdminKey').value||''});fetch('/api/nps?'+q.toString(),{method:'DELETE'}).then(async r=>{if(!r.ok){alert(await r.text());return}state.manual_nps=(await r.json()).manual_nps;renderNpsHistory();renderAll()});return}
    if(e.target.closest('#drillMore')){e.stopPropagation();loadMoreDrill();return}
    if(e.target.closest('#saveDormant')){saveDormant();return}
    const add=e.target.closest('[data-team-add]');if(add){addTeam(add.dataset.teamAdd);return}
    const rem=e.target.closest('[data-team-remove]');if(rem){removeTeam(rem.dataset.role,rem.dataset.name);return}
    const financeDrill=e.target.closest('[data-finance-drill]');if(financeDrill){e.preventDefault();openFinanceDrill(financeDrill.dataset.financeDrill,financeDrill.dataset.financeGroup||"",financeDrill.dataset.financeWeek||"");return}
    const x=e.target.closest('[data-drill="1"]');if(x)openDrill(x)
  });
  document.body.addEventListener('input',e=>{if(e.target?.id==='dashboardChatQuestion'){dashboardChatDraft=e.target.value;persistDashboardChatState()}if(e.target.matches('[data-task-search]')){taskWorkspaceFilters.search=e.target.value;renderKeyTasks();requestAnimationFrame(()=>{const field=document.querySelector('[data-task-search]');field?.focus();field?.setSelectionRange(field.value.length,field.value.length)})}});
  document.body.addEventListener('keydown',e=>{if(e.key==='Enter'&&!e.shiftKey&&e.target?.id==='dashboardChatQuestion'){e.preventDefault();askDashboardChat()}});
  let draggedTaskId="";
  document.body.addEventListener('dragstart',e=>{const card=e.target.closest('[data-task-drag]');if(!card)return;draggedTaskId=card.dataset.taskDrag;e.dataTransfer.effectAllowed='move';e.dataTransfer.setData('text/plain',draggedTaskId);card.classList.add('is-dragging')});
  document.body.addEventListener('dragend',e=>{e.target.closest('[data-task-drag]')?.classList.remove('is-dragging');document.querySelectorAll('[data-task-drop].is-drop-target').forEach(node=>node.classList.remove('is-drop-target'));draggedTaskId=""});
  document.body.addEventListener('dragover',e=>{const column=e.target.closest('[data-task-drop]');if(!column||!draggedTaskId)return;e.preventDefault();e.dataTransfer.dropEffect='move';column.classList.add('is-drop-target')});
  document.body.addEventListener('dragleave',e=>{const column=e.target.closest('[data-task-drop]');if(column&&!column.contains(e.relatedTarget))column.classList.remove('is-drop-target')});
  document.body.addEventListener('drop',e=>{const column=e.target.closest('[data-task-drop]');if(!column||!draggedTaskId)return;e.preventDefault();column.classList.remove('is-drop-target');moveTaskToStage(draggedTaskId,column.dataset.taskDrop);draggedTaskId=""});
  document.body.addEventListener('change',e=>{if(e.target.matches('[data-audit-filter]'))renderCrmAuditRows();if(e.target.matches('[data-task-filter]')){taskWorkspaceFilters[e.target.dataset.taskFilter]=e.target.value;renderKeyTasks()}if(e.target.matches('[data-daily-sales-date]')){dailySalesDate=e.target.value;dailySalesData=null;void loadDailySales(true)}if(e.target.id==='keyTaskStatus')updateTaskStageDeadlineState();if(e.target.id==='keyTaskTemplate')applyTaskTemplate(e.target.value)});
  $("#closeDrill").addEventListener('click',()=>$("#drillDialog").close());$("#drillSearch").addEventListener('input',renderDrillRows);
  $("#closePlan").addEventListener('click',()=>$("#planDialog").close());$("#planMonth").addEventListener('change',loadPlanDialogMonth);$("#planScope").addEventListener('change',()=>{updatePlanContextTypes();updatePlanKey()});$("#planContextType").addEventListener('change',updatePlanKey);$("#planContextKey").addEventListener('change',buildPlanForm);$("#savePlan").addEventListener('click',savePlan);

  $("#closeComment").addEventListener('click',()=>$("#commentDialog").close());
  $("#saveComment").addEventListener('click',async()=>{if(!commentTarget)return;const r=await fetch('/api/comment',{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({month:$('#month').value,scope:commentTarget.scope,metric:commentTarget.metric,comment:$('#commentText').value})});if(!r.ok){alert(await r.text());return}state.comments=(await r.json()).comments;$('#commentDialog').close();renderAll()});
  $("#closeNps").addEventListener('click',()=>$("#npsDialog").close());
  $("#closeNpsDetails").addEventListener('click',()=>$("#npsDetailsDialog").close());
  $("#npsExpert").addEventListener('change',()=>{npsTarget=$("#npsExpert").value;$("#npsValue").value='';$("#npsNote").value='';renderNpsHistory()});
  $("#saveNps").addEventListener('click',async()=>{npsTarget=$("#npsExpert").value||npsTarget;if(!npsTarget)return;const raw=$("#npsValue").value;if(raw===''){alert('Введи NPS от 0 до 10');return}const r=await fetch('/api/nps',{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({month:$('#month').value,expert:npsTarget,value:Number(raw),note:$('#npsNote').value,admin_key:$('#npsAdminKey').value})});if(!r.ok){alert(await r.text());return}state.manual_nps=(await r.json()).manual_nps;$("#npsValue").value='';$("#npsNote").value='';renderNpsHistory();renderAll()});
  $("#closeTeam").addEventListener('click',()=>$("#teamDialog").close());
  $("#closeTaskProfile").addEventListener('click',()=>$("#taskProfileDialog").close());
  $("#saveTaskProfile").addEventListener('click',async()=>{const response=await fetch('/api/key-tasks/profiles',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name:$("#taskProfileName").value,role:$("#taskProfileRole").value})});if(!response.ok){alert((await response.json().catch(()=>({detail:"Не удалось добавить сотрудника"}))).detail||"Не удалось добавить сотрудника");return}const payload=await response.json();saveTaskProfile(payload.profile.id);$("#taskProfileDialog").close();keyTasksData=null;await loadKeyTasks(true)});
  $("#closeTaskProject").addEventListener('click',()=>$("#taskProjectDialog").close());
  $("#saveTaskProject").addEventListener('click',async()=>{const response=await fetch('/api/key-tasks/projects',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name:$("#taskProjectName").value})});if(!response.ok){alert((await response.json().catch(()=>({detail:"Не удалось добавить проект"}))).detail||"Не удалось добавить проект");return}keyTasksData=null;await loadKeyTasks(true);openTaskProjectsDialog()});
  $("#closeTaskStage").addEventListener('click',()=>$("#taskStageDialog").close());
  $("#saveTaskStage").addEventListener('click',async()=>{const response=await fetch('/api/key-tasks/statuses',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name:$("#taskStageName").value})});if(!response.ok){alert((await response.json().catch(()=>({detail:"Не удалось добавить этап"}))).detail||"Не удалось добавить этап");return}keyTasksData=null;await loadKeyTasks(true);openTaskStagesDialog()});
  $("#closeTaskBulk").addEventListener('click',()=>$("#taskBulkDialog").close());
  $("#saveTaskBulk").addEventListener('click',saveTaskBulk);
  $("#closeTaskTemplate").addEventListener('click',()=>$("#taskTemplateDialog").close());
  $("#saveTaskTemplate").addEventListener('click',async()=>{const payload={name:$("#taskTemplateName").value,title:$("#taskTemplateTitle").value,description:$("#taskTemplateDescription").value,priority:$("#taskTemplatePriority").value};const response=await fetch('/api/key-tasks/templates',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});if(!response.ok){alert((await response.json().catch(()=>({detail:"Не удалось сохранить шаблон"}))).detail||"Не удалось сохранить шаблон");return}keyTasksData=null;await loadKeyTasks(true);openTaskTemplatesDialog()});
  $("#closeTaskSavedView").addEventListener('click',()=>$("#taskSavedViewDialog").close());
  $("#saveTaskSavedView").addEventListener('click',submitTaskView);
  $("#closeKeyTask").addEventListener('click',()=>$("#keyTaskDialog").close());
  $("#saveKeyTask").addEventListener('click',saveKeyTask);
  $("#addKeyTaskLink").addEventListener('click',()=>{const links=readTaskLinks();links.push({url:"",label:""});renderTaskLinkInputs(links);document.querySelector('#keyTaskLinks [data-task-link-row]:last-child [data-task-link-url]')?.focus()});
  $("#closeTaskMeeting").addEventListener('click',()=>$("#taskMeetingDialog").close());
  $("#cancelTaskMeeting").addEventListener('click',()=>$("#taskMeetingDialog").close());
  $("#saveTaskMeeting").addEventListener('click',saveTaskMeeting);
  $("#closeTrafficGroup").addEventListener('click',()=>$("#trafficGroupDialog").close());
  $("#addTrafficSource").addEventListener('click',addTrafficSourceToGroup);
  $("#saveTrafficGroup").addEventListener('click',saveTrafficGroupDialog);
  $("#saveTeamMember").addEventListener('click',async()=>{const name=$("#teamUser").value,role=$("#teamRole").value;if(!name)return;const r=await fetch('/api/team',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({role,name,admin_key:$("#teamDialogAdminKey").value||''})});if(!r.ok){alert(await r.text());return}state.team=(await r.json()).team;$("#teamDialog").close();renderAll()});
  $("#deleteTaskFromDialog").addEventListener('click',()=>{if(taskEditingId)deleteKeyTask(taskEditingId).then(()=>$("#keyTaskDialog").close())});
  $("#archiveTaskFromDialog").addEventListener('click',async()=>{if(!taskEditingId)return;const task=(keyTasksData?.tasks||[]).find(row=>row.id===taskEditingId),response=await fetch(`/api/key-tasks/${encodeURIComponent(taskEditingId)}`,{method:'PATCH',headers:{'Content-Type':'application/json'},body:JSON.stringify({archived:!task?.archived,changed_by_profile_id:activeTaskProfileId})});if(!response.ok){alert((await response.json().catch(()=>({detail:"Не удалось изменить архив"}))).detail||"Не удалось изменить архив");return}$("#keyTaskDialog").close();keyTasksData=null;await loadKeyTasks(true)});
  const es=new EventSource('/events');es.addEventListener('update',scheduleBackgroundLoad);es.onerror=()=>{$("#liveDot").className='bad'};
  window.addEventListener("offline",()=>{if(state){$("#liveDot").className="bad";$("#liveText").textContent="ПОКАЗАНА ПОСЛЕДНЯЯ ВЕРСИЯ · НЕТ СЕТИ"}});
  window.addEventListener("online",scheduleBackgroundLoad);
  renderDashboardChat();load();setInterval(scheduleBackgroundLoad,120000);
  setInterval(()=>{if(["experts","department-experts"].includes(requestedView()))void loadActsExperts(true)},60000);
}

function addTaskMeetingShortcut(){const actions=$("#key-tasks .task-workspace-actions");if(!actions||actions.querySelector("[data-task-meeting-open]"))return;const button=document.createElement("button");button.type="button";button.className="btn meeting-action";button.dataset.taskMeetingOpen="1";button.textContent="Итог встречи";const add=actions.querySelector("[data-key-task-add]");if(add)actions.insertBefore(button,add);else actions.append(button)}
const renderTaskProjectHubBase=renderTaskProjectHub;
renderTaskProjectHub=function(){renderTaskProjectHubBase();addTaskMeetingShortcut()};
const renderKeyTasksBase=renderKeyTasks;
renderKeyTasks=function(){renderKeyTasksBase();addTaskMeetingShortcut()};
init();

// A background refresh must not rebuild the whole dashboard: that used to reset
// the visible section, open accordions and the text being typed in the chat.
// Render the current view into a detached DOM tree and only reconcile its nodes.
let activeLoadMode=null;
const loadDashboardSnapshot=load;
load=async function(options={}){
  const mode={background:Boolean(options.background)};
  activeLoadMode=mode;
  try{return await loadDashboardSnapshot(options)}finally{if(activeLoadMode===mode)activeLoadMode=null}
};

function copyAttributes(target,source){
  if(target.tagName!=="DETAILS"){
    [...target.attributes].forEach(attribute=>{if(!source.hasAttribute(attribute.name))target.removeAttribute(attribute.name)});
    [...source.attributes].forEach(attribute=>{if(target.getAttribute(attribute.name)!==attribute.value)target.setAttribute(attribute.name,attribute.value)});
  }
}
function reconcileNode(target,source){
  if(target.nodeType!==source.nodeType||target.nodeName!==source.nodeName){target.replaceWith(source.cloneNode(true));return}
  if(target.nodeType===Node.TEXT_NODE){if(target.nodeValue!==source.nodeValue)target.nodeValue=source.nodeValue;return}
  copyAttributes(target,source);
  const editing=document.activeElement===target&&/^(INPUT|TEXTAREA|SELECT)$/.test(target.tagName);
  if(editing)return;
  const oldNodes=[...target.childNodes],newNodes=[...source.childNodes];
  for(let index=0;index<newNodes.length;index++){
    if(!oldNodes[index])target.appendChild(newNodes[index].cloneNode(true));
    else reconcileNode(oldNodes[index],newNodes[index]);
  }
  for(let index=oldNodes.length-1;index>=newNodes.length;index--)oldNodes[index].remove();
}
function renderCurrentViewInto(sandbox,viewId){
  if(viewId==="overview")return renderOverview();
  if(viewId==="sales")return state.sales?.details_loaded&&state.sales?.details_key===snapshotKey()?renderSales():renderSalesPlaceholder("Загружаю детальные продажи…");
  if(viewId==="production"){renderProduction();return}
  if(viewId==="experts"){renderExperts();return}
  if(viewId==="department-experts"){renderProduction();renderExperts();renderExpertsDepartment();return}
  if(viewId==="risks")return renderRisks();
  if(viewId==="forecast")return renderForecast();
  if(viewId==="plans")return renderPlans();
  if(viewId==="calls")return renderCallsPlaceholder();
  if(viewId==="marketing")return renderMarketingPlaceholder();
  if(viewId==="crm-audit")return renderCrmAuditPlaceholder();
  if(viewId==="hub")return renderHub();
  if(viewId==="key-tasks")return keyTasksData?renderKeyTasks():renderKeyTasksPlaceholder("Загружаю задачи…");
}
function softRenderCurrentView(){
  const viewId=requestedView(),liveView=document.getElementById(viewId);
  if(!liveView||!liveView.childNodes.length)return false;
  // Jarvis is a signed cross-origin iframe. Reconciliation creates an empty
  // sandbox for this view and used to erase the live frame on every refresh.
  if(viewId==="sales-calls")return true;
  // A background poll must never rebuild an expanded working view.  The
  // refreshed snapshot remains in state and is shown after the user closes
  // the disclosure, changes section, or requests a manual refresh.
  if(liveView.querySelector("details[open]"))return true;
  const sandbox=document.createElement("div");
  document.querySelectorAll(".view").forEach(view=>{
    const copy=document.createElement(view.tagName);
    copy.id=view.id;copy.className=view.className;sandbox.appendChild(copy);
  });
  const queryOne=document.querySelector.bind(document),queryAll=document.querySelectorAll.bind(document);
  document.querySelector=selector=>sandbox.querySelector(selector)||queryOne(selector);
  document.querySelectorAll=selector=>{
    const matches=sandbox.querySelectorAll(selector);
    return matches.length?matches:queryAll(selector);
  };
  try{renderCurrentViewInto(sandbox,viewId)}finally{document.querySelector=queryOne;document.querySelectorAll=queryAll}
  const nextView=sandbox.querySelector("#"+viewId);
  if(!nextView)return false;
  reconcileNode(liveView,nextView);
  return true;
}
const renderDashboardFully=renderAll;
renderAll=function(){
  if(activeLoadMode?.background&&state?.ok&&softRenderCurrentView())return;
  return renderDashboardFully();
};


// Build marker: helps verify that the browser is not showing stale frontend files.
window.addEventListener("DOMContentLoaded",()=>{
  const top=document.querySelector(".topbar")||document.querySelector("header")||document.body;
  if(!document.querySelector("#buildMarker")){
    const b=document.createElement("span");
    b.id="buildMarker";
    b.className="build-marker";
    b.textContent="v3.6.24";
    top.appendChild(b);
  }
});
