"use client";

const SUGGESTIONS = [
  "What was the FY2025 Aviation Fund balance?",
  "How much did ADOT receive in FY2024?",
  "Show me General Fund revenue projections",
];

interface Props {
  onPick: (query: string) => void;
}

// Lean strip — just the chip row. The shared container (border-top,
// background, page-level position) is supplied by the parent in page.tsx
// so the chips and the input live inside ONE visual container.
export default function SuggestionRow({ onPick }: Props) {
  return (
    // `overflow-x-auto` enables native two-finger trackpad horizontal scroll.
    // The inner row is `mx-auto w-fit`: when the chips fit, the group is
    // centered in the viewport; when they overflow (future longer/more
    // chips), the user can scroll horizontally — works for any chip set.
    <div className="overflow-x-auto">
      <div className="flex flex-row gap-2 px-4 pt-2 pb-1 mx-auto w-fit">
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
