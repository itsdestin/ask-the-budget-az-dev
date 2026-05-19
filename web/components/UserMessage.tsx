"use client";

import type { UserTurn } from "@/state/chat-types";

interface Props {
  turn: UserTurn;
}

export default function UserMessage({ turn }: Props) {
  return (
    <div className="flex justify-end">
      <div
        className={
          "bg-accent text-on-accent rounded-[12px_12px_4px_12px] px-3.5 py-2 max-w-[78%] font-sans text-sm leading-relaxed whitespace-pre-wrap " +
          (turn.pending ? "opacity-70" : "")
        }
        title={turn.pending ? "sending…" : undefined}
      >
        {turn.text}
      </div>
    </div>
  );
}
