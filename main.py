from fastapi import FastAPI

from app.applications.router import router as applications_router
from app.campus.router import router as campus_router
from app.credentials.router import router as credentials_router
from app.dashboard.router import router as dashboard_router
from app.interview_engine.router import router as interview_engine_router
from app.preferences.router import router as preferences_router
from app.questions.router import router as questions_router
from app.test_engine.router import router as test_engine_router

app = FastAPI()
app.include_router(applications_router)
app.include_router(preferences_router)
app.include_router(questions_router)
app.include_router(credentials_router)
app.include_router(campus_router)
app.include_router(interview_engine_router)
app.include_router(dashboard_router)
app.include_router(test_engine_router)


@app.get("/health")
def health():
    return {"status": "ok"}
