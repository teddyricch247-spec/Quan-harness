"use client";

import Link from "next/link";
import { CHAT_ENABLED } from "@/lib/flags";
import { needsYou } from "@/lib/useAttention";
import { useShell } from "./ShellContext";

/** The red dot on a tab: "the other surface needs you" (C4). */
export function TabBadge({ show }: { show: boolean }) {
  if (!show) return null;
  return <span className="inline-block w-2 h-2 rounded-full bg-brand ml-1.5" role="img" aria-label="Needs your attention" />;
}

/**
 * Chat | Code. Not rendered at all until CHAT_ENABLED (C4: "the switch is hidden, so there is no
 * dead tab"). The dot on a tab shows when *that* surface has something waiting; the surface you are
 * already on never needs one, because you are looking at it.
 */
export default function TabSwitch() {
  const { surface, attention } = useShell();
  if (!CHAT_ENABLED) return null;

  const item = (label: string, href: string, active: boolean, dot: boolean) => (
    <Link
      href={href}
      aria-current={active ? "page" : undefined}
      className={`flex-1 inline-flex items-center justify-center rounded-[7px] px-4 py-1.5 text-sm min-h-[32px] ${
        active ? "bg-white font-semibold text-ink" : "text-muted"
      }`}
    >
      {label}
      <TabBadge show={!active && dot} />
    </Link>
  );

  return (
    <nav aria-label="Surface" className="flex bg-soft rounded-[9px] p-[3px] w-[180px]">
      {item("Chat", "/ask", surface === "chat", needsYou(attention.chat))}
      {item("Code", "/projects", surface === "code", needsYou(attention.code))}
    </nav>
  );
}
