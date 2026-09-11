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
const BROWSER_CACHE_PREFIX="mavis-dashboard-snapshot:v3:";
const INSTALL_HINT_DISMISSED_KEY="mavis-dashboard-install-hint-dismissed:v1";
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

const SALES_LABELS={
  leads:["Лиды","num"],qualified:["Квал. лиды","num"],qualified_rate:["Лид → квал.","pct"],lead_to_deal_rate:["Квал. → сделка","pct"],
  lead_to_sale_rate:["Лид → продажа","pct"],qualified_to_sale_rate:["Квал. → продажа","pct"],
  deals:["Сделки","num"],lost_deals:["Слитые сделки","num"],deal_amount:["Сумма созданных сделок","money"],sales:["Продажи","num"],sales_amount:["Сумма продаж","money"],average_check:["Средний чек","money"],
  deal_to_sale_rate:["Сделка → продажа","pct"],products_per_deal:["Продуктов / сделку","num"],products:["Продукты в сделках","num"],product_amount:["Сумма продуктов в сделках","money"],
  sold_products:["Продано продуктов","num"],sold_product_amount:["Сумма прод. продуктов","money"],average_product_check:["Средний чек продукта","money"],product_sale_rate:["Продукт → продажа","pct"],
  paid_amount:["Платежи (поле CRM)","money"],net_revenue:["Чистая выручка","money"]
};
const PROD_LABELS={
  closed_count:["Закрыто продуктов","num"],closed_amount:["Сумма закрытых","money"],avg_check:["Средний чек","money"],
  new_count:["Пришло за период","num"],new_amount:["Сумма пришедших","money"],period_closed_count:["Закрыто из пришедших","num"],period_closed_amount:["Сумма закрытых из пришедших","money"],new_to_success_pct:["Конверсия периода","pct"],
  capacity_count:["Ёмкость периода, шт","num"],capacity_amount:["Ёмкость периода, BYN","money"],returns_count:["Возвраты","num"],returns_amount:["Сумма возвратов","money"],
  avg_production_days:["Срок производства","days"],avg_deviation_days:["Отклонение от нормы","days"],within_norm_pct:["В нормативе","pct"],
  nps_avg:["NPS вручную","num"],dormant_count:["Зависшие по ожидаемой дате","num"],returned_to_production:["Вернулось в производство","num"],dormant_with_reason_pct:["Причина заполнена","pct"]
};

const $=s=>document.querySelector(s);
const $$=s=>[...document.querySelectorAll(s)];
const fmt=n=>new Intl.NumberFormat("ru-RU",{maximumFractionDigits:1}).format(Number(n||0));
const money=n=>new Intl.NumberFormat("ru-RU",{maximumFractionDigits:0}).format(Number(n||0))+" BYN";
const pct=n=>fmt(n)+"%";
const days=n=>fmt(n)+" дн.";
const esc=s=>String(s??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"}[c]));
const attr=s=>esc(String(s??""));
function format(v,type){return type==="money"?money(v):type==="pct"?pct(v):type==="days"?days(v):fmt(v)}

function selectedManagers(){return state?.team?.managers||["Ирина Богомольцева","Роман Авсеенко"]}
function selectedExperts(){return state?.team?.experts||["Екатерина Николаева","Елизавета Горбатова","Ольга Панькова"]}
function managers(){const s=new Set(selectedManagers());return (state?.sales?.managers||[]).filter(x=>s.has(x.name))}
function experts(){const s=new Set(selectedExperts());return (state?.production?.experts||[]).filter(x=>s.has(x.name))}
function expertNpsMeta(e){const m=state?.manual_nps?.[e.name];if(!m)return {value:null,count:0,entries:[]};return {value:Number(m.value),count:Number(m.count||0),entries:m.entries||[]}}
function expertNps(e){return expertNpsMeta(e).value}
function overallManualNpsMeta(){
  let total=0,sum=0;
  experts().forEach(e=>{const m=expertNpsMeta(e);if(m.value!==null&&Number.isFinite(m.value)&&m.count>0){sum+=m.value*m.count;total+=m.count}});
  return {value:total?sum/total:null,count:total};
}
function overallManualNps(){return overallManualNpsMeta().value}
function npsText(v){return v===null||v===undefined?"Не задан":fmt(v)}
function getComment(scope,metric){return state?.comments?.[`${scope}|${metric}`]?.comment||""}

function getPlan(scope,metric,contextType="overall",contextKey=""){
  return Number(state?.plans?.[`${scope}|${contextType}|${contextKey}`]?.[metric]||0);
}
function drillAttrs(scope,metric,extra={}){
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
  const shown=value===null||value===undefined?'—':fmt(value);
  return `<div class="card nps-manual-card"><div class="kpi-label">NPS вручную</div><div class="kpi-value">${shown}</div><div class="kpi-meta"><span>${count?`Среднее по ${fmt(count)} оценкам`:'Оценок пока нет'}</span></div><button class="btn soft-action" data-open-nps="1">+ Добавить оценку NPS</button></div>`;
}
function progressPct(scope,metric,fact,ct="overall",ck=""){const p=getPlan(scope,metric,ct,ck);return p?Math.max(0,Math.min(100,Number(fact||0)/p*100)):0}
function deptHero({kind,title,eyebrow,value,valueType='money',scope,metric,extra={},planMetric=metric,substats=[]}){
  const plan=getPlan(scope,planMetric); const pp=plan?Number(value||0)/plan*100:0;
  return `<div class="department-hero ${kind} clickable" ${drillAttrs(scope,metric,extra)}><div class="dept-hero-top"><div><div class="dept-kicker">${esc(eyebrow)}</div><h2>${esc(title)}</h2></div><div class="dept-ring" style="--ring:${Math.max(0,Math.min(100,pp))*3.6}deg"><span>${plan?Math.round(pp)+'%':'—'}</span></div></div><div class="dept-value">${format(value,valueType)}</div><div class="dept-plan"><span>План ${plan?format(plan,valueType):'—'}</span><span>${plan?`Выполнение ${pct(pp)}`:'Заполни план'}</span></div><div class="dept-substats">${substats.map(s=>`<div><span>${esc(s.label)}</span><strong>${format(s.value,s.type||'num')}</strong></div>`).join('')}</div></div>`;
}
function signalCard(kind,title,value,type,scope,metric,note="",extra={}){return `<div class="signal-card ${kind} clickable" ${drillAttrs(scope,metric,extra)}><div class="signal-top"><span>${esc(title)}</span><span class="signal-arrow">›</span></div><div class="signal-value">${format(value,type)}</div><div class="signal-note">${esc(note)}</div></div>`;}
function panel(title,body,note=""){return `<div class="panel"><div class="panel-head"><div class="panel-title">${esc(title)}</div><div class="muted">${esc(note)}</div></div>${body}</div>`}
function tdLink(value,scope,metric,type,extra={}){return `<span class="cell-link" ${drillAttrs(scope,metric,extra)}>${format(value,type)}</span>`}

function cleanRevenueCaption(){
  const finance=state?.clean_revenue||{};
  if(finance.status==="online")return "Чистая выручка из «Графика платежей»";
  if(finance.status==="stale")return "Последняя подтверждённая чистая выручка; источник обновляется";
  if(finance.status==="not_configured")return "Источник чистой выручки ещё не подключён";
  return "Чистая выручка временно недоступна";
}
function financeAmount(key){
  const finance=state?.clean_revenue||{},value=Number(finance[key]);
  return ["online","stale"].includes(finance.status)&&Number.isFinite(value)?money(value):"—";
}
function financialIncomingAmount(fallback=0){
  const finance=state?.clean_revenue||{},value=Number(finance.incoming_amount);
  return ["online","stale"].includes(finance.status)&&Number.isFinite(value)?value:Number(fallback||0);
}
function financialSalesMetrics(s){
  const incoming=financialIncomingAmount(s?.sales_amount),sales=Number(s?.sales||0);
  return {incoming,averageCheck:sales?incoming/sales:0};
}
function incomingRevenueCaption(){
  const finance=state?.clean_revenue||{};
  if(finance.status==="online")return "Чистая выручка + подрядчики из «Графика платежей»";
  if(finance.status==="stale")return "Последняя подтверждённая сумма: чистая выручка + подрядчики";
  return "Сумма CRM до восстановления финансового источника";
}
function contractorCaption(){
  const finance=state?.clean_revenue||{};
  if(finance.status==="online")return "Учтено в чистой выручке";
  if(finance.status==="stale")return "Последнее подтверждённое значение";
  return cleanRevenueCaption();
}
function salesRevenueHero(s){
  const plan=getPlan("sales","sales_amount"),financial=financialSalesMetrics(s),percent=plan?financial.incoming/plan*100:0;
  return `<div class="department-hero sales"><div class="dept-hero-top"><div><h2>Продажи</h2><div class="dept-kicker">ОБЩАЯ СУММА ПОСТУПЛЕНИЙ</div></div><div class="dept-ring" style="--ring:${Math.max(0,Math.min(100,percent))*3.6}deg"><span>${plan?Math.round(percent)+"%":"—"}</span></div></div><div class="dept-value">${money(financial.incoming)}</div><div class="dept-plan"><span>План ${plan?money(plan):"—"}</span><span>${plan?`Выполнение ${pct(percent)}`:"Заполни план"}</span></div><div class="dept-substats"><div><span>Продажи</span><strong>${fmt(s.sales)}</strong></div><div><span>Сделки</span><strong>${fmt(s.deals)}</strong></div><div><span>Средний чек</span><strong>${money(financial.averageCheck)}</strong></div></div></div>`;
}
function renderHub(){
  const s=state.sales.overall.total.metrics,p=state.production.kpi,financial=financialSalesMetrics(s);
  $("#hub").innerHTML=`<section class="department-directory" aria-label="Разделы операционного дашборда">
    <header class="operations-hero">
      <div class="operations-hero-copy"><div class="eyebrow">MAVIS GROUP · ОПЕРАЦИОННЫЙ ЦЕНТР</div><h2>Пульс бизнеса</h2><p>Главные результаты месяца и быстрый вход в рабочие контуры команды.</p></div>
      <div class="operations-hero-stats"><div><span>Поступления</span><strong>${money(financial.incoming)}</strong><small>${esc(incomingRevenueCaption())}</small></div><div><span>Производство</span><strong>${money(p.closed_amount)}</strong><small>${fmt(p.closed_count)} закрыто</small></div><div><span>Чистая выручка</span><strong>${financeAmount("value")}</strong><small>${esc(cleanRevenueCaption())}</small></div></div>
    </header>
    <div class="directory-heading"><div><div class="eyebrow">КОНТУРЫ УПРАВЛЕНИЯ</div><h3>Работа отделов</h3></div><p>Открывайте раздел — показатели, первичные данные и расшифровки остаются внутри одного контура.</p></div>
    <div class="department-directory-grid">
      <button type="button" class="department-entry sales-entry" data-open-view="sales"><span class="entry-kicker">01 · Коммерция</span><strong>Продажи</strong><b>${money(financial.incoming)}</b><small>Общая сумма поступлений · ${fmt(s.sales)} продаж</small><i>Открыть →</i></button>
      <button type="button" class="department-entry experts-entry" data-open-view="department-experts"><span class="entry-kicker">02 · Исполнение</span><strong>Эксперты</strong><b>${money(p.closed_amount)}</b><small>${fmt(p.closed_count)} закрыто · производство и эксперты</small><i>Открыть →</i></button>
      <button type="button" class="department-entry calls-entry" data-open-view="sales-calls"><span class="entry-kicker">03 · Контроль качества</span><strong>Звонки продаж</strong><b>Jarvis</b><small>Записи, расшифровки, оценка и рекомендации РОПу</small><i>Открыть →</i></button>
      <button type="button" class="department-entry overview-entry" data-open-view="overview"><span class="entry-kicker">04 · Руководителю</span><strong>Общий краткий свод</strong><b>${fmt(s.sales)} продаж</b><small>Продажи, производство, риски и оперативные сигналы</small><i>Открыть →</i></button>
      <button type="button" class="department-entry marketing-entry" data-open-view="marketing"><span class="entry-kicker">05 · Привлечение</span><strong>Маркетинг</strong><b>Bitrix24</b><small>Лиды, источники, конверсия и экономика кампаний</small><i>Открыть →</i></button>
      <button type="button" class="department-entry audit-entry" data-open-view="crm-audit"><span class="entry-kicker">06 · Качество данных</span><strong>Аудит CRM</strong><b>Контроль</b><small>Ежедневный свод и карточки сделок для разбора</small><i>Открыть →</i></button>
      <button type="button" class="department-entry muted-entry" data-open-view="expert-calls"><span class="entry-kicker">07 · В разработке</span><strong>Звонки экспертов</strong><b>Скоро</b><small>Контур оставлен пустым до подключения данных</small><i>Открыть →</i></button>
    </div>
  </section>`;
}
function integrationState(status){return ({not_configured:"Интеграция ещё не настроена",invalid_configuration:"Некорректная настройка интеграции",unavailable:"Источник временно недоступен",stale:"Показаны последние полученные данные"})[status]||"Данные обновляются"}
function renderCallsPlaceholder(){
  $("#sales-calls").innerHTML=`<div class="section-page"><h2>Звонки продажи</h2><p class="section-page-lead">Здесь появятся показатели Jarvis по последнему дню звонков.</p><div class="integration-state">Загрузка данных Jarvis…</div></div>`;
  $("#expert-calls").innerHTML=`<div class="section-page"><h2>Звонки эксперты</h2><p class="section-page-lead">Данные и правила оценки ещё не настроены. Раздел оставлен пустым намеренно — показатели появятся после подключения источника.</p><div class="integration-state">Нет подключённых данных</div></div>`;
}
async function loadJarvisExperience(){
  const target=$("#sales-calls");if(!target)return;
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
      ${`<div class="signal-card violet nps-signal"><div class="signal-top"><span>NPS вручную</span><span class="signal-arrow">+</span></div><div class="signal-value">${npsText(nps)}</div><div class="signal-note">${npsMeta.count?`${fmt(npsMeta.count)} оценок · среднее`:'Оценок пока нет'}</div><button class="signal-action" data-open-nps="1">+ Добавить оценку</button></div>`}
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
      ["sales","Число продаж в отчётном периоде","num"],
      ["lead_to_sale_rate","% из лида в продажу","pct"],
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
      ["sales","Число продаж в отчётном периоде","num"],
      ["qualified_to_sale_rate","% из квал. лида в продажу","pct"],
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
      ["sales","Число продаж в отчётном периоде","num"],
      ["deal_to_sale_rate","Конверсия из созданной сделки в продажу","pct"],
      ["average_check","Средний чек","money"],
      ["sales_amount","Выручка","money"]
    ]
  }
];

function rnpGroup(name){return (state.sales.groups||[]).find(x=>x.name===name)}
function isPctMetric(k){return ["qualified_rate","lead_to_deal_rate","lead_to_sale_rate","qualified_to_sale_rate","deal_to_sale_rate","product_sale_rate"].includes(k)}
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
function rnpPlanCell(groupKey,metric,type,fact){
  const p=getPlan("sales",metric,"source_group",groupKey);
  return `<span>${p?format(p,type):"—"}</span><strong>${format(fact,type)}</strong><span>${p?pct(Number(fact||0)/p*100):"—"}</span>`;
}
function rnpMonthlyTable(cfg,g){
  const m=g?.current?.metrics||{};
  return `<div class="rnp-month-table">
    <div class="rnp-month-head"><span>Показатель</span><span>План</span><span>Факт</span><span>%</span></div>
    ${cfg.metrics.map(([k,label,type])=>`<div class="rnp-month-row"><span>${esc(label)}</span>${rnpPlanCell(cfg.key,k,type,m[k]||0)}</div>`).join("")}
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
  const metrics=periodType==="previous"
    ? [["sales","Продажи","num"],["sales_amount","Выручка","money"],["average_check","Средний чек","money"]]
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
        ${rnpDailyTable(cfg,g,w,periodType,metrics)}
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
function rnpBlock(cfg){
  const g=rnpGroup(cfg.key)||{current:{metrics:{},weeks:{},days:{}},previous:{metrics:{}},total:{metrics:{}}};
  const c=g.current.metrics||{},p=g.previous.metrics||{},t=g.total.metrics||{};
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
          <span>Отчётный период</span>
          <strong>${money(c.sales_amount||0)}</strong>
          <small>${fmt(c.sales||0)} продаж</small>
        </div>
        <div>
          <span>Предыдущий период / хвост</span>
          <strong>${money(p.sales_amount||0)}</strong>
          <small>${fmt(p.sales||0)} продаж</small>
        </div>
        <div class="rnp-total">
          <span>Итого продажи месяца</span>
          <strong>${money(t.sales_amount||0)}</strong>
          <small>${fmt(t.sales||0)} продаж</small>
        </div>
        <div>
          <span>План выручки</span>
          <strong>${plan?money(plan):"—"}</strong>
          <small>${plan?pct((t.sales_amount||0)/plan*100):"не заполнен"}</small>
        </div>
      </div>
    </summary>

    <div class="rnp-block-expanded">
      ${rnpMonthlyTable(cfg,g)}
      <details class="rnp-subdetails">
        <summary><strong>Недельная динамика</strong><span>план / факт · раскрывается до дней</span></summary>
        ${rnpWeekTable(cfg,g,"total")}
      </details>
      ${rnpSourceList(cfg)}
    </div>
  </details>`;
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
function renderSales(){
  const x=state.sales.overall.total.metrics,financial=financialSalesMetrics(x);
  const sf=state.sales.sale_filter||{};
  const stageText=(sf.stage_names||[]).length?(sf.stage_names||[]).join(", "):"Предоплата + успешная продажа";
  $("#sales").innerHTML=`
    <div class="toolbar dept-toolbar rnp-toolbar">
      <div><div class="eyebrow">ОТДЕЛ ПРОДАЖ</div><div class="muted">Три блока продаж → план/факт → недели → дни → источники</div></div>
      <div class="toolbar-actions"><button class="btn soft-action" data-open-team="manager">+ Менеджер</button><button class="btn ghost" id="openPlanSales">Все планы</button></div>
    </div>

    <div class="rnp-overall-strip">
      <div><span>Общая сумма поступлений</span><strong>${money(financial.incoming)}</strong><small>${esc(incomingRevenueCaption())}</small></div>
      <div><span>Чистая выручка</span><strong>${financeAmount("value")}</strong><small>${esc(cleanRevenueCaption())}</small></div>
      <div><span>Подрядчики</span><strong>${financeAmount("contractor_amount")}</strong><small>${esc(contractorCaption())}</small></div>
      <div><span>Продажи месяца</span><strong>${fmt(x.sales)}</strong></div>
      <div><span>Средний чек</span><strong>${money(financial.averageCheck)}</strong></div>
    </div>

    <div class="sales-semantics-note"><strong>Финансовая логика:</strong> общая сумма поступлений = чистая выручка + подрядчики из приложения «Чистая выручка». Суммы в разбивках по менеджерам, источникам, неделям и дням остаются CRM-расшифровкой: подрядчики не распределяются по конкретному менеджеру, источнику или дню.</div>
    <div class="rnp-three-blocks">${RNP_GROUPS.map(rnpBlock).join("")}</div>
    <div class="sales-semantics-note"><strong>Логика воронки:</strong> «Созданные сделки» включают все сделки, созданные в месяце. «Продажи» и общая сумма поступлений — только стадии 14. Предоплата получена и 15. Продажа успешна. Отказы и слитые сделки в продажи не входят.</div>

    <section class="rnp-secondary">
      <details class="rnp-main-details" open><summary><div><strong>Разбивка по менеджерам</strong><span>Роман / Ирина → холодные / входящие / повторные → источник → период → даты</span></div></summary>${rnpManagerMatrix()}</details>
      <details class="rnp-main-details"><summary><div><strong>Разбивка по продуктам</strong><span>${fmt(x.products)} продуктов в сделках · ${fmt(x.sold_products)} продано</span></div></summary>
        ${salesProductTable()}
        <div class="product-definition-note"><strong>Конверсия по продуктам</strong> = количество продуктов из сделок, созданных в выбранном месяце, которые продались в этом же месяце / количество продуктов в сделках, созданных в выбранном месяце. <strong>Хвост в эту конверсию не входит.</strong></div>
      </details>
    </section>
  `;
  $("#openPlanSales")?.addEventListener("click",()=>openPlanDialog("sales"));
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
  const rows=experts().map(r=>`<tr><td>${esc(r.name)}</td><td class="num">${tdLink(r.closed_count,"production","closed_count","num",{expert:r.name})}</td><td class="num">${tdLink(r.closed_amount,"production","closed_amount","money",{expert:r.name})}</td><td class="num">${tdLink(r.avg_production_days,"production","avg_production_days","days",{expert:r.name})}</td><td class="num">${tdLink(r.within_norm_pct,"production","within_norm_pct","pct",{expert:r.name})}</td>${compact?"":`<td class="num">${getPlan("production","closed_amount","expert",r.name)?money(getPlan("production","closed_amount","expert",r.name)):"—"}</td><td class="num">${getPlan("production","closed_amount","expert",r.name)?pct(r.closed_amount/getPlan("production","closed_amount","expert",r.name)*100):"—"}</td><td class="num">${npsText(expertNps(r))}${expertNpsMeta(r).count?` · ${fmt(expertNpsMeta(r).count)} оц.`:''} <button class="mini-edit" data-nps-edit="1" data-expert="${attr(r.name)}">+ добавить</button></td><td class="num">${tdLink(r.active_count,"production","active","num",{expert:r.name})}</td><td class="num">${tdLink(r.returns_count,"production","returns_count","num",{expert:r.name})}</td>`}</tr>`).join("");
  return `<div class="scroll-x"><table><thead><tr><th>Эксперт</th><th class="num">Закрыто</th><th class="num">Сумма</th><th class="num">Срок</th><th class="num">В норме</th>${compact?"":"<th class='num'>План BYN</th><th class='num'>% плана</th><th class='num'>NPS вручную</th><th class='num'>Активно</th><th class='num'>Возвраты</th>"}</tr></thead><tbody>${rows}</tbody></table></div>`;
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
    <summary><strong>Недельная динамика</strong><span>план / факт · раскрывается до дней</span></summary>
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
function renderProduction(){
  const npsMeta=overallManualNpsMeta();
  const p={...state.production.kpi,nps_avg:npsMeta.value};
  $("#production").innerHTML=`<div class="toolbar dept-toolbar production-toolbar"><div><div class="eyebrow">ПРОИЗВОДСТВО</div><div class="muted">${esc(state.production.period_label)} · результат, поток, воронка и сроки</div></div><div class="toolbar-actions"><button class="btn soft-action" data-open-team="expert">+ Добавить эксперта</button><button class="btn soft-action" data-open-nps="1">+ NPS вручную</button><button class="btn ghost" id="openPlanProd">Изменить планы</button></div></div>
  <div class="department-page-head production-page-head">${deptHero({kind:'production',title:'Результат производства',eyebrow:'ЗАКРЫТЫЕ АКТЫ',value:p.closed_amount,valueType:'money',scope:'production',metric:'closed_amount',substats:[{label:'Закрыто продуктов',value:p.closed_count},{label:'Средний чек',value:p.avg_check,type:'money'},{label:'В нормативе',value:p.within_norm_pct,type:'pct'}]})}${manualNpsCard(p.nps_avg,npsMeta.count)}</div>
  <div class="section-title">Результат периода</div>
  <div class="kpi-grid compact-cards">${card("Закрыто продуктов",p.closed_count,"production","closed_count","num")}${card("Сумма закрытых",p.closed_amount,"production","closed_amount","money")}${card("Средний чек",p.avg_check,"production","avg_check","money")}</div>
  ${productionWeeklyDynamics()}
  <div class="section-title">Поток выбранного периода</div>
  <div class="kpi-grid dense">${card("Пришло продуктов",p.new_count,"production","new_count","num")}${card("Сумма пришедших",p.new_amount,"production","new_amount","money")}${card("Закрыто из пришедших",p.period_closed_count,"production","period_closed_count","num")}${card("Сумма закрытых из пришедших",p.period_closed_amount,"production","period_closed_amount","money")}${card("Конверсия в успех",p.new_to_success_pct,"production","new_to_success_pct","pct",{},`${fmt(p.period_closed_count)} закрыто из ${fmt(p.new_count)} пришедших`)}</div>
  <div class="section-title">Воронка и сроки</div>
  <div class="kpi-grid dense">${card("Ёмкость периода",p.capacity_count,"production","capacity_count","num",{},money(p.capacity_amount))}${card("Возвраты",p.returns_count,"production","returns_count","num",{},money(p.returns_amount))}${card("Средний срок",p.avg_production_days,"production","avg_production_days","days")}${card("Отклонение от нормы",p.avg_deviation_days,"production","avg_deviation_days","days")}${card("В нормативе",p.within_norm_pct,"production","within_norm_pct","pct")}</div>
  <details class="rnp-main-details production-product-breakdown"><summary><div><strong>Разбивка по продуктам</strong><span>нажми на показатель → эксперт → продукт → компания</span></div></summary>${prodProductTable()}</details>
  <div class="grid-2">${panel("Эксперты",expertTable(false),"состав можно менять прямо здесь")}${panel("Стадии производства",prodStages(),"количество и сумма")}</div>`;
  $("#openPlanProd")?.addEventListener("click",()=>openPlanDialog("production"));
}

function renderExperts(){
  const cards=experts().map(e=>{const nm=expertNpsMeta(e),nv=nm.value;return `<div class="expert-card"><div class="expert-card-top"><div><div class="expert-name">${esc(e.name)}</div><div class="expert-result">${money(e.closed_amount)}</div></div><button class="btn nps-button" data-nps-edit="1" data-expert="${attr(e.name)}">${nv===null?'+ Добавить NPS':'NPS '+fmt(nv)+' · '+fmt(nm.count)+' оц. · добавить'}</button></div><div class="expert-stats"><div><span>Закрыто</span><strong>${tdLink(e.closed_count,"production","closed_count","num",{expert:e.name})}</strong></div><div><span>В работе</span><strong>${tdLink(e.active_count,"production","active","num",{expert:e.name})}</strong></div><div><span>В норме</span><strong>${pct(e.within_norm_pct)}</strong></div><div><span>Возвраты</span><strong>${tdLink(e.returns_count,"production","returns_count","num",{expert:e.name})}</strong></div></div><details class="nested"><summary>По продуктам (${e.products.length})</summary><div class="nested-body"><table><thead><tr><th>Продукт</th><th class="num">Закрыто</th><th class="num">Сумма</th><th class="num">Срок</th><th class="num">В норме</th></tr></thead><tbody>${e.products.map(p=>`<tr><td>${esc(p.name)}</td><td class="num">${tdLink(p.closed_count,"production","closed_count","num",{expert:e.name,product:p.name})}</td><td class="num">${tdLink(p.closed_amount,"production","closed_amount","money",{expert:e.name,product:p.name})}</td><td class="num">${tdLink(p.avg_days,"production","avg_production_days","days",{expert:e.name,product:p.name})}</td><td class="num">${tdLink(p.within_norm_pct,"production","within_norm_pct","pct",{expert:e.name,product:p.name})}</td></tr>`).join("")}</tbody></table></div></details></div>`}).join("");
  $("#experts").innerHTML=`<div class="toolbar dept-toolbar"><div><div class="eyebrow">ЭКСПЕРТЫ</div><div class="muted">Закрытые продукты, нагрузка, нормативы и NPS — NPS всегда вводит руководитель</div></div><div class="toolbar-actions"><button class="btn primary-light" data-open-team="expert">+ Добавить эксперта из Bitrix</button><button class="btn soft-action" data-open-nps="1">+ Внести NPS вручную</button></div></div><div class="expert-grid">${cards||'<div class="empty">Эксперты не выбраны. Нажми «Добавить эксперта из Bitrix».</div>'}</div>`;
}

function reasonTable(){return `<table><thead><tr><th>Причина зависания</th><th class="num">Кол-во</th><th class="num">%</th></tr></thead><tbody>${state.production.dormant.reasons.map(r=>`<tr><td>${esc(r.name)}</td><td class="num">${tdLink(r.count,"production","dormant_count","num",{reason:r.name})}</td><td class="num">${tdLink(r.pct,"production","dormant_count","pct",{reason:r.name})}</td></tr>`).join("")}</tbody></table>`}
function returnReasonTable(){return `<table><thead><tr><th>Причина возврата</th><th class="num">Кол-во</th><th class="num">Сумма</th><th class="num">%</th></tr></thead><tbody>${state.production.return_reasons.map(r=>`<tr><td>${esc(r.name)}</td><td class="num">${tdLink(r.count,"production","returns_count","num",{reason:r.name})}</td><td class="num">${money(r.amount)}</td><td class="num">${pct(r.pct)}</td></tr>`).join("")}</tbody></table>`}
function overdueTable(){return `<table><thead><tr><th>Просрочка</th><th class="num">Кол-во</th></tr></thead><tbody>${Object.entries(state.production.overdue.buckets).map(([k,v])=>`<tr><td>${esc(k)}</td><td class="num">${fmt(v)}</td></tr>`).join("")}</tbody></table>`}
function renderRisks(){
  const p=state.production.kpi;
  const crit=(state.dormant_config?.selected_stages||[]).join(", ")||"все активные стадии";
  $("#risks").innerHTML=`<div class="criteria-box"><strong>Критерий «Зависшие»:</strong> воронка ID 30 + выбранные стадии + <strong>предполагаемая дата закрытия попадает в выбранный период</strong>. Поэтому для сентября считаются только карточки с предполагаемой датой закрытия в сентябре. Стадии: ${esc(crit)}. Всего активных карточек в воронке независимо от даты: ${fmt(p.dormant_all_count||0)}.</div>
  <div class="kpi-grid">
    ${card("Зависшие периода",p.dormant_count,"production","dormant_count","num",{},money(p.dormant_amount))}
    ${card("Причина заполнена",p.dormant_with_reason_pct,"production","dormant_with_reason_pct","pct",{},`${fmt(state.production.dormant.with_reason_count)} из ${fmt(p.dormant_count)} сделок`)}
    ${card("Вернулось в производство",p.returned_to_production,"production","returned_to_production","num",{},money(p.returned_to_production_amount))}
    ${card("Просрочена ожидаемая дата",state.production.overdue.count,"production","overdue","num",{},money(state.production.overdue.amount))}
  </div>
  <div class="grid-3">${panel("Причины зависания",reasonTable(),"% считается от зависших с предполагаемой датой в выбранном периоде")}${panel("Причины возврата",returnReasonTable())}${panel("Просрочка ожидаемой даты",overdueTable())}</div>`;
}

function contextOptions(scope,type){
  if(type==="overall")return [{value:"",label:"Общий план"}];
  if(scope==="sales"&&type==="manager")return managers().map(x=>({value:x.name,label:x.name}));
  if(scope==="sales"&&type==="source_group")return state.sales.groups.map(x=>({value:x.name,label:x.name}));
  if(scope==="sales"&&type==="source")return state.sales.exact_sources.map(x=>({value:x.name,label:x.name}));
  if(scope==="sales"&&type==="product")return state.sales.product_categories.map(x=>({value:x.name,label:x.name}));
  if(scope==="production"&&type==="expert")return experts().map(x=>({value:x.name,label:x.name}));
  if(scope==="production"&&type==="product")return state.production.products.map(x=>({value:x.name,label:x.name}));
  return [];
}

function teamSettings(){
  const users=state.available_users||[];
  const block=(role,title,names)=>`<div class="team-block"><div class="subhead">${esc(title)}</div><div class="team-tags">${names.map(n=>`<span class="team-tag">${esc(n)} <button data-team-remove="1" data-role="${role}" data-name="${attr(n)}">×</button></span>`).join('')}</div><div class="team-add"><select data-team-select="${role}">${users.map(u=>`<option value="${attr(u)}">${esc(u)}</option>`).join('')}</select><button class="btn ghost" data-team-add="${role}">Добавить</button></div></div>`;
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

function renderAll(){
  if(!state?.ok){const e=`<div class="error">${esc(state?.error||"Ошибка загрузки")}</div>`;$$('.view').forEach(x=>x.innerHTML=e);return}
  renderOverview();renderSales();renderProduction();renderExperts();renderExpertsDepartment();renderRisks();renderForecast();renderPlans();renderCallsPlaceholder();renderMarketingPlaceholder();renderCrmAuditPlaceholder();renderHub();warmOperationsSections();openView(requestedView(),false);
  $("#liveDot").className="ok";const d=new Date(state.updated_at);$("#liveText").textContent=`BITRIX ONLINE · ${d.toLocaleTimeString("ru-RU",{hour:"2-digit",minute:"2-digit",second:"2-digit"})}`;
}

const VIEW_TITLES={
  hub:"Все разделы", overview:"Общий краткий свод", sales:"Продажи", "department-experts":"Эксперты",
  "sales-calls":"Звонки продажи", "expert-calls":"Звонки эксперты", marketing:"Маркетинг", "crm-audit":"Аудит CRM",
  risks:"Риски", dynamics:"Динамика", forecast:"Прогноз", plans:"Планы и настройки"
};
function requestedView(){const value=location.hash.slice(1);return VIEW_TITLES[value]?value:"hub"}
function openView(view,updateHistory=true){
  if(!$("#"+view))return;
  $$(".view").forEach(item=>item.classList.toggle("active",item.id===view));
  const isHub=view==="hub";
  $("#sectionNav").classList.toggle("hidden",isHub);
  $("#sectionNavTitle").textContent=VIEW_TITLES[view]||"";
  if(view==="dynamics")renderDynamics();
  if(view==="forecast")renderForecast();
  if(view==="sales-calls")loadJarvisExperience();
  if(view==="marketing")loadOperationsSection("marketing");
  if(view==="crm-audit")loadOperationsSection("crm-audit");
  if(updateHistory){history.pushState(null,"",view==="hub"?location.pathname:`#${view}`);window.scrollTo({top:0,behavior:window.matchMedia("(prefers-reduced-motion: reduce)").matches?"auto":"smooth"});}
}

function loadingView(month){
  const label=$("#month").selectedOptions[0]?.textContent||month;
  return `<div class="loading-state"><div class="loading-spinner"></div><div><div class="loading-title">Синхронизирую ${esc(label)}</div><div class="muted">Интерфейс уже доступен. Первый расчёт Bitrix идёт в фоне; дальше данные будут открываться из кеша сразу.</div></div></div>`;
}

function customQueryParams(){
  if($("#period").value!=="custom")return "";
  const a=$("#customStart").value,b=$("#customEnd").value;
  return `&custom_start=${encodeURIComponent(a)}&custom_end=${encodeURIComponent(b)}`;
}
async function load(){
  const month=$("#month").value,period=$("#period").value;
  if(loadTimer){clearTimeout(loadTimer);loadTimer=null}
  if(loadController)loadController.abort();
  loadController=new AbortController();

  const sameState=state&&state.month_key===month&&(state.period||"month")===period;
  if(!sameState){
    const cached=readBrowserSnapshot(month,period);
    if(cached){
      state=cached.snapshot;
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
    const r=await fetch(`/api/snapshot?month=${encodeURIComponent(month)}&period=${encodeURIComponent(period)}${customQueryParams()}`,{cache:"no-store",signal:loadController.signal});
    if(r.status===401){location.href="/login";return}
    const j=await r.json();
    const offlineSnapshot=r.headers.get("X-Mavis-Cache")==="offline";

    if(r.status===202 || j.loading){
      $("#liveDot").className="";
      $("#liveText").textContent=state&&state.month_key===month
        ?"ПОКАЗАНЫ ПОСЛЕДНИЕ ДАННЫЕ · Bitrix обновляется в фоне"
        :"BITRIX · ПЕРВИЧНАЯ СИНХРОНИЗАЦИЯ";
      loadTimer=setTimeout(load,2500);
      return;
    }
    if(!r.ok)throw new Error(j.detail||j.error||JSON.stringify(j));

    state=j;
    saveBrowserSnapshot(j);
    renderAll();
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
  const label=(d.scope==="sales"?SALES_LABELS[d.metric]?.[0]:PROD_LABELS[d.metric]?.[0])||d.metric;
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
function openTeamDialog(role="expert"){
  teamTargetRole=role;$("#teamRole").value=role;const users=state?.available_users||[];$("#teamUser").innerHTML=users.map(u=>`<option value="${attr(u)}">${esc(u)}</option>`).join('');$("#teamDialogTitle").textContent=role==='expert'?'Добавить эксперта из Bitrix':'Добавить менеджера из Bitrix';$("#teamDialog").showModal();
}
function openPlanDialog(scope="sales",contextType="overall",contextKey=""){
  $("#planScope").value=scope;
  updatePlanContextTypes();
  const typeSel=$("#planContextType");
  const wanted=[...typeSel.options].find(o=>o.value===contextType && !o.disabled);
  typeSel.value=wanted?contextType:"overall";
  const opts=contextOptions(scope,typeSel.value);
  $("#planContextKey").innerHTML=opts.map(o=>`<option value="${attr(o.value)}">${esc(o.label)}</option>`).join('');
  if(opts.some(o=>o.value===contextKey))$("#planContextKey").value=contextKey;
  buildPlanForm();
  $("#planDialog").showModal();
}
function updatePlanContextTypes(){const scope=$("#planScope").value;const sel=$("#planContextType");[...sel.options].forEach(o=>o.disabled=(scope==="sales"&&o.value==="expert")||(scope==="production"&&["manager","source_group","source"].includes(o.value)));if(sel.selectedOptions[0]?.disabled)sel.value="overall"}
function updatePlanKey(){const opts=contextOptions($("#planScope").value,$("#planContextType").value);$("#planContextKey").innerHTML=opts.map(o=>`<option value="${attr(o.value)}">${esc(o.label)}</option>`).join('');buildPlanForm()}
function buildPlanForm(){if(!state)return;const scope=$("#planScope").value,type=$("#planContextType").value,key=$("#planContextKey").value||"",defs=scope==="sales"?SALES_LABELS:PROD_LABELS,vals=state.plans?.[`${scope}|${type}|${key}`]||{};$("#planForm").innerHTML=Object.entries(defs).map(([metric,[label]])=>`<div class="plan-field"><label>${esc(label)}</label><input type="number" step="0.01" data-plan-metric="${attr(metric)}" value="${vals[metric]??''}"></div>`).join('')}
async function savePlan(){const scope=$("#planScope").value,context_type=$("#planContextType").value,context_key=$("#planContextKey").value||"",values={};$$('[data-plan-metric]').forEach(i=>values[i.dataset.planMetric]=Number(i.value||0));const r=await fetch('/api/plans',{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({month:$("#month").value,scope,context_type,context_key,values,admin_key:$("#adminKey").value})});if(!r.ok){alert(await r.text());return}const j=await r.json();state.plans=j.dict;$("#planDialog").close();renderAll()}

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
  $("#month").addEventListener('change',()=>{state=null;load()});$("#period").addEventListener('change',()=>{const custom=$("#period").value==="custom";$("#customPeriod").classList.toggle("hidden",!custom);if(custom){const m=$("#month").value+"-01";if(!$("#customStart").value)$("#customStart").value=m;if(!$("#customEnd").value){const [y,mo]=$("#month").value.split('-').map(Number);$("#customEnd").value=new Date(y,mo,0).toISOString().slice(0,10)}}state=null;load()});$("#customStart").addEventListener('change',()=>{if($("#period").value==="custom"){state=null;load()}});$("#customEnd").addEventListener('change',()=>{if($("#period").value==="custom"){state=null;load()}});$("#refreshBtn").addEventListener('click',load);$("#tvBtn").addEventListener('click',()=>document.body.classList.toggle('tv-mode'));
  window.addEventListener("hashchange",()=>openView(requestedView(),false));
  document.body.addEventListener('click',e=>{
    const view=e.target.closest('[data-open-view],[data-view]');if(view){openView(view.dataset.openView||view.dataset.view);return}
    const cb=e.target.closest('[data-comment-scope]');if(cb){e.stopPropagation();commentTarget={scope:cb.dataset.commentScope,metric:cb.dataset.commentMetric,title:cb.dataset.commentTitle};$('#commentTitle').textContent=commentTarget.title;$('#commentText').value=getComment(commentTarget.scope,commentTarget.metric);$('#commentDialog').showModal();return}
    const np=e.target.closest('[data-nps-edit]');if(np){e.stopPropagation();openNpsDialog(np.dataset.expert||'');return}
    const openNps=e.target.closest('[data-open-nps]');if(openNps){e.stopPropagation();openNpsDialog(openNps.dataset.expert||'');return}
    const openTeam=e.target.closest('[data-open-team]');if(openTeam){e.stopPropagation();openTeamDialog(openTeam.dataset.openTeam||'expert');return}
    const productPlan=e.target.closest('[data-edit-product-plan]');if(productPlan){e.stopPropagation();openPlanDialog("production","product",productPlan.dataset.editProductPlan||"");return}
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
    const x=e.target.closest('[data-drill="1"]');if(x)openDrill(x)
  });
  document.body.addEventListener('change',e=>{if(e.target.matches('[data-audit-filter]'))renderCrmAuditRows()});
  $("#closeDrill").addEventListener('click',()=>$("#drillDialog").close());$("#drillSearch").addEventListener('input',renderDrillRows);
  $("#closePlan").addEventListener('click',()=>$("#planDialog").close());$("#planScope").addEventListener('change',()=>{updatePlanContextTypes();updatePlanKey()});$("#planContextType").addEventListener('change',updatePlanKey);$("#planContextKey").addEventListener('change',buildPlanForm);$("#savePlan").addEventListener('click',savePlan);

  $("#closeComment").addEventListener('click',()=>$("#commentDialog").close());
  $("#saveComment").addEventListener('click',async()=>{if(!commentTarget)return;const r=await fetch('/api/comment',{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({month:$('#month').value,scope:commentTarget.scope,metric:commentTarget.metric,comment:$('#commentText').value})});if(!r.ok){alert(await r.text());return}state.comments=(await r.json()).comments;$('#commentDialog').close();renderAll()});
  $("#closeNps").addEventListener('click',()=>$("#npsDialog").close());
  $("#npsExpert").addEventListener('change',()=>{npsTarget=$("#npsExpert").value;$("#npsValue").value='';$("#npsNote").value='';renderNpsHistory()});
  $("#saveNps").addEventListener('click',async()=>{npsTarget=$("#npsExpert").value||npsTarget;if(!npsTarget)return;const raw=$("#npsValue").value;if(raw===''){alert('Введи NPS от 0 до 10');return}const r=await fetch('/api/nps',{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({month:$('#month').value,expert:npsTarget,value:Number(raw),note:$('#npsNote').value,admin_key:$('#npsAdminKey').value})});if(!r.ok){alert(await r.text());return}state.manual_nps=(await r.json()).manual_nps;$("#npsValue").value='';$("#npsNote").value='';renderNpsHistory();renderAll()});
  $("#closeTeam").addEventListener('click',()=>$("#teamDialog").close());
  $("#closeTrafficGroup").addEventListener('click',()=>$("#trafficGroupDialog").close());
  $("#addTrafficSource").addEventListener('click',addTrafficSourceToGroup);
  $("#saveTrafficGroup").addEventListener('click',saveTrafficGroupDialog);
  $("#saveTeamMember").addEventListener('click',async()=>{const name=$("#teamUser").value,role=$("#teamRole").value;if(!name)return;const r=await fetch('/api/team',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({role,name,admin_key:$("#teamDialogAdminKey").value||''})});if(!r.ok){alert(await r.text());return}state.team=(await r.json()).team;$("#teamDialog").close();renderAll()});
  const es=new EventSource('/events');es.addEventListener('update',()=>load());es.onerror=()=>{$("#liveDot").className='bad'};
  window.addEventListener("offline",()=>{if(state){$("#liveDot").className="bad";$("#liveText").textContent="ПОКАЗАНА ПОСЛЕДНЯЯ ВЕРСИЯ · НЕТ СЕТИ"}});
  window.addEventListener("online",()=>load());
  load();setInterval(load,120000);
}
init();


// Build marker: helps verify that the browser is not showing stale frontend files.
window.addEventListener("DOMContentLoaded",()=>{
  const top=document.querySelector(".topbar")||document.querySelector("header")||document.body;
  if(!document.querySelector("#buildMarker")){
    const b=document.createElement("span");
    b.id="buildMarker";
    b.className="build-marker";
    b.textContent="v3.1.0";
    top.appendChild(b);
  }
});
