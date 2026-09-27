.PHONY: install dev api web build test run reset-demo
install:
	pip install -r backend/requirements-dev.txt
	cd frontend && npm ci
api:
	cd backend && uvicorn app.main:app --reload --port 8000
web:
	cd frontend && npm run dev
build:
	cd frontend && npm run build
test:
	cd backend && python -m pytest -q
run: build
	cd backend && uvicorn app.main:app --port 8000
# Deletes backend/var (demo database, trained models, audit log, signing key) so the demo data is regenerated.
reset-demo:
	rm -rf backend/var
