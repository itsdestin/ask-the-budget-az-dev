"use client";

import Mascot from "./mascot/Mascot";

const SUGGESTIONS = [
  "What was the FY2025 Aviation Fund balance?",
  "How much did ADOT receive in FY2024?",
  "Show me General Fund revenue projections",
];

interface Props {
  onPick: (query: string) => void;
}

export default function WelcomeHero({ onPick }: Props) {
  return (
    <div className="flex-1 flex flex-col items-center justify-center text-center px-6 py-12 gap-2">
      <Mascot pose="wave" size="hero" className="mb-2" />
      <h1 className="font-serif text-3xl font-bold text-fg">
        Hi — let&apos;s look at the budget.
      </h1>
      <p className="text-fg-2 max-w-xl">
        I&apos;ll search the JLBC Appropriations Reports, Baseline Books, AGAO Annual
        Financial Reports, and Governor&apos;s Executive Budget. Every claim gets a
        citation to the source page.
      </p>
      <div className="mt-4 text-xs uppercase tracking-wider text-fg-muted">
        try one of these
      </div>
      <div className="flex flex-wrap gap-2 justify-center max-w-xl">
        {SUGGESTIONS.map((q) => (
          <button
            key={q}
            type="button"
            onClick={() => onPick(q)}
            className="rounded-full border border-edge bg-panel px-3 py-1.5 text-xs text-fg
                       hover:border-accent hover:text-accent transition-colors"
          >
            {q}
          </button>
        ))}
      </div>
    </div>
  );
}
