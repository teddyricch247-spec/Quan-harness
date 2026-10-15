import type { Config } from "tailwindcss";

// §11.4 of the spec: avoid the generic AI-tool look (soft-shadow cards, a single
// terracotta accent, tracked-out uppercase eyebrows). Monospace for anything
// code/log-shaped, a restrained two-weight type scale elsewhere, and color used
// functionally.
//
// Phase Convert (C4, "Visual language"): neutral, at least 90 % white, the red accent only on
// the logo and on the "needs you" dots, no emoji as icons, no suggestion chips, no upsell
// banners. The tokens below are the wireframe's `:root`; the pre-Convert names (ink, paper, line,
// muted, accent, accent-soft, ok) are kept so the existing Settings pages keep working unchanged.
const config: Config = {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}", "./lib/**/*.{ts,tsx}"],
  theme: {
    extend: {
      // The drawer is pinned from here up and the workspace shows both panes (C7 "Responsive rules").
      screens: { desk: "900px" },
      colors: {
        ink: "#161616",
        paper: "#f4f4f4",
        soft: "#ebebeb",
        line: "#e1e1e1",
        muted: "#6b6f76",
        brand: "#d6282d",
        accent: "#b5461e",
        "accent-soft": "#f4e3da",
        ok: "#2f6b4f", // unchanged from before Convert — it is also used as text, where a lighter green fails contrast
        warn: "#c98a00",
        "warn-soft": "#fffaf0",
      },
      fontFamily: {
        sans: ["ui-sans-serif", "system-ui", "-apple-system", "Segoe UI", "sans-serif"],
        mono: ["ui-monospace", "SFMono-Regular", "Menlo", "Consolas", "monospace"],
      },
      spacing: {
        "safe-top": "env(safe-area-inset-top, 0px)",
        "safe-bottom": "env(safe-area-inset-bottom, 0px)",
      },
    },
  },
  plugins: [],
};

export default config;
