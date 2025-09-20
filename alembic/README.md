Alembic migrations directory.

Usage:
- Ensure DATABASE_URL is set.
- Create initial migration from current models:
  alembic revision --autogenerate -m "initial"
- Apply:
  alembic upgrade head