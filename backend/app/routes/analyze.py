from fastapi import APIRouter
from app.models.schemas import AnalyzeRequest, AnalyzeResponse
from app.services.alignment import calculate_alignment

router = APIRouter()


@router.post("/analyze", response_model=AnalyzeResponse)
def analyze_page(request: AnalyzeRequest):

    score = calculate_alignment(
    request.intention,
    request.url,
    request.title,
    request.content
    )

    return AnalyzeResponse(
        alignment=score,
        state="analyzed",
        reason="Alignment calculated using semantic similarity."
    )