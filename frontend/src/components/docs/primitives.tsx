'use client';

import React, { useCallback, useEffect, useRef, useState } from 'react';
import Link from 'next/link';
import { AlertTriangle, Check, Copy, Info } from 'lucide-react';
import { useApp } from '../../context/AppContext';
import { ROUTES } from '../../lib/routes';
import { highlight, type Lang } from './highlight';
import { OVERVIEW_SLUG, docsHref, getDocsGroupTitle, getDocsNeighbors, getDocsPage } from './nav';

/* ------------------------------------------------------------------ */
/* Text                                                                */
/* ------------------------------------------------------------------ */

export const C: React.FC<{ children: React.ReactNode }> = ({ children }) => (
  <code className="docs-code">{children}</code>
);

export const P: React.FC<{ children: React.ReactNode }> = ({ children }) => (
  <p className="docs-p">{children}</p>
);

export const Lead: React.FC<{ children: React.ReactNode }> = ({ children }) => (
  <p className="docs-lead">{children}</p>
);

export const Ul: React.FC<{ children: React.ReactNode }> = ({ children }) => (
  <ul className="docs-list">{children}</ul>
);

export const H3: React.FC<{ id?: string; children: React.ReactNode }> = ({ id, children }) => (
  <h3 id={id} className="docs-h3">
    {children}
  </h3>
);

/** In-page (#anchor), app (/route) or external link, styled the same way. */
export const A: React.FC<{ href: string; children: React.ReactNode }> = ({ href, children }) => {
  if (href.startsWith('/')) {
    return (
      <Link href={href} className="docs-link">
        {children}
      </Link>
    );
  }
  if (href.startsWith('#') || href.startsWith('mailto:')) {
    return (
      <a href={href} className="docs-link">
        {children}
      </a>
    );
  }
  return (
    <a href={href} className="docs-link" target="_blank" rel="noopener noreferrer">
      {children}
    </a>
  );
};

/* ------------------------------------------------------------------ */
/* Page frame                                                          */
/* ------------------------------------------------------------------ */

/** A heading inside a docs page. The id makes it linkable and puts it in "On this page". */
export const H2: React.FC<{ id: string; children: React.ReactNode }> = ({ id, children }) => (
  <h2 id={id} className="docs-h2">
    {children}
  </h2>
);

/** Link to the API Keys page, or to sign-in when the reader is signed out. */
export const KeysLink: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const { isLoggedIn } = useApp();
  return (
    <Link href={isLoggedIn ? ROUTES.keys : ROUTES.login} className="docs-link">
      {children}
    </Link>
  );
};

/** Title, lead, body and previous/next links for one docs page. */
export const DocArticle: React.FC<{ slug: string; children: React.ReactNode }> = ({ slug, children }) => {
  const page = getDocsPage(slug);
  if (!page) return null;
  const group = getDocsGroupTitle(slug);
  const { prev, next } = getDocsNeighbors(slug);

  return (
    <article id="docs-article" className="min-w-0 max-w-[760px]">
      {group && slug !== OVERVIEW_SLUG && <p className="m-0 mb-3 text-sm text-ink-3">{group}</p>}
      <h1 className="docs-h1">{page.heading ?? page.title}</h1>
      <p className="docs-lead">{page.description}</p>
      {children}

      <nav aria-label="Previous and next page" className="mt-20 grid gap-3 border-t border-line-soft pt-8 sm:grid-cols-2">
        {prev ? (
          <Link
            href={docsHref(prev.slug)}
            className="group rounded-2xl border border-line p-4 transition-colors hover:bg-surface focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent-blue"
          >
            <span className="block text-xs text-ink-3">Previous</span>
            <span className="mt-1 block text-[0.9375rem] font-medium text-ink">{prev.title}</span>
          </Link>
        ) : (
          <span />
        )}
        {next ? (
          <Link
            href={docsHref(next.slug)}
            className="group rounded-2xl border border-line p-4 transition-colors hover:bg-surface focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent-blue sm:text-right"
          >
            <span className="block text-xs text-ink-3">Next</span>
            <span className="mt-1 block text-[0.9375rem] font-medium text-ink">{next.title}</span>
          </Link>
        ) : (
          <span />
        )}
      </nav>
    </article>
  );
};

/* ------------------------------------------------------------------ */
/* Copy                                                                */
/* ------------------------------------------------------------------ */

export const CopyButton: React.FC<{
  text: string;
  /** `dark` sits on the code-block header, `light` on white. */
  tone?: 'dark' | 'light';
  /** Icon only (used beside URLs). */
  iconOnly?: boolean;
  label?: string;
}> = ({ text, tone = 'dark', iconOnly = false, label = 'Copy' }) => {
  const [copied, setCopied] = useState(false);
  const timer = useRef<number | null>(null);

  useEffect(
    () => () => {
      if (timer.current !== null) window.clearTimeout(timer.current);
    },
    [],
  );

  const onCopy = useCallback(async () => {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      if (timer.current !== null) window.clearTimeout(timer.current);
      timer.current = window.setTimeout(() => setCopied(false), 1800);
    } catch {
      // Clipboard blocked (insecure context or permissions): leave the button as is.
    }
  }, [text]);

  const colors =
    tone === 'dark'
      ? 'text-code-comment hover:text-white hover:bg-white/10'
      : 'text-ink-3 hover:text-ink hover:bg-line-soft';

  return (
    <button
      type="button"
      onClick={onCopy}
      aria-label={copied ? 'Copied' : `${label} to clipboard`}
      className={`inline-flex shrink-0 cursor-pointer items-center gap-1.5 rounded-full text-xs font-medium transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent-blue ${colors} ${
        iconOnly ? 'h-8 w-8 justify-center' : 'h-8 px-3'
      }`}
    >
      {copied ? <Check className="h-3.5 w-3.5" /> : <Copy className="h-3.5 w-3.5" />}
      {!iconOnly && <span>{copied ? 'Copied' : label}</span>}
    </button>
  );
};

/** A value that people will paste somewhere (a base URL, a model id). */
export const CopyField: React.FC<{ value: string }> = ({ value }) => (
  <span className="inline-flex max-w-full items-center gap-1 rounded-xl bg-surface py-1 pl-3 pr-1">
    <code className="min-w-0 break-all font-mono text-[0.8125rem] text-ink">{value}</code>
    <CopyButton text={value} tone="light" iconOnly label="Copy" />
  </span>
);

/* ------------------------------------------------------------------ */
/* Code                                                                */
/* ------------------------------------------------------------------ */

export interface CodeTab {
  label: string;
  lang: Lang;
  code: string;
}

export const CodeBlock: React.FC<{ tabs: CodeTab[] }> = ({ tabs }) => {
  const [active, setActive] = useState(0);
  const tab = tabs[Math.min(active, tabs.length - 1)];
  const multi = tabs.length > 1;

  return (
    <figure className="m-0 mb-6 overflow-hidden rounded-2xl bg-code-bg">
      <div className="flex items-center justify-between gap-3 border-b border-white/10 py-1.5 pl-2.5 pr-2">
        {multi ? (
          <div role="tablist" aria-label="Language" className="flex min-w-0 gap-1 overflow-x-auto">
            {tabs.map((t, i) => (
              <button
                key={t.label}
                type="button"
                role="tab"
                aria-selected={i === active}
                onClick={() => setActive(i)}
                className={`h-8 shrink-0 cursor-pointer rounded-full px-3 text-xs font-medium transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent-blue ${
                  i === active ? 'bg-white/12 text-white' : 'text-code-comment hover:text-white'
                }`}
              >
                {t.label}
              </button>
            ))}
          </div>
        ) : (
          <span className="pl-1.5 text-xs font-medium text-code-comment">{tab.label}</span>
        )}
        <CopyButton text={tab.code} />
      </div>
      <pre
        tabIndex={0}
        role={multi ? 'tabpanel' : undefined}
        className="m-0 overflow-x-auto px-5 py-4 font-mono text-[0.8125rem] leading-[1.7] text-code-ink focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-accent-blue"
      >
        <code>{highlight(tab.code, tab.lang)}</code>
      </pre>
    </figure>
  );
};

/* ------------------------------------------------------------------ */
/* Callouts, tables, lists                                             */
/* ------------------------------------------------------------------ */

type Tone = 'note' | 'warn';

export const Callout: React.FC<{ tone?: Tone; title: string; children: React.ReactNode }> = ({
  tone = 'note',
  title,
  children,
}) => {
  const warn = tone === 'warn';
  const Icon = warn ? AlertTriangle : Info;
  return (
    <aside
      className={`mb-6 flex max-w-[68ch] gap-3 rounded-2xl border p-4 ${
        warn ? 'border-warning-border bg-warning-soft' : 'border-line bg-surface'
      }`}
    >
      <Icon className={`mt-0.5 h-4 w-4 shrink-0 ${warn ? 'text-warning' : 'text-ink-2'}`} strokeWidth={1.9} />
      <div className="min-w-0 text-sm leading-relaxed text-ink-2">
        <p className={`m-0 mb-1 font-medium ${warn ? 'text-warning' : 'text-ink'}`}>{title}</p>
        <div className="[&_p]:m-0 [&_p+p]:mt-2">{children}</div>
      </div>
    </aside>
  );
};

export const Table: React.FC<{ head: string[]; rows: React.ReactNode[][]; minWidth?: number }> = ({
  head,
  rows,
  minWidth = 520,
}) => (
  <div className="docs-table-wrap">
    <table className="docs-table" style={{ minWidth }}>
      <thead>
        <tr>
          {head.map((h) => (
            <th key={h || 'item'} scope="col">
              {h === '' ? <span className="sr-only">Item</span> : h}
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        {rows.map((row, i) => (
          <tr key={i}>
            {row.map((cell, j) => (
              <td key={j}>{cell}</td>
            ))}
          </tr>
        ))}
      </tbody>
    </table>
  </div>
);

/** A method + path, for the endpoint tables. */
export const Route: React.FC<{ method: 'GET' | 'POST'; path: string }> = ({ method, path }) => (
  <span className="inline-flex items-center gap-2 whitespace-nowrap">
    <span className="rounded-md bg-surface-2 px-1.5 py-0.5 font-mono text-[0.6875rem] font-medium text-ink-2">
      {method}
    </span>
    <code className="font-mono text-[0.8125rem] text-ink">{path}</code>
  </span>
);

/** Label / value rows, ruled like the pricing card. */
export const FactList: React.FC<{ rows: { label: string; value: React.ReactNode }[] }> = ({ rows }) => (
  <dl className="m-0 mb-8 max-w-[680px] border-b border-line-soft">
    {rows.map((r) => (
      <div
        key={r.label}
        className="grid gap-1 border-t border-line-soft py-3.5 sm:grid-cols-[210px_minmax(0,1fr)] sm:gap-6"
      >
        <dt className="text-sm text-ink-3">{r.label}</dt>
        <dd className="m-0 min-w-0 text-sm text-ink">{r.value}</dd>
      </div>
    ))}
  </dl>
);

/* ------------------------------------------------------------------ */
/* Steps (used only where the content really is a sequence)           */
/* ------------------------------------------------------------------ */

export const Steps: React.FC<{ children: React.ReactNode }> = ({ children }) => (
  <ol className="m-0 mb-8 list-none space-y-7 p-0">{children}</ol>
);

export const Step: React.FC<{ n: number; title: string; children: React.ReactNode }> = ({ n, title, children }) => (
  <li className="grid grid-cols-[28px_minmax(0,1fr)] gap-4">
    <span className="mt-0.5 grid h-7 w-7 place-items-center rounded-full bg-ink text-xs font-medium text-white">
      {n}
    </span>
    <div className="min-w-0">
      <h3 className="m-0 mb-1.5 text-[1.0625rem] font-medium leading-snug tracking-[-0.015em] text-ink">{title}</h3>
      {children}
    </div>
  </li>
);
