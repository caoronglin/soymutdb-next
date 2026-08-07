// One-off: regenerate src/routeTree.gen.ts with the installed TanStack Router
// generator (router-plugin is a devDependency but not wired into vite.config).
import { resolve } from "node:path";
import { Generator, getConfig } from "@tanstack/router-generator";

const root = resolve(import.meta.dirname, "..");
const config = getConfig(
    {
        target: "react",
        routesDirectory: resolve(root, "src/routes"),
        generatedRouteTree: resolve(root, "src/routeTree.gen.ts"),
        autoCodeSplitting: false,
    },
    root,
);

const gen = new Generator({ config, root });
await gen.run();
console.log("[gen-routetree] routeTree.gen.ts regenerated");
