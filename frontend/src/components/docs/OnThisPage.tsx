'use client';

import React, { useEffect, useState } from 'react';

interface Heading {
  id: string;
  text: string;
}

// "On this page": lists the <h2 id> headings of the current docs article and
// highlights the one being read. It reads the DOM after each navigation
// (`pathname` is the dependency), so pages need no extra wiring: an H2 with an
// id is enough. Hidden when a page has fewer than two headings.
export const OnThisPage: React.FC<{ pathname: string }> = ({ pathname }) => {
  const [headings, setHeadings] = useState<Heading[]>([]);
  const [active, setActive] = useState<string | null>(null);

  useEffect(() => {
    const els = Array.from(document.querySelectorAll<HTMLElement>('#docs-article h2[id]'));
    setHeadings(els.map((el) => ({ id: el.id, text: el.textContent ?? '' })));
    setActive(els[0]?.id ?? null);
    if (els.length === 0) return;

    let frame = 0;
    const update = () => {
      frame = 0;
      let current = els[0].id;
      for (const el of els) {
        if (el.getBoundingClientRect().top <= 140) current = el.id;
        else break;
      }
      setActive(current);
    };
    const onScroll = () => {
      if (!frame) frame = window.requestAnimationFrame(update);
    };

    window.addEventListener('scroll', onScroll, { passive: true });
    update();
    return () => {
      window.removeEventListener('scroll', onScroll);
      if (frame) window.cancelAnimationFrame(frame);
    };
  }, [pathname]);

  if (headings.length < 2) return null;

  return (
    <nav aria-label="On this page">
      <p className="m-0 mb-3 text-xs font-medium text-ink-3">On this page</p>
      <ul className="m-0 list-none border-l border-line-soft p-0">
        {headings.map((h) => {
          const isActive = h.id === active;
          return (
            <li key={h.id}>
              <a
                href={`#${h.id}`}
                aria-current={isActive ? 'location' : undefined}
                className={`-ml-px block border-l py-1.5 pl-4 text-[0.8125rem] leading-snug transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent-blue ${
                  isActive
                    ? 'border-ink font-medium text-ink'
                    : 'border-transparent text-ink-3 hover:border-line hover:text-ink'
                }`}
              >
                {h.text}
              </a>
            </li>
          );
        })}
      </ul>
    </nav>
  );
};
