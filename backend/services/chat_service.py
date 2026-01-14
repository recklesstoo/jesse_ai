from __future__ import annotations

from typing import Any, Dict, List

from sqlalchemy.orm import Session

from backend.models import AISignal, CommandEvent


class ChatService:
    def generate_reply(
        self,
        bot_id: str,
        messages: List[Dict[str, str]],
        bot_state: Dict[str, Any],
        db: Session,
    ) -> str:
        last_user_msg = ""
        for message in reversed(messages):
            if message.get("role") == "user":
                last_user_msg = message.get("content", "").lower()
                break

        price = bot_state.get("last_price", "N/A")
        connected = bot_state.get("connected", False)
        mode = bot_state.get("mode", "UNKNOWN")

        if "status" in last_user_msg or "estado" in last_user_msg:
            return (
                f"Bot {bot_id} status:\n"
                f"- Connected: {'Yes' if connected else 'No'}\n"
                f"- Mode: {mode}\n"
                f"- Last price: {price}\n"
                f"- Last seen: {bot_state.get('last_seen_utc', 'never')}"
            )

        if "price" in last_user_msg or "precio" in last_user_msg:
            return f"Current price for {bot_state.get('instrument', 'MNQ')} is {price}."

        if any(term in last_user_msg for term in ("signal", "señal", "trend")):
            last_signal = (
                db.query(AISignal)
                .filter(AISignal.bot_id == bot_id)
                .order_by(AISignal.ts_utc.desc())
                .first()
            )
            if last_signal:
                return (
                    f"AI signal:\n"
                    f"- Signal: {last_signal.signal}\n"
                    f"- Bias: {last_signal.bias}\n"
                    f"- Confidence: {last_signal.confidence:.2f}\n"
                    f"- Explain: {last_signal.explain}"
                )
            return "I do not have enough signal data yet."

        if "command" in last_user_msg or "orden" in last_user_msg:
            cmds = (
                db.query(CommandEvent)
                .filter(CommandEvent.bot_id == bot_id)
                .order_by(CommandEvent.ts_utc.desc())
                .limit(3)
                .all()
            )
            if cmds:
                history = "\n".join(
                    f"- {cmd.event} ({cmd.ts_utc.strftime('%H:%M:%S')})" for cmd in cmds
                )
                return f"Recent command events:\n{history}"
            return "No recent commands recorded."

        if "help" in last_user_msg or "ayuda" in last_user_msg:
            return (
                "I can help with:\n"
                "- 'status': Bot health and mode\n"
                "- 'price': Latest price\n"
                "- 'signal': AI signal summary\n"
                "- 'commands': Recent command log"
            )

        return (
            f"Monitoring {bot_state.get('instrument', 'MNQ')} at {price}. "
            f"Ask me about 'status', 'signal', or 'commands'."
        )


chat_service = ChatService()
