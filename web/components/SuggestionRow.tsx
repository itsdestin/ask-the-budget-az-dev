"use client";

const SUGGESTIONS = [
  "What was the FY2025 Aviation Fund balance?",
  "How much did ADOT receive in FY2024?",
  "Show me General Fund revenue projections",
];

interface Props {
  onPick: (query: string) => void;
}

export default function SuggestionRow({ onPick }: Props) {
  return (
    <div className="flex-shrink-0 border-t border-edge bg-panel/30 overflow-x-auto">
      <div className="flex flex-row gap-2 px-4 py-2 max-w-3xl mx-auto">
        {SUGGESTIONS.map((q) => (
          <button
            key={q}
            type="button"
            onClick={() => onPick(q)}
            className="flex-shrink-0 whitespace-nowrap rounded-full border border-edge bg-panel
                       px-3 py-1.5 text-xs text-fg hover:border-accent hover:text-accent
                       transition-colors"
          >
            {q}
          </button>
        ))}
      </div>
    </div>
  );
}
