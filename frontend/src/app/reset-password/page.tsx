import type { Metadata } from 'next';
import { ResetPasswordPage } from '../../components/pages/ResetPasswordPage';

export const metadata: Metadata = {
  title: 'Reset Password — Quancis',
  robots: { index: false, follow: false },
};

export default function Page() {
  return <ResetPasswordPage />;
}
