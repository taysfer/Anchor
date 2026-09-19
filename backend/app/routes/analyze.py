from fastapi import APIRouter
from app.models.schemas import AnalyzeRequest, AnalyzeResponse
from app.services.alignment import calculate_alignment
from app.sessions.manager import add_page_to_session

# Router for webpage analysis requests
router = APIRouter()

# Receives the user's intention and current webpage information, then calculates how closely the page aligns with that intention
@router.post("/analyze", response_model=AnalyzeResponse)
def analyze_page(request: AnalyzeRequest):

    # Compare the user's intention with the current webpage
    score = calculate_alignment(
        request.intention,
        request.url,
        request.title,
        request.content
    )

    # Add pages to the session so the extension can display a history of analyzed pages
    add_page_to_session(
    request.session_id,
    request.intention,
    request.url,
    request.title,
    score
)
    
    # Return the semantic similarity score to the extension
    return AnalyzeResponse(
        alignment=score,
        state="analyzed",
        reason="Alignment calculated using semantic similarity."
    )