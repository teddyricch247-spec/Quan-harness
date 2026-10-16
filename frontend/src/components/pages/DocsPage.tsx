import React from 'react';
import { DocArticle } from '../docs/primitives';
import { DOCS_CONTENT } from '../docs/content';

// One docs page, by slug. Used by /docs (slug "overview") and /docs/[slug].
// The frame around it (sidebar, section picker, "On this page") is
// components/docs/DocsShell.tsx, mounted once by app/docs/layout.tsx.
// To add a page: add its entry to components/docs/nav.ts, write its body in
// components/docs/pages/, and register it in components/docs/content.tsx.
export const DocsPage: React.FC<{ slug: string }> = ({ slug }) => {
  const Body = DOCS_CONTENT[slug];
  if (!Body) return null;
  return (
    <DocArticle slug={slug}>
      <Body />
    </DocArticle>
  );
};
