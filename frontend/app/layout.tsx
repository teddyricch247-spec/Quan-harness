import type { Metadata, Viewport } from "next";
import "./globals.css";
import AppShell from "@/components/AppShell";

export const metadata: Metadata = {
  title: "Quan Harness",
  description: "Delegate coding tasks to an AI agent with real access to your own codebase.",
};

// §11's mobile-quality requirement: `viewport-fit=cover` lets the shell draw under the notch and
// home indicator and then clear them with env(safe-area-inset-*) (see TopBar, Sheet, Composer).
export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  viewportFit: "cover",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="font-sans antialiased">
        <AppShell>{children}</AppShell>
      </body>
    </html>
  );
}
