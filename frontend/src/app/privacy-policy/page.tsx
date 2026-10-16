import type { Metadata } from 'next';
import { PrivacyPage } from '../../components/pages/PrivacyPage';

export const metadata: Metadata = {
  title: 'Privacy Policy — Quancis',
  description: 'How Quancis collects, uses, and protects your information.',
};

export default function Page() {
  return <PrivacyPage />;
}
