from datetime import datetime
from zoneinfo import ZoneInfo


def agg(leads=58,qual=35,deals=27,sales=12,revenue=28650,products=57,sold_products=24):
    deal_amount=revenue*2.5
    return {"metrics":{
        "leads":leads,"qualified":qual,"qualified_rate":round(qual/leads*100,1) if leads else 0,
        "lead_to_deal_rate":round(deals/qual*100,1) if qual else 0,"deals":deals,"deal_amount":deal_amount,
        "sales":sales,"sales_amount":revenue,"average_check":round(revenue/sales,2) if sales else 0,
        "deal_to_sale_rate":round(sales/deals*100,1) if deals else 0,"products_per_deal":round(products/deals,2) if deals else 0,
        "products":products,"product_amount":revenue*3,"sold_products":sold_products,"sold_product_amount":revenue*1.07,
        "average_product_check":round(revenue*1.07/sold_products,2) if sold_products else 0,"product_sale_rate":round(sold_products/products*100,1) if products else 0,
        "paid_amount":22100,"net_revenue":19400},
        "weeks":{"leads":[13,14,12,11,8],"qualified":[8,9,7,6,5],"qualified_rate":[61.5,64.3,58.3,54.5,62.5],"lead_to_deal_rate":[75,77.8,71.4,83.3,80],"deals":[6,7,5,5,4],"deal_amount":[15000,17500,12500,13500,9000],"sales":[2,3,2,3,2],"sales_amount":[4500,7800,4100,7200,5050],"products":[12,14,10,11,10],"product_amount":[21000,22000,16000,17000,10000],"sold_products":[4,6,4,6,4],"sold_product_amount":[5000,8000,4800,7600,5200]}}


def demo_snapshot(month,period):
    now=datetime.now(ZoneInfo("Europe/Minsk"))
    overall={"current":agg(),"previous":agg(0,0,31,8,19500,64,17),"total":agg(58,35,58,20,48150,121,41)}
    groups=[]
    for n,m in [("Холодный звонок",agg(20,10,9,3,7800,20,7)),("Входящий звонок (прямой)",agg(24,17,12,6,12600,25,11)),("Из реанимации",agg(8,5,4,0,0,7,0)),("Прочее",agg(6,3,2,3,8250,5,6))]:
        groups.append({"name":n,"current":m,"previous":m,"total":m})
    managers=[]
    for n,m in [("Роман Авсеенко",agg(26,16,13,7,16400,26,14)),("Ирина Богомольцева",agg(22,13,11,5,12250,24,10))]:
        managers.append({"name":n,"current":m,"previous":m,"total":m,"groups":groups})
    products=[]
    for n,c in [("Системы менеджмента",12),("Специалисты",10),("Строительство",19),("Лицензирование",9),("Продукция",7)]:
        m=agg(0,0,10,4,7000,c,max(1,int(c*.45)));products.append({"name":n,"current":m,"previous":m,"total":m})
    prod_kpi={"closed_amount":25170,"closed_count":21,"new_count":44,"new_amount":54800,"period_closed_count":8,"period_closed_amount":10450,"new_to_success_pct":18.2,"avg_check":1198.6,"capacity_count":57,"capacity_amount":68400,"returns_count":2,"returns_amount":2100,"avg_production_days":17.4,"avg_full_cycle_days":21.8,"avg_deviation_days":-2.6,"within_norm_pct":81.0,"base_bonus":920,"nps_avg":9.4,"act_share_pct":90.5,"inactive_count":16,"inactive_amount":19200,"dormant_count":298,"dormant_amount":312400,"returned_to_production":2,"returned_to_production_amount":2100,"dormant_expected_count":34,"dormant_overdue_count":17,"dormant_with_reason_pct":60.7}
    prod_products=[{"name":"СПК","category":"Строительство","complexity":"Средняя","norm_days":21,"avg_deviation_days":-4.8,"new_count":11,"new_amount":13000,"closed_count":7,"closed_amount":7350,"period_closed_count":3,"conversion_pct":27.3,"capacity_count":12,"capacity_amount":14200,"returns_count":0,"returns_amount":0,"active_count":14,"avg_check":1050,"avg_production_days":16.2,"avg_full_cycle_days":20.1,"within_norm_pct":85.7,"base_bonus":276.5,"nps_avg":9.5,"act_share_pct":100},
    {"name":"Аттестация","category":"Строительство","complexity":"Средняя","norm_days":30,"avg_deviation_days":-7.9,"new_count":10,"new_amount":11500,"closed_count":6,"closed_amount":6300,"period_closed_count":2,"conversion_pct":20,"capacity_count":14,"capacity_amount":16200,"returns_count":1,"returns_amount":1050,"active_count":17,"avg_check":1050,"avg_production_days":22.1,"avg_full_cycle_days":26.0,"within_norm_pct":83.3,"base_bonus":249,"nps_avg":9.2,"act_share_pct":83.3}]
    experts=[]
    for n,c,a,d in [("Екатерина Николаева",9,10700,16.2),("Елизавета Горбатова",7,8250,18.4),("Ольга Панькова",5,6220,17.8)]:
        experts.append({"name":n,"new_count":14,"active_count":18,"returns_count":1,"inactive_count":4,"closed_count":c,"closed_amount":a,"avg_check":a/c,"avg_production_days":d,"avg_full_cycle_days":d+4,"within_norm_pct":82,"base_bonus":350,"nps_avg":9.4,"act_share_pct":90,"products":[{"name":"СПК","closed_count":3,"closed_amount":3150,"avg_days":16,"within_norm_pct":100}]})
    product_managers=[{"name":m["name"],"categories":products} for m in managers]
    return {"ok":True,"updated_at":now.isoformat(),"month_key":month,"period":period,"pace":{"business_days_total":22,"business_days_elapsed":4,"share":4/22},
      "sales":{"overall":overall,"groups":groups,"exact_sources":groups,"managers":managers,"product_categories":products,"product_managers":product_managers,"stages":[{"name":"3. Собрана потребность клиента","count":18,"amount":32600},{"name":"5. КП отправлено","count":13,"amount":25700}],"active_deals_count":61},
      "production":{"period_label":"Демо","kpi":prod_kpi,"products":prod_products,"experts":experts,"stages":[{"name":"2. Сбор информации","count":34,"amount":42100},{"name":"4. Подбор","count":29,"amount":38500}],"dormant":{"with_reason_count":181,"with_reason_pct":60.7,"reasons":[{"name":"Нет людей","count":73,"pct":24.5},{"name":"Нет денег","count":48,"pct":16.1}]},"return_reasons":[{"name":"Несоблюдение сроков","count":1,"amount":1050,"pct":50},{"name":"Добровольный отказ","count":1,"amount":1050,"pct":50}],"overdue":{"count":47,"amount":58800,"buckets":{"1–7 дней":16,"8–14 дней":12,"15–30 дней":11,"30+ дней":8}}},
      "metric_status":{"upsells":{"connected":False,"note":"Нужно поле Bitrix"},"upsell_bonus":{"connected":False,"note":"Нужно поле Bitrix"},"total_bonus":{"connected":False,"note":"Нужно поле Bitrix"},"expert_rework_pct":{"connected":False,"note":"Нужно поле Bitrix"},"base_bonus":{"connected":True,"note":"Справочник"},"inactive_7d":{"connected":True,"note":"DATE_MODIFY"}},"_demo":True}
