"use client";

/** Phase Convert (C3 #6): an explicit empty/first-run/not-yet state instead of a blank panel. */
export default function EmptyState({
  title,
  children,
  action,
}: {
  title: string;
  children?: React.ReactNode;
  action?: React.ReactNode;
}) {
  return (
    <div className="text-center px-6 py-10">
      <p className="font-semibold">{title}</p>
      {children && <p className="text-sm text-muted mt-1 max-w-[34ch] mx-auto">{children}</p>}
      {action && <div className="mt-4 flex justify-center">{action}</div>}
    </div>
  );
}
