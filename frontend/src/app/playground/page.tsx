import type { Metadata } from 'next';
import { PlaygroundPage } from '../../components/pages/PlaygroundPage';

export const metadata: Metadata = {
  title: 'Playground & Chat — Quancis',
  description: 'Try Quan Kael beta directly in the browser before wiring up the API.',
  // Signed-in app screen, like /dashboard, /usage and /account.
  robots: { index: false, follow: false },
};

export default function Page() {
  return <PlaygroundPage />;
}
