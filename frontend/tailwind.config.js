/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      fontFamily: {
        sans: ["Inter", "ui-sans-serif", "system-ui", "sans-serif"],
        display: ["Space Grotesk", "Inter", "ui-sans-serif", "sans-serif"],
      },
      colors: {
        "neon-cyan": "#00c2ff",
        "neon-purple": "#7c5cfc",
        "neon-pink": "#f472b6",
        "neon-green": "#34d399",
        "neon-orange": "#fb923c",
        "bg-base": "#0d0f17",
        "bg-card": "#181a28",
        "bg-card2": "#1f2134",
      },
      borderRadius: { "2xl": "20px", "3xl": "28px" },
      keyframes: {
        "fade-up": {
          "0%": { opacity: "0", transform: "translateY(16px)" },
          "100%": { opacity: "1", transform: "translateY(0)" },
        },
        shimmer: {
          "0%": { backgroundPosition: "-400px 0" },
          "100%": { backgroundPosition: " 400px 0" },
        },
      },
      animation: {
        "fade-up": "fade-up 0.45s ease-out both",
      },
    },
  },
  plugins: [],
};
