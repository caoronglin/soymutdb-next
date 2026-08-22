import assert from "node:assert/strict";
import { readFile, readdir } from "node:fs/promises";
import { test } from "node:test";

async function sourceFiles(directory) {
  const entries = await readdir(directory, { withFileTypes: true });
  const nested = await Promise.all(
    entries.map((entry) => {
      const url = new URL(`${entry.name}${entry.isDirectory() ? "/" : ""}`, directory);
      return entry.isDirectory()
        ? sourceFiles(url)
        : entry.name.endsWith(".ts") || entry.name.endsWith(".tsx")
          ? [url]
          : [];
    }),
  );
  return nested.flat();
}

test("motion runtime uses bounded browser primitives without GSAP or Lenis", async () => {
  const roots = [new URL("./src/", import.meta.url), new URL("../../apps/web/src/", import.meta.url)];
  const files = (await Promise.all(roots.map(sourceFiles))).flat();
  for (const file of files) {
    const source = await readFile(file, "utf8");
    assert.doesNotMatch(source, /(?:from|import\s*\()\s*["'](?:gsap|lenis|@soymutdb\/motion)/i, file.pathname);
    assert.doesNotMatch(source, /\b(?:gsap|lenis|ScrollTrigger)\b/, file.pathname);
  }
});

test("motion manifests do not install legacy animation engines", async () => {
  for (const relative of ["./package.json", "../../apps/web/package.json"]) {
    const manifest = JSON.parse(await readFile(new URL(relative, import.meta.url), "utf8"));
    for (const section of ["dependencies", "devDependencies", "peerDependencies"]) {
      assert.equal(manifest[section]?.gsap, undefined, `${relative} ${section}.gsap`);
      assert.equal(manifest[section]?.lenis, undefined, `${relative} ${section}.lenis`);
    }
  }
});
