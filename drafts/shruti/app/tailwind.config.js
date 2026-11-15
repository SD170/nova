/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        void: '#05030A',
        purple: { DEFAULT: '#7C3AED', soft: '#A78BFA' },
        neon: '#39FF14',
      },
      fontFamily: {
        display: ['Orbitron', '"Space Grotesk"', 'system-ui', 'sans-serif'],
        grotesk: ['"Space Grotesk"', 'Inter', 'system-ui', 'sans-serif'],
        sans: ['Inter', 'system-ui', '-apple-system', 'sans-serif'],
      },
    },
  },
  plugins: [],
}
