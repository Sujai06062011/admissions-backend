from fastapi import FastAPI

from app.applications.router import router as applications_router

app = FastAPI()
app.include_router(applications_router)


@app.get("/health")
def health():
    return {"status": "ok"}
