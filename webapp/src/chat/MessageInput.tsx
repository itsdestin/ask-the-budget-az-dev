// The composer. Ported from web/components/MessageInput.tsx, then rebuilt as
// the single-line "ask bar" (Destin, 2026-08-02).
//
// It wears Home's hero-search recipe verbatim — pill radius, canvas fill, 2px
// line, navy focus ring on white (`.page-home .search-field` in app.css). That
// is already the app's search-input identity on two pages, so AI Mode's box is
// now recognisably the same object rather than a third kind of input.
//
// WHY an <input> and not the auto-growing <textarea> it used to be: Destin
// asked for a single-line box. The cost is that Shift+Enter no longer inserts a
// newline and a pasted multi-paragraph question flattens to one line. That is
// accepted; if it bites, the fix is a one-row <textarea> styled identically
// that grows only when a newline actually arrives — the surrounding layout does
// not care which element is in here. (The auto-grow effect that used to live in
// this file, and the overflow-y juggling that stopped Firefox painting a
// scrollbar inside an empty box, went with the textarea.)

import { useState, type ReactNode } from "react";

interface Props {
  onSubmit: (text: string) => void;
  disabled?: boolean;
  placeholder?: string;
  /** The tools menu, rendered between the paperclip and the input. Passed in
   *  rather than imported so this component stays a dumb bar — the menu needs
   *  conversation state (tier, corpus) that the composer has no business
   *  knowing about. */
  tools?: ReactNode;
  /** Interrupts the streaming turn. Present ONLY while one is in flight — the
   *  caller decides that, because "is a turn streaming" is conversation state
   *  and `disabled` alone does not mean it (a blocked spend limit disables the
   *  bar too, and there is nothing to stop in that case). */
  onStop?: () => void;
}

export default function MessageInput({
  onSubmit,
  disabled,
  placeholder,
  tools,
  onStop,
}: Props) {
  const [value, setValue] = useState("");

  const handleSubmit = () => {
    const text = value.trim();
    if (!text || disabled) return;
    onSubmit(text);
    setValue("");
  };

  return (
    <div className="ask-bar">
      {/* STUB, deliberately. Attachments do not exist: the harness reads the
          corpus and Invariant 7 keeps it off the share, so there is nothing
          for a file to attach TO yet.

          It is rendered now because of where it is going. Destin, 2026-08-02:
          analysts will eventually hand the agent a ONE-OFF context document —
          a bill, a memo — to ask about WITHOUT ingesting it into the corpus.
          That is a different feature from the Upload page, which adds
          documents permanently for everyone. A future session should NOT
          "finish" this button by pointing it at /upload; that would quietly
          turn a per-conversation scratch document into a shared corpus write.

          aria-disabled rather than `disabled`: a genuinely disabled button
          receives no pointer events, so the browser never shows its title —
          and the tooltip explaining why the button does nothing would itself
          do nothing. */}
      <button
        type="button"
        className="ask-icon ask-attach"
        aria-disabled="true"
        aria-label="Attach a document"
        title="Attachments not yet implemented"
        data-testid="ask-attach"
      >
        <svg
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
          aria-hidden="true"
        >
          <path d="M21.4 11.05 12.25 20.2a5.5 5.5 0 1 1-7.78-7.78l9.2-9.2a3.67 3.67 0 0 1 5.18 5.19l-9.19 9.19a1.83 1.83 0 1 1-2.6-2.59l8.5-8.49" />
        </svg>
      </button>

      {tools}

      <input
        type="text"
        value={value}
        onChange={(e) => setValue(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter") {
            e.preventDefault();
            handleSubmit();
          }
        }}
        placeholder={placeholder ?? "Ask about the budget…"}
        disabled={disabled}
      />
      {/* Stop sits to the LEFT of Send, and does not replace it. Swapping is
          the commoner pattern and is worse here: the button under the cursor
          would change identity mid-stream, so a click meaning "send my next
          question" would land on "throw away the answer". Send goes inert
          instead, and stays exactly where it was. */}
      {onStop && (
        <button
          type="button"
          onClick={onStop}
          className="ask-stop"
          aria-label="Stop"
          title="Stop generating"
        >
          {/* The ring around it is CSS (see .ask-stop::before) — it spins for
              as long as this button exists, which is exactly as long as a turn
              is streaming. The button IS the progress indicator; a separate
              spinner would be a second thing saying the same thing. */}
          <svg viewBox="0 0 24 24" aria-hidden="true">
            <rect x="7" y="7" width="10" height="10" rx="2" fill="currentColor" />
          </svg>
        </button>
      )}
      <button
        type="button"
        onClick={handleSubmit}
        disabled={disabled || value.trim().length === 0}
        className="ask-send"
      >
        Send
      </button>
    </div>
  );
}
