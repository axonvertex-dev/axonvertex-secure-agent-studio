import { copyFileSync, mkdirSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const packageRoot = resolve(here, "..");
const source = resolve(
  packageRoot,
  "../../integrations/agent-system-fasttrack/runtime-adapter-ts/config/runtime-targets.json",
);
const target = resolve(packageRoot, "dist/runtime-targets.json");

mkdirSync(dirname(target), { recursive: true });
copyFileSync(source, target);
console.log(`Synced governed runtime config -> ${target}`);
