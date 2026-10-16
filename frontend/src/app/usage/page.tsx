import type { Metadata } from 'next';
import { UsagePage } from '../../components/pages/UsagePage';
import { RequireAuth } from '../../components/RequireAuth';

export const metadata: Metadata = {
  title: 'Usage & Cost — Quancis',
  robots: { index: false, follow: false },
};

export default function Page() {
  return (
    <RequireAuth>
      <UsagePage />
    </RequireAuth>
  );
}
