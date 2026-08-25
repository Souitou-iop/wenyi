/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        apple: {
          primary: "#0066cc",
          "primary-focus": "#0071e3",
          "primary-on-dark": "#2997ff",
          ink: "#1d1d1f",
          "ink-muted-80": "#333333",
          "ink-muted-48": "#7a7a7a",
          "divider-soft": "#f0f0f0",
          hairline: "#e0e0e0",
          canvas: "#ffffff",
          parchment: "#f5f5f7",
          pearl: "#fafafc",
          "tile-1": "#272729",
          "tile-2": "#2a2a2c",
          "tile-3": "#252527",
          black: "#000000",
          "chip-translucent": "#d2d2d7",
        }
      },
      borderRadius: {
        'apple-sm': '8px',
        'apple-md': '11px',
        'apple-lg': '18px',
        'apple-pill': '9999px',
      },
      fontFamily: {
        display: ['"SF Pro Display"', '-apple-system', 'BlinkMacSystemFont', '"PingFang SC"', '"Helvetica Neue"', 'sans-serif'],
        body: ['"SF Pro Text"', '-apple-system', 'BlinkMacSystemFont', '"PingFang SC"', '"Helvetica Neue"', 'sans-serif'],
        mono: ['"SF Mono"', 'Menlo', 'Monaco', 'Courier New', 'monospace'],
      },
      letterSpacing: {
        'apple-headline': '-0.374px',
        'apple-display': '-0.28px',
      }
    },
  },
  plugins: [],
}
