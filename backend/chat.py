from typing import List, Dict, Any
from sqlalchemy.orm import Session
from .models import Bar, CommandEvent, AISignal

class ChatService:
    def __init__(self):
        pass

    def generate_reply(self, bot_id: str, messages: List[Dict[str, str]], bot_state: Dict[str, Any], db: Session) -> str:
        """
        Genera una respuesta basada en reglas y contexto del sistema.
        Simula un asistente inteligente sin LLM externo.
        """
        last_user_msg = ""
        for m in reversed(messages):
            if m.get("role") == "user":
                last_user_msg = m.get("content", "").lower()
                break
        
        # Contexto
        price = bot_state.get("last_price", "N/A")
        connected = bot_state.get("connected", False)
        mode = bot_state.get("mode", "UNKNOWN")
        
        # Intent Recognition simple
        if "status" in last_user_msg or "estado" in last_user_msg:
            return (
                f"🤖 **Estado del Bot {bot_id}**\n"
                f"- Conexión: {'✅ Online' if connected else '❌ Offline'}\n"
                f"- Modo: {mode}\n"
                f"- Último Precio: {price}\n"
                f"- Última Actualización: {bot_state.get('last_seen_utc', 'Nunca')}"
            )

        if "precio" in last_user_msg or "price" in last_user_msg:
            return f"El precio actual de {bot_state.get('instrument', 'MNQ')} es **{price}**."

        if "señal" in last_user_msg or "signal" in last_user_msg or "trend" in last_user_msg:
            # Consultar última señal en DB
            last_sig = db.query(AISignal).filter(AISignal.bot_id == bot_id).order_by(AISignal.ts_utc.desc()).first()
            if last_sig:
                return (
                    f"📊 **Análisis IA**\n"
                    f"- Señal: {last_sig.signal}\n"
                    f"- Sesgo: {last_sig.bias}\n"
                    f"- Confianza: {last_sig.confidence:.2f}\n"
                    f"- Explicación: {last_sig.explain}"
                )
            else:
                return "No tengo suficientes datos para generar una señal de IA todavía."

        if "comando" in last_user_msg or "orden" in last_user_msg:
            # Consultar últimos comandos
            cmds = db.query(CommandEvent).filter(CommandEvent.bot_id == bot_id).order_by(CommandEvent.ts_utc.desc()).limit(3).all()
            if cmds:
                hist = "\n".join([f"- {c.event} ({c.ts_utc.strftime('%H:%M:%S')})" for c in cmds])
                return f"Últimos eventos de comandos:\n{hist}"
            return "No he procesado comandos recientemente."

        if "ayuda" in last_user_msg or "help" in last_user_msg:
            return (
                "Puedo ayudarte con:\n"
                "- 'Estado': Ver conexión y modo.\n"
                "- 'Precio': Ver cotización actual.\n"
                "- 'Señal': Ver análisis de IA.\n"
                "- 'Comandos': Ver historial reciente."
            )

        # Fallback genérico
        return (
            f"Entendido. Estoy monitoreando {bot_state.get('instrument', 'MNQ')} en {price}. "
            "Pregúntame por el 'estado' o la 'señal' actual."
        )

chat_service = ChatService()