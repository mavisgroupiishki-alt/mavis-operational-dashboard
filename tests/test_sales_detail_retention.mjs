import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import vm from "node:vm";

const source = readFileSync(new URL("../app/static/app.js", import.meta.url), "utf8");
const match = source.match(/function preserveSalesDetails\(previous,nextSales,key\)\{[\s\S]*?\n\}(?=\nfunction salesDetailsNeedRefresh)/);
const freshnessMatch = source.match(/function salesDetailsNeedRefresh\(sales,snapshotUpdatedAt\)\{[\s\S]*?\n\}/);
const totalConversionMatch = source.match(/function rnpTotalDealToSaleRate\(c,p,t\)\{[\s\S]*?\n\}/);
const allocationMatch = source.match(/function allocateCleanRevenue\(crmAmount,crmTotal,cleanRevenue\)\{[\s\S]*?\n\}/);

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

test("clean revenue allocation preserves the financial total", () => {
  assert.ok(allocationMatch, "allocateCleanRevenue must exist");
  const context = {};
  vm.createContext(context);
  vm.runInContext(`${allocationMatch[0]};globalThis.allocateCleanRevenue=allocateCleanRevenue;`, context);
  const values = [5590, 40340, 69565].map(value => context.allocateCleanRevenue(value, 115495, 94360));
  assert.equal(values.reduce((total, value) => total + value, 0), 94360);
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
