import { readFileSync } from "node:fs";
import { resolve } from "node:path";

export function readStyles() {
  const root = process.cwd();
  const entry = readFileSync(resolve(root, "src/styles/index.css"), "utf8");
  const imports = [...entry.matchAll(/@import\s+["']\.\/([^"']+)["'];/g)];
  return imports
    .map(([, file]) => readFileSync(resolve(root, "src/styles", file!), "utf8"))
    .join("\n");
}
