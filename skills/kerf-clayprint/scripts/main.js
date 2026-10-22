// True when this module is the script node was asked to run. Works on Node 20+, unlike import.meta.main (Node 24.2+).
import { realpathSync } from 'node:fs';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { MODE } from './tokens.js';

export const isMain = (url) => {
  if (!process.argv[1]) return false;
  try { return realpathSync(process.argv[1]) === realpathSync(fileURLToPath(url)); }
  catch { return false; }
};

// Sizes are read at import, so a story whose mode differs from this process reruns the same command under its mode.
// Returns true when the rerun has handled the command.
export function rerunForMode(story) {
  const want = story?.mode === 'read' ? 'read' : 'present';
  if (want === MODE) return false;
  const child = spawnSync(process.execPath, [...process.execArgv, ...process.argv.slice(1)], { stdio: 'inherit', env: { ...process.env, CLAYPRINT_MODE: want } });
  process.exitCode = child.status ?? 1;
  return true;
}
