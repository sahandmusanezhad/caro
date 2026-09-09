import type { Config } from 'tailwindcss';

export default {
  content: ['./app/**/*.{ts,tsx}', './components/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        ground: 'var(--ground)', surface: 'var(--surface)', sunk: 'var(--sunk)',
        ink: 'var(--ink)', 'ink-2': 'var(--ink-2)', 'ink-3': 'var(--ink-3)',
        line: 'var(--line)', 'line-2': 'var(--line-2)',
        accent: 'var(--accent)', 'accent-soft': 'var(--accent-soft)',
        warn: 'var(--warn)', 'warn-soft': 'var(--warn-soft)',
        bad: 'var(--bad)', 'bad-soft': 'var(--bad-soft)',
        good: 'var(--good)', 'good-soft': 'var(--good-soft)',
      },
      fontFamily: { fa: ['Vazirmatn', 'system-ui', 'sans-serif'], mono: ['"IBM Plex Mono"', 'ui-monospace', 'monospace'] },
    },
  },
  plugins: [],
} satisfies Config;
