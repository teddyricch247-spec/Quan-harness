import { useEffect, useState } from 'react';

// Peak windows are half-open: [1,4) and [6,10) UTC — i.e. 01:00:00–03:59:59 and
// 06:00:00–09:59:59. Edit these two ranges if the expensive hours change.
const PEAK_WINDOWS = [
  [1, 4],
  [6, 10],
];

function isPeak(date) {
  const h = date.getUTCHours();
  return PEAK_WINDOWS.some(([start, end]) => h >= start && h < end);
}

function pad(n) {
  return String(n).padStart(2, '0');
}

function formatUtc(date) {
  return `${pad(date.getUTCHours())}:${pad(date.getUTCMinutes())}:${pad(date.getUTCSeconds())}`;
}

const STORAGE_KEY = 'utcPeakClock.showExplanation';

export default function UtcPeakClock() {
  const [now, setNow] = useState(() => new Date());
  const [showExplanation, setShowExplanation] = useState(() => {
    try {
      return localStorage.getItem(STORAGE_KEY) !== 'hidden';
    } catch {
      return true;
    }
  });

  useEffect(() => {
    const id = setInterval(() => setNow(new Date()), 1000);
    return () => clearInterval(id);
  }, []);

  const peak = isPeak(now);

  function toggleExplanation() {
    setShowExplanation((prev) => {
      const next = !prev;
      try {
        localStorage.setItem(STORAGE_KEY, next ? 'shown' : 'hidden');
      } catch {
        // ignore storage errors (private browsing, etc.)
      }
      return next;
    });
  }

  return (
    <div className={`utc-clock${peak ? ' utc-clock-peak' : ''}`}>
      <div className="utc-clock-row">
        <span className="utc-clock-time">{formatUtc(now)} UTC</span>
        {peak && <span className="badge utc-clock-badge">Peak</span>}
        <button
          type="button"
          className="ghost utc-clock-toggle"
          onClick={toggleExplanation}
          aria-label={showExplanation ? 'Hide peak-time explanation' : 'Show peak-time explanation'}
          aria-pressed={showExplanation}
        >
          !
        </button>
      </div>
      {peak && showExplanation && (
        <p className="utc-clock-note">Peak time — API rates are expensive right now.</p>
      )}
    </div>
  );
}
