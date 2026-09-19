from fastapi import FastAPI
from app.routes.analyze import router as analyze_router

app = FastAPI(
    title="Anchor API",
    description="Backend API for Anchor",
    version="0.1.0"
)


@app.get("/")
def root():
    return {
        "name": "Anchor API",
        "status": "running"
    }


@app.get("/health")
def health():
    return {
        "status": "ok"
    }


app.include_router(analyze_router)