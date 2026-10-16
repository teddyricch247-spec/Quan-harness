import type { Metadata } from 'next';
import { AdminPage } from '../../components/pages/AdminPage';
import { RequireAuth } from '../../components/RequireAuth';

export const metadata: Metadata = {
  title: 'Admin — Quancis',
  robots: { index: false, follow: false },
};

export default function Page() {
  return (
    <RequireAuth>
      <AdminPage />
    </RequireAuth>
  );
}
