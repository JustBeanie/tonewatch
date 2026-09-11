"""Multipart WAV analysis route."""

import tempfile
import wave
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile

from tonewatch.api.analyze import analyze_wav
from tonewatch.api.deps import authenticated

router = APIRouter(prefix="/api", tags=["analyze"])
MAX_FILE_BYTES = 20 * 1024 * 1024


@router.post("/analyze", dependencies=[Depends(authenticated)])
async def analyze(request: Request, file: UploadFile = File(...)) -> dict[str, Any]:
    temporary: Path | None = None
    size = 0
    try:
        with tempfile.NamedTemporaryFile(
            dir=request.app.state.settings.data_dir, suffix=".wav", delete=False
        ) as handle:
            temporary = Path(handle.name)
            while chunk := await file.read(1024 * 1024):
                size += len(chunk)
                if size > MAX_FILE_BYTES:
                    raise HTTPException(413, "upload too large")
                handle.write(chunk)
        try:
            with wave.open(str(temporary), "rb") as wav:
                if wav.getnframes() / wav.getframerate() > 600:
                    raise HTTPException(413, "audio too long")
        except HTTPException:
            raise
        except (wave.Error, EOFError, ZeroDivisionError):
            raise HTTPException(415, "expected RIFF/WAVE audio") from None
        return analyze_wav(temporary, request.app.state.config)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
