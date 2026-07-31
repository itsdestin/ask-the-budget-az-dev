// The composer. Ported from web/components/MessageInput.tsx.
//
// Layout-level concerns (border, page-edge padding, background) are owned by
// the parent so the input can share one visual container with the suggestion
// chips. This component renders only the input itself.

import { useEffect, useRef, useState } from "react";

interface Props {
  onSubmit: (text: string) => void;
  disabled?: boolean;
  placeholder?: string;
}

const MAX_HEIGHT_PX = 240;

export default function MessageInput({
  onSubmit,
  disabled,
  placeholder,
}: Props) {
  const [value, setValue] = useState("");
  const ref = useRef<HTMLTextAreaElement | null>(null);

  // Auto-grow up to a cap. Height is zeroed first so scrollHeight reports the
  // content height rather than the current (possibly larger) box.
  useEffect(() => {
    const ta = ref.current;
    if (!ta) return;
    ta.style.height = "0px";
    ta.style.height = `${Math.min(ta.scrollHeight, MAX_HEIGHT_PX)}px`;
  }, [value]);

  const handleSubmit = () => {
    const text = value.trim();
    if (!text || disabled) return;
    onSubmit(text);
    setValue("");
  };

  return (
    <div className="chat-input">
      <textarea
        ref={ref}
        value={value}
        onChange={(e) => setValue(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter" && !e.shiftKey) {
            e.preventDefault();
            handleSubmit();
          }
        }}
        placeholder={
          placeholder ??
          "Ask about Arizona's budget — Enter to send, Shift+Enter for newline"
        }
        disabled={disabled}
        rows={1}
      />
      <button
        type="button"
        onClick={handleSubmit}
        disabled={disabled || value.trim().length === 0}
        className="chat-send"
      >
        Send
      </button>
    </div>
  );
}
