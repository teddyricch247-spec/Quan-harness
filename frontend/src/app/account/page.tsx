import type { Metadata } from 'next';
import { AccountPage } from '../../components/pages/AccountPage';
import { RequireAuth } from '../../components/RequireAuth';

export const metadata: Metadata = {
  title: 'Account & Settings — Quancis',
  robots: { index: false, follow: false },
};

export default function Page() {
  return (
    <RequireAuth>
      <AccountPage />
    </RequireAuth>
  );
}
