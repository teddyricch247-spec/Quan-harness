import type { Metadata } from 'next';
import { notFound } from 'next/navigation';
import { DocsPage } from '../../../components/pages/DocsPage';
import { DOCS_PAGES, OVERVIEW_SLUG, docsHref, getDocsPage } from '../../../components/docs/nav';

// /docs/<slug>: every docs page except the overview, which lives at /docs
// (/docs/overview redirects there, see next.config.ts). Pages are generated at
// build time from components/docs/nav.ts; an unknown slug is a 404.
export const dynamicParams = false;

type Props = { params: Promise<{ slug: string }> };

export function generateStaticParams() {
  return DOCS_PAGES.filter((p) => p.slug !== OVERVIEW_SLUG).map((p) => ({ slug: p.slug }));
}

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { slug } = await params;
  const page = getDocsPage(slug);
  if (!page) return {};
  return {
    title: `${page.title} — Quancis Docs`,
    description: page.description,
    alternates: { canonical: docsHref(slug) },
  };
}

export default async function Page({ params }: Props) {
  const { slug } = await params;
  if (slug === OVERVIEW_SLUG || !getDocsPage(slug)) notFound();
  return <DocsPage slug={slug} />;
}
