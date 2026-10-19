from app.db import SessionLocal
from app.ingest.seed import seed_all

if __name__ == "__main__":
    with SessionLocal() as session:
        report = seed_all(session)
        print("seed report:", report)
