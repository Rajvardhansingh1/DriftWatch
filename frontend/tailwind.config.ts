import type { Config } from "tailwindcss";

// "Instrument panel" theme — see decision.md D-009/D-014.
const config: Config = {
  darkMode: "class",
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}", "./lib/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        bg: "#0A0E14",
        panel: "#10151D",
        line: "#1E2733",
        text: "#E6EDF3",
        dim: "#8A97A6",
        stable: "#3DDC97",
        drift: "#F2B84B",
        alert: "#FF5C5C",
      },
      fontFamily: {
        sans: ["var(--font-plex-sans)", "system-ui", "sans-serif"],
        mono: ["var(--font-plex-mono)", "ui-monospace", "monospace"],
      },
    },
  },
  plugins: [],
};

export default config;
