from fastapi import FastAPI

app = FastAPI(title="Nim AI Arena")


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
