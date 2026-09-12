/* ESLint, flat config.
 *
 * `next lint` was the linter here and it is gone in Next 16. Worse than
 * deprecated, it is INTERACTIVE: with no ESLint configured it prompts for a
 * preset and waits, so `npm run lint` hung forever anywhere without a
 * terminal — a CI job, a pre-commit hook, an agent. A check that cannot run
 * unattended is not a check, and this project has spent enough on guards that
 * were only theoretically enforced.
 *
 * `next/core-web-vitals` is the ruleset `next lint` would have installed under
 * "Strict". Nothing is added beyond it here: a linter's first run should
 * report the state of the code, not the state of somebody's preferences.
 */
import { dirname } from 'path';
import { fileURLToPath } from 'url';
import { FlatCompat } from '@eslint/eslintrc';

const compat = new FlatCompat({
  baseDirectory: dirname(fileURLToPath(import.meta.url)),
});

const config = [
  { ignores: ['.next/**', 'node_modules/**', 'next-env.d.ts'] },
  ...compat.extends('next/core-web-vitals', 'next/typescript'),
];

export default config;
