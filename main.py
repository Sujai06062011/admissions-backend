from fastapi import FastAPI

from app.applications.router import router as applications_router
from app.campus.router import router as campus_router
from app.credentials.router import router as credentials_router
from app.preferences.router import router as preferences_router
from app.questions.router import router as questions_router

app = FastAPI()
app.include_router(applications_router)
app.include_router(preferences_router)
app.include_router(questions_router)
app.include_router(credentials_router)
app.include_router(campus_router)


@app.get("/health")
def health():
    return {"status": "ok"}
