import { ApiKey, ModelBenchmark, RequestLog, UsageDay, UserProfile } from '../types';

export const INITIAL_USER: UserProfile = {
  id: 'usr_quan_9941a8',
  name: 'Developer Account',
  email: 'developer@quancis.space',
  avatar: 'https://images.unsplash.com/photo-1534528741775-53994a69daeb?w=150&auto=format&fit=crop&q=80',
  tier: 'Scale',
  role: 'user',
  creditBalance: 142.80,
  monthlySpend: 24.32,
  createdAt: '2026-01-15',
  provider: 'email',
  lowBalanceAlertEnabled: false,
  lowBalanceAlertThresholdUsd: 10,
};

export const INITIAL_API_KEYS: ApiKey[] = [
  {
    id: 'key_prod_01',
    name: 'Production',
    key: 'sk-quan-9f82••••••••••••••••••••••••',
    prefix: 'sk-quan-9f82',
    createdAt: '2026-02-10',
    lastUsedAt: '2 mins ago',
    active: true,
    thinkingLevel: 'sdk',
  },
  {
    id: 'key_dev_02',
    name: 'Development',
    key: 'sk-quan-18e9••••••••••••••••••••••••',
    prefix: 'sk-quan-18e9',
    createdAt: '2026-03-01',
    lastUsedAt: '3 hours ago',
    active: true,
    thinkingLevel: 'sdk',
  },
  {
    id: 'key_play_03',
    name: 'Playground',
    key: 'sk-quan-4e78••••••••••••••••••••••••',
    prefix: 'sk-quan-4e78',
    createdAt: '2026-03-12',
    lastUsedAt: 'Just now',
    active: true,
    thinkingLevel: 'sdk',
  },
];

export const BENCHMARKS: ModelBenchmark[] = [
  {
    metric: 'SWE-bench Verified (Resolved)',
    quanAI: 54.2,
    gpt4o: 43.1,
    claude35Sonnet: 51.4,
    o1Mini: 48.9,
    unit: '%',
    description: 'Real-world GitHub software engineering bug fixes with multi-file reasoning',
  },
  {
    metric: 'ToolBench Agentic Accuracy',
    quanAI: 92.6,
    gpt4o: 84.5,
    claude35Sonnet: 89.2,
    o1Mini: 86.8,
    unit: '%',
    description: 'Multi-turn API decision-making, parameter extraction, and execution validation',
  },
  {
    metric: 'HumanEval+ Code Synthesis',
    quanAI: 95.8,
    gpt4o: 89.4,
    claude35Sonnet: 93.7,
    o1Mini: 92.1,
    unit: '%',
    description: 'Zero-shot and self-critiqued Python code generation accuracy',
  },
  {
    metric: 'MATH-500 Verified Logic',
    quanAI: 91.4,
    gpt4o: 76.8,
    claude35Sonnet: 82.3,
    o1Mini: 90.0,
    unit: '%',
    description: 'Multi-step competitive mathematical problem solving with formal verification step',
  },
  {
    metric: 'Input Token Price / 1M',
    quanAI: 1.50,
    gpt4o: 5.00,
    claude35Sonnet: 3.00,
    o1Mini: 3.00,
    unit: '$',
    description: 'Uncached base input token price (Up to $0.15 with 90% cache hit)',
  },
  {
    metric: 'Output Token Price / 1M',
    quanAI: 4.00,
    gpt4o: 15.00,
    claude35Sonnet: 15.00,
    o1Mini: 12.00,
    unit: '$',
    description: 'High-accuracy synthesized output token cost',
  },
];

export const RECENT_LOGS: RequestLog[] = [
  {
    id: 'req_98a71f01',
    timestamp: 'Just now',
    endpoint: '/v1/chat/completions',
    model: 'kael-beta',
    status: 200,
    tokens: 4280,
    cacheHit: true,
    latency: 1840,
    cost: 0.0062,
  },
  {
    id: 'req_98a71f02',
    timestamp: '1 min ago',
    endpoint: '/v1/chat/completions',
    model: 'kael-beta',
    status: 200,
    tokens: 8120,
    cacheHit: true,
    latency: 2420,
    cost: 0.0118,
  },
  {
    id: 'req_98a71f03',
    timestamp: '4 mins ago',
    endpoint: '/v1/chat/completions',
    model: 'kael-beta',
    status: 200,
    tokens: 1950,
    cacheHit: false,
    latency: 1210,
    cost: 0.0051,
  },
  {
    id: 'req_98a71f04',
    timestamp: '12 mins ago',
    endpoint: '/v1/chat/completions',
    model: 'kael-beta',
    status: 200,
    tokens: 15400,
    cacheHit: true,
    latency: 3890,
    cost: 0.0224,
  },
  {
    id: 'req_98a71f05',
    timestamp: '25 mins ago',
    endpoint: '/v1/models',
    model: 'system',
    status: 200,
    tokens: 0,
    cacheHit: false,
    latency: 42,
    cost: 0.0000,
  },
  {
    id: 'req_98a71f06',
    timestamp: '41 mins ago',
    endpoint: '/v1/chat/completions',
    model: 'kael-beta',
    status: 200,
    tokens: 6300,
    cacheHit: true,
    latency: 1950,
    cost: 0.0089,
  },
];

export const USAGE_HISTORY: UsageDay[] = [
  { date: 'Aug 12', inputTokens: 420000, cachedTokens: 350000, outputTokens: 180000, totalRequests: 142, costDollars: 1.44, avgLatencyMs: 1920 },
  { date: 'Aug 13', inputTokens: 680000, cachedTokens: 590000, outputTokens: 290000, totalRequests: 210, costDollars: 2.33, avgLatencyMs: 1840 },
  { date: 'Aug 14', inputTokens: 950000, cachedTokens: 820000, outputTokens: 410000, totalRequests: 325, costDollars: 3.28, avgLatencyMs: 2010 },
  { date: 'Aug 15', inputTokens: 1200000, cachedTokens: 1050000, outputTokens: 520000, totalRequests: 412, costDollars: 4.16, avgLatencyMs: 1950 },
  { date: 'Aug 16', inputTokens: 890000, cachedTokens: 780000, outputTokens: 380000, totalRequests: 290, costDollars: 3.04, avgLatencyMs: 1890 },
  { date: 'Aug 17', inputTokens: 1450000, cachedTokens: 1310000, outputTokens: 630000, totalRequests: 518, costDollars: 5.04, avgLatencyMs: 2150 },
  { date: 'Aug 18 (Today)', inputTokens: 1120000, cachedTokens: 990000, outputTokens: 480000, totalRequests: 389, costDollars: 3.88, avgLatencyMs: 1930 },
];

export const PLAYGROUND_PRESETS = [
  {
    title: 'High-Stakes Agentic Tool Routing',
    description: 'Complex multi-step decision requiring dynamic parameter validation and tool selection',
    prompt: `You are an autonomous DevOps triage agent. A microservice in production has thrown 429 rate limit errors on Stripe webhooks, caused redis connection pool exhaustion, and CPU spiked to 98%. 

Available tools:
1. inspect_k8s_pods(namespace: string, filter: string)
2. scale_deployment(name: string, replicas: number)
3. adjust_redis_pool_size(max_connections: number, timeout_ms: number)
4. throttle_incoming_webhooks(route: string, rate_limit_rps: number)
5. notify_oncall(severity: "P1" | "P2" | "P3", summary: string)

Formulate the optimal sequential execution plan with safety bounds, execute necessary simulated actions, and verify zero data loss.`,
  },
  {
    title: 'Self-Critiqued Distributed Caching Bug',
    description: 'Subtle race condition in multi-threaded Redis cache-aside with thundering herd',
    prompt: `Analyze this Go concurrency implementation of a single-flight cache-aside pattern with Redis. Identify all edge cases, deadlock risks, and race conditions under 100,000 concurrent requests during cold cache startup, then provide the hardened, mathematically verified version.`,
  },
  {
    title: 'Algorithmic Optimization & Proof',
    description: 'Maximum submatrix sum with strict O(N^3) to O(N^2 log N) reduction proof',
    prompt: `Given a 2D integer matrix of size N x M with negative and positive values, provide an optimal dynamic programming algorithm with 2D Kadane's optimization. Include formal space/time complexity proof and edge cases handling (all negatives, 1x1, 10^5 elements).`,
  },
  {
    title: 'Zero-Shot SQL Schema Synthesis',
    description: 'Multi-tenant RBAC with row-level security and high-throughput append logs',
    prompt: `Design a high-scale PostgreSQL 17 schema for an AI API billing and meter platform supporting 50M daily events. Implement partitions by month, composite indexes for time-series aggregation, and Row-Level Security (RLS) policies for multi-tenant isolation.`,
  },
];
