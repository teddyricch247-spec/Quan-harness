import type { Metadata } from 'next';
import { ApiKeysPage } from '../../components/pages/ApiKeysPage';
import { RequireAuth } from '../../components/RequireAuth';

export const metadata: Metadata = {
  title: 'API Keys — Quancis',
  robots: { index: false, follow: false },
};

export default function Page() {
  return (
    <RequireAuth>
      <ApiKeysPage />
    </RequireAuth>
  );
}
