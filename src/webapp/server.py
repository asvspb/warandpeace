
import os
import secrets
import base64
from fastapi import FastAPI, Depends, HTTPException, Request, Response
from fastapi.staticfiles import StaticFiles
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from prometheus_client import make_asgi_app, Counter, Histogram
import uvicorn

from src.webapp import routes_articles, routes_duplicates, routes_dlq, routes_api

# --- Metrics ---
REQUEST_COUNT = Counter("web_request_total", "Total requests", ["method", "path", "status_code"])
REQUEST_LATENCY = Histogram("web_request_latency_seconds", "Request latency", ["method", "path"])

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

if auth_user and auth_pass:
    app.include_router(routes_articles.router, tags=["Frontend"], dependencies=auth_dependency)
    app.include_router(routes_duplicates.router, tags=["Frontend"], dependencies=auth_dependency)
    app.include_router(routes_dlq.router, tags=["Frontend"], dependencies=auth_dependency)
    if os.getenv("WEB_API_ENABLED", "false").lower() == "true":
        app.include_router(routes_api.router, tags=["API"], dependencies=auth_dependency)
else:
    app.include_router(routes_articles.router, tags=["Frontend"])
    app.include_router(routes_duplicates.router, tags=["Frontend"])
    app.include_router(routes_dlq.router, tags=["Frontend"])
    if os.getenv("WEB_API_ENABLED", "false").lower() == "true":
        app.include_router(routes_api.router, tags=["API"])


# --- Public Endpoints ---
@app.get("/healthz", tags=["Monitoring"])
def health_check():
    """Health check endpoint."""
    return {"status": "ok"}

# Mount metrics app publicly
metrics_app = make_asgi_app()
app.mount("/metrics", metrics_app)

# --- Middlewares ---
@app.middleware("http")
async def basic_auth_middleware(request: Request, call_next):
    """Enforce Basic Auth at request time when credentials are set via env.
    Allows public access to /healthz, /metrics, /static, /favicon.ico.
    """
    public_prefixes = ("/healthz", "/metrics", "/static", "/favicon.ico")
    path = request.url.path

    # Skip auth for public endpoints
    if path.startswith(public_prefixes):
        return await call_next(request)

    env_user = os.environ.get("WEB_BASIC_AUTH_USER")
    env_pass = os.environ.get("WEB_BASIC_AUTH_PASSWORD")

    # If credentials are configured, require Authorization header
    if env_user and env_pass:
        auth_header = request.headers.get("Authorization")
        if not auth_header or not auth_header.startswith("Basic "):
            return Response(status_code=401, headers={"WWW-Authenticate": "Basic"})
        try:
            raw = base64.b64decode(auth_header.split(" ", 1)[1]).decode("utf-8")
            username, password = raw.split(":", 1)
        except Exception:
            return Response(status_code=401, headers={"WWW-Authenticate": "Basic"})

        if not (secrets.compare_digest(username, env_user) and secrets.compare_digest(password, env_pass)):
            return Response(status_code=401, headers={"WWW-Authenticate": "Basic"})

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

# --- Main Entry Point ---
if __name__ == "__main__":
    if os.getenv("WEB_ENABLED", "false").lower() == "true":
        uvicorn.run(
            app,
            host=os.getenv("WEB_HOST", "0.0.0.0"),
            port=int(os.getenv("WEB_PORT", "8080")),
        )
