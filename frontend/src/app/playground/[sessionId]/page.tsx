import type { Metadata } from 'next';
import { PlaygroundPage } from '../../../components/pages/PlaygroundPage';

export const metadata: Metadata = {
  title: 'Playground & Chat — Quancis',
  description: 'Try Quan Kael beta directly in the browser before wiring up the API.',
  // Signed-in app screen, like /dashboard, /usage and /account.
  robots: { index: false, follow: false },
};

// Deployed on Vercel, which renders Next.js routes on demand — so unlike
// a static export, this plain dynamic segment doesn't need
// generateStaticParams to enumerate session ids in advance, and a direct
// link or hard refresh on /playground/<id> just works without any
// host-side rewrite rule. PlaygroundPage reads the id via useParams() and
// fetches that one session's messages client-side (auth is entirely
// client-side via Supabase, so there's no server-side data to fetch here).
export default function Page() {
  return <PlaygroundPage />;
}
