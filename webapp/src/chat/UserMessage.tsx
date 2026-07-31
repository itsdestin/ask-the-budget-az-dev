// One user turn. Ported from web/components/UserMessage.tsx.

import type { UserTurn } from "./chat-types.js";

interface Props {
  turn: UserTurn;
}

export default function UserMessage({ turn }: Props) {
  return (
    <div className="chat-user-row">
      <div
        className={`chat-user-bubble${turn.pending ? " is-pending" : ""}`}
        title={turn.pending ? "sending…" : undefined}
      >
        {turn.text}
      </div>
    </div>
  );
}
