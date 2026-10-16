import type { Metadata } from 'next';
import { HomeGate } from '../components/HomeGate';
import { BETA, PRO_BETA, usd } from '../components/docs/facts';

// The platform home targets the developer intent ("get a Kael API key"), so
// its title and description differ from www.quancis.space, which targets the
// brand. A self-referencing canonical keeps this URL as the one Google
// shows for that intent.
export const metadata: Metadata = {
  title: 'Kael API — Get an API Key | Quancis Developer Platform',
  description:
    `Create an account, get an API key and call Kael, a composite intelligence, through an OpenAI-compatible API. Kael Beta is ${usd(BETA.price.input)}/M input, ${usd(BETA.price.cachedInput)}/M cached input, ${usd(BETA.price.output)}/M output. Kael Pro Beta costs more: ${usd(PRO_BETA.price.input)}/M input, ${usd(PRO_BETA.price.output)}/M output.`,
  alternates: { canonical: '/' },
};

export default function Page() {
  return <HomeGate />;
}
