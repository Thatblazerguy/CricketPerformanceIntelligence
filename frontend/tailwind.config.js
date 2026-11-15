/** @type {import('tailwindcss').Config} */
// CPI design system — Tailwind bindings.
//
// Every colour resolves to a CSS custom property defined per theme in
// src/index.css (`:root` = dark, `[data-theme='light']` = light). Utilities such
// as `text-slate-300` or `bg-accent/10` therefore re-theme instantly without
// any component knowing which theme is active.
//
// The stock ramps that pages use directly (slate, indigo, emerald, red, amber,
// blue, violet…) are mapped onto the CPI palette. In light mode the ramps are
// mirrored (50 ↔ 950) so that "light text on dark" utilities written for the
// dark theme become "dark text on light" automatically, and tint backgrounds
// such as `bg-indigo-950/40` become pale washes.
const STEPS = [50, 100, 200, 300, 400, 500, 600, 700, 800, 900, 950];
const ramp = name => Object.fromEntries(STEPS.map(s => [s, `rgb(var(--${name}-${s}) / <alpha-value>)`]));
const v = name => `rgb(var(--${name}) / <alpha-value>)`;

const slate = ramp('slate');
const indigo = ramp('indigo');
const blue = ramp('blue');
const violet = ramp('violet');
const green = ramp('teal');
const red = ramp('red');
const amber = ramp('amber');

export default {
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  theme: {
    extend: {
      colors: {
        // `white` is the theme's maximum-contrast ink: white on dark, near-black on light.
        white: v('white'),
        'on-accent': '#ffffff',
        slate, gray: slate, zinc: slate, neutral: slate, stone: slate,
        indigo, sky: blue, blue, violet, purple: violet, fuchsia: violet,
        emerald: green, green, teal: green, lime: green, cyan: blue,
        red, rose: red, pink: red,
        amber, yellow: amber, orange: amber,
        surface: { DEFAULT: v('surface'), raised: v('surface-raised'), sunken: v('surface-sunken'), hover: v('surface-hover'), overlay: v('surface-overlay') },
        canvas: { DEFAULT: v('bg'), 2: v('bg-2') },
        line: { DEFAULT: v('line'), strong: v('line-strong'), soft: v('line-soft') },
        pos: { DEFAULT: v('pos'), soft: v('pos-soft'), muted: v('pos-muted') },
        neg: { DEFAULT: v('neg'), soft: v('neg-soft'), muted: v('neg-muted') },
        warn: { DEFAULT: v('warn'), soft: v('warn-soft'), muted: v('warn-muted') },
        gold: { DEFAULT: v('gold'), soft: v('gold-soft'), muted: v('gold-muted') },
        accent: { DEFAULT: v('accent'), soft: v('accent-soft'), strong: v('accent-strong'), muted: v('accent-muted') },
        electric: { DEFAULT: v('electric'), soft: v('electric-soft'), muted: v('electric-muted') },
        ink: { DEFAULT: v('ink'), muted: v('ink-muted'), faint: v('ink-faint') },
      },
      fontFamily: {
        sans: ['-apple-system', 'BlinkMacSystemFont', '"SF Pro Text"', '"SF Pro Display"', 'Inter', 'system-ui', '"Segoe UI"', 'Roboto', 'sans-serif'],
        display: ['-apple-system', 'BlinkMacSystemFont', '"SF Pro Display"', 'Inter', 'system-ui', 'sans-serif'],
        mono: ['ui-monospace', '"SF Mono"', 'SFMono-Regular', 'Menlo', '"JetBrains Mono"', 'monospace'],
      },
      fontSize: {
        '3xs': ['0.625rem', { lineHeight: '0.875rem' }],
        '2xs': ['0.6875rem', { lineHeight: '1rem' }],
      },
      borderRadius: {
        sm: '0.375rem', md: '0.625rem', lg: '0.75rem', xl: '1rem', '2xl': '1.25rem', '3xl': '1.5rem', '4xl': '1.75rem',
      },
      boxShadow: {
        sm: 'var(--shadow-sm)',
        DEFAULT: 'var(--shadow-sm)',
        md: 'var(--shadow-md)',
        lg: 'var(--shadow-lg)',
        xl: 'var(--shadow-lg)',
        '2xl': 'var(--shadow-pop)',
        panel: 'var(--shadow-card)',
        card: 'var(--shadow-card)',
        pop: 'var(--shadow-pop)',
        glass: 'var(--glass-shadow)',
        focus: '0 0 0 3px rgb(var(--accent) / 0.28)',
      },
      zIndex: { header: '20', nav: '30', drawer: '40', dropdown: '45', modal: '50', toast: '60' },
      transitionTimingFunction: {
        out: 'cubic-bezier(0.22, 1, 0.36, 1)',
        spring: 'cubic-bezier(0.34, 1.32, 0.64, 1)',
      },
      transitionDuration: { 120: '120ms', 180: '180ms', 250: '250ms', 350: '350ms' },
      keyframes: {
        'fade-up': { from: { opacity: '0', transform: 'translateY(6px)' }, to: { opacity: '1', transform: 'none' } },
        'fade-in': { from: { opacity: '0' }, to: { opacity: '1' } },
        'pop-in': { from: { opacity: '0', transform: 'scale(0.97) translateY(-4px)' }, to: { opacity: '1', transform: 'none' } },
        shimmer: { from: { backgroundPosition: '-400px 0' }, to: { backgroundPosition: '400px 0' } },
        'grow-x': { from: { transform: 'scaleX(0)' }, to: { transform: 'scaleX(1)' } },
      },
      animation: {
        'fade-up': 'fade-up 300ms cubic-bezier(0.22,1,0.36,1) both',
        'fade-in': 'fade-in 200ms ease-out both',
        'pop-in': 'pop-in 200ms cubic-bezier(0.22,1,0.36,1) both',
        shimmer: 'shimmer 1.4s linear infinite',
        'grow-x': 'grow-x 600ms cubic-bezier(0.22,1,0.36,1) both',
      },
    },
  },
  plugins: [],
};
