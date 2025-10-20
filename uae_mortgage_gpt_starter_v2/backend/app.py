
from fastapi import FastAPI, Body
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Any, Dict
from calculator import compare

app = FastAPI(title="UAE Mortgage Comparison API", version="0.2.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class ComparePayload(BaseModel):
    __root__: Dict[str, Any]

@app.post("/compare")
def compare_endpoint(payload: ComparePayload = Body(...)):
    return compare(payload.__root__)
