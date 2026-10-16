import React from 'react';

// A deliberately tiny syntax highlighter for the docs' code blocks. It only
// knows the five kinds of snippet the docs contain, and it adds no
// dependency. Each rule is a regex literal with NO capturing groups (the
// combined regex below uses one capture group per rule to tell them apart).
// Colors are theme tokens from globals.css (--color-code-*).

export type Lang = 'bash' | 'python' | 'ts' | 'json' | 'text';

interface Rule {
  cls: string;
  re: RegExp;
}

const NUMBER: Rule = { cls: 'text-code-number', re: /\b\d+(?:\.\d+)?\b/ };

const RULES: Record<Lang, Rule[]> = {
  text: [],
  json: [
    { cls: 'text-code-key', re: /"(?:[^"\\\n]|\\.)*"(?=\s*:)/ },
    { cls: 'text-code-string', re: /"(?:[^"\\\n]|\\.)*"/ },
    { cls: 'text-code-number', re: /\b(?:true|false|null)\b/ },
    NUMBER,
  ],
  bash: [
    { cls: 'text-code-comment', re: /#[^\n]*/ },
    { cls: 'text-code-string', re: /'[^']*'|"(?:[^"\\]|\\.)*"/ },
    { cls: 'text-code-key', re: /\$[A-Za-z_][A-Za-z0-9_]*/ },
    { cls: 'text-code-keyword', re: /\s-{1,2}[A-Za-z][\w-]*/ },
    { cls: 'text-code-keyword', re: /\b(?:curl|export)\b/ },
  ],
  python: [
    { cls: 'text-code-comment', re: /#[^\n]*/ },
    { cls: 'text-code-string', re: /"""[\s\S]*?"""|'(?:[^'\\\n]|\\.)*'|"(?:[^"\\\n]|\\.)*"/ },
    {
      cls: 'text-code-keyword',
      re: /\b(?:import|from|as|def|return|for|in|if|elif|else|with|print|None|True|False|async|await|class|try|except|not|and|or|lambda)\b/,
    },
    NUMBER,
  ],
  ts: [
    { cls: 'text-code-comment', re: /\/\/[^\n]*/ },
    { cls: 'text-code-string', re: /'(?:[^'\\\n]|\\.)*'|"(?:[^"\\\n]|\\.)*"|`(?:[^`\\]|\\.)*`/ },
    {
      cls: 'text-code-keyword',
      re: /\b(?:import|from|const|let|await|async|function|return|new|export|default|if|else|for|of|in|true|false|null|undefined|class|try|catch|type|interface|as)\b/,
    },
    NUMBER,
  ],
};

const COMBINED: Partial<Record<Lang, RegExp>> = {};

function combinedFor(lang: Lang): RegExp {
  let re = COMBINED[lang];
  if (!re) {
    re = new RegExp(RULES[lang].map((r) => `(${r.re.source})`).join('|'), 'g');
    COMBINED[lang] = re;
  }
  re.lastIndex = 0;
  return re;
}

export function highlight(code: string, lang: Lang): React.ReactNode[] {
  if (RULES[lang].length === 0) return [code];

  const rules = RULES[lang];
  const re = combinedFor(lang);
  const out: React.ReactNode[] = [];
  let last = 0;
  let m: RegExpExecArray | null;

  while ((m = re.exec(code)) !== null) {
    if (m[0] === '') {
      re.lastIndex += 1;
      continue;
    }
    if (m.index > last) out.push(code.slice(last, m.index));
    const ruleIndex = m.slice(1).findIndex((g) => g !== undefined);
    out.push(
      <span key={out.length} className={rules[ruleIndex].cls}>
        {m[0]}
      </span>,
    );
    last = m.index + m[0].length;
  }
  if (last < code.length) out.push(code.slice(last));
  return out;
}
