from fastapi import FastAPI
from app.routes.analyze import router as analyze_router
from app.sessions.manager import get_session

# Main FastAPI application for the DoomEye backend
app = FastAPI(
    title="Anchor API",
    description="Backend API for Anchor",
    version="0.1.0"
)

# Basic endpoint to verify that the API is running
@app.get("/")
def root():
    return {
        "name": "Anchor API",
        "status": "running"
    }

# Health check used to confirm that the backend is available
@app.get("/health")
def health():
    return {
        "status": "ok"
    }

# Endpoint to retrieve the current state of a user's session, including the intention and analyzed pages
@app.get("/sessions/{session_id}")
def session(session_id: str):
    return get_session(session_id)

# Adds the /analyze endpoint to the application
app.include_router(analyze_router)