"use client";

import { useState } from "react";

/**
 * §24's pattern, used for both project deletion ("type the project's name") and
 * account deletion ("type DELETE"): a real typed confirmation, not a generic
 * "are you sure?" dialog. One component, parameterized by what has to be typed.
 */
export default function ConfirmTypedAction({
  requiredText,
  onConfirm,
  confirmLabel = "Delete",
  danger = true,
}: {
  requiredText: string;
  onConfirm: () => void | Promise<void>;
  confirmLabel?: string;
  danger?: boolean;
}) {
  const [value, setValue] = useState("");
  const [busy, setBusy] = useState(false);
  const matches = value === requiredText;

  return (
    <div className="space-y-2">
      <label className="label">
        Type <span className="mono font-semibold text-ink">{requiredText}</span> to confirm
      </label>
      <input className="input" value={value} onChange={(e) => setValue(e.target.value)} />
      <button
        disabled={!matches || busy}
        className={danger ? "btn-danger disabled:opacity-40" : "btn-primary disabled:opacity-40"}
        onClick={async () => {
          setBusy(true);
          try {
            await onConfirm();
          } finally {
            setBusy(false);
          }
        }}
      >
        {busy ? "Working…" : confirmLabel}
      </button>
    </div>
  );
}
