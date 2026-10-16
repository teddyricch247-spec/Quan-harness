'use client';

import React from 'react';
import { ChevronDown } from 'lucide-react';
import { BETA_OPTIONS, PRO_BETA_OPTIONS, SDK_OPTION, thinkingOption } from '../lib/thinkingLevels';
import { BETA, PRO_BETA } from './docs/facts';

interface Props {
  value: string;
  onChange: (value: string) => void;
  disabled?: boolean;
  id?: string;
  ariaLabel?: string;
  /** Smaller control for use inside the keys table. */
  compact?: boolean;
}

// Grouped by model, because a level only applies to the model that offers it.
// A native <select> on purpose: it is the one dropdown that works inside the
// keys table's horizontal scroller (a custom popover would be clipped by it)
// and it uses the phone's own picker on mobile.
export const ThinkingLevelSelect: React.FC<Props> = ({ value, onChange, disabled, id, ariaLabel, compact }) => {
  return (
    <div className="relative inline-block w-full">
      <select
        id={id}
        aria-label={ariaLabel}
        value={thinkingOption(value).value}
        disabled={disabled}
        onChange={(e) => onChange(e.target.value)}
        className={`w-full appearance-none rounded-xl border border-line bg-white pr-8 text-ink focus:border-accent-blue focus:outline-none disabled:cursor-not-allowed disabled:opacity-60 cursor-pointer ${
          compact ? 'py-1.5 pl-3 text-xs' : 'py-2.5 pl-3 text-xs'
        }`}
      >
        <option value={SDK_OPTION.value}>SDK (default)</option>
        <optgroup label={BETA.name}>
          {BETA_OPTIONS.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </optgroup>
        <optgroup label={`${PRO_BETA.name} (higher price per token)`}>
          {PRO_BETA_OPTIONS.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </optgroup>
      </select>
      <ChevronDown className="pointer-events-none absolute right-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-ink-3" />
    </div>
  );
};
