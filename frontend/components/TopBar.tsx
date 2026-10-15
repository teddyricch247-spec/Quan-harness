"use client";

import Link from "next/link";
import { BackIcon, MenuIcon } from "./icons";
import { useShell } from "./ShellContext";

/**
 * Phase Convert (C7). The bar every screen starts with: a leading control, a title (or any node),
 * and trailing controls. Leading is the drawer button by default; pass `back` for a sub-page's
 * back arrow ("back arrow returns to Settings", C6). Touch targets are 36 px or more, and the bar
 * clears the notch with the safe-area inset.
 */
export default function TopBar({
  title,
  subtitle,
  back,
  onBack,
  hideMenu = false,
  right,
  center,
  onTitleClick,
}: {
  title?: React.ReactNode;
  subtitle?: React.ReactNode;
  back?: string;
  onBack?: () => void;
  hideMenu?: boolean;
  right?: React.ReactNode;
  center?: React.ReactNode;
  onTitleClick?: () => void;
}) {
  const { openDrawer } = useShell();

  return (
    <header className="flex items-center gap-2 px-3 min-h-[56px] flex-none pt-safe-top bg-paper">
      {back ? (
        <Link href={back} onClick={onBack} aria-label="Back" className="w-9 h-9 grid place-items-center rounded-lg border border-line bg-white flex-none">
          <BackIcon />
        </Link>
      ) : (
        <button
          onClick={openDrawer}
          aria-label="Open menu"
          className={`w-9 h-9 grid place-items-center rounded-lg border border-line bg-white flex-none desk:hidden ${hideMenu ? "hidden" : ""}`}
        >
          <MenuIcon />
        </button>
      )}
      <div className="flex-1 min-w-0 flex items-center justify-center desk:justify-start">
        {center ??
          (title != null && (
            <div className="min-w-0 w-full">
              {onTitleClick ? (
                <h1 className="font-semibold truncate text-[15px]">
                  <button onClick={onTitleClick} className="block max-w-full text-left truncate">
                    {title}
                  </button>
                </h1>
              ) : (
                <h1 className="font-semibold truncate text-[15px]">{title}</h1>
              )}
              {subtitle != null && <div className="text-xs text-muted mono truncate">{subtitle}</div>}
            </div>
          ))}
      </div>
      <div className="flex items-center gap-2 flex-none">{right}</div>
    </header>
  );
}
