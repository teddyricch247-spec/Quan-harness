import type { Metadata } from 'next';
import { PricingPage } from '../../components/pages/PricingPage';
import { BETA, PRO_BETA, usd } from '../../components/docs/facts';

export const metadata: Metadata = {
  title: 'Pricing — Quancis',
  description:
    `Kael Beta costs ${usd(BETA.price.input)}/M input, ${usd(BETA.price.cachedInput)}/M cached input (up to 80% off) and ${usd(BETA.price.output)}/M output tokens. Kael Pro Beta costs ${usd(PRO_BETA.price.input)}/M input, ${usd(PRO_BETA.price.cachedInput)}/M cached input and ${usd(PRO_BETA.price.output)}/M output. Compared against GPT-6 Astra, GPT-6 Sol, Claude Opus 5.5, Claude Fable 5.1, and Kimi K3.`,
};

export default function Page() {
  return <PricingPage />;
}
