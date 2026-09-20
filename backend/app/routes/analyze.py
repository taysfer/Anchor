from fastapi import APIRouter

from app.models.schemas import AnalyzeRequest, AnalyzeResponse
from app.services.alignment import calculate_alignment
from app.sessions.manager import add_page_to_session, get_alignment_scores
from app.services.drift import detect_drift

# Router for webpage analysis requests
router = APIRouter()

# Receives the user's intention and current webpage information, then calculates how closely the page aligns with that intention
@router.post("/analyze", response_model=AnalyzeResponse)
def analyze_page(request: AnalyzeRequest):

    # Calculate how closely the current page matches
    # the user's original intention
    score = calculate_alignment(
        request.intention,
        request.url,
        request.title,
        request.content
    )

    # Store the current page and its alignment score
    # in the user's browsing session
    add_page_to_session(
        request.session_id,
        request.intention,
        request.url,
        request.title,
        score
    )

    # Get all alignment scores collected during this session
    scores = get_alignment_scores(request.session_id)

    # Check whether the recent browsing pattern
    # suggests sustained drift from the intention
    drifting = detect_drift(scores)

    # Return a different state depending on whether
    # drift was detected
    if drifting:
        state = "drifting"
        intervention = True
        reason = "Recent browsing has moved away from your original intention."
    else:
        state = "aligned"
        intervention = False
        reason = "No sustained drift detected."

    return AnalyzeResponse(
        alignment=score,
        state=state,
        intervention=intervention,
        reason=reason
    )

