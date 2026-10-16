"use client";

import { memo, useMemo, useState } from "react";
import { Align, Block, Inline, parseMarkdown } from "@/lib/markdown";

/**
 * Renders an agent message as Markdown: headings, lists, code blocks and, above all, tables.
 *
 * Every element is built from the parser's typed tree (lib/markdown.ts), never from an HTML string,
 * so model output cannot inject markup. Links open in a new tab with rel="noopener noreferrer".
 * A table scrolls sideways inside its own box on a narrow screen, so it can never push the page
 * wider (the shell sets overflow-x: hidden, see app/globals.css).
 */
function Markdown({ text }: { text: string }) {
  const blocks = useMemo(() => parseMarkdown(text), [text]);
  return <div className="space-y-2 break-words min-w-0">{blocks.map((b, i) => <BlockView key={i} block={b} />)}</div>;
}

export default memo(Markdown);

const HEADING_CLASS = ["", "text-base font-semibold", "text-base font-semibold", "text-sm font-semibold", "text-sm font-semibold", "text-sm font-medium", "text-sm font-medium"];

function BlockView({ block, tight = false }: { block: Block; tight?: boolean }) {
  switch (block.t) {
    case "p":
      return tight ? <>{renderInline(block.c)}</> : <p>{renderInline(block.c)}</p>;
    case "h":
      return <p className={`${HEADING_CLASS[block.level]} pt-1`} role="heading" aria-level={block.level}>{renderInline(block.c)}</p>;
    case "hr":
      return <hr className="border-line" />;
    case "quote":
      return (
        <blockquote className="border-l-2 border-line pl-3 text-muted space-y-2">
          {block.c.map((b, i) => <BlockView key={i} block={b} />)}
        </blockquote>
      );
    case "code":
      return <CodeBlock lang={block.lang} code={block.v} />;
    case "list": {
      const Tag = block.ordered ? "ol" : "ul";
      return (
        <Tag className={`${block.ordered ? "list-decimal" : "list-disc"} pl-5 space-y-1`} start={block.ordered ? block.start : undefined}>
          {block.items.map((item, i) => (
            <li key={i} className={item.checked === null ? "" : "list-none -ml-5 flex gap-1.5"}>
              {item.checked !== null && (
                <span aria-hidden="true" className="mono text-xs pt-0.5 flex-none">{item.checked ? "[x]" : "[ ]"}</span>
              )}
              <div className={item.checked === null ? "space-y-1" : "space-y-1 min-w-0"}>
                {item.c.map((b, j) => <BlockView key={j} block={b} tight={item.c.length === 1} />)}
              </div>
            </li>
          ))}
        </Tag>
      );
    }
    case "table":
      return <TableView head={block.head} rows={block.rows} align={block.align} />;
  }
}

function TableView({ head, rows, align }: { head: Inline[][]; rows: Inline[][][]; align: Align[] }) {
  const style = (i: number) => (align[i] ? { textAlign: align[i] as "left" | "right" | "center" } : undefined);
  return (
    <div className="overflow-x-auto rounded-lg border border-line bg-white max-w-full" role="region" tabIndex={0} aria-label="Table">
      <table className="w-full border-collapse text-[13px] leading-snug">
        <thead>
          <tr className="bg-paper">
            {head.map((cell, i) => (
              <th key={i} scope="col" style={style(i)} className="text-left font-semibold px-2.5 py-1.5 border-b border-line align-bottom">
                {renderInline(cell)}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, r) => (
            <tr key={r} className={r > 0 ? "border-t border-line" : ""}>
              {row.map((cell, i) => (
                <td key={i} style={style(i)} className="px-2.5 py-1.5 align-top min-w-[5rem]">
                  {renderInline(cell)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function CodeBlock({ lang, code }: { lang: string; code: string }) {
  const [copied, setCopied] = useState(false);
  function copy() {
    try {
      void navigator.clipboard.writeText(code).then(() => {
        setCopied(true);
        setTimeout(() => setCopied(false), 1500);
      });
    } catch {
      // clipboard blocked (insecure context, permissions): the text is still selectable
    }
  }
  return (
    <div className="rounded-lg bg-neutral-900 text-neutral-100 overflow-hidden">
      <div className="flex items-center justify-between px-3 pt-1.5 text-[11px] text-neutral-400">
        <span className="mono">{lang || "text"}</span>
        <button type="button" onClick={copy} className="underline decoration-neutral-600 hover:text-neutral-100">
          {copied ? "Copied" : "Copy"}
        </button>
      </div>
      <pre className="mono text-xs px-3 pb-3 pt-1.5 overflow-x-auto max-h-96 overflow-y-auto"><code>{code}</code></pre>
    </div>
  );
}

function renderInline(nodes: Inline[]): React.ReactNode {
  return nodes.map((n, i) => {
    switch (n.t) {
      case "text":
        return n.v;
      case "br":
        return <br key={i} />;
      case "code":
        return <code key={i} className="mono text-[0.85em] bg-soft rounded px-1 py-px break-words">{n.v}</code>;
      case "strong":
        return <strong key={i} className="font-semibold">{renderInline(n.c)}</strong>;
      case "em":
        return <em key={i}>{renderInline(n.c)}</em>;
      case "del":
        return <del key={i}>{renderInline(n.c)}</del>;
      case "link":
        return (
          <a key={i} href={n.href} target="_blank" rel="noopener noreferrer" className="underline break-all">
            {renderInline(n.c)}
          </a>
        );
    }
  });
}
