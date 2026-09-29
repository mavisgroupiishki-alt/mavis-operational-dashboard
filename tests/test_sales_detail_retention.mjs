import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import vm from "node:vm";

const source = readFileSync(new URL("../app/static/app.js", import.meta.url), "utf8");
const match = source.match(/function preserveSalesDetails\(previous,nextSales,key\)\{[\s\S]*?\n\}(?=\nfunction salesDetailsNeedRefresh)/);
const freshnessMatch = source.match(/function salesDetailsNeedRefresh\(sales,snapshotUpdatedAt\)\{[\s\S]*?\n\}/);
const totalConversionMatch = source.match(/function rnpTotalDealToSaleRate\(c,p,t\)\{[\s\S]*?\n\}/);
const cleanRevenueMatch = source.match(/function rnpCleanRevenue\(filter=\{\}\)\{[\s\S]*?\n\}/);
const managerTableMatch = source.match(/function salesOperationalManagerTable\(\)\{[\s\S]*?\n\}/);

test("loaded sales details are refreshed when the snapshot revision changes", () => {
  assert.ok(freshnessMatch, "salesDetailsNeedRefresh must exist");
  const context = {};
  vm.createContext(context);
  vm.runInContext(`${freshnessMatch[0]};globalThis.salesDetailsNeedRefresh=salesDetailsNeedRefresh;`, context);
  assert.equal(context.salesDetailsNeedRefresh({ details_loaded: true, details_revision: "old" }, "new"), true);
  assert.equal(context.salesDetailsNeedRefresh({ details_loaded: true, details_revision: "new" }, "new"), false);
  assert.equal(context.salesDetailsNeedRefresh({ details_loaded: false }, "new"), false);
});

test("total conversion with tail is calculated from the two visible cohorts", () => {
  assert.ok(totalConversionMatch, "rnpTotalDealToSaleRate must exist");
  const context = {};
  vm.createContext(context);
  vm.runInContext(`${totalConversionMatch[0]};globalThis.rnpTotalDealToSaleRate=rnpTotalDealToSaleRate;`, context);
  assert.ok(Math.abs(context.rnpTotalDealToSaleRate({ deals: 96, sales: 24 }, { deals: 96, sales: 10 }, { total_deal_to_sale_rate: 0 }) - (34 / 192 * 100)) < 1e-9);
});

test("clean revenue is summed from the linked payment-schedule deals, not allocated by CRM amount", () => {
  assert.ok(cleanRevenueMatch, "rnpCleanRevenue must exist");
  const context = { state: { clean_revenue: {
    status: "online",
    deal_revenue_available: true,
    deal_revenue_rows: [
      { group: "Холодные продажи", period_type: "current", clean_revenue: 890 },
      { group: "Холодные продажи", period_type: "previous", clean_revenue: 4700 },
      { group: "Входящий трафик продажи", period_type: "current", clean_revenue: 40340 },
    ],
  } } };
  vm.createContext(context);
  vm.runInContext(`${cleanRevenueMatch[0]};globalThis.rnpCleanRevenue=rnpCleanRevenue;`, context);
  assert.deepEqual(
    JSON.parse(JSON.stringify(context.rnpCleanRevenue({ group: "Холодные продажи" }))),
    { current: 890, previous: 4700, total: 5590 },
  );
});

test("manager table renders when there are sales outside the selected team", () => {
  assert.ok(managerTableMatch, "salesOperationalManagerTable must exist");
  const context = {
    state: { sales: { overall: { total: { metrics: { deals: 3, sales: 2, sales_amount: 300 } } } } },
    managers: () => [{ name: "Ирина", total: { metrics: { deals: 1, sales: 1, sales_amount: 100 } } }],
    managerCleanRevenue: () => 80,
    otherManagersCleanRevenue: () => 160,
    esc: x => x,
    tdLink: x => String(x),
    fmt: x => String(x),
    money: x => String(x),
  };
  vm.createContext(context);
  vm.runInContext(`${managerTableMatch[0]};globalThis.salesOperationalManagerTable=salesOperationalManagerTable;`, context);
  assert.doesNotThrow(() => context.salesOperationalManagerTable());
});

test("a compact background snapshot retains the loaded sales detail for its period", () => {
  assert.ok(match, "preserveSalesDetails must exist");
  const context = {};
  vm.createContext(context);
  vm.runInContext(`${match[0]};globalThis.preserveSalesDetails=preserveSalesDetails;`, context);

  const preserved = context.preserveSalesDetails(
    { overall: { old: true }, managers: [{ name: "Ирина" }], details_loaded: true, details_key: "2026-09|month|" },
    { overall: { fresh: true } },
    "2026-09|month|",
  );
  assert.equal(preserved.details_loaded, true);
  assert.equal(preserved.details_key, "2026-09|month|");
  assert.equal(preserved.overall.fresh, true);
  assert.deepEqual(preserved.managers, [{ name: "Ирина" }]);
});

test("a compact manager total never erases the loaded manager groups", () => {
  const context = {};
  vm.createContext(context);
  vm.runInContext(`${match[0]};globalThis.preserveSalesDetails=preserveSalesDetails;`, context);

  const preserved = context.preserveSalesDetails(
    {
      managers: [{
        name: "Ирина",
        total: { metrics: { sales_amount: 50000 } },
        groups: [{ name: "Холодные продажи", current: { metrics: { sales: 10 } } }],
      }],
      details_loaded: true,
      details_key: "2026-09|month|",
    },
    { managers: [{ name: "Ирина", total: { metrics: { sales_amount: 54220 } } }] },
    "2026-09|month|",
  );

  assert.equal(preserved.managers[0].total.metrics.sales_amount, 54220);
  assert.equal(preserved.managers[0].groups[0].current.metrics.sales, 10);
});

test("a different period never inherits old sales detail", () => {
  const context = {};
  vm.createContext(context);
  vm.runInContext(`${match[0]};globalThis.preserveSalesDetails=preserveSalesDetails;`, context);

  const fresh = context.preserveSalesDetails(
    { managers: [{ name: "Ирина" }], details_loaded: true, details_key: "2026-09|month|" },
    { overall: { fresh: true } },
    "2026-10|month|",
  );
  assert.equal(fresh.details_loaded, undefined);
  assert.equal(fresh.managers, undefined);
});
