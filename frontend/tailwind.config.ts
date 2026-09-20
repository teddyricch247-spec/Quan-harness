import type { Config } from "tailwindcss";

// §11.4 of the spec: avoid the generic AI-tool look (soft-shadow cards, a single
// terracotta accent, tracked-out uppercase eyebrows). Monospace for anything
// code/log-shaped, a restrained two-weight type scale elsewhere, and color used
// functionally — the accent exists for the one "stop and look here" moment
// (destructive confirmations, approval-shaped UI), not sprinkled everywhere.
const config: Config = {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        ink: "#16181c",
        paper: "#fafaf8",
        line: "#e4e2dd",
        muted: "#6b6f76",
        accent: "#b5461e",
        "accent-soft": "#f4e3da",
        ok: "#2f6b4f",
      },
      fontFamily: {
        sans: ["-apple-system", "BlinkMacSystemFont", "Segoe UI", "Inter", "sans-serif"],
        mono: ["SFMono-Regular", "Menlo", "Consolas", "monospace"],
      },
    },
  },
  plugins: [],
};

export default config;
