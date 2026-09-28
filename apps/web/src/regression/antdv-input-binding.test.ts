// @vitest-environment node
import { readFileSync, readdirSync, statSync } from "node:fs";
import { dirname, join, relative } from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

/**
 * Guards the Antdv Next binding contract on the `@soymutdb/ui-vue` facade.
 *
 * `antdv-next@1.5.4` declares `value` + `update:value` on `Input`; it has no
 * `modelValue` anywhere in its type surface
 * (`grep -c modelValue node_modules/antdv-next/dist/index.d.ts` → 0). A bare
 * `v-model` therefore compiles to `:model-value` + `@update:model-value`, both
 * of which the component ignores: the field looks editable (the browser keeps
 * its own text) while the bound ref stays empty, so submitting sends nothing.
 *
 * That is not hypothetical — the global search box and the mutant-line mutagen
 * filter both shipped that way, and only a real typing session exposed it.
 * Every facade `Input` must bind `v-model:value`.
 */
const here = dirname(fileURLToPath(import.meta.url));
const APP_SRC = join(here, "..");

function vueFiles(dir: string): string[] {
  const out: string[] = [];
  for (const entry of readdirSync(dir)) {
    const full = join(dir, entry);
    if (statSync(full).isDirectory()) {
      out.push(...vueFiles(full));
    } else if (entry.endsWith(".vue")) {
      out.push(full);
    }
  }
  return out;
}

/** Extract each `<Input ... />` element from an SFC template. */
function facadeInputElements(source: string): string[] {
  return source.match(/<Input\b[\s\S]*?\/>/g) ?? [];
}

describe("Antdv Next Input binding contract (facade)", () => {
  const files = vueFiles(APP_SRC).filter((file) => !file.endsWith(".test.ts"));

  it("finds the facade Input usages it is meant to guard", () => {
    const usages = files.flatMap((file) => facadeInputElements(readFileSync(file, "utf-8")));
    // If this drops to zero the guard has become vacuous — check the sources.
    expect(usages.length).toBeGreaterThan(0);
  });

  it("never binds a bare v-model to a facade Input", () => {
    const offenders: string[] = [];
    for (const file of files) {
      for (const element of facadeInputElements(readFileSync(file, "utf-8"))) {
        // `v-model:value=` carries the argument; a bare `v-model=` does not.
        if (/\bv-model\s*=/.test(element)) {
          offenders.push(`${relative(APP_SRC, file)}: ${element.split("\n")[0].trim()}`);
        }
      }
    }
    expect(
      offenders,
      "antdv-next Input has value/update:value, not modelValue — use v-model:value",
    ).toEqual([]);
  });

  it("keeps the previously broken fields on v-model:value", () => {
    const searchView = readFileSync(join(APP_SRC, "views", "SearchView.vue"), "utf-8");
    const mutantsView = readFileSync(join(APP_SRC, "views", "MutantsListView.vue"), "utf-8");

    expect(searchView).toContain('v-model:value="input"');
    expect(mutantsView).toContain('v-model:value="input"');
  });
});
