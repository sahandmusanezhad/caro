import type { Config } from 'tailwindcss';

export default {
  content: ['./app/**/*.{ts,tsx}', './components/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        // `surface` is the palette's surface at seven tenths: a pane, not a
        // wall (globals.css, GLASS). The opaque value is `--surface` itself.
        ground: 'var(--ground)',
        surface: 'color-mix(in srgb, var(--surface) 70%, transparent)',
        sunk: 'color-mix(in srgb, var(--sunk) 75%, transparent)',
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
