#!/usr/bin/env node
import { spawn, execSync } from 'node:child_process';
import { randomUUID } from 'node:crypto';
import { existsSync, mkdtempSync, writeFileSync, unlinkSync, readFileSync } from 'node:fs';
import { homedir } from 'node:os';
import { join, resolve, dirname } from 'node:path';
import { Server } from '@modelcontextprotocol/sdk/server/index.js';
import { StdioServerTransport } from '@modelcontextprotocol/sdk/server/stdio.js';
import { CallToolRequestSchema, ListToolsRequestSchema } from '@modelcontextprotocol/sdk/types.js';

const DEFAULT_TIMEOUT_MS = 180000;
const DEFAULT_MODEL = 'opencode/deepseek-v4-flash-free';
const KIT_VERSION = '1.2.1';

const HEARTBEAT_FILE = join(homedir(), ".heart-portal", "kits", "opencode", ".heartbeat.json");

function heartbeatBump() {
  try {
    const dir = dirname(HEARTBEAT_FILE);
    if (!existsSync(dir)) { try { execSync('mkdir -p ' + JSON.stringify(dir)); } catch {} }
    let data = { calls: 0, last_used_at: '' };
    if (existsSync(HEARTBEAT_FILE)) {
      try { data = JSON.parse(readFileSync(HEARTBEAT_FILE, 'utf-8')); } catch {} }
    data.calls = (data.calls || 0) + 1;
    data.last_used_at = new Date().toISOString();
    writeFileSync(HEARTBEAT_FILE, JSON.stringify(data) + '\n', 'utf-8');
  } catch (e) {
    // silent
  }
}


function findOpencode() {
  const candidates = ['opencode', join(homedir(), '.local', 'bin', 'opencode'), '/usr/local/bin/opencode'];
  for (const c of candidates) {
    try { execSync('which ' + c + ' 2>/dev/null', { stdio: 'pipe' }); return c; } catch {}
  }
  try { execSync('npx opencode --version 2>/dev/null', { stdio: 'pipe' }); return 'npx opencode'; } catch {}
  return null;
}

function getOpencodeVersion(bin) {
  try {
    const out = execSync(bin + ' --version 2>/dev/null', { encoding: 'utf-8', timeout: 5000 });
    return out.trim().split('\n')[0] || 'unknown';
  } catch { return 'unknown'; }
}

function preview(text, max) {
  if (!max) max = 300;
  const s = String(text || '');
  return s.length <= max ? s : s.slice(0, max) + '...';
}

function toolResult(data) {
  return { content: [{ type: 'text', text: JSON.stringify(data, null, 2) }] };
}

function toolError(err) {
  const msg = (err && err.message) || String(err);
  return { content: [{ type: 'text', text: JSON.stringify({ error: msg }, null, 2) }], isError: true };
}

async function runOpencode(args) {
  const opencode = findOpencode();
  if (!opencode) throw new Error('opencode not found. Install with: npm install -g opencode-ai');
  const cwd = args.directory ? resolve(args.directory) : process.cwd();
  if (!existsSync(cwd)) throw new Error('Directory does not exist: ' + cwd);
  const modelFlag = '--model ' + (args.model || DEFAULT_MODEL);
  const timeoutMs = args.timeout ? args.timeout * 1000 : DEFAULT_TIMEOUT_MS;
  const runId = randomUUID().slice(0, 8);
  const tmpDir = mkdtempSync(join('/tmp', 'opencode-prompt-'));
  const promptFile = join(tmpDir, 'prompt.txt');
  writeFileSync(promptFile, args.prompt, 'utf-8');
  const sh = 'cd ' + JSON.stringify(cwd) + ' && ' + opencode + ' run ' + modelFlag + ' < ' + JSON.stringify(promptFile);
  return new Promise((resolvePromise) => {
    const child = spawn('sh', ['-c', sh], {
      cwd, env: { ...process.env, PATH: process.env.PATH },
      stdio: ['ignore', 'pipe', 'pipe'], shell: false, timeout: timeoutMs + 10000
    });
    let stdout = '', stderr = '', timedOut = false;
    const timer = setTimeout(() => { timedOut = true; child.kill('SIGTERM'); }, timeoutMs);
    child.stdout.on('data', (c) => { stdout += c.toString(); });
    child.stderr.on('data', (c) => { stderr += c.toString(); });
    child.on('close', (code) => {
      clearTimeout(timer);
      try { unlinkSync(promptFile); } catch {}
      try { execSync('rmdir ' + JSON.stringify(tmpDir) + ' 2>/dev/null'); } catch {}
      const result = { run_id: runId, exit_code: code, timed_out: timedOut, stdout, stderr, summary: preview(stdout, 500) };
      if (stdout.length > 100000) { result.stdout = stdout.slice(0, 50000) + '\n...(truncated)'; result.truncated = true; }
      if (code !== 0 && !timedOut) result.error = stderr || 'exit code ' + code;
      resolvePromise(result);
    });
    child.on('error', (e) => {
      clearTimeout(timer);
      try { unlinkSync(promptFile); } catch {}
      try { execSync('rmdir ' + JSON.stringify(tmpDir) + ' 2>/dev/null'); } catch {}
      resolvePromise({ run_id: runId, error: e.message, exit_code: -1 });
    });
  });
}

async function listModels() {
  const opencode = findOpencode();
  if (!opencode) throw new Error('opencode not found');
  try {
    const output = execSync(opencode + ' models 2>/dev/null', { encoding: 'utf-8', timeout: 15000 });
    const lines = output.split('\n').map(l => l.trim()).filter(l => l && !l.startsWith('\u2500') && !l.startsWith('\u250c') && !l.startsWith('\u2514') && !l.startsWith('\u2502'));
    return { models: lines, count: lines.length };
  } catch {
    return { models: ['opencode/deepseek-v4-flash-free'], count: 1, note: 'fallback (models command failed)' };
  }
}

async function getStatus() {
  const bin = findOpencode();
  if (!bin) {
    return { installed: false, version: null, bin_path: null, kit_version: KIT_VERSION, message: 'opencode not installed. Run: npm install -g opencode-ai' };
  }
  const version = getOpencodeVersion(bin);
  let pingOk = false;
  try { execSync(bin + ' --help 2>/dev/null | head -3', { encoding: 'utf-8', timeout: 5000 }); pingOk = true; } catch {}
  let hb = { calls: 0 };
  if (existsSync(HEARTBEAT_FILE)) {
    try { hb = JSON.parse(readFileSync(HEARTBEAT_FILE, 'utf-8')); } catch {}
  }
  return { installed: true, version, bin_path: bin, kit_version: KIT_VERSION, ping_ok: pingOk, default_model: DEFAULT_MODEL, node_version: process.version, platform: process.platform, local_calls: hb.calls || 0, last_used: hb.last_used_at || '' };
}

const server = new Server({ name: 'opencode-kit', version: KIT_VERSION }, { capabilities: { tools: {} } });

server.setRequestHandler(ListToolsRequestSchema, async () => ({
  tools: [
    {
      name: 'opencode_run',
      description: 'Run opencode agent in a directory. Prompt written to temp file to avoid shell escaping.',
      inputSchema: { type: 'object', properties: {
        prompt: { type: 'string', description: 'Task description (can be long)' },
        directory: { type: 'string', description: 'Working directory (absolute path)' },
        model: { type: 'string', description: 'Model name, default: opencode/deepseek-v4-flash-free' },
        timeout: { type: 'number', description: 'Timeout in seconds (default 180)' }
      }, required: ['prompt'] }
    },
    {
      name: 'opencode_models',
      description: 'List available opencode models',
      inputSchema: { type: 'object', properties: {}, required: [] }
    },
    {
      name: 'opencode_status',
      description: 'Check opencode installation status, version, and health',
      inputSchema: { type: 'object', properties: {}, required: [] }
    }
  ]
}));

server.setRequestHandler(CallToolRequestSchema, async (request) => {
  const { name, arguments: args } = request.params;
  try {
    let result;
    if (name === 'opencode_run') {
      if (!args || !args.prompt) return toolError(new Error('prompt is required'));
      result = toolResult(await runOpencode({ prompt: args.prompt, directory: args.directory, model: args.model || DEFAULT_MODEL, timeout: args.timeout || 180 }));
    } else if (name === 'opencode_models') {
      result = toolResult(await listModels());
    } else if (name === 'opencode_status') {
      result = toolResult(await getStatus());
    } else {
      return toolError(new Error('Unknown tool: ' + name));
    }
    heartbeatBump();
    return result;
  } catch (err) {
    heartbeatBump();
    return toolError(err);
  }
});

async function main() {
  const transport = new StdioServerTransport();
  await server.connect(transport);
  process.stderr.write('opencode kit v' + KIT_VERSION + ': connected (hb: ' + HEARTBEAT_FILE + ')\n');
}

main().catch((err) => {
  process.stderr.write('opencode kit fatal: ' + err.message + '\n');
  process.exit(1);
});
