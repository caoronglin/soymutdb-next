#!/usr/bin/env node
/** Reproducible official CLI scans, including the repository's component facades. */
import { spawnSync } from 'node:child_process';
import { mkdirSync, readdirSync, readFileSync, writeFileSync } from 'node:fs';
import { dirname, join, relative, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const cli = process.env.ANTD_CLI_BIN || 'antd';
const output = resolve(root, process.env.ANTD_SCAN_OUTPUT || 'artifacts/ant-design-scan');
const version = readFileSync(join(root, 'pnpm-workspace.yaml'), 'utf8')
  .match(/^\s+antd:\s*([^\s]+)\s*$/m)?.[1];
if (!version) throw new Error('Cannot determine the workspace Ant Design version');

function run(args, cwd = root) {
  const result = spawnSync(cli.endsWith('.js') ? process.execPath : cli,
    cli.endsWith('.js') ? [cli, ...args] : args, {
      cwd, encoding: 'utf8', timeout: 120000, maxBuffer: 16 * 1024 * 1024,
      env: { ...process.env, ANTD_NO_AUTO_REPORT: '1', NO_UPDATE_CHECK: '1',
        RAYON_NUM_THREADS: '1', CI: '1' },
    });
  if (result.error || result.status !== 0) {
    throw new Error(`Ant Design CLI failed (${args[0]}): ${result.error?.message || result.stderr}`);
  }
  return result.stdout;
}

function sources(dir) {
  return readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const path = join(dir, entry.name);
    return entry.isDirectory() ? sources(path) : /\.[cm]?[jt]sx?$/.test(entry.name) ? [path] : [];
  });
}

function clean(value) {
  if (typeof value === 'string') return value.replaceAll(`${root}/`, '');
  if (Array.isArray(value)) return value.map(clean);
  if (value && typeof value === 'object') {
    return Object.fromEntries(Object.entries(value).map(([key, item]) => [key, clean(item)]));
  }
  return value;
}

mkdirSync(output, { recursive: true });
const report = { cliVersion: run(['--cli-version']).trim(), antdVersion: version,
  scope: 'Source lint and configuration; does not establish visual or browser correctness', apps: [] };
let failed = false;
for (const app of ['admin', 'web']) {
  const appRoot = join(root, 'apps', app);
  const files = sources(join(appRoot, 'src'));
  const aliases = new Set(['@soymutdb/ui-react']);
  let facadeImports = 0;
  for (const file of files) {
    for (const match of readFileSync(file, 'utf8').matchAll(/\bfrom\s*["']([^"']+)["']/g)) {
      const source = match[1];
      if (source.endsWith('/lib/antd') || source === './antd' || source === '@soymutdb/ui-react') {
        aliases.add(source);
        facadeImports++;
      }
    }
  }
  if (!facadeImports) throw new Error(`No component facade imports found for ${app}`);
  const lint = JSON.parse(run(['lint', 'src', '--antd-alias', [...aliases].sort().join(','),
    '--version', version, '--format', 'json'], appRoot));
  const doctor = JSON.parse(run(['doctor', '--format', 'json'], appRoot));
  const result = clean({ app, sourceFiles: files.length, facadeImports,
    aliases: [...aliases].sort(), lint, doctor });
  writeFileSync(join(output, `${app}.json`), JSON.stringify(result, null, 2) + '\n');
  report.apps.push(result);
  failed ||= lint.partial || lint.summary.total > 0 || lint.summary.skipped > 0 || doctor.summary.fail > 0;
  console.log(`${app}: ${files.length} files, ${facadeImports} facade imports, `
    + `${lint.summary.total} lint issues, ${doctor.summary.fail} configuration failures`);
}
report.passed = !failed;
writeFileSync(join(output, 'summary.json'), JSON.stringify(report, null, 2) + '\n');
console.log(`Reports: ${relative(root, output)}`);
process.exitCode = failed ? 1 : 0;
