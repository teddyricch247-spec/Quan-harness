// Phase Convert (C4): "no emoji as icons". Small inline SVGs, all stroke-based so they inherit
// `currentColor`; sized by the caller with `className`.
type IconProps = { className?: string };

const base = {
  viewBox: "0 0 24 24",
  fill: "none",
  stroke: "currentColor",
  strokeWidth: 1.8,
  strokeLinecap: "round" as const,
  strokeLinejoin: "round" as const,
  "aria-hidden": true,
};

export const MenuIcon = ({ className = "w-5 h-5" }: IconProps) => (
  <svg {...base} className={className}>
    <path d="M4 7h16M4 12h16M4 17h16" />
  </svg>
);
export const PlusIcon = ({ className = "w-5 h-5" }: IconProps) => (
  <svg {...base} className={className}>
    <path d="M12 5v14M5 12h14" />
  </svg>
);
export const SendIcon = ({ className = "w-5 h-5" }: IconProps) => (
  <svg {...base} className={className}>
    <path d="M12 19V5M6 11l6-6 6 6" />
  </svg>
);
export const BackIcon = ({ className = "w-5 h-5" }: IconProps) => (
  <svg {...base} className={className}>
    <path d="M15 5l-7 7 7 7" />
  </svg>
);
export const MoreIcon = ({ className = "w-5 h-5" }: IconProps) => (
  <svg {...base} className={className}>
    <circle cx="5" cy="12" r="1.2" fill="currentColor" />
    <circle cx="12" cy="12" r="1.2" fill="currentColor" />
    <circle cx="19" cy="12" r="1.2" fill="currentColor" />
  </svg>
);
export const CloseIcon = ({ className = "w-5 h-5" }: IconProps) => (
  <svg {...base} className={className}>
    <path d="M6 6l12 12M18 6L6 18" />
  </svg>
);
export const ChevronIcon = ({ className = "w-4 h-4" }: IconProps) => (
  <svg {...base} className={className}>
    <path d="M9 6l6 6-6 6" />
  </svg>
);
export const CheckIcon = ({ className = "w-4 h-4" }: IconProps) => (
  <svg {...base} className={className}>
    <path d="M5 12.5l4.5 4.5L19 7.5" />
  </svg>
);
export const AlertIcon = ({ className = "w-4 h-4" }: IconProps) => (
  <svg {...base} className={className}>
    <path d="M12 8v5M12 16.5v.01" />
    <circle cx="12" cy="12" r="9" />
  </svg>
);
export const Spinner = ({ className = "w-4 h-4" }: IconProps) => (
  <svg {...base} className={`${className} animate-spin`}>
    <path d="M12 3a9 9 0 1 0 9 9" />
  </svg>
);
export const ImageIcon = ({ className = "w-5 h-5" }: IconProps) => (
  <svg {...base} className={className}>
    <rect x="4" y="5" width="16" height="14" rx="2" />
    <circle cx="9" cy="10" r="1.6" />
    <path d="M20 16l-4.5-4.5L8 19" />
  </svg>
);
