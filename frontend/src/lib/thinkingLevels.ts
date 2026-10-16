// The thinking-level choices an API key can be set to (API Keys page).
//
// Source of truth for WHICH levels exist and which model each belongs to:
// backend/app/models/kael/config.py `reasoning_tiers` (mirrored by BETA and
// PRO_BETA in components/docs/facts.ts, which this file reads). Every level
// belongs to exactly one model: low, high and max are Kael Beta's; z-low and
// z-high are Kael Pro Beta's. A pinned level therefore applies only to its own
// model. On the other model the key behaves like "SDK": the request decides
// (backend/app/kael_pipeline.py, _pinned_tier).
//
// "sdk" is not a tier: it means "this key pins nothing, the request decides".
// The backend stores it as NULL and returns the string "sdk"
// (backend/app/api_keys.py).

import { BETA, PRO_BETA, usd } from '../components/docs/facts';

export const SDK_LEVEL = 'sdk';

export interface ThinkingOption {
  value: string;
  /** What the dropdown shows: "Low", "z-low", "SDK". */
  label: string;
  /** Name of the model this level belongs to; null for SDK. */
  modelName: string | null;
  /** Label plus model, for places with no dropdown group around it: "High (Kael Beta)". */
  fullLabel: string;
  /** One line shown under the dropdown; says what the choice does for this key. */
  hint: string;
  /** Kael Pro Beta's levels are priced higher per token than Kael Beta's. */
  higherPrice: boolean;
}

// Short description of each level, written to fit "... runs at <level> (<blurb>)".
const COPY: Record<string, { label: string; blurb: string }> = {
  low: { label: 'Low', blurb: 'the quickest level' },
  high: { label: 'High', blurb: 'good for debugging and multi-step work' },
  max: { label: 'Max', blurb: 'slowest to start, for your hardest work' },
  'z-low': { label: 'z-low', blurb: 'for demanding work' },
  'z-high': { label: 'z-high', blurb: 'the most thorough level' },
};

export const SDK_OPTION: ThinkingOption = {
  value: SDK_LEVEL,
  label: 'SDK',
  modelName: null,
  fullLabel: 'SDK',
  hint: `Your SDK or request decides. If it sets nothing, ${BETA.name} uses ${BETA.defaultLevel} and ${PRO_BETA.name} uses ${PRO_BETA.defaultLevel}.`,
  higherPrice: false,
};

const optionsFor = (model: typeof BETA | typeof PRO_BETA, other: typeof BETA | typeof PRO_BETA): ThinkingOption[] =>
  model.thinkingLevels.map((value) => {
    const copy = COPY[value];
    const label = copy?.label ?? value;
    const higherPrice = model === PRO_BETA;
    const price = higherPrice ? ` Priced at ${usd(model.price.input)} in, ${usd(model.price.output)} out per 1M tokens.` : '';
    return {
      value,
      label,
      modelName: model.name,
      fullLabel: `${label} (${model.name})`,
      hint:
        `Every ${model.name} request from this key runs at ${value}${copy ? ` (${copy.blurb})` : ''}.${price} ` +
        `Requests to ${other.name} from this key still use whatever the request sets.`,
      higherPrice,
    };
  });

export const BETA_OPTIONS: ThinkingOption[] = optionsFor(BETA, PRO_BETA);
export const PRO_BETA_OPTIONS: ThinkingOption[] = optionsFor(PRO_BETA, BETA);
export const LEVEL_OPTIONS: ThinkingOption[] = [...BETA_OPTIONS, ...PRO_BETA_OPTIONS];

export const THINKING_OPTIONS: ThinkingOption[] = [SDK_OPTION, ...LEVEL_OPTIONS];

/** The option for a value from the backend; anything unknown reads as SDK. */
export function thinkingOption(value: string | undefined | null): ThinkingOption {
  return THINKING_OPTIONS.find((o) => o.value === value) ?? SDK_OPTION;
}
