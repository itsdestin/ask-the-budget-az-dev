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
          "max-w-[80%] rounded-md bg-inset border border-edge px-3 py-2 text-fg text-sm whitespace-pre-wrap " +
          (turn.pending ? "opacity-70" : "")
        }
        title={turn.pending ? "sending…" : undefined}
      >
        {turn.text}
      </div>
    </div>
  );
}
