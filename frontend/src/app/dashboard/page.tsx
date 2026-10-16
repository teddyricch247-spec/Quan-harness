import type { Metadata } from 'next';
import { DashboardPage } from '../../components/pages/DashboardPage';
import { RequireAuth } from '../../components/RequireAuth';

export const metadata: Metadata = {
  title: 'Dashboard — Quancis',
  robots: { index: false, follow: false },
};

export default function Page() {
  return (
    <RequireAuth>
      <DashboardPage />
    </RequireAuth>
  );
}
