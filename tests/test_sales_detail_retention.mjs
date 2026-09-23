import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import vm from "node:vm";

const source = readFileSync(new URL("../app/static/app.js", import.meta.url), "utf8");
const match = source.match(/function preserveSalesDetails\(previous,nextSales,key\)\{[\s\S]*?\n\}/);

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
