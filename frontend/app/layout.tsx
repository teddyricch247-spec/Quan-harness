import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Quan Harness",
  description: "Delegate coding tasks to an AI agent with real access to your own codebase.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="font-sans antialiased">{children}</body>
    </html>
  );
}
