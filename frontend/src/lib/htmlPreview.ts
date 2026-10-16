// Preview of HTML code that Kael sends in a Playground reply.
//
// A code block in a reply that is HTML gets a "Preview" button. It opens the
// code in a sandboxed iframe (components/pages/PlaygroundPage.tsx,
// HtmlPreviewModal). HTML only: no other language is run.
//
// Safety, because the code comes from a model and a model can be steered by a
// file or a pasted page:
//  - The iframe uses sandbox="allow-scripts" and NOT allow-same-origin, so the
//    page runs as an opaque origin: it cannot read this site's storage, cookies
//    or login, and cannot reach into the Playground page. It also cannot
//    navigate the top page, open popups or submit forms (none of those
//    sandbox flags are given).
//  - A Content-Security-Policy is put at the top of the previewed document
//    (below): inline scripts and styles work, a few well-known CDNs may load
//    libraries and fonts, pictures may load, and every network request from a
//    script (fetch, XHR, WebSocket), form submission and nested frame is
//    blocked. Nothing here is a promise that previewed code is harmless; the
//    preview window tells the reader not to type passwords or personal details
//    into it.
//  - It is never opened as a blob: or data: URL in a new tab, because a blob
//    URL made here would share this site's origin and lose the sandbox.

const HTML_LANGUAGES = new Set(['html', 'htm']);
const WHOLE_PAGE_RE = /^\s*(<!doctype\s+html|<html[\s>])/i;

// True for a code block that is HTML: tagged html/htm, or untagged but plainly a
// whole page (starts with a doctype or <html>).
export const isHtmlCode = (language: string, code: string): boolean => {
  const lang = (language || '').toLowerCase();
  if (HTML_LANGUAGES.has(lang)) return code.trim().length > 0;
  if ((lang === '' || lang === 'text') && WHOLE_PAGE_RE.test(code)) return true;
  return false;
};

const CSP = [
  "default-src 'none'",
  "script-src 'unsafe-inline' https://cdnjs.cloudflare.com https://cdn.jsdelivr.net",
  "style-src 'unsafe-inline' https://cdnjs.cloudflare.com https://cdn.jsdelivr.net https://fonts.googleapis.com",
  'img-src data: blob: https:',
  'font-src data: https://fonts.gstatic.com https://cdnjs.cloudflare.com https://cdn.jsdelivr.net',
  'media-src data: blob: https:',
  "connect-src 'none'",
  "form-action 'none'",
  "base-uri 'none'",
  "frame-src 'none'",
].join('; ');

const CSP_META = `<meta http-equiv="Content-Security-Policy" content="${CSP}">`;
const VIEWPORT_META = '<meta name="viewport" content="width=device-width, initial-scale=1">';

// The document to put in the iframe's srcdoc: the code with the policy (and,
// when the code has none, a phone-friendly viewport) added at the very top of
// its head, before any of its own scripts can run.
export const buildPreviewDocument = (html: string): string => {
  const extra = CSP_META + (/name\s*=\s*["']?viewport/i.test(html) ? '' : VIEWPORT_META);
  const head = /<head(\s[^>]*)?>/i.exec(html);
  if (head) {
    const at = head.index + head[0].length;
    return html.slice(0, at) + extra + html.slice(at);
  }
  const root = /<html(\s[^>]*)?>/i.exec(html);
  if (root) {
    const at = root.index + root[0].length;
    return `${html.slice(0, at)}<head>${extra}</head>${html.slice(at)}`;
  }
  const doctype = /^\s*<!doctype[^>]*>/i.exec(html);
  if (doctype) {
    const at = doctype.index + doctype[0].length;
    return `${html.slice(0, at)}<head>${extra}</head>${html.slice(at)}`;
  }
  return `<!DOCTYPE html><html><head><meta charset="utf-8">${extra}</head><body>${html}</body></html>`;
};
