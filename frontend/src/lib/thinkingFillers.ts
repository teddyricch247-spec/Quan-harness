// Filler words the backend sends while no real thinking title is ready yet
// ("Thinking", "Checking the answer over", ...). They show that work is still
// happening, so they may be used as the live label, but they are not steps and
// must not be counted or stored with the reply.
//
// Keep in sync with backend/app/thinking_fillers.py (the backend also drops
// them from what it saves).
const FILLERS = new Set(
  [
    'Thinking',
    'Considering',
    'Weighing options',
    'Working through it',
    'Reasoning',
    'Analyzing',
    'Mulling it over',
    'Working on the answer',
    'Writing out the response',
    'Putting the answer together',
    'Still writing it out',
    'Checking the answer over',
    'Double-checking the details',
    'Looking it over',
    'Pulling it together',
    'Refining the answer',
    'Weighing the strongest ideas',
    // Wording used before 2026-10-08; saved replies may still contain it.
    'Drafting the answer',
    'Still writing the draft',
    'Reviewing the draft',
    'Checking the draft over',
    'Looking over the draft',
  ].map((w) => w.toLowerCase())
);

export function isThinkingFiller(title: string): boolean {
  return FILLERS.has(title.trim().toLowerCase());
}
