/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        cosmic: "#050812",
        deep: "#0b1020",
        orbital: "#101a2d",
        surface: "#121d32",
        cyanGlow: "#35d6ff",
        plasma: "#2f80ff",
        success: "#2ee59d",
        amber: "#ffb84d",
        danger: "#ff4d5e"
      },
      fontFamily: {
        ui: ["Plus Jakarta Sans", "Inter", "Geist", "Satoshi", "Helvetica", "Arial", "sans-serif"],
        mono: ["Cascadia Code", "Consolas", "JetBrains Mono", "Courier New", "monospace"]
      },
      boxShadow: {
        glow: "0 0 22px rgba(53, 214, 255, 0.28)",
        danger: "0 0 18px rgba(255, 77, 94, 0.25)"
      }
    }
  },
  plugins: []
};
