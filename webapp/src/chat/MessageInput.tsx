// The composer. Ported from web/components/MessageInput.tsx, then rebuilt as
// the single-line "ask bar" (Destin, 2026-08-02).
//
// It wears Home's hero-search recipe verbatim — pill radius, canvas fill, 2px
// line, navy focus ring on white (`.page-home .search-field` in app.css). That
// is already the app's search-input identity on two pages, so AI Mode's box is
// now recognisably the same object rather than a third kind of input.
//
// It is a <textarea> that WRAPS and grows to a hard ceiling of four lines,
// then scrolls (Destin, 2026-08-02). The plain <input> it briefly was pushed
// long questions sideways off the end of the field, which is unreadable while
// you are still writing the thing.
//
// Past four lines it scrolls with NO scrollbar and a fade at whichever edge
// has more text behind it. The fade is the entire affordance — with the bar
// hidden, a faded half-line is the only thing telling you the box has more in
// it, so the fade may not be decorative and may not be always-on: a permanent
// top fade on a one-line question would just look like the text was broken.

import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type CSSProperties,
  type ReactNode,
} from "react";

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

/** The ceiling, in lines. Past this the box stops growing and starts scrolling. */
const MAX_ROWS = 4;

export default function MessageInput({
  onSubmit,
  disabled,
  placeholder,
  tools,
  onStop,
}: Props) {
  const [value, setValue] = useState("");
  const taRef = useRef<HTMLTextAreaElement | null>(null);
  /** Height of the empty box, captured once — the yardstick for "has it grown
   *  past one line?", which drives the corner radius below. */
  const oneLineRef = useRef<number | null>(null);
  const [grown, setGrown] = useState(false);
  const [fade, setFade] = useState({ top: false, bottom: false });

  /** Re-measure after anything that can change the content or the scroll
   *  position. Height is zeroed first so scrollHeight reports the CONTENT's
   *  height rather than the box's current (possibly already-clamped) one. */
  const measure = useCallback(() => {
    const ta = taRef.current;
    if (!ta) return;
    ta.style.height = "auto";
    const content = ta.scrollHeight;
    if (oneLineRef.current === null) oneLineRef.current = content;
    // Assign the full height and let CSS `max-height` do the clamping — that
    // keeps the four-line ceiling expressed once, in em, next to the
    // line-height it depends on, instead of duplicated as a pixel constant
    // here that would silently drift if the type scale changed.
    ta.style.height = `${content}px`;
    const visible = ta.clientHeight;

    setGrown(content > (oneLineRef.current ?? content) + 2);
    // 2px of slack: a fractional line box (15.5px x 1.6 = 24.8px) rounds
    // against an integer scrollHeight, and a half-pixel of "overflow" is not
    // overflow — it is the same rounding that used to make Firefox paint a
    // scrollbar inside an empty composer.
    const overflowing = content - visible > 2;
    const top = ta.scrollTop;
    setFade({
      top: overflowing && top > 2,
      bottom: overflowing && top + visible < content - 2,
    });
  }, []);

  useEffect(measure, [value, measure]);

  const handleSubmit = () => {
    const text = value.trim();
    if (!text || disabled) return;
    onSubmit(text);
    setValue("");
  };

  return (
    // A full pill around a four-line box reads as a stadium, so the radius
    // steps down to --r-lg once it has actually grown. Both are existing
    // tokens; nothing new enters the palette.
    <div className={grown ? "ask-bar is-grown" : "ask-bar"}>
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

      <textarea
        ref={taRef}
        rows={1}
        style={{ "--ask-max-rows": MAX_ROWS } as CSSProperties}
        value={value}
        onChange={(e) => setValue(e.target.value)}
        onScroll={measure}
        onKeyDown={(e) => {
          // Enter sends; Shift+Enter is a newline, which is why this is a
          // textarea again.
          if (e.key === "Enter" && !e.shiftKey) {
            e.preventDefault();
            handleSubmit();
          }
        }}
        className={
          fade.top && fade.bottom
            ? "is-fade-both"
            : fade.top
              ? "is-fade-top"
              : fade.bottom
                ? "is-fade-bottom"
                : undefined
        }
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
