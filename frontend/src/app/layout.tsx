import type { Metadata } from 'next';
import { Inter, JetBrains_Mono } from 'next/font/google';
import './globals.css';
import { AppProviders } from '../components/providers/AppProviders';
import { SITE_URL } from '../lib/site';

const inter = Inter({
  subsets: ['latin'],
  weight: ['400', '500', '600'],
  variable: '--font-inter',
  display: 'swap',
});

const jetBrainsMono = JetBrains_Mono({
  subsets: ['latin'],
  weight: ['400', '500', '600', '700'],
  style: ['normal', 'italic'],
  variable: '--font-jetbrains-mono',
  display: 'swap',
});

const DEFAULT_TITLE = 'Quancis Developer Platform — Kael API';
const DEFAULT_DESCRIPTION =
  'Get an API key for Kael, the composite intelligence from Quancis. Works with the Chat Completions, Responses and Anthropic Messages formats.';

export const metadata: Metadata = {
  metadataBase: new URL(SITE_URL),
  title: DEFAULT_TITLE,
  description: DEFAULT_DESCRIPTION,
  openGraph: {
    title: DEFAULT_TITLE,
    description: DEFAULT_DESCRIPTION,
    siteName: 'Quancis',
    type: 'website',
  },
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" className={`${inter.variable} ${jetBrainsMono.variable}`}>
      <body className="bg-white text-ink antialiased font-sans selection:bg-ink selection:text-white">
        <AppProviders>{children}</AppProviders>
      </body>
    </html>
  );
}
