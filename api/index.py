from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import Optional, Dict, Any
import os
import sys
from pathlib import Path

# Add project root to path for imports
project_root = Path(__file__).parent.parent.absolute()
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from agents.workflow.orchestrator import run_modernization_workflow

from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(
    title="Air-Gapped C++ Modernization Engine API",
    description="API for transforming legacy C++ into modern C++17.",
    version="0.1.0",
    root_path="/api"
)

# Enable CORS for frontend communication
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)



class ModernizationRequest(BaseModel):
    code: str
    source_file: Optional[str] = "input.cpp"
    output_path: Optional[str] = None

@app.get("/")
async def root():
    return {
        "status": "online",
        "engine": "Modernization Engine API",
        "endpoints": {
            "modernize": "/modernize (POST)",
            "health": "/health (GET)"
        }
    }

@app.get("/health")
async def health():
    return {"status": "healthy"}

from agents.workflow.orchestrator import run_modernization_workflow, run_lite_modernization

# ... (inside modernize function)
@app.post("/modernize")
async def modernize(request: ModernizationRequest):
    """
    Triggers the modernization workflow for the provided C++ code.
    """
    try:
        # For Vercel Hobby, we use Lite mode to avoid 10s timeout
        # If the user wants full power, they should run locally or on a Pro plan
        result = run_lite_modernization(
            code=request.code,
            source_file=request.source_file or "api_input.cpp"
        )
        
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

