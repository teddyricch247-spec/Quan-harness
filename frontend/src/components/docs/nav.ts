import { docsPath } from '../../lib/routes';

// The docs table of contents and the registry of docs pages. One entry per
// page: the slug is the URL (/docs/<slug>, except `overview` which is /docs),
// `title` is the sidebar label, `heading` (optional) overrides the page's H1,
// and `description` is both the page's lead paragraph and its meta description.
// The page body for each slug is registered in ./content.tsx.

export interface DocsPageMeta {
  slug: string;
  title: string;
  heading?: string;
  description: string;
}

export interface DocsNavGroup {
  title: string;
  pages: DocsPageMeta[];
}

export const OVERVIEW_SLUG = 'overview';

export const DOCS_NAV: DocsNavGroup[] = [
  {
    title: 'Start',
    pages: [
      {
        slug: 'overview',
        title: 'Overview',
        heading: 'Build with Kael',
        description:
          'Kael is the Quancis intelligence system, available through one API. Use the OpenAI or Anthropic SDK you already have, and change only the base URL and the model name.',
      },
      {
        slug: 'quickstart',
        title: 'Quickstart',
        description: 'Create a key, check your balance, and send your first request in a few minutes.',
      },
      {
        slug: 'authentication',
        title: 'Authentication',
        description: 'How to send your API key, what a key can do, and how to keep it safe.',
      },
    ],
  },
  {
    title: 'Build',
    pages: [
      {
        slug: 'endpoints',
        title: 'Endpoints',
        description: 'The three request formats Kael speaks, the routes for each, and what comes back.',
      },
      {
        slug: 'request-fields',
        title: 'Request fields',
        description: 'Which request fields Kael uses, and which ones it accepts but ignores.',
      },
      {
        slug: 'thinking',
        title: 'Thinking levels',
        description: 'Choose how hard Kael works on a request with reasoning_effort.',
      },
      {
        slug: 'streaming',
        title: 'Streaming',
        description: "Stream answers over server-sent events, including Kael's short thinking titles.",
      },
      {
        slug: 'tools',
        title: 'Tool calling',
        description: 'Let Kael call your functions, and how tool calls behave.',
      },
      {
        slug: 'images',
        title: 'Images',
        description: 'Send images alongside text. Other file types are not supported yet.',
      },
      {
        slug: 'system-prompts',
        title: 'System prompts',
        description: 'How Kael treats your system prompt, and what it adds around it.',
      },
      {
        slug: 'sdks',
        title: 'SDKs and frameworks',
        description: 'Working setups for the OpenAI and Anthropic SDKs, LangChain, and the Vercel AI SDK.',
      },
    ],
  },
  {
    title: 'Platform',
    pages: [
      {
        slug: 'about',
        title: 'About Kael',
        description: 'When to choose Kael, what to expect from it, and how requests are screened.',
      },
      {
        slug: 'pricing',
        title: 'Pricing and billing',
        description: 'Per-token prices, exactly what you are billed for, and how your balance works.',
      },
      {
        slug: 'caching',
        title: 'Prompt caching',
        description: 'Cached input costs less. How it is applied and how to see it in your usage.',
      },
      {
        slug: 'limits',
        title: 'Limits',
        description: 'Context, output, rate, concurrency, and time limits.',
      },
      {
        slug: 'errors',
        title: 'Errors',
        description: 'Status codes, error codes, and which errors to retry.',
      },
      {
        slug: 'privacy',
        title: 'Data and privacy',
        description: 'What Quancis stores, for how long, and what it does not do with your data.',
      },
    ],
  },
  {
    title: 'Console',
    pages: [
      {
        slug: 'dashboard',
        title: 'Dashboard and usage',
        description: 'Your balance, live request log, and cost analytics.',
      },
      {
        slug: 'playground',
        title: 'Playground',
        description: 'Chat with Kael in the browser, billed at the same per-token prices as the API.',
      },
      {
        slug: 'api-keys',
        title: 'API keys',
        description: 'Create, inspect, and delete the keys that authenticate your requests.',
      },
      {
        slug: 'account',
        title: 'Account',
        description: 'Profile, password, and low-balance alerts.',
      },
    ],
  },
  {
    title: 'Help',
    pages: [
      {
        slug: 'not-yet',
        title: 'Not available yet',
        description: "What Kael and the platform don't do today, stated plainly.",
      },
      {
        slug: 'support',
        title: 'Support',
        description: 'How to reach Quancis, and what to include so we can help quickly.',
      },
    ],
  },
];

export const DOCS_PAGES: DocsPageMeta[] = DOCS_NAV.flatMap((g) => g.pages);

export const docsHref = docsPath;

export function getDocsPage(slug: string): DocsPageMeta | undefined {
  return DOCS_PAGES.find((p) => p.slug === slug);
}

export function getDocsNeighbors(slug: string): { prev: DocsPageMeta | null; next: DocsPageMeta | null } {
  const i = DOCS_PAGES.findIndex((p) => p.slug === slug);
  if (i === -1) return { prev: null, next: null };
  return { prev: DOCS_PAGES[i - 1] ?? null, next: DOCS_PAGES[i + 1] ?? null };
}

export function getDocsGroupTitle(slug: string): string | undefined {
  return DOCS_NAV.find((g) => g.pages.some((p) => p.slug === slug))?.title;
}
