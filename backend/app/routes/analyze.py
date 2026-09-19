from fastapi import APIRouter
from app.models.schemas import AnalyzeRequest, AnalyzeResponse

router = APIRouter()


@router.post("/analyze", response_model=AnalyzeResponse)
def analyze_page(request: AnalyzeRequest):

    # Temporary fake result
    # Actual AI analysis will replace this later
    return AnalyzeResponse(
        alignment=0.85,
        state="aligned",
        reason="Placeholder analysis"
    )