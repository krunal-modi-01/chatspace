#!/usr/bin/env node
/**
 * CI/lint guard (T53–T56): bans raw Tailwind palette classes
 * (`gray-*`/`amber-*`/`emerald-*`/`red-*`/`indigo-*`) under `src/components/**`.
 *
 * architecture/design-tokens.md §2/§12/§15: color is a semantic token
 * (`--color-*`) or a token-driven recipe (`.tint-surface`/`.tint-neutral`,
 * `Badge`), never a raw palette shade — a hardcoded Tailwind color class in a
 * component is a defect the moment it's written, not something caught later
 * in review. This script is that gate, wired into `npm run lint` (and so
 * into CI's existing "frontend (lint, typecheck, test, build)" job).
 *
 * Scope: `frontend/src/components/**` only (not `src/pages/**`, which is out
 * of scope for this ticket).
 *
 * Allowlist (documented, narrow, not a blanket exemption):
 *  - `ui/AuroraBackground.tsx` — the ambient gradient/noise wrapper's
 *    `indigo-*` blob colors are the *documented* gradient recipe
 *    (design-tokens.md §3), not a stray palette class.
 *
 * `nav/MyChannelsNav.tsx`'s hand-rolled visibility/role pill badges were
 * removed by T58 in favor of the shared `Badge` primitive (design-tokens.md
 * §14) — it is intentionally no longer allowlisted. Every component must be
 * clean; new violations anywhere fail the build.
 */

import { readdirSync, readFileSync, statSync } from 'node:fs';
import { dirname, join, relative } from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = dirname(fileURLToPath(import.meta.url));
const COMPONENTS_ROOT = join(__dirname, '..', 'src', 'components');

// Matches e.g. `bg-gray-100`, `dark:text-indigo-400`, `border-red-300/60` —
// any Tailwind color utility built on one of the banned palettes at a real
// Tailwind shade step. Word-boundary on both sides so it doesn't match
// substrings of unrelated identifiers.
const BANNED_PATTERN =
  /\b(gray|amber|emerald|red|indigo)-(50|100|200|300|400|500|600|700|800|900|950)\b/g;

const ALLOWLIST = new Set([join('ui', 'AuroraBackground.tsx')]);

/** @param {string} dir @returns {string[]} */
function walk(dir) {
  const out = [];
  for (const entry of readdirSync(dir)) {
    const full = join(dir, entry);
    const st = statSync(full);
    if (st.isDirectory()) {
      out.push(...walk(full));
    } else if (/\.(tsx|ts)$/.test(entry) && !entry.endsWith('.test.tsx') && !entry.endsWith('.test.ts')) {
      out.push(full);
    }
  }
  return out;
}

const files = walk(COMPONENTS_ROOT);
/** @type {{ file: string, line: number, match: string }[]} */
const violations = [];

for (const file of files) {
  const rel = relative(COMPONENTS_ROOT, file);
  if (ALLOWLIST.has(rel)) continue;

  const content = readFileSync(file, 'utf8');
  const lines = content.split('\n');
  lines.forEach((lineText, idx) => {
    const matches = lineText.match(BANNED_PATTERN);
    if (matches) {
      for (const match of matches) {
        violations.push({ file: relative(process.cwd(), file), line: idx + 1, match });
      }
    }
  });
}

if (violations.length > 0) {
  console.error('palette-class-guard: BLOCKED — raw Tailwind palette classes found under src/components/**:\n');
  for (const v of violations) {
    console.error(`  ${v.file}:${v.line}  (${v.match})`);
  }
  console.error(
    '\nUse a semantic token instead: var(--color-*) for surfaces/text, or the ' +
      '.tint-surface/.tint-neutral badge recipe (architecture/design-tokens.md §12) for ' +
      'status colors. See architecture/design-tokens.md §2/§15.',
  );
  process.exit(1);
}

console.log('palette-class-guard: clean — no raw palette classes under src/components/**.');
