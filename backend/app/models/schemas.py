from pydantic import BaseModel

# Defines the data the extension sends to the backend
# when it wants a webpage analyzed
class AnalyzeRequest(BaseModel):
    session_id: str
    intention: str
    url: str
    title: str
    content: str

# Defines the data returned after a webpage is analyzed
class AnalyzeResponse(BaseModel):
    alignment: float
    state: str
    reason: str