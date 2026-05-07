"use client";

import type { AssistantTurn } from "@/state/chat-types";
import MarkdownContent from "./MarkdownContent";
import ToolCard from "./ToolCard";

interface Props {
  turn: AssistantTurn;
}

const STOP_NOTE: Record<string, string> = {
  max_tokens: "Response cut off — token limit reached.",
  refusal: "Claude refused to answer this turn.",
  stop_sequence: "Hit a stop sequence.",
  pause_turn: "Paused — partial response.",
  session_died: "YouCoded session exited mid-turn.",
  aborted: "Stopped by user.",
};

export default function AssistantTurnBubble({ turn }: Props) {
  return (
    <div className="flex flex-col gap-1">
      {turn.blocks.map((block) => {
        if (block.kind === "text") {
          return (
            <div
              key={block.uuid}
              className="rounded-md bg-well border border-edge-dim p-3 text-fg text-sm"
            >
              <MarkdownContent content={block.text} />
            </div>
          );
        }
        return <ToolCard key={block.toolUseId} tool={block} />;
      })}
      {turn.isComplete && turn.stopReason && STOP_NOTE[turn.stopReason] && (
        <div className="text-xs text-fg-muted italic px-1">
          {STOP_NOTE[turn.stopReason]}
        </div>
      )}
    </div>
  );
}
