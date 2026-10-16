import type { Metadata } from 'next';
import { DocsPage } from '../../components/pages/DocsPage';
import { ROUTES } from '../../lib/routes';

export const metadata: Metadata = {
  title: 'Docs: Build with Kael — Quancis',
  description:
    'Documentation for the Kael API: quickstart, authentication, endpoints, thinking levels, streaming, pricing, limits, errors, and the Quancis console.',
  alternates: { canonical: ROUTES.docs },
};

export default function Page() {
  return <DocsPage slug="overview" />;
}
