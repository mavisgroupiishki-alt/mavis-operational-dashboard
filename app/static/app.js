let state=null;
let selectedPeriodType="current";
let drillRows=[];
let loadTimer=null;
let loadController=null;

const SALES_LABELS={
  leads:["Лиды","num"],qualified:["Квал. лиды","num"],qualified_rate:["Лид → квал.","pct"],lead_to_deal_rate:["Квал. → сделка","pct"],
  deals:["Сделки","num"],deal_amount:["Сумма сделок","money"],sales:["Продажи","num"],sales_amount:["Сумма продаж","money"],average_check:["Средний чек","money"],
  deal_to_sale_rate:["Сделка → продажа","pct"],products_per_deal:["Продуктов / сделку","num"],products:["Продукты в сделках","num"],product_amount:["Сумма продуктов","money"],
  sold_products:["Продано продуктов","num"],sold_product_amount:["Сумма прод. продуктов","money"],average_product_check:["Средний чек продукта","money"],product_sale_rate:["Продукт → продажа","pct"],
  paid_amount:["Оплачено","money"],net_revenue:["Чистая выручка","money"]
};
const PROD_LABELS={
  closed_amount:["Закрытые акты","money"],closed_count:["Закрытые продукты","num"],new_count:["Новые от ОП","num"],new_amount:["Сумма новых","money"],
  period_closed_count:["Закрыто из новых","num"],period_closed_amount:["Сумма закрытых из новых","money"],new_to_success_pct:["Новые → успех","pct"],avg_check:["Средний чек","money"],
  capacity_count:["Ёмкость, шт","num"],capacity_amount:["Ёмкость, BYN","money"],returns_count:["Возвраты","num"],returns_amount:["Сумма возвратов","money"],
  avg_production_days:["Срок производства","days"],avg_full_cycle_days:["Полный цикл","days"],avg_deviation_days:["Отклонение от нормы","days"],within_norm_pct:["В нормативе","pct"],base_bonus:["Базовая премия","money"],
  nps_avg:["NPS","num"],act_share_pct:["С актом","pct"],inactive_count:["Без изменений 7+ дней","num"],dormant_count:["Зависшие","num"],returned_to_production:["Вернулось в производство","num"],dormant_with_reason_pct:["Причина зависания заполнена","pct"]
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
  const pr=progress(scope,metric,Number(value||0),ct,ck);
  let pace="";
  if(state?.period==="month"&&state?.pace?.share&&pr.plan&&["sales_amount","sales","closed_amount","closed_count"].includes(metric)){
    const target=pr.plan*state.pace.share,delta=Number(value||0)-target;
    pace=`<div class="kpi-meta"><span>план на сегодня ${format(target,type)}</span><span>${delta>=0?"+":""}${format(delta,type)}</span></div>`;
  }
  return `<div class="card clickable" ${drillAttrs(scope,metric,extra)}><div class="kpi-label">${esc(title)}</div><div class="kpi-value">${format(value,type)}</div><div class="kpi-meta"><span>${pr.plan?`план ${format(pr.plan,type)}`:esc(note)}</span><span>${pr.plan?pct(value/pr.plan*100):""}</span></div>${pr.plan?`<div class="progress"><span class="${pr.cls}" style="width:${Math.min(100,Math.max(0,pr.p))}%"></span></div>`:""}${pace}</div>`;
}
function panel(title,body,note=""){return `<div class="panel"><div class="panel-head"><div class="panel-title">${esc(title)}</div><div class="muted">${esc(note)}</div></div>${body}</div>`}
function tdLink(value,scope,metric,type,extra={}){return `<span class="cell-link" ${drillAttrs(scope,metric,extra)}>${format(value,type)}</span>`}

function renderOverview(){
  const s=state.sales.overall.current.metrics,p=state.production.kpi;
  $("#overview").innerHTML=`
  <div class="kpi-grid">
    ${card("Выручка ОП",s.sales_amount,"sales","sales_amount","money",{period_type:"current"})}
    ${card("Оплачено",s.paid_amount,"sales","paid_amount","money",{period_type:"current"})}
    ${card("Чистая выручка",s.net_revenue,"sales","net_revenue","money",{period_type:"current"},"из поля Bitrix")}
    ${card("Закрытые акты",p.closed_amount,"production","closed_amount","money")}
  </div>
  <div class="kpi-grid">
    ${card("Продажи",s.sales,"sales","sales","num",{period_type:"current"})}
    ${card("Продано продуктов",s.sold_products,"sales","sold_products","num",{period_type:"current"})}
    ${card("Закрыто продуктов",p.closed_count,"production","closed_count")}
    ${card("Ёмкость производства",p.capacity_amount,"production","capacity_amount","money",{},`${fmt(p.capacity_count)} продуктов`)}
  </div>
  <div class="grid-2">
    ${panel("ОП · менеджеры",salesManagerTable(true),"нажми на цифру для расшифровки")}
    ${panel("Производство · эксперты",expertTable(true),"закрытые продукты")}
  </div>
  <div class="grid-3">
    ${panel("Зависшие",`<div class="risk-number">${tdLink(p.dormant_count,"production","dormant_count","num")}</div><div class="muted">${tdLink(p.dormant_amount,"production","dormant_count","money")}</div>`)}
    ${panel("Без изменений 7+ дней",`<div class="risk-number">${tdLink(p.inactive_count,"production","inactive_count","num")}</div><div class="muted">${money(p.inactive_amount)}</div>`)}
    ${panel("Вернулось в производство",`<div class="risk-number">${tdLink(p.returned_to_production,"production","returned_to_production","num")}</div><div class="muted">${money(p.returned_to_production_amount)}</div>`)}
  </div>`;
}

function salesPeriodSelector(){return `<div class="segmented" id="salesPeriodType"><button data-ptype="total" class="${selectedPeriodType==="total"?"active":""}">Итого 3 мес.</button><button data-ptype="current" class="${selectedPeriodType==="current"?"active":""}">Отчётный период</button><button data-ptype="previous" class="${selectedPeriodType==="previous"?"active":""}">Предыдущий период</button></div>`}
function salesManagerTable(compact=false){
  let rows=state.sales.managers.map(m=>{const x=m[selectedPeriodType].metrics;return `<tr><td>${esc(m.name)}</td><td class="num">${tdLink(x.deals,"sales","deals","num",{period_type:selectedPeriodType,manager:m.name})}</td><td class="num">${tdLink(x.sales,"sales","sales","num",{period_type:selectedPeriodType,manager:m.name})}</td><td class="num">${tdLink(x.sales_amount,"sales","sales_amount","money",{period_type:selectedPeriodType,manager:m.name})}</td>${compact?"":`<td class="num">${getPlan("sales","sales_amount","manager",m.name)?money(getPlan("sales","sales_amount","manager",m.name)):"—"}</td><td class="num">${getPlan("sales","sales_amount","manager",m.name)?pct(x.sales_amount/getPlan("sales","sales_amount","manager",m.name)*100):"—"}</td><td class="num">${tdLink(x.deal_to_sale_rate,"sales","deal_to_sale_rate","pct",{period_type:selectedPeriodType,manager:m.name})}</td><td class="num">${tdLink(x.sold_products,"sales","sold_products","num",{period_type:selectedPeriodType,manager:m.name})}</td>`}</tr>`}).join("");
  return `<div class="scroll-x"><table><thead><tr><th>Менеджер</th><th class="num">Сделки</th><th class="num">Продажи</th><th class="num">Выручка</th>${compact?"":"<th class='num'>План BYN</th><th class='num'>% плана</th><th class='num'>Конв.</th><th class='num'>Прод. продукты</th>"}</tr></thead><tbody>${rows}</tbody></table></div>`;
}
function sourceTable(exact=false){
  const rows=(exact?state.sales.exact_sources:state.sales.groups).map(r=>{const x=r[selectedPeriodType].metrics;const extra=exact?{period_type:selectedPeriodType,source:r.name}:{period_type:selectedPeriodType,group:r.name};return `<tr><td>${esc(r.name)}</td>${exact?`<td>${esc(r.group)}</td>`:""}<td class="num">${tdLink(x.leads,"sales","leads","num",extra)}</td><td class="num">${tdLink(x.qualified,"sales","qualified","num",extra)}</td><td class="num">${tdLink(x.deals,"sales","deals","num",extra)}</td><td class="num">${tdLink(x.sales,"sales","sales","num",extra)}</td><td class="num">${tdLink(x.sales_amount,"sales","sales_amount","money",extra)}</td><td class="num">${getPlan("sales","sales_amount",exact?"source":"source_group",r.name)?money(getPlan("sales","sales_amount",exact?"source":"source_group",r.name)):"—"}</td><td class="num">${getPlan("sales","sales_amount",exact?"source":"source_group",r.name)?pct(x.sales_amount/getPlan("sales","sales_amount",exact?"source":"source_group",r.name)*100):"—"}</td><td class="num">${tdLink(x.deal_to_sale_rate,"sales","deal_to_sale_rate","pct",extra)}</td><td class="num">${tdLink(x.sold_products,"sales","sold_products","num",extra)}</td></tr>`}).join("");
  return `<div class="scroll-x"><table><thead><tr><th>${exact?"Источник":"Группа"}</th>${exact?"<th>Группа</th>":""}<th class="num">Лиды</th><th class="num">Квал.</th><th class="num">Сделки</th><th class="num">Продажи</th><th class="num">Выручка</th><th class="num">План</th><th class="num">% плана</th><th class="num">Конв.</th><th class="num">Продукты</th></tr></thead><tbody>${rows}</tbody></table></div>`;
}
function salesProductTable(){
  const rows=state.sales.product_categories.map(r=>{const x=r[selectedPeriodType].metrics;const extra={period_type:selectedPeriodType,product:r.name};return `<tr><td>${esc(r.name)}</td><td class="num">${tdLink(x.products,"sales","products","num",extra)}</td><td class="num">${tdLink(x.product_amount,"sales","product_amount","money",extra)}</td><td class="num">${tdLink(x.sold_products,"sales","sold_products","num",extra)}</td><td class="num">${tdLink(x.sold_product_amount,"sales","sold_product_amount","money",extra)}</td><td class="num">${tdLink(x.average_product_check,"sales","average_product_check","money",extra)}</td><td class="num">${tdLink(x.product_sale_rate,"sales","product_sale_rate","pct",extra)}</td></tr>`}).join("");
  return `<div class="scroll-x"><table><thead><tr><th>Категория</th><th class="num">В сделках</th><th class="num">Сумма</th><th class="num">Продано</th><th class="num">Сумма продаж</th><th class="num">Ср чек</th><th class="num">Конв.</th></tr></thead><tbody>${rows}</tbody></table></div>`;
}
function weeklyGrid(){
  const w=state.sales.overall.current.weeks;
  const defs=[["leads","Лиды","num"],["qualified","Квал. лиды","num"],["qualified_rate","% в квал.","pct"],["lead_to_deal_rate","Квал. → сделка","pct"],["deals","Сделки","num"],["deal_amount","Сумма сделок","money"],["sales","Продажи","num"],["sales_amount","Выручка","money"],["products","Продукты","num"],["product_amount","Сумма продуктов","money"],["sold_products","Продано продуктов","num"],["sold_product_amount","Сумма прод. продуктов","money"]];
  let cells=`<div class="head">Показатель</div>${[1,2,3,4,5].map(i=>`<div class="head">${i} нед.</div>`).join("")}`;
  defs.forEach(([k,label,type])=>{cells+=`<div class="metric">${esc(label)}</div>`;for(let i=0;i<5;i++)cells+=`<div class="value" ${drillAttrs("sales",k,{period_type:"current",week:i})}>${format(w[k]?.[i]||0,type)}</div>`});
  return `<div class="week-grid">${cells}</div>`;
}
function salesStages(){
  const rows=state.sales.stages.map(r=>`<tr><td>${esc(r.name)}</td><td class="num">${tdLink(r.count,"sales","deals","num",{period_type:"total",stage:r.name})}</td><td class="num">${tdLink(r.amount,"sales","deal_amount","money",{period_type:"total",stage:r.name})}</td></tr>`).join("");
  return `<table><thead><tr><th>Стадия</th><th class="num">Сделок</th><th class="num">Сумма</th></tr></thead><tbody>${rows}</tbody></table>`;
}

function salesManagerBreakdowns(){
  const productMap=new Map((state.sales.product_managers||[]).map(x=>[x.name,x.categories||[]]));
  return (state.sales.managers||[]).map(m=>{
    const groups=(m.groups||[]).map(g=>{const x=g[selectedPeriodType].metrics,extra={period_type:selectedPeriodType,manager:m.name,group:g.name};return `<tr><td>${esc(g.name)}</td><td class="num">${tdLink(x.leads,"sales","leads","num",extra)}</td><td class="num">${tdLink(x.deals,"sales","deals","num",extra)}</td><td class="num">${tdLink(x.sales,"sales","sales","num",extra)}</td><td class="num">${tdLink(x.sales_amount,"sales","sales_amount","money",extra)}</td><td class="num">${tdLink(x.deal_to_sale_rate,"sales","deal_to_sale_rate","pct",extra)}</td></tr>`}).join("");
    const products=(productMap.get(m.name)||[]).map(p=>{const x=p[selectedPeriodType].metrics,extra={period_type:selectedPeriodType,manager:m.name,product:p.name};return `<tr><td>${esc(p.name)}</td><td class="num">${tdLink(x.products,"sales","products","num",extra)}</td><td class="num">${tdLink(x.product_amount,"sales","product_amount","money",extra)}</td><td class="num">${tdLink(x.sold_products,"sales","sold_products","num",extra)}</td><td class="num">${tdLink(x.sold_product_amount,"sales","sold_product_amount","money",extra)}</td><td class="num">${tdLink(x.product_sale_rate,"sales","product_sale_rate","pct",extra)}</td></tr>`}).join("");
    return `<details class="manager-breakdown"><summary><span>${esc(m.name)}</span><span class="muted">источники + продукты</span></summary><div class="manager-breakdown-body"><div><div class="subhead">По группам источников</div><div class="scroll-x"><table><thead><tr><th>Группа</th><th class="num">Лиды</th><th class="num">Сделки</th><th class="num">Продажи</th><th class="num">Выручка</th><th class="num">Конв.</th></tr></thead><tbody>${groups}</tbody></table></div></div><div><div class="subhead">По продуктовым категориям</div><div class="scroll-x"><table><thead><tr><th>Категория</th><th class="num">В сделках</th><th class="num">Сумма</th><th class="num">Продано</th><th class="num">Выручка</th><th class="num">Конв.</th></tr></thead><tbody>${products}</tbody></table></div></div></div></details>`;
  }).join("");
}
function renderSales(){
  const x=state.sales.overall[selectedPeriodType].metrics;
  $("#sales").innerHTML=`<div class="toolbar"><div><div class="eyebrow">ПЛАН / ФАКТ ОП</div><div class="muted">Логика исходной вкладки сохранена: отчётный месяц + 2 предыдущих месяца</div></div>${salesPeriodSelector()}</div>
  <div class="kpi-grid dense">${Object.entries(SALES_LABELS).map(([k,[label,type]])=>card(label,x[k],"sales",k,type,{period_type:selectedPeriodType})).join("")}</div>
  <div class="grid-2">${panel("4 группы источников",sourceTable(false),"общий → группа → сделки")}${panel("Менеджеры",salesManagerTable(false),"разбивка по каждому МОП")}</div>
  ${panel("Менеджеры · детальная матрица",salesManagerBreakdowns(),"каждый МОП → группы источников + продуктовые категории")}
  ${panel("Недельная динамика · отчётный месяц",weeklyGrid(),"1–7 · 8–14 · 15–21 · 22–28 · 29–конец")}
  <div class="grid-2">${panel("Точные источники Bitrix",sourceTable(true),"не только 4 агрегированные группы")}${panel("Продуктовые категории",salesProductTable(),"5 категорий из исходной таблицы")}</div>
  ${panel("Текущая воронка продаж",salesStages(),`${fmt(state.sales.active_deals_count)} активных сделок`)}`;
  $("#salesPeriodType")?.addEventListener("click",e=>{const b=e.target.closest("button[data-ptype]");if(!b)return;selectedPeriodType=b.dataset.ptype;renderSales();renderOverview();});
}

function prodProductTable(){
  const rows=state.production.products.map(r=>{const plan=getPlan("production","closed_amount","product",r.name);return `<tr><td>${esc(r.name)}</td><td>${esc(r.complexity||r.category)}</td><td class="num">${r.norm_days?days(r.norm_days):"—"}</td><td class="num">${tdLink(r.new_count,"production","new_count","num",{product:r.name})}</td><td class="num">${tdLink(r.new_amount,"production","new_amount","money",{product:r.name})}</td><td class="num">${tdLink(r.closed_count,"production","closed_count","num",{product:r.name})}</td><td class="num">${tdLink(r.closed_amount,"production","closed_amount","money",{product:r.name})}</td><td class="num">${plan?money(plan):"—"}</td><td class="num">${plan?pct(r.closed_amount/plan*100):"—"}</td><td class="num">${tdLink(r.conversion_pct,"production","new_to_success_pct","pct",{product:r.name})}</td><td class="num">${tdLink(r.avg_check,"production","avg_check","money",{product:r.name})}</td><td class="num">${tdLink(r.avg_production_days,"production","avg_production_days","days",{product:r.name})}</td><td class="num">${tdLink(r.avg_deviation_days,"production","avg_deviation_days","days",{product:r.name})}</td><td class="num">${tdLink(r.within_norm_pct,"production","within_norm_pct","pct",{product:r.name})}</td><td class="num">${tdLink(r.capacity_count,"production","capacity_count","num",{product:r.name})}</td><td class="num">${tdLink(r.capacity_amount,"production","capacity_amount","money",{product:r.name})}</td><td class="num">${tdLink(r.returns_count,"production","returns_count","num",{product:r.name})}</td><td class="num">${tdLink(r.returns_amount,"production","returns_amount","money",{product:r.name})}</td></tr>`}).join("");
  return `<div class="scroll-x"><table><thead><tr><th>Продукт</th><th>Сложность</th><th class="num">Норма</th><th class="num">Новых</th><th class="num">Новых BYN</th><th class="num">Закрыто</th><th class="num">Закрыто BYN</th><th class="num">План</th><th class="num">% плана</th><th class="num">Конв.</th><th class="num">Ср чек</th><th class="num">Срок</th><th class="num">Откл.</th><th class="num">В норме</th><th class="num">Ёмкость</th><th class="num">Ёмкость BYN</th><th class="num">Возвраты</th><th class="num">Возвраты BYN</th></tr></thead><tbody>${rows}</tbody></table></div>`;
}
function expertTable(compact=false){
  const rows=state.production.experts.map(r=>`<tr><td>${esc(r.name)}</td><td class="num">${tdLink(r.closed_count,"production","closed_count","num",{expert:r.name})}</td><td class="num">${tdLink(r.closed_amount,"production","closed_amount","money",{expert:r.name})}</td><td class="num">${tdLink(r.avg_production_days,"production","avg_production_days","days",{expert:r.name})}</td><td class="num">${tdLink(r.within_norm_pct,"production","within_norm_pct","pct",{expert:r.name})}</td>${compact?"":`<td class="num">${getPlan("production","closed_amount","expert",r.name)?money(getPlan("production","closed_amount","expert",r.name)):"—"}</td><td class="num">${getPlan("production","closed_amount","expert",r.name)?pct(r.closed_amount/getPlan("production","closed_amount","expert",r.name)*100):"—"}</td><td class="num">${tdLink(r.nps_avg,"production","nps_avg","num",{expert:r.name})}</td><td class="num">${tdLink(r.active_count,"production","active","num",{expert:r.name})}</td><td class="num">${tdLink(r.inactive_count,"production","inactive_count","num",{expert:r.name})}</td><td class="num">${tdLink(r.returns_count,"production","returns_count","num",{expert:r.name})}</td>`}</tr>`).join("");
  return `<div class="scroll-x"><table><thead><tr><th>Эксперт</th><th class="num">Закрыто</th><th class="num">Сумма</th><th class="num">Срок</th><th class="num">В норме</th>${compact?"":"<th class='num'>План BYN</th><th class='num'>% плана</th><th class='num'>NPS</th><th class='num'>Активно</th><th class='num'>7+ дней</th><th class='num'>Возвраты</th>"}</tr></thead><tbody>${rows}</tbody></table></div>`;
}
function prodStages(){return `<table><thead><tr><th>Стадия</th><th class="num">Кол-во</th><th class="num">Сумма</th></tr></thead><tbody>${state.production.stages.map(r=>`<tr><td>${esc(r.name)}</td><td class="num">${tdLink(r.count,"production","active","num",{stage:r.name})}</td><td class="num">${tdLink(r.amount,"production","active","money",{stage:r.name})}</td></tr>`).join("")}</tbody></table>`}
function renderProduction(){
  const p=state.production.kpi;
  $("#production").innerHTML=`<div class="toolbar"><div><div class="eyebrow">ПРОИЗВОДСТВО</div><div class="muted">${esc(state.production.period_label)} · всё из ТЗ + ежедневной отчётности</div></div><button class="btn ghost" id="openPlanProd">Изменить планы</button></div>
  <div class="kpi-grid dense">${Object.entries(PROD_LABELS).map(([k,[label,type]])=>card(label,p[k],"production",k,type)).join("")}</div>
  ${panel("Разбивка по продуктам",prodProductTable(),"каждый показатель раскрывается до сделок")}
  <div class="grid-2">${panel("Эксперты",expertTable(false),"закрытия + срок + норматив + риски")}${panel("Стадии производства",prodStages(),"количество и сумма")}</div>`;
  $("#openPlanProd")?.addEventListener("click",()=>openPlanDialog("production"));
}

function renderExperts(){
  const cards=state.production.experts.map(e=>`<div class="card"><div class="kpi-label">${esc(e.name)}</div><div class="kpi-value">${money(e.closed_amount)}</div><div class="kpi-meta"><span>${fmt(e.closed_count)} закрыто · ${fmt(e.active_count)} в работе</span><span>${pct(e.within_norm_pct)} в норме</span></div><details class="nested"><summary>По продуктам (${e.products.length})</summary><div class="nested-body"><table><thead><tr><th>Продукт</th><th class="num">Закрыто</th><th class="num">Сумма</th><th class="num">Срок</th><th class="num">В норме</th></tr></thead><tbody>${e.products.map(p=>`<tr><td>${esc(p.name)}</td><td class="num">${tdLink(p.closed_count,"production","closed_count","num",{expert:e.name,product:p.name})}</td><td class="num">${tdLink(p.closed_amount,"production","closed_amount","money",{expert:e.name,product:p.name})}</td><td class="num">${tdLink(p.avg_days,"production","avg_production_days","days",{expert:e.name,product:p.name})}</td><td class="num">${tdLink(p.within_norm_pct,"production","within_norm_pct","pct",{expert:e.name,product:p.name})}</td></tr>`).join("")}</tbody></table></div></details></div>`).join("");
  $("#experts").innerHTML=`<div class="toolbar"><div><div class="eyebrow">ЭКСПЕРТЫ</div><div class="muted">Закрытые продукты, нагрузка, нормативы, NPS и возвраты</div></div></div><div class="grid-3">${cards}</div>`;
}

function reasonTable(){return `<table><thead><tr><th>Причина зависания</th><th class="num">Кол-во</th><th class="num">%</th></tr></thead><tbody>${state.production.dormant.reasons.map(r=>`<tr><td>${esc(r.name)}</td><td class="num">${tdLink(r.count,"production","dormant_count","num",{reason:r.name})}</td><td class="num">${tdLink(r.pct,"production","dormant_count","pct",{reason:r.name})}</td></tr>`).join("")}</tbody></table>`}
function returnReasonTable(){return `<table><thead><tr><th>Причина возврата</th><th class="num">Кол-во</th><th class="num">Сумма</th><th class="num">%</th></tr></thead><tbody>${state.production.return_reasons.map(r=>`<tr><td>${esc(r.name)}</td><td class="num">${tdLink(r.count,"production","returns_count","num",{reason:r.name})}</td><td class="num">${money(r.amount)}</td><td class="num">${pct(r.pct)}</td></tr>`).join("")}</tbody></table>`}
function overdueTable(){return `<table><thead><tr><th>Просрочка</th><th class="num">Кол-во</th></tr></thead><tbody>${Object.entries(state.production.overdue.buckets).map(([k,v])=>`<tr><td>${esc(k)}</td><td class="num">${fmt(v)}</td></tr>`).join("")}</tbody></table>`}
function renderRisks(){
  const p=state.production.kpi;
  $("#risks").innerHTML=`<div class="kpi-grid">
    ${card("Зависшие сейчас",p.dormant_count,"production","dormant_count","num",{},money(p.dormant_amount))}
    ${card("Вернулось в производство",p.returned_to_production,"production","returned_to_production","num",{},money(p.returned_to_production_amount))}
    ${card("Просрочена ожидаемая дата",state.production.overdue.count,"production","overdue","num",{},money(state.production.overdue.amount))}
    ${card("Без изменений 7+ дней",p.inactive_count,"production","inactive_count","num",{},money(p.inactive_amount))}
  </div>
  <div class="kpi-grid"><div class="card clickable" ${drillAttrs("production","dormant_expected_count")}><div class="kpi-label">Зависшие с ожидаемой датой в периоде</div><div class="kpi-value">${fmt(p.dormant_expected_count)}</div></div><div class="card clickable" ${drillAttrs("production","dormant_overdue_count")}><div class="kpi-label">Зависшие с просроченной датой</div><div class="kpi-value">${fmt(p.dormant_overdue_count)}</div></div><div class="card"><div class="kpi-label">Причина заполнена</div><div class="kpi-value">${pct(p.dormant_with_reason_pct)}</div><div class="kpi-meta"><span>${fmt(state.production.dormant.with_reason_count)} сделок</span></div></div><div class="card"><div class="kpi-label">Возвраты за период</div><div class="kpi-value">${fmt(p.returns_count)}</div><div class="kpi-meta"><span>${money(p.returns_amount)}</span></div></div></div>
  <div class="grid-3">${panel("Причины зависания",reasonTable())}${panel("Причины возврата",returnReasonTable())}${panel("Просрочка ожидаемой даты",overdueTable())}</div>`;
}

function contextOptions(scope,type){
  if(type==="overall")return [{value:"",label:"Общий план"}];
  if(scope==="sales"&&type==="manager")return state.sales.managers.map(x=>({value:x.name,label:x.name}));
  if(scope==="sales"&&type==="source_group")return state.sales.groups.map(x=>({value:x.name,label:x.name}));
  if(scope==="sales"&&type==="source")return state.sales.exact_sources.map(x=>({value:x.name,label:x.name}));
  if(scope==="sales"&&type==="product")return state.sales.product_categories.map(x=>({value:x.name,label:x.name}));
  if(scope==="production"&&type==="expert")return state.production.experts.map(x=>({value:x.name,label:x.name}));
  if(scope==="production"&&type==="product")return state.production.products.map(x=>({value:x.name,label:x.name}));
  return [];
}
function renderPlanInline(){
  const statuses=state.metric_status||{};
  $("#plans").innerHTML=`<div class="toolbar"><div><div class="eyebrow">ПЛАНЫ И КАЧЕСТВО ДАННЫХ</div><div class="muted">Планы редактируются без Excel; можно задавать общий план и планы в разрезах</div></div><button class="btn primary" id="openPlans">Редактировать планы</button></div>
  <div class="grid-2">${panel("Планы продаж",planSummary("sales"))}${panel("Планы производства",planSummary("production"))}</div>
  ${panel("Статус дополнительных метрик",`<div class="mapping-grid">${Object.entries(statuses).map(([k,v])=>`<div class="mapping-item"><div><div class="name">${esc(k)}</div><div class="note">${esc(v.note)}</div></div><span class="badge ${v.connected?"good":"warn"}">${v.connected?"подключено":"нужен mapping"}</span></div>`).join("")}</div>`,"ничего не выдумываем: неподключенные поля отмечены явно")}`;
  $("#openPlans")?.addEventListener("click",()=>openPlanDialog("sales"));
}
function planSummary(scope){
  const defs=scope==="sales"?SALES_LABELS:PROD_LABELS;
  const key=`${scope}|overall|`,vals=state.plans?.[key]||{};
  return `<table><thead><tr><th>Показатель</th><th class="num">План</th></tr></thead><tbody>${Object.entries(defs).map(([k,[label,type]])=>`<tr><td>${esc(label)}</td><td class="num">${vals[k]?format(vals[k],type):"—"}</td></tr>`).join("")}</tbody></table>`;
}
function renderPlans(){renderPlanInline()}

function renderAll(){
  if(!state?.ok){const e=`<div class="error">${esc(state?.error||"Ошибка загрузки")}</div>`;$$('.view').forEach(x=>x.innerHTML=e);return}
  renderOverview();renderSales();renderProduction();renderExperts();renderRisks();renderPlans();
  $("#liveDot").className="ok";const d=new Date(state.updated_at);$("#liveText").textContent=`BITRIX ONLINE · ${d.toLocaleTimeString("ru-RU",{hour:"2-digit",minute:"2-digit",second:"2-digit"})}`;
}

function loadingView(month){
  const label=$("#month").selectedOptions[0]?.textContent||month;
  return `<div class="loading-state"><div class="loading-spinner"></div><div><div class="loading-title">Синхронизирую ${esc(label)}</div><div class="muted">Интерфейс уже доступен. Первый расчёт Bitrix идёт в фоне; дальше данные будут открываться из кеша сразу.</div></div></div>`;
}

async function load(){
  const month=$("#month").value,period=$("#period").value;
  if(loadTimer){clearTimeout(loadTimer);loadTimer=null}
  if(loadController)loadController.abort();
  loadController=new AbortController();
  // При переключении месяца никогда не блокируем контролы.
  if(!state || state.month_key!==month || state.period!==period){
    $("#overview").innerHTML=loadingView(month);
    $("#liveDot").className="";
    $("#liveText").textContent="СИНХРОНИЗАЦИЯ В ФОНЕ";
  }
  try{
    const r=await fetch(`/api/snapshot?month=${encodeURIComponent(month)}&period=${encodeURIComponent(period)}`,{cache:"no-store",signal:loadController.signal});
    if(r.status===401){location.href="/login";return}
    const j=await r.json();
    if(r.status===202 || j.loading){
      $("#liveDot").className="";$("#liveText").textContent="BITRIX · ПЕРВИЧНАЯ СИНХРОНИЗАЦИЯ";
      loadTimer=setTimeout(load,1800);
      return;
    }
    if(!r.ok)throw new Error(j.detail||j.error||JSON.stringify(j));
    state=j;renderAll();
    if(j.syncing){$("#liveText").textContent="BITRIX ONLINE · обновляю в фоне"}
  }catch(e){
    if(e.name==='AbortError')return;
    $("#liveDot").className="bad";$("#liveText").textContent="НЕТ СВЯЗИ";
    if(!state)$("#overview").innerHTML=`<div class="error">${esc(e.message)}</div>`;
  }
}

function detailHtml(r){
  const title=r.title||r.deal_title||r.service||r.id;const amount=r.amount!==undefined?money(r.amount):"";
  const meta=[r.kind==='lead'?r.status:r.stage,r.manager||r.expert,r.source,r.service,r.created?new Date(r.created).toLocaleDateString('ru-RU'):null,r.close?`закрыто ${new Date(r.close).toLocaleDateString('ru-RU')}`:null,r.prod_days!==undefined&&r.prod_days!==null?`${r.prod_days} раб.дн.`:null,r.norm_days?`норма ${r.norm_days}`:null,r.return_reason].filter(Boolean);
  const products=(r.products||[]).map(p=>`${p.name} × ${fmt(p.quantity)} · ${money(p.amount)}`).join("; ");
  return `<div class="detail-card" data-search="${attr([title,...meta,products].join(' ').toLowerCase())}"><div class="detail-main"><div><div class="detail-title">${r.url?`<a href="${attr(r.url)}" target="_blank" rel="noreferrer">${esc(title)}</a>`:esc(title)}</div><div class="detail-meta">${meta.map(x=>`<span>${esc(x)}</span>`).join("")}</div>${products?`<div class="detail-products">${esc(products)}</div>`:""}</div><div class="detail-money">${amount}</div></div></div>`;
}
async function openDrill(el){
  const d=el.dataset,params=new URLSearchParams({scope:d.scope,metric:d.metric,month:$("#month").value,period:$("#period").value});
  ["periodType","manager","group","source","product","expert","stage","reason","week"].forEach(k=>{if(d[k]!==undefined)params.set(k.replace(/[A-Z]/g,m=>'_'+m.toLowerCase()),d[k])});
  const label=(d.scope==="sales"?SALES_LABELS[d.metric]?.[0]:PROD_LABELS[d.metric]?.[0])||d.metric;
  $("#drillTitle").textContent=label;$("#drillSubtitle").textContent="Загружаю расшифровку…";$("#drillBody").innerHTML='<div class="loading">Загрузка…</div>';$("#drillDialog").showModal();
  try{const r=await fetch('/api/drilldown?'+params.toString());if(!r.ok)throw new Error(await r.text());const j=await r.json();drillRows=j.rows||[];$("#drillCount").textContent=`${j.count} записей`;$("#drillSubtitle").textContent=[d.manager,d.expert,d.group,d.source,d.product,d.stage,d.reason,d.week!==undefined?`неделя ${Number(d.week)+1}`:null].filter(Boolean).join(' · ');renderDrillRows()}
  catch(e){$("#drillBody").innerHTML=`<div class="error">${esc(e.message)}</div>`}
}
function renderDrillRows(){const q=normSearch($("#drillSearch").value);const rows=q?drillRows.filter(r=>JSON.stringify(r).toLowerCase().includes(q)):drillRows;$("#drillBody").innerHTML=rows.length?rows.map(detailHtml).join(''):'<div class="empty">Нет записей</div>'}
function normSearch(s){return String(s||'').trim().toLowerCase()}

function openPlanDialog(scope="sales"){$("#planScope").value=scope;updatePlanContextTypes();updatePlanKey();buildPlanForm();$("#planDialog").showModal()}
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

function init(){
  fillMonths();
  $("#month").addEventListener('change',()=>{state=null;load()});$("#period").addEventListener('change',()=>{state=null;load()});$("#refreshBtn").addEventListener('click',load);$("#tvBtn").addEventListener('click',()=>document.body.classList.toggle('tv-mode'));
  $("#tabs").addEventListener('click',e=>{const b=e.target.closest('[data-view]');if(!b)return;$$('.tab').forEach(x=>x.classList.remove('active'));$$('.view').forEach(x=>x.classList.remove('active'));b.classList.add('active');$('#'+b.dataset.view).classList.add('active')});
  document.body.addEventListener('click',e=>{const x=e.target.closest('[data-drill="1"]');if(x)openDrill(x)});
  $("#closeDrill").addEventListener('click',()=>$("#drillDialog").close());$("#drillSearch").addEventListener('input',renderDrillRows);
  $("#closePlan").addEventListener('click',()=>$("#planDialog").close());$("#planScope").addEventListener('change',()=>{updatePlanContextTypes();updatePlanKey()});$("#planContextType").addEventListener('change',updatePlanKey);$("#planContextKey").addEventListener('change',buildPlanForm);$("#savePlan").addEventListener('click',savePlan);
  const es=new EventSource('/events');es.addEventListener('update',()=>load());es.onerror=()=>{$("#liveDot").className='bad'};
  load();setInterval(load,120000);
}
init();
