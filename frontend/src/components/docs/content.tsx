import React from 'react';
import { Overview, Quickstart, Authentication } from './pages/start';
import { Endpoints, RequestFields, Thinking, Streaming, Tools, Images, SystemPrompts, Sdks } from './pages/build';
import { AboutKael, Pricing, Caching, Limits, Errors, Privacy } from './pages/platform';
import { Dashboard, Playground, ApiKeys, Account } from './pages/console';
import { NotYet, Support } from './pages/help';

// slug -> page body. The slugs, titles and descriptions live in ./nav.ts;
// every slug there needs an entry here (and vice versa).
export const DOCS_CONTENT: Record<string, React.FC> = {
  overview: Overview,
  quickstart: Quickstart,
  authentication: Authentication,

  endpoints: Endpoints,
  'request-fields': RequestFields,
  thinking: Thinking,
  streaming: Streaming,
  tools: Tools,
  images: Images,
  'system-prompts': SystemPrompts,
  sdks: Sdks,

  about: AboutKael,
  pricing: Pricing,
  caching: Caching,
  limits: Limits,
  errors: Errors,
  privacy: Privacy,

  dashboard: Dashboard,
  playground: Playground,
  'api-keys': ApiKeys,
  account: Account,

  'not-yet': NotYet,
  support: Support,
};
