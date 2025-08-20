
import os
import secrets
import base64
from fastapi import FastAPI, Depends, HTTPException, Request, Response, Form
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.templating import Jinja2Templates
from prometheus_client import make_asgi_app, Counter, Histogram, CollectorRegistry
import uvicorn

from src.webapp import routes_articles, routes_duplicates, routes_dlq, routes_api, routes_webauthn
from src.database import init_db

# --- Metrics ---
# Use a dedicated registry to avoid duplicate registration on module reloads (tests)
METRICS_REGISTRY = CollectorRegistry()
REQUEST_COUNT = Counter(
    "web_request_total", "Total requests", ["method", "path", "status_code"], registry=METRICS_REGISTRY
)
REQUEST_LATENCY = Histogram(
    "web_request_latency_seconds", "Request latency", ["method", "path"], registry=METRICS_REGISTRY
)

# --- App Initialization ---
app = FastAPI(
    title="War & Peace DB Web Interface",
    description="A web interface to browse the articles database.",
    version="0.1.0",
    docs_url=None, 
    redoc_url=None,
    openapi_url=None
)

app.mount("/static", StaticFiles(directory="src/webapp/static"), name="static")
templates_login = Jinja2Templates(directory="src/webapp/templates")
# Expose auth mode to templates
templates_login.env.globals["auth_mode"] = os.getenv("WEB_AUTH_MODE", "basic").strip().lower()
# --- Login page route (for WebAuthn mode) ---
@app.get("/login", tags=["Auth"], include_in_schema=False)
def login_page(request: Request):
    return templates_login.TemplateResponse(request, "login.html")

@app.get("/logout", tags=["Auth"], include_in_schema=False)
def logout(request: Request):
    request.session.clear()
    return Response(status_code=303, headers={"Location": "/login"})

@app.get("/register-key", tags=["Auth"], include_in_schema=False)
def register_key_page(request: Request):
    return templates_login.TemplateResponse(request, "register_key.html")

# --- Basic Auth UI (optional nicer flow) ---
@app.get("/basic-login", tags=["Auth"], include_in_schema=False)
def basic_login_page(request: Request):
    return templates_login.TemplateResponse(request, "basic_login.html")

@app.post("/basic-login", tags=["Auth"], include_in_schema=False)
async def basic_login_submit(request: Request, username: str = Form(...), password: str = Form(...)):
    env_user = os.environ.get("WEB_BASIC_AUTH_USER", "")
    env_pass = os.environ.get("WEB_BASIC_AUTH_PASSWORD", "")
    if secrets.compare_digest(username, env_user) and secrets.compare_digest(password, env_pass):
        request.session["admin"] = True
        return Response(status_code=303, headers={"Location": "/"})
    # invalid credentials -> show form with error
    return templates_login.TemplateResponse(request, "basic_login.html", {"error": "Неверные логин или пароль"})


# --- Sessions ---
# Enable session middleware for future WebAuthn-based admin auth
_session_secret = os.getenv("WEB_SESSION_SECRET", "dev-session-secret-change-me")
app.add_middleware(
    SessionMiddleware,
    secret_key=_session_secret,
    session_cookie="wp_session",
    same_site="strict",
    https_only=False,  # set True behind TLS in production
)

# --- Security ---
security = HTTPBasic()

def basic_auth_dependency(credentials: HTTPBasicCredentials = Depends(security)):
    """Dependency to check Basic Auth credentials."""
    correct_user = os.environ.get("WEB_BASIC_AUTH_USER", "")
    correct_pass = os.environ.get("WEB_BASIC_AUTH_PASSWORD", "")
    
    is_user_correct = secrets.compare_digest(credentials.username, correct_user)
    is_pass_correct = secrets.compare_digest(credentials.password, correct_pass)
    
    if not (is_user_correct and is_pass_correct):
        raise HTTPException(
            status_code=401,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Basic"},
        )
    return credentials.username

# --- Routers ---
auth_user = os.environ.get("WEB_BASIC_AUTH_USER")
auth_pass = os.environ.get("WEB_BASIC_AUTH_PASSWORD")
auth_dependency = [Depends(basic_auth_dependency)]

if os.getenv("WEB_AUTH_MODE", "basic").strip().lower() == "basic" and auth_user and auth_pass:
    app.include_router(routes_articles.router, tags=["Frontend"], dependencies=auth_dependency)
    app.include_router(routes_duplicates.router, tags=["Frontend"], dependencies=auth_dependency)
    app.include_router(routes_dlq.router, tags=["Frontend"], dependencies=auth_dependency)
    if os.getenv("WEB_API_ENABLED", "false").lower() == "true":
        app.include_router(routes_api.router, tags=["API"], dependencies=auth_dependency)
    # WebAuthn endpoints remain public for login/registration flows
    app.include_router(routes_webauthn.router, tags=["Auth"]) 
else:
    app.include_router(routes_articles.router, tags=["Frontend"])
    app.include_router(routes_duplicates.router, tags=["Frontend"])
    app.include_router(routes_dlq.router, tags=["Frontend"])
    if os.getenv("WEB_API_ENABLED", "false").lower() == "true":
        app.include_router(routes_api.router, tags=["API"])
    app.include_router(routes_webauthn.router, tags=["Auth"]) 


# --- Public Endpoints ---
@app.get("/healthz", tags=["Monitoring"])
def health_check():
    """Health check endpoint."""
    return {"status": "ok"}

# Mount metrics app publicly (use the same dedicated registry)
metrics_app = make_asgi_app(registry=METRICS_REGISTRY)
app.mount("/metrics", metrics_app)

# --- Middlewares ---
@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    """Enforce either API key, WebAuthn session or Basic Auth.
    Allows public access to /healthz, /metrics, /static, /favicon.ico, /webauthn, /login.
    """
    public_prefixes = ("/healthz", "/metrics", "/static", "/favicon.ico", "/webauthn", "/login", "/register-key", "/basic-login")
    path = request.url.path

    # Skip auth for public endpoints
    if path.startswith(public_prefixes):
        return await call_next(request)

    # API key enforcement for /api when configured
    # If WEB_API_KEY is set and API is enabled, require X-API-Key or Authorization: Api-Key <key>
    if path.startswith("/api") and os.getenv("WEB_API_ENABLED", "false").lower() == "true":
        expected_key = os.environ.get("WEB_API_KEY")
        if expected_key:
            auth_header = request.headers.get("Authorization")
            x_api_key = request.headers.get("X-API-Key")
            provided_key = None
            if x_api_key:
                provided_key = x_api_key.strip()
            elif auth_header and auth_header.startswith("Api-Key "):
                provided_key = auth_header.split(" ", 1)[1].strip()

            if not provided_key or not secrets.compare_digest(provided_key, expected_key):
                return Response(status_code=401)

            # Valid API key: proceed without Basic Auth
            return await call_next(request)

    env_user = os.environ.get("WEB_BASIC_AUTH_USER")
    env_pass = os.environ.get("WEB_BASIC_AUTH_PASSWORD")

    # Determine WebAuthn enforcement state once per request
    mode = os.getenv("WEB_AUTH_MODE", "basic").strip().lower()
    webauthn_enforce = os.getenv("WEB_WEBAUTHN_ENFORCE", "false").lower() == "true"
    webauthn_enabled = (mode == "webauthn") and webauthn_enforce

    # If session already marked admin (from UI login), let request pass
    session_data = request.scope.get("session")
    if isinstance(session_data, dict) and session_data.get("admin"):
        return await call_next(request)

    # If basic credentials configured and WebAuthn is NOT enforced, require Basic Auth
    if env_user and env_pass and not webauthn_enabled:
        auth_header = request.headers.get("Authorization")
        if not auth_header or not auth_header.startswith("Basic "):
            # If user used UI login but header missing, redirect to UI login
            return Response(status_code=401, headers={"WWW-Authenticate": "Basic"})
        try:
            raw = base64.b64decode(auth_header.split(" ", 1)[1]).decode("utf-8")
            username, password = raw.split(":", 1)
        except Exception:
            return Response(status_code=401, headers={"WWW-Authenticate": "Basic"})

        if not (secrets.compare_digest(username, env_user) and secrets.compare_digest(password, env_pass)):
            return Response(status_code=401, headers={"WWW-Authenticate": "Basic"})
    if webauthn_enabled:
        # API enforcement handled above; here protect the rest of the app except public
        # Be defensive in case SessionMiddleware is not present yet (e.g., during tests or misconfiguration)
        session_data = request.scope.get("session")
        is_admin = False
        if isinstance(session_data, dict):
            is_admin = bool(session_data.get("admin"))
        # No session or not admin -> redirect to login
        if not is_admin:
            return Response(status_code=303, headers={"Location": "/login"})


    return await call_next(request)
@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["Content-Security-Policy"] = "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Permissions-Policy"] = "geolocation=()"
    return response

@app.middleware("http")
async def add_process_time_header(request: Request, call_next):
    """Middleware to add metrics for each request."""
    with REQUEST_LATENCY.labels(request.method, request.url.path).time():
        response = await call_next(request)
        REQUEST_COUNT.labels(request.method, request.url.path, response.status_code).inc()
    return response

# --- Startup ---
@app.on_event("startup")
async def _startup_init_db():
    # Ensure SQLite schema (including webauthn_credential) exists for web app
    try:
        init_db()
    except Exception:
        # Avoid crashing on startup; errors will surface in endpoints/logs
        pass

# --- Main Entry Point ---
if __name__ == "__main__":
    if os.getenv("WEB_ENABLED", "false").lower() == "true":
        uvicorn.run(
            app,
            host=os.getenv("WEB_HOST", "0.0.0.0"),
            port=int(os.getenv("WEB_PORT", "8080")),
        )
