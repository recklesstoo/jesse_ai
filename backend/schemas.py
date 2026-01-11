from pydantic import BaseModel, Field
from typing import List, Dict, Any, Optional

# Reutilizamos los esquemas existentes del app.py original y añadimos nuevos

class CommandIn(BaseModel):
    action: str
    qty: int = 0
    slTicks: int = 0
    tpTicks: int = 0
    tag: str = "manual"
    symbol: str = "MNQ"

class ChatIn(BaseModel):
    botId: str
    messages: List[Dict[str, str]]

class MLTrainRequest(BaseModel):
    botId: str
    force: bool = False

class AISignalOut(BaseModel):
    signal: str
    bias: str
    confidence: float
    explain: str
    updatedAt: Optional[str]
    barTs: Optional[str]

class WyckoffConfigIn(BaseModel):
    botId: Optional[str] = None
    # Permite campos dinámicos
    class Config:
        extra = "allow"

class AutoConfigIn(BaseModel):
    botId: Optional[str] = None
    class Config:
        extra = "allow"