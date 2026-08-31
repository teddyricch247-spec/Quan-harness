import { useEffect, useState } from 'react';

const STORAGE_KEY = 'harness.theme';

// index.html already runs this same read synchronously before React mounts (see the
// inline script there) so the correct theme applies before first paint — this just
// keeps this component's own state in sync with whatever that script decided.
function getInitialTheme() {
  try {
    const stored = localStorage.getItem(STORAGE_KEY);
    if (stored === 'light' || stored === 'dark') return stored;
  } catch {
    // storage unavailable — fall through to system preference
  }
  return window.matchMedia?.('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
}

export default function ThemeToggle() {
  const [theme, setTheme] = useState(getInitialTheme);

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    try {
      localStorage.setItem(STORAGE_KEY, theme);
    } catch {
      // private browsing / storage disabled — toggle still works for this tab
    }
  }, [theme]);

  return (
    <button
      type="button"
      className="ghost theme-toggle"
      onClick={() => setTheme((t) => (t === 'dark' ? 'light' : 'dark'))}
      aria-label={theme === 'dark' ? 'Switch to light mode' : 'Switch to dark mode'}
    >
      {theme === 'dark' ? 'Light' : 'Dark'}
    </button>
  );
}
