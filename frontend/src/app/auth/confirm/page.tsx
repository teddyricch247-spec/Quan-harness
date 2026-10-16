import type { Metadata } from 'next';
import { AuthConfirmPage } from '../../../components/pages/AuthConfirmPage';

export const metadata: Metadata = {
  title: 'Confirm — Quancis',
  robots: { index: false, follow: false },
};

export default function Page() {
  return <AuthConfirmPage />;
}
