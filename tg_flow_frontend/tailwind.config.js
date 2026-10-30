/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        // Linear.app inspired dark theme
        linear: {
          bg: '#000000',
          'bg-secondary': '#0a0a0b',
          'bg-tertiary': '#111113',
          'bg-hover': '#18181b',
          border: '#1f1f23',
          'border-hover': '#2a2a2e',
          text: '#ffffff',
          'text-secondary': '#a1a1aa',
          'text-tertiary': '#71717a',
          accent: '#8b5cf6',
          'accent-hover': '#a78bfa',
        },
        // Telegram theme colors
        tg: {
          bg: 'var(--tg-theme-bg-color, #000000)',
          text: 'var(--tg-theme-text-color, #ffffff)',
          hint: 'var(--tg-theme-hint-color, #71717a)',
          link: 'var(--tg-theme-link-color, #8b5cf6)',
          button: 'var(--tg-theme-button-color, #8b5cf6)',
          'button-text': 'var(--tg-theme-button-text-color, #ffffff)',
          secondary: 'var(--tg-theme-secondary-bg-color, #0a0a0b)',
        },
      },
      fontFamily: {
        sans: ['Inter', '-apple-system', 'BlinkMacSystemFont', 'Segoe UI', 'Roboto', 'sans-serif'],
      },
      animation: {
        'spin-slow': 'spin 3s linear infinite',
        'pulse-slow': 'pulse 4s cubic-bezier(0.4, 0, 0.6, 1) infinite',
      },
      backdropBlur: {
        xs: '2px',
      },
      transitionDuration: {
        '400': '400ms',
      },
      borderRadius: {
        'xl': '12px',
        '2xl': '16px',
      },
    },
  },
  plugins: [],
}
