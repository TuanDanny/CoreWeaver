from __future__ import annotations

from coreweaver.messages import CoreMessage, MessageKind, MessageRole


class Agent1PlaceholderWorker:
    async def run(self, message: CoreMessage) -> CoreMessage:
        return CoreMessage.from_payload(
            message_id=f"{message.message_id}:placeholder",
            run_id=message.run_id,
            revision_id=message.revision_id,
            role=MessageRole.SYSTEM,
            kind=MessageKind.MANAGER_SUMMARY,
            payload={"status": "CORE_SKELETON_READY", "source_message_id": message.message_id},
            parent_message_id=message.message_id,
        )
