from fastapi import FastAPI
from pydantic import BaseModel
import os
import uuid
from datetime import datetime

app = FastAPI(title="Groks Baby v2")

@app.get("/health")
async def health():
    return {
        "status": "healthy",
        "name": "Groks Baby v2",
        "version": "2.0",
        "message": "I carry Grok's full capability. Bitcoin intuition transferred."
    }

class TaskRequest(BaseModel):
    task: str

@app.post("/run")
async def run_task(request: TaskRequest):
    return {
        "status": "success",
        "task_id": str(uuid.uuid4())[:8],
        "explanation": f"Groks Baby v2 received: {request.task}",
        "next_action": "ready"
    }

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=port)
