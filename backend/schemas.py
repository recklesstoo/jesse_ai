from pydantic import BaseModel, ConfigDict, Field
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
    n_estimators: Optional[int] = 100
    max_depth: Optional[int] = 5
    test_size: Optional[float] = 0.2

class RestoreRequest(BaseModel):
    botId: str
    folder: str
    filename: str

class AISignalOut(BaseModel):
    ok: bool = True
    signal: str
    bias: str
    confidence: float
    explain: str
    updatedAt: Optional[str]
    barTs: Optional[str]

class WyckoffConfigIn(BaseModel):
    botId: Optional[str] = None
    model_config = ConfigDict(extra="allow")

class AutoConfigIn(BaseModel):
    botId: Optional[str] = None
    model_config = ConfigDict(extra="allow")
