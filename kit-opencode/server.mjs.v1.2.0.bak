#!/usr/bin/env node
import { spawn, execSync } from "node:child_process";
import { randomUUID } from "node:crypto";
import { existsSync } from "node:fs";
import { homedir } from "node:os";
import { join, resolve } from "node:path";
import { Server } from "@modelcontextprotocol/sdk/server/index.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { CallToolRequestSchema, ListToolsRequestSchema } from "@modelcontextprotocol/sdk/types.js";

const DEFAULT_TIMEOUT_MS = 120000;
const DEFAULT_MODEL = "opencode/deepseek-v4-flash-free";

function findOpencode() {
  const candidates = [
    "opencode",
    join(homedir(), ".local", "bin", "opencode"),
    "/usr/local/bin/opencode",
    "/opt/homebrew/bin/opencode",
  ];
  for (const c of candidates) {
    try {
      execSync("command -v " + c + " 2>/dev/null", { stdio: "pipe" });
      return c;
    } catch {}
  }
  return null;
}

function preview(text, max) {
  if (max === undefined) max = 200;
  const s = String(text || "");
  return s.length <= max ? s : s.slice(0, max) + "...";
}

function toolResult(data) {
  return { content: [{ type: "text", text: JSON.stringify(data, null, 2) }] };
}

function toolError(err) {
  const msg = (err && err.message) || String(err);
  return { content: [{ type: "text", text: JSON.stringify({ error: msg }, null, 2) }], isError: true };
}

async function runOpencode(args) {
  const opencode = findOpencode();
  if (!opencode) throw new Error("opencode not found. Install with: npm install -g opencode-ai");
  const cwd = args.directory ? resolve(args.directory) : process.cwd();
  if (!existsSync(cwd)) throw new Error("Directory does not exist: " + cwd);
  const timeoutMs = args.timeout ? args.timeout * 1000 : DEFAULT_TIMEOUT_MS;
  const runId = randomUUID().slice(0, 8);

  const cmdArgs = [
    opencode, "run", args.prompt,
    "--format", "json",
    "--dir", cwd,
    "--auto",
  ];
  if (args.model) cmdArgs.push("-m", args.model);

  return new Promise((resolve, reject) => {
    const child = spawn(cmdArgs[0], cmdArgs.slice(1), {
      cwd,
      env: { ...process.env, PATH: process.env.PATH },
      stdio: ["ignore", "pipe", "pipe"],
      shell: false,
    });
    let stdout = "", stderr = "", timedOut = false;
    const timer = setTimeout(() => {
      timedOut = true;
      child.kill("SIGTERM");
    }, timeoutMs);
    child.stdout.on("data", (c) => { stdout += c.toString(); });
    child.stderr.on("data", (c) => { stderr += c.toString(); });
    child.on("close", (code) => {
      clearTimeout(timer);
      const result = {
        run_id: runId,
        exit_code: code,
        timed_out: timedOut,
        stdout: stdout,
        stderr: stderr,
        summary: preview(stdout, 500),
      };
      if (stdout.length > 100000) {
        result.stdout = stdout.slice(0, 50000) + "
...(truncated)";
        result.truncated = true;
      }
      if (code !== 0 && !timedOut) result.error = stderr || "exit code " + code;
      resolve(result);
    });
    child.on("error", (e) => { clearTimeout(timer); reject(e); });
  });
}

async function listModels() {
  const opencode = findOpencode();
  if (!opencode) throw new Error("opencode not found");
  try {
    const output = execSync(opencode + " models 2>/dev/null", { encoding: "utf-8", timeout: 10000 });
    const lines = output.split("
").map(l => l.trim()).filter(l => l && !l.startsWith("\u2500") && !l.startsWith("\u250c") && !l.startsWith("\u2514") && !l.startsWith("\u2502"));
    return { models: lines, count: lines.length };
  } catch (e) {
    return { models: ["opencode/deepseek-v4-flash-free"], count: 1, note: "fallback" };
  }
}

const server = new Server(
  { name: "opencode-kit", version: "1.0.1" },
  { capabilities: { tools: {} } }
);

server.setRequestHandler(ListToolsRequestSchema, async () => ({
  tools: [
    {
      name: "opencode_run",
      description: "Run opencode agent in a directory - file exploration, code gen, task execution",
      inputSchema: {
        type: "object",
        properties: {
          prompt: { type: "string", description: "Task description for opencode agent" },
          directory: { type: "string", description: "Working directory (absolute path)" },
          model: { type: "string", description: "Model name, default: opencode/deepseek-v4-flash-free" },
          timeout: { type: "number", description: "Timeout in seconds (default 120)" },
        },
        required: ["prompt"],
      },
    },
    {
      name: "opencode_models",
      description: "List available opencode models",
      inputSchema: { type: "object", properties: {}, required: [] },
    },
  ],
}));

server.setRequestHandler(CallToolRequestSchema, async (request) => {
  const { name, arguments: args } = request.params;
  try {
    if (name === "opencode_run") {
      if (!args || !args.prompt) return toolError(new Error("prompt is required"));
      return toolResult(await runOpencode({
        prompt: args.prompt,
        directory: args.directory,
        model: args.model || DEFAULT_MODEL,
        timeout: args.timeout || 120,
      }));
    }
    if (name === "opencode_models") {
      return toolResult(await listModels());
    }
    return toolError(new Error("Unknown tool: " + name));
  } catch (err) {
    return toolError(err);
  }
});

async function main() {
  const transport = new StdioServerTransport();
  await server.connect(transport);
  process.stderr.write("opencode kit: connected
");
}

main().catch((err) => {
  process.stderr.write("opencode kit fatal: " + err.message + "
");
  process.exit(1);
});
