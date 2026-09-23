import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import vm from "node:vm";

function dashboardPlanApi() {
  const app = readFileSync(new URL("../app/static/app.js", import.meta.url), "utf8")
    .replace(/\ninit\(\);\n[\s\S]*$/, "\nglobalThis.__dashboardTest={rememberPlanWrite,reconcilePendingPlans};\n");
  const store = new Map();
  const context = {
    Array, Date, Intl, JSON, Map, Math, Number, Object, String, URLSearchParams,
    clearTimeout, console, setTimeout,
    document: { querySelector: () => null, querySelectorAll: () => [], body: {} },
    localStorage: { getItem: key => store.get(`local:${key}`) || null, setItem: (key, value) => store.set(`local:${key}`, value) },
    sessionStorage: { getItem: key => store.get(`session:${key}`) || null, setItem: (key, value) => store.set(`session:${key}`, value) },
    window: { addEventListener: () => {} },
  };
  vm.createContext(context);
  vm.runInContext(app, context);
  return context.__dashboardTest;
}

test("a stale snapshot cannot overwrite a just-saved plan", () => {
  const plans = dashboardPlanApi();
  plans.rememberPlanWrite("production|overall|", { new_amount: 160000 });

  const stale = plans.reconcilePendingPlans({
    "production|overall|": { new_amount: 93300, closed_count: 21 },
  });
  assert.equal(stale["production|overall|"].new_amount, 160000);

  const confirmed = plans.reconcilePendingPlans({
    "production|overall|": { new_amount: 160000, closed_count: 21 },
  });
  assert.equal(confirmed["production|overall|"].new_amount, 160000);

  const later = plans.reconcilePendingPlans({
    "production|overall|": { new_amount: 93300, closed_count: 21 },
  });
  assert.equal(later["production|overall|"].new_amount, 93300);
});
