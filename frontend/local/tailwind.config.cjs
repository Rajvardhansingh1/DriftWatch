// The same theme as the website (tailwind.config.ts), scanning only the files the local page uses.
module.exports = {
  darkMode: "class",
  content: ["./local/**/*.{ts,tsx}", "./components/SignalChart.tsx", "./components/SyncChip.tsx"],
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
      fontFamily: { mono: ["ui-monospace", "SFMono-Regular", "Menlo", "Consolas", "monospace"] },
    },
  },
  plugins: [],
};
