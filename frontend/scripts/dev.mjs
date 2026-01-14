import { spawn } from "node:child_process";
import { fileURLToPath } from "node:url";
import path from "node:path";

const argv = process.argv.slice(2);

const findPort = () => {
  for (let i = argv.length - 1; i >= 0; i--) {
    const value = argv[i];
    if (!value) continue;
    const match = value.match(/^--port(?:=)?(\d+)$/);
    if (match) return Number(match[1]);
    if (/^\d+$/.test(value)) return Number(value);
  }
  if (process.env.PORT && /^\d+$/.test(process.env.PORT)) return Number(process.env.PORT);
  if (process.env.VITE_PORT && /^\d+$/.test(process.env.VITE_PORT)) return Number(process.env.VITE_PORT);
  return 3001;
};

const port = findPort();

const rootDir = path.dirname(fileURLToPath(import.meta.url));
const viteBin = path.resolve(rootDir, "..", "node_modules", "vite", "bin", "vite.js");

const passThroughArgs = argv.filter((arg) => arg && !/^\d+$/.test(arg) && !arg.startsWith("--port"));
const viteArgs = ["--host", "--port", String(port), ...passThroughArgs];

const child = spawn(process.execPath, [viteBin, ...viteArgs], {
  stdio: "inherit",
  cwd: path.resolve(rootDir, ".."),
  env: process.env,
});

child.on("exit", (code) => process.exit(code ?? 0));
