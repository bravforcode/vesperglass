/** @type {import('tailwindcss').Config} */
export default {
  darkMode: 'class',
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  theme: {
    extend: {
      colors: {
        abyss: '#07090E',
        surface: {
          DEFAULT: '#0C1017',
          elevated: '#121824',
          glass: 'rgba(12, 16, 23, 0.72)',
          highlight: '#182030',
        },
        token: {
          cyan: '#00F2FE',
          emerald: '#10B981',
          violet: '#8B5CF6',
          amber: '#F59E0B',
          rose: '#F43F5E',
        },
        border: {
          subtle: 'rgba(255, 255, 255, 0.06)',
          medium: 'rgba(255, 255, 255, 0.12)',
        },
      },
      fontFamily: {
        sans: ['Inter', 'Plus Jakarta Sans', '-apple-system', 'sans-serif'],
        mono: ['JetBrains Mono', 'Geist Mono', 'Menlo', 'monospace'],
      },
      boxShadow: {
        'glass-card': '0 8px 32px 0 rgba(0, 0, 0, 0.36)',
        'glow-cyan': '0 0 20px -3px rgba(0, 242, 254, 0.35)',
        'glow-emerald': '0 0 20px -3px rgba(16, 185, 129, 0.35)',
        'glow-violet': '0 0 20px -3px rgba(139, 92, 246, 0.35)',
        'glow-amber': '0 0 20px -3px rgba(245, 158, 11, 0.35)',
      },
      backdropBlur: {
        xs: '2px',
        md: '12px',
      },
    },
  },
  plugins: [],
};
