import type { Metadata } from 'next';
import { TermsPage } from '../../components/pages/TermsPage';

export const metadata: Metadata = {
  title: 'Terms of Service — Quancis',
  description: 'The terms governing your use of the Quancis API, playground, dashboard, and related services.',
};

export default function Page() {
  return <TermsPage />;
}
