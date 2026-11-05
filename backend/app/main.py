from fastapi import FastAPI

app = FastAPI(title="Bank AI Agent API")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
