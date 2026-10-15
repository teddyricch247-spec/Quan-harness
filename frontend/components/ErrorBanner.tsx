"use client";

export default function ErrorBanner({ message }: { message: string | null }) {
  if (!message) return null;
  return (
    <div className="border border-accent/40 bg-accent-soft text-accent text-sm rounded-md px-3 py-2 mb-4">
      {message}
    </div>
  );
}
