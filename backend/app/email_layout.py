"""The one visual shell every Quancis email is built from.

Pure module: no I/O, no config, no third-party imports, so it is trivial to
test and to preview without sending anything (see render_email_previews.py).

DESIGN LANGUAGE. The tokens below are copied from the platform, not
invented for email. Source of truth is frontend/src/app/globals.css
(`@theme`) and frontend/src/components/BrandMark.tsx. If the platform's
palette changes, change the constants here in the same commit.

  platform token            email use
  ------------------------  -----------------------------------------
  --color-ink  #16181A      titles, primary button, mark's dark cells
  --color-ink-2 #5C6167     body copy
  --color-ink-3 #949AA1     eyebrows, labels, footer
  --color-line #E8E8E5      card border, dividers
  --color-surface #F7F7F5   page background, inset panels
  .page-eyebrow             11px / 0.14em / uppercase above the title
  .page-title               weight 500, tracking -0.036em
  .btn-pill-dark            pill button (radius 999px, ink fill)
  .card-panel / .stat-card  20px-radius bordered card, label + big value
  .badge-pill-*             success / warning / danger / info colours
  BrandMark + "uancis"      mark is the Q, so the wordmark is "uancis"
                            (same as Navbar.tsx), not "QUANCIS"

EMAIL-CLIENT RULES this module follows:
  * Layout is nested <table>s with inline styles, so it survives Outlook
    and Gmail. A <style> block is added on top as progressive
    enhancement only (mobile padding and dark mode); nothing breaks if a
    client drops it.
  * Everything user-supplied is HTML-escaped. Templates never concatenate
    raw values into markup; they hand plain strings to the block classes
    below. `**bold**` and `code` are the only inline markup, applied AFTER
    escaping.
  * Dark mode: `color-scheme` meta + prefers-color-scheme overrides
    (Apple Mail, iOS Mail, Outlook apps). Gmail ignores these and applies
    its own inversion, which the neutral palette tolerates.
  * No remote images (Gmail/Outlook block them by default). The brand mark
    is built from table cells.
  * A hidden preheader controls the inbox preview line.
"""

from __future__ import annotations

import html as _html
import re
from dataclasses import dataclass
from html.parser import HTMLParser

# ---------------------------------------------------------------- tokens
INK = "#16181A"
INK_2 = "#5C6167"
INK_3 = "#949AA1"
LINE = "#E8E8E5"
LINE_SOFT = "#F2F2F0"
SURFACE = "#F7F7F5"
BG = "#FFFFFF"
BRAND_RED = "#E4002B"  # the mark's one red cell (BrandMark.tsx RED)

ACCENT_BLUE = "#2563EB"
KINDS = {
    # kind: (soft background, border, strong text)
    "info": ("#EFF6FF", "#BFDBFE", "#2563EB"),
    "success": ("#F0FDF4", "#BBF7D0", "#16A34A"),
    "warning": ("#FFFBEB", "#FDE68A", "#B45309"),
    "danger": ("#FEF3F2", "#FECDCA", "#D92D20"),
}

# Dark counterparts, from the platform's hero / code surfaces.
DK_BG = "#141618"
DK_CARD = "#1A1C1E"
DK_LINE = "#2B2E32"
DK_INK = "#F2F2F0"
DK_BODY = "#BFC5CC"
DK_MUTED = "#949AA1"

FONT = "Inter,-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif"
MONO = "'JetBrains Mono',ui-monospace,SFMono-Regular,'SF Mono',Menlo,Consolas,monospace"

# The site loads Inter (400/500/600) and JetBrains Mono through next/font
# (frontend/src/app/layout.tsx). Mail clients cannot use next/font, so the
# same two families are requested from Google Fonts as progressive
# enhancement: Apple Mail, iOS Mail and some Outlook builds load them;
# Gmail and others ignore the link and fall back to the stacks above, which
# the layout is built to survive. Loading the CSS makes a request to Google
# when the email is opened in a client that supports it; no data about the
# user is sent. Remove FONT_CSS_URL's <link> if that is ever unwanted.
FONT_CSS_URL = (
    "https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600"
    "&family=JetBrains+Mono:wght@400;500&display=swap"
)

DEFAULT_SITE_URL = "https://platform.quancis.space"
SUPPORT_EMAIL = "support@quancis.space"
# ---------------------------------------------------------------- output
@dataclass(frozen=True)
class Email:
    """What a template returns. `subject` and `html` go to
    email_service.send_email(to, subject, html); the plain-text part is
    derived from `html` there."""

    subject: str
    html: str


# ---------------------------------------------------------------- escaping
def esc(value: object) -> str:
    return _html.escape("" if value is None else str(value), quote=True)


_BOLD = re.compile(r"\*\*(.+?)\*\*")
_CODE = re.compile(r"`(.+?)`")


def inline(text: str) -> str:
    """Escape, then apply the two inline styles. Order matters: escaping
    first means markup can only come from this function, never from the
    input."""
    out = esc(text)
    out = _BOLD.sub(rf'<strong style="color:{INK};font-weight:600;" class="q-ink">\1</strong>', out)
    out = _CODE.sub(
        rf'<span class="q-panel q-ink" style="font-family:{MONO};font-size:13px;color:{INK};'
        rf'background:{SURFACE};padding:2px 6px;border-radius:6px;">\1</span>',
        out,
    )
    return out


# ---------------------------------------------------------------- blocks
@dataclass(frozen=True)
class Para:
    text: str
    muted: bool = False  # small print under a CTA ("Didn't request this?")


@dataclass(frozen=True)
class Button:
    label: str
    url: str
    secondary: bool = False  # outline pill instead of the dark pill


@dataclass(frozen=True)
class LinkFallback:
    """'Button not working?' line. Security emails (confirm, reset)
    carry one so a stripped or broken button never strands the user."""

    url: str


@dataclass(frozen=True)
class Callout:
    kind: str  # info | success | warning | danger
    text: str
    title: str | None = None


@dataclass(frozen=True)
class Stat:
    """One big value in a panel, like the platform's .stat-card."""

    label: str
    value: str
    note: str | None = None


@dataclass(frozen=True)
class Facts:
    """Label / value rows in an inset panel. Row = (label, value) or
    (label, value, mono)."""

    rows: tuple


@dataclass(frozen=True)
class Table:
    """Like the platform's .data-table. Cells are plain strings."""

    headers: tuple
    rows: tuple


@dataclass(frozen=True)
class Steps:
    items: tuple


Block = Para | Button | LinkFallback | Callout | Stat | Facts | Table | Steps


def _para(b: Para) -> str:
    cls, color, size, mb = ("q-muted", INK_3, 12, 0) if b.muted else ("q-body", INK_2, 15, 18)
    return (
        f'<p class="{cls}" style="margin:0 0 {mb or 0}px;font-size:{size}px;line-height:1.65;'
        f'color:{color};">{inline(b.text)}</p>'
    )


def _safe_url(url: str) -> str:
    """Only http(s) and mailto links are ever emitted as hrefs. Anything
    else (javascript:, data:, a scheme-less string from a misconfigured
    FRONTEND_URL) becomes "#", so a template can never produce a script
    link no matter what a caller passes in."""
    value = (url or "").strip()
    return value if value.lower().startswith(("https://", "http://", "mailto:")) else "#"


def _button(b: Button) -> str:
    if b.secondary:
        bg, fg, border, cls = BG, INK, f"1px solid #E3E3DF", "q-btn2"
    else:
        bg, fg, border, cls = INK, "#FFFFFF", f"1px solid {INK}", "q-btn"
    return (
        '<table role="presentation" cellpadding="0" cellspacing="0" border="0" style="margin:8px 0 26px;"><tr>'
        f'<td class="{cls}" bgcolor="{bg}" style="border-radius:999px;background:{bg};border:{border};">'
        f'<a href="{esc(_safe_url(b.url))}" class="{cls}" style="display:inline-block;padding:15px 30px;'
        f"font-family:{FONT};font-size:15px;font-weight:500;letter-spacing:-0.005em;line-height:1;"
        f'color:{fg};background:{bg};border-radius:999px;text-decoration:none;">{esc(b.label)}</a>'
        "</td></tr></table>"
    )


def _link_fallback(b: LinkFallback) -> str:
    return (
        f'<p class="q-muted" style="margin:0 0 6px;font-size:12px;line-height:1.6;color:{INK_3};">'
        "Button not working? Paste this link into your browser:</p>"
        f'<p class="q-muted" style="margin:0 0 22px;font-family:{MONO};font-size:11px;line-height:1.6;'
        f'color:{INK_3};word-break:break-all;">{esc(_safe_url(b.url))}</p>'
    )


def _callout(b: Callout) -> str:
    soft, border, strong = KINDS.get(b.kind, KINDS["info"])
    title = (
        f'<p style="margin:0 0 4px;font-size:13px;font-weight:600;line-height:1.4;color:{strong};">{esc(b.title)}</p>'
        if b.title
        else ""
    )
    return (
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" '
        f'style="margin:0 0 22px;border-collapse:separate;"><tr>'
        f'<td class="q-co-{b.kind if b.kind in KINDS else "info"}" style="background:{soft};border:1px solid {border};border-radius:14px;padding:16px 18px;">'
        f'{title}<p class="q-body" style="margin:0;font-size:14px;line-height:1.6;color:{INK_2};">{inline(b.text)}</p>'
        "</td></tr></table>"
    )


def _panel_open() -> str:
    return (
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" class="q-panel" '
        f'style="margin:0 0 22px;border-collapse:separate;background:{SURFACE};border:1px solid {LINE};'
        'border-radius:16px;"><tr><td style="padding:18px 20px;">'
    )


def _stat(b: Stat) -> str:
    note = (
        f'<p class="q-muted" style="margin:8px 0 0;font-size:13px;line-height:1.5;color:{INK_3};">{inline(b.note)}</p>'
        if b.note
        else ""
    )
    return (
        _panel_open()
        + f'<p class="q-muted" style="margin:0 0 8px;font-size:11px;font-weight:500;letter-spacing:0.13em;'
        f'text-transform:uppercase;color:{INK_3};">{esc(b.label)}</p>'
        f'<p class="q-ink" style="margin:0;font-family:{MONO};font-size:30px;font-weight:500;'
        f'letter-spacing:-0.03em;line-height:1.1;color:{INK};">{esc(b.value)}</p>'
        + note
        + "</td></tr></table>"
    )


def _facts(b: Facts) -> str:
    rows = []
    last = len(b.rows) - 1
    for i, row in enumerate(b.rows):
        label, value = row[0], row[1]
        mono = len(row) > 2 and row[2]
        divider = "" if i == last else f"border-bottom:1px solid {LINE};"
        vfont = f"font-family:{MONO};font-size:13px;" if mono else "font-size:14px;"
        rows.append(
            f'<tr><td class="q-line q-muted" style="padding:11px 0;{divider}font-size:11px;font-weight:500;'
            f'letter-spacing:0.13em;text-transform:uppercase;color:{INK_3};white-space:nowrap;">{esc(label)}</td>'
            f'<td class="q-line q-ink" align="right" style="padding:11px 0 11px 16px;{divider}{vfont}color:{INK};'
            f'word-break:break-word;">{esc(value)}</td></tr>'
        )
    return (
        _panel_open()
        + '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">'
        + "".join(rows)
        + "</table></td></tr></table>"
    )


def _table(b: Table) -> str:
    th = "".join(
        f'<th align="left" class="q-line q-muted" style="padding:0 10px 10px 0;font-size:11px;font-weight:500;'
        f'letter-spacing:0.13em;text-transform:uppercase;color:{INK_3};border-bottom:1px solid {LINE};">{esc(h)}</th>'
        for h in b.headers
    )
    body = []
    for r in b.rows:
        tds = "".join(
            f'<td class="q-line q-body" style="padding:12px 10px 12px 0;font-size:14px;color:{INK_2};'
            f'border-bottom:1px solid {LINE_SOFT};">{esc(c)}</td>'
            for c in r
        )
        body.append(f"<tr>{tds}</tr>")
    return (
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" '
        'style="margin:0 0 22px;border-collapse:collapse;">'
        f"<tr>{th}</tr>{''.join(body)}</table>"
    )


def _steps(b: Steps) -> str:
    rows = []
    for n, text in enumerate(b.items, 1):
        rows.append(
            "<tr>"
            f'<td valign="top" style="padding:0 14px 14px 0;"><table role="presentation" cellpadding="0" cellspacing="0" border="0"><tr>'
            f'<td class="q-panel q-ink" align="center" style="width:26px;height:26px;background:{SURFACE};border:1px solid {LINE};'
            f'border-radius:999px;font-size:12px;font-weight:500;color:{INK};line-height:26px;">{n}</td></tr></table></td>'
            f'<td class="q-body" valign="top" style="padding:3px 0 14px;font-size:15px;line-height:1.55;color:{INK_2};">{inline(text)}</td>'
            "</tr>"
        )
    return (
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="margin:0 0 14px;">'
        + "".join(rows)
        + "</table>"
    )


_RENDERERS = {
    Para: _para,
    Button: _button,
    LinkFallback: _link_fallback,
    Callout: _callout,
    Stat: _stat,
    Facts: _facts,
    Table: _table,
    Steps: _steps,
}


# ---------------------------------------------------------------- chrome
def _mark() -> str:
    """BrandMark.tsx's 4x4 grid:  .xx. / x..x / x.x. / .x.R  — built from
    7px table cells (28px square) so it needs no remote image."""

    def cell(on: bool, red: bool = False) -> str:
        if not on:
            return '<td style="width:7px;height:7px;line-height:7px;font-size:0;">&nbsp;</td>'
        if red:
            return f'<td style="width:7px;height:7px;line-height:7px;font-size:0;background:{BRAND_RED};">&nbsp;</td>'
        return f'<td class="q-mark" style="width:7px;height:7px;line-height:7px;font-size:0;background:{INK};">&nbsp;</td>'

    grid = [
        (0, 1, 1, 0),
        (1, 0, 0, 1),
        (1, 0, 1, 0),
        (0, 1, 0, 2),  # 2 = the red cell
    ]
    trs = "".join(
        "<tr>" + "".join(cell(v != 0, red=(v == 2)) for v in row) + "</tr>" for row in grid
    )
    return (
        '<table role="img" aria-label="Quancis" cellpadding="0" cellspacing="0" border="0" data-text="" '
        f'style="border-collapse:collapse;line-height:0;font-size:0;">{trs}</table>'
    )


def _header() -> str:
    return (
        '<table role="presentation" cellpadding="0" cellspacing="0" border="0"><tr>'
        f'<td style="vertical-align:middle;">{_mark()}</td>'
        '<td style="padding-left:8px;vertical-align:middle;">'
        f'<span class="q-ink" data-text="Quancis" aria-hidden="true" style="font-family:{FONT};font-size:18px;'
        f'font-weight:600;letter-spacing:-0.015em;color:{INK};">uancis</span>'
        "</td></tr></table>"
    )


def _footer(reason: str, site_url: str) -> str:
    base = site_url.rstrip("/")
    link = f'style="color:{INK_3};text-decoration:underline;" class="q-muted"'
    return (
        f'<p class="q-muted" style="margin:0 0 12px;font-size:12px;line-height:1.6;color:{INK_3};">{esc(reason)}</p>'
        f'<p class="q-muted" style="margin:0;font-size:12px;line-height:1.6;color:{INK_3};">'
        f'<a href="{esc(base)}/terms-of-service" {link}>Terms of Service</a>&nbsp;&middot;&nbsp;'
        f'<a href="{esc(base)}/privacy-policy" {link}>Privacy Policy</a>&nbsp;&middot;&nbsp;'
        f'<a href="mailto:{SUPPORT_EMAIL}" {link}>{SUPPORT_EMAIL}</a></p>'
    )


_STYLE = f"""
  :root {{ color-scheme: light dark; supported-color-schemes: light dark; }}
  body {{ margin:0; padding:0; -webkit-text-size-adjust:100%; }}
  @media (max-width:620px) {{
    .q-wrap {{ padding:16px 10px !important; }}
    .q-card {{ padding:28px 22px !important; }}
    .q-title {{ font-size:26px !important; }}
  }}
  @media (prefers-color-scheme: dark) {{
    .q-bg {{ background:{DK_BG} !important; }}
    .q-card {{ background:{DK_CARD} !important; border-color:{DK_LINE} !important; }}
    .q-ink {{ color:{DK_INK} !important; }}
    .q-body {{ color:{DK_BODY} !important; }}
    .q-muted {{ color:{DK_MUTED} !important; }}
    .q-line {{ border-color:{DK_LINE} !important; }}
    .q-panel {{ background:{DK_BG} !important; border-color:{DK_LINE} !important; }}
    .q-mark {{ background:{DK_INK} !important; }}
    .q-co-info {{ background:#13203A !important; border-color:#1E3A6E !important; }}
    .q-co-success {{ background:#102A19 !important; border-color:#1E5A32 !important; }}
    .q-co-warning {{ background:#2B2110 !important; border-color:#5C4310 !important; }}
    .q-co-danger {{ background:#2A1715 !important; border-color:#5A2420 !important; }}
    .q-btn {{ background:#FFFFFF !important; border-color:#FFFFFF !important; color:{INK} !important; }}
    .q-btn2 {{ background:transparent !important; border-color:{DK_LINE} !important; color:{DK_INK} !important; }}
  }}
"""


def render(
    *,
    subject: str,
    preheader: str,
    title: str,
    blocks: list,
    eyebrow: str | None = None,
    reason: str = "You're receiving this because you have a Quancis account.",
    site_url: str = DEFAULT_SITE_URL,
) -> Email:
    """Assemble one email. `blocks` is a list of the block dataclasses above.
    Unknown block types raise, so a typo fails in tests rather than
    silently dropping content from a real email."""
    body_parts = []
    for b in blocks:
        renderer = _RENDERERS.get(type(b))
        if renderer is None:
            raise TypeError(f"Unknown email block: {type(b).__name__}")
        body_parts.append(renderer(b))

    eyebrow_html = (
        f'<p class="q-muted" style="margin:0 0 12px;font-size:11px;font-weight:500;letter-spacing:0.14em;'
        f'text-transform:uppercase;color:{INK_3};">{esc(eyebrow)}</p>'
        if eyebrow
        else ""
    )
    pad = "&zwnj;&nbsp;" * 40  # pushes body text out of the inbox preview line
    html = f"""<!DOCTYPE html>
<html lang="en" xmlns="http://www.w3.org/1999/xhtml">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="X-UA-Compatible" content="IE=edge">
<meta name="color-scheme" content="light dark">
<meta name="supported-color-schemes" content="light dark">
<title>{esc(subject)}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="{esc(FONT_CSS_URL)}" rel="stylesheet">
<style>{_STYLE}</style>
</head>
<body class="q-bg" style="margin:0;padding:0;background:{SURFACE};">
<div style="display:none;max-height:0;overflow:hidden;opacity:0;mso-hide:all;font-size:1px;line-height:1px;color:{SURFACE};">{esc(preheader)}{pad}</div>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" class="q-bg" bgcolor="{SURFACE}" style="background:{SURFACE};">
<tr><td align="center" class="q-wrap" style="padding:36px 16px;font-family:{FONT};">
<table role="presentation" width="560" cellpadding="0" cellspacing="0" border="0" style="width:100%;max-width:560px;">
<tr><td style="padding:0 6px 20px;">{_header()}</td></tr>
<tr><td class="q-card" style="background:{BG};border:1px solid {LINE};border-radius:20px;padding:40px 36px;">
{eyebrow_html}<h1 class="q-title q-ink" style="margin:0 0 18px;font-family:{FONT};font-size:30px;font-weight:500;line-height:1.12;letter-spacing:-0.036em;color:{INK};">{esc(title)}</h1>
{"".join(body_parts)}
</td></tr>
<tr><td style="padding:24px 8px 0;font-family:{FONT};">{_footer(reason, site_url)}</td></tr>
</table>
</td></tr></table>
</body>
</html>"""
    return Email(subject=subject, html=html)


# ---------------------------------------------------------------- plain text
class _TextExtractor(HTMLParser):
    """Small, dependency-free HTML to plain text for the email text part.
    Handles what email_layout.py emits: skips <style>/<head>/hidden
    preheader, honours data-text="..." (used so the wordmark reads
    "Quancis" instead of "uancis" and the table-built logo vanishes), turns
    links into "label (url)", and keeps block structure as line breaks."""

    _BLOCK = {"p", "div", "h1", "h2", "h3", "tr", "table", "li", "br"}
    _SKIP = {"style", "head", "title", "script"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip_tag: str | None = None
        self._skip_depth = 0
        self._href: str | None = None
        self._link_text: list[str] = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if self._skip_tag:
            if tag == self._skip_tag:
                self._skip_depth += 1
            return
        hidden = "display:none" in (a.get("style") or "").replace(" ", "")
        if tag in self._SKIP or hidden or "data-text" in a:
            self._skip_tag, self._skip_depth = tag, 1
            if "data-text" in a and a["data-text"]:
                self.parts.append(a["data-text"])
            return
        if tag == "a":
            self._href, self._link_text = a.get("href"), []
        if tag in self._BLOCK:
            self.parts.append("\n")
        if tag == "td":
            self.parts.append(" ")

    def handle_endtag(self, tag):
        if self._skip_tag:
            if tag == self._skip_tag:
                self._skip_depth -= 1
                if self._skip_depth == 0:
                    self._skip_tag = None
            return
        if tag == "a" and self._href is not None:
            label = "".join(self._link_text).strip()
            href = self._href
            self._href = None
            if href and label and label != href:
                shown = href[len("mailto:"):] if href.startswith("mailto:") else href
                if shown not in label:
                    self.parts.append(f" ({shown})")
        if tag in self._BLOCK:
            self.parts.append("\n")

    def handle_data(self, data):
        if self._skip_tag:
            return
        self.parts.append(data)
        if self._href is not None:
            self._link_text.append(data)


def html_to_text(html: str) -> str:
    p = _TextExtractor()
    p.feed(html)
    p.close()
    lines = []
    for raw in "".join(p.parts).replace("\xa0", " ").replace("\u200c", "").split("\n"):
        line = " ".join(raw.split())
        if line:
            lines.append(line)
    return "\n\n".join(lines) + "\n"


