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

  return (
    <div className="border-t border-edge bg-panel/60 px-4 py-3">
      <div className="max-w-3xl mx-auto flex gap-2 items-end">
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
          className="flex-1 resize-none bg-canvas border border-edge rounded-md px-3 py-2 text-fg text-sm leading-relaxed focus:outline-none focus:border-fg-dim disabled:opacity-50"
        />
        <button
          type="button"
          onClick={handleSubmit}
          disabled={disabled || value.trim().length === 0}
          className="rounded-md border border-edge bg-accent text-on-accent text-sm px-4 py-2 hover:opacity-90 disabled:opacity-40 disabled:cursor-not-allowed transition-opacity"
        >
          Send
        </button>
      </div>
    </div>
  );
}
