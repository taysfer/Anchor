from pydantic import BaseModel


class AnalyzeRequest(BaseModel):
    intention: str
    url: str
    title: str
    content: str


class AnalyzeResponse(BaseModel):
    alignment: float
    state: str
    reason: str