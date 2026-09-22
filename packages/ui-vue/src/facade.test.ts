/**
 * Facade contract test (plan D4).
 *
 * Guards the @soymutdb/ui-vue seam without importing the Antdv Next runtime
 * (which does not resolve under vitest's node resolver on pnpm 12 — the real
 * proof that Antdv Next still resolves is `vue-tsc` typecheck + the app build):
 *   - the facade must keep re-exporting the component surface the apps import
 *     (a static check on the re-export block), so an upstream rename trips this
 *     before any app compiles against a broken facade;
 *   - the shared design tokens keep their brand values and CSS derivation.
 */
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

import { brandCssVariables, brandTokens } from "./design-tokens";

const here = dirname(fileURLToPath(import.meta.url));
const indexSource = readFileSync(join(here, "index.ts"), "utf-8");

const FACADE_COMPONENTS = [
    "Button",
    "Card",
    "ConfigProvider",
    "Layout",
    "Result",
    "Space",
    "Tag",
    "Typography",
] as const;

describe("ui-vue facade re-export surface (plan D4)", () => {
    it("re-exports every Antdv Next primitive the apps consume", () => {
        const reExportBlock = indexSource.slice(
            indexSource.indexOf("export {")
        );
        for (const name of FACADE_COMPONENTS) {
            expect(
                reExportBlock,
                `facade no longer re-exports ${name} from antdv-next`,
            ).toMatch(new RegExp(`\\b${name}\\b`));
        }
    });

    it("imports the design system only from antdv-next", () => {
        expect(indexSource).toContain('from "antdv-next"');
    });
});

describe("shared design tokens", () => {
    it("keeps the brand oklch primitives stable", () => {
        expect(brandTokens.primary).toBe("oklch(0.46 0.13 152)");
        expect(brandTokens.radius).toBe(10);
    });

    it("derives CSS variables with a configurable prefix", () => {
        const vars = brandCssVariables("smdb");
        expect(vars["--smdb-primary"]).toBe(brandTokens.primary);
        expect(vars["--smdb-radius"]).toBe("0.625rem");
    });
});
