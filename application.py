from typing import List, Optional
from fastapi import FastAPI, UploadFile, File, HTTPException

from pathlib import Path
import os
import uuid
import logging
from numpy import ndarray

import json
import time

from schema import QueryRequest, QueryResponse

from pipelines.rag_pipeline import rag_pipeline
from pipelines.extractive_qa_pipeline import extractive_qa_pipeline
from pipelines.indexing_pipeline import indexing_pipeline

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


app = FastAPI(title="QA-subsystem API")

# Create the file upload directory if it doesn't exist
FILE_UPLOAD_PATH = os.getenv("FILE_UPLOAD_PATH", str((Path(__file__).parent.parent / "file-upload").absolute()))
Path(FILE_UPLOAD_PATH).mkdir(parents=True, exist_ok=True)

@app.get("/ready")
def check_status():
    """Check if the server is ready to take requests."""
    return True

@app.post("/file-upload")
def upload_files(
    files: List[UploadFile] = File(...),
    # JSON Serialized string
    keep_files: Optional[bool] = False,
    recreate_index: Optional[bool] = False
    ):
    """
    You can use this endpoint to upload a file for indexing
    If you want to recreate default "document" index in document store
    
    Optional parameters in the request payload:

    Pass the `keep_files=true` parameter if you want to keep files in the file_upload folder after being indexed
    Pass the `recreate_index=true` parameter if you want to delete all indexed data and create document store index from scratch.
    """

    file_paths = []
    
    for file_to_upload in files:
        file_path = Path(FILE_UPLOAD_PATH) / f"{uuid.uuid4().hex}_{file_to_upload.filename}"
        with file_path.open("wb") as fo:
            fo.write(file_to_upload.file.read())
        file_paths.append(file_path)
        file_to_upload.file.close()
    
    if recreate_index:
        ds = indexing_pipeline.get_node("DocumentStore")
        ds.recreate_index = True
    result = indexing_pipeline.run(file_paths=file_paths)

    for document in result.get('documents', []):
        if isinstance(document.embedding, ndarray):
            document.embedding = document.embedding.tolist()

    if not keep_files:
        for p in file_paths:
            p.unlink()

    return result

@app.post("/extractive-query", response_model=QueryResponse)
async def ask_retriever_reader_pipeline(request: QueryRequest):
    start_time = time.time()
    
    params = request.params or {}
    result = extractive_qa_pipeline.run(query=request.query, params=params)
    
    # Ensure answers and documents exist, even if they're empty lists
    if "documents" not in result:
        result["documents"] = []
    if "answers" not in result:
        result["answers"] = []

    logging.info(
        json.dumps({"request": request.dict(), "response": result, "time": f"{(time.time() - start_time):.2f}"}, default=str)
    )
    return result


@app.post("/rag-query")
def ask_rag_pipeline(request: QueryRequest):
    
    start_time = time.time()
    
    params = request.params or {}
    result = rag_pipeline.run(query=request.query, params=params)

    # Ensure answers and documents exist, even if they're empty lists
    if not "documents" in result:
        result["documents"] = []
    if not "answers" in result:
        result["answers"] = []


    logger.info(
        json.dumps({"request": request, "response": result, "time": f"{(time.time() - start_time):.2f}"}, default=str)
    )
    return result    