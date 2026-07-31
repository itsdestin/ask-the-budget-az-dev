// Starter-question chips. Ported from web/components/SuggestionRow.tsx.
//
// The shared container (border, background, page-level position) is supplied
// by the parent so the chips and the composer sit inside ONE visual box.

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
    <div className="chat-suggestions">
      <div className="chat-suggestions-row">
        {SUGGESTIONS.map((q) => (
          <button
            key={q}
            type="button"
            onClick={() => onPick(q)}
            className="chat-suggestion"
          >
            {q}
          </button>
        ))}
      </div>
    </div>
  );
}
