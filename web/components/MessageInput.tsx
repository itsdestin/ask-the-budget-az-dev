"use client";

import { useEffect, useRef, useState } from "react";

interface Props {
  onSubmit: (text: string) => void;
  disabled?: boolean;
  placeholder?: string;
}

export default function MessageInput({
  onSubmit,
  disabled,
  placeholder,
}: Props) {
  const [value, setValue] = useState("");
  const ref = useRef<HTMLTextAreaElement | null>(null);

  // Auto-grow up to a cap.
  useEffect(() => {
    const ta = ref.current;
    if (!ta) return;
    ta.style.height = "0px";
    ta.style.height = `${Math.min(ta.scrollHeight, 240)}px`;
  }, [value]);

  const handleSubmit = () => {
    const text = value.trim();
    if (!text || disabled) return;
    onSubmit(text);
    setValue("");
  };

  // Layout-level concerns (border-top, page-edge padding, background) are
  // owned by the parent so the input shares a single visual container with
  // the suggestion chips. This component renders only the input itself.
  return (
    <div className="max-w-3xl mx-auto bg-well border-[1.5px] border-edge rounded-[10px] focus-within:border-accent focus-within:ring-2 focus-within:ring-accent/30 flex gap-2 items-end px-2 py-1.5">
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
            placeholder ?? "Ask about Arizona's budget — Enter to send, Shift+Enter for newline"
          }
          disabled={disabled}
          rows={1}
          className="flex-1 resize-none bg-transparent border-none px-3 py-2 text-fg text-sm leading-relaxed focus:outline-none disabled:opacity-50"
        />
        <button
          type="button"
          onClick={handleSubmit}
          disabled={disabled || value.trim().length === 0}
          className="bg-accent text-on-accent rounded-md px-3.5 py-1.5 text-xs font-semibold font-sans hover:opacity-90 disabled:opacity-40 disabled:cursor-not-allowed transition-opacity"
        >
          Send
      </button>
    </div>
  );
}
