"""Authentication route registration boundary."""

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.get("/status")
async def status(request: Request) -> dict[str, bool | str]:
    """Report whether the browser may enter without submitting a password."""
    via = "none"
    if request.app.state.auth.ingress_valid(request):
        via = "ingress"
    elif request.app.state.auth.session_valid(request) is not None:
        via = "session"
    elif request.headers.get("authorization", "")[7:].strip() == request.app.state.auth.token:
        via = "bearer"
    return {
        "authenticated": via != "none",
        "password_required": request.app.state.auth.password_hash is not None,
        "via": via,
    }


def _write_auth(request: Request) -> None:
    request.app.state.auth.authorize(request, state_changing=True)


@router.post("/login")
async def login(request: Request) -> JSONResponse:
    body = await request.json()
    password = body.get("password") if isinstance(body, dict) else None
    if not isinstance(password, str):
        raise HTTPException(422, "password is required")
    ip = request.client.host if request.client else "unknown"
    sid, csrf = request.app.state.auth.check_login(ip, password)
    response = JSONResponse({"csrf_token": csrf})
    secure = request.url.scheme == "https"
    response.set_cookie(
        "tonewatch_session", sid, httponly=True, samesite="strict", secure=secure, max_age=43200
    )
    response.set_cookie(
        "tonewatch_csrf", csrf, httponly=False, samesite="strict", secure=secure, max_age=43200
    )
    return response


@router.post("/logout", dependencies=[Depends(_write_auth)])
async def logout(request: Request) -> JSONResponse:
    request.app.state.auth.sessions.pop(request.cookies.get("tonewatch_session", ""), None)
    response = JSONResponse({"ok": True})
    response.delete_cookie("tonewatch_session")
    response.delete_cookie("tonewatch_csrf")
    return response
