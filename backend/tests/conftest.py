import os
import tempfile

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from fastapi.testclient import TestClient

_tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_tmp.close()
os.environ["DATABASE_URL"] = "sqlite:///" + _tmp.name
os.environ["REDIS_URL"] = "redis://localhost:6379/0"
os.environ["SEED_DEMO"] = "false"

from src.config.database import Base, get_db  # noqa: E402
from src.main import app  # noqa: E402
from src.models.user import User  # noqa: E402
from src.utils.security import hash_password  # noqa: E402

engine = create_engine(
 os.environ["DATABASE_URL"],
 connect_args={"check_same_thread": False, "timeout": 30},
)
TestSession = sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)
Base.metadata.create_all(engine)


def _get_test_db():
 with TestSession() as db:
  yield db


app.dependency_overrides[get_db] = _get_test_db


from sqlalchemy import text as _text  # noqa: E402

RESET_TABLES = ["pairing_batches", "pairing_previews", "samples",
                "acquisition_batches", "datasets", "runs", "studies",
                "reports", "reviews", "instruments", "audits"]


@pytest.fixture
def db():
 # 仅清空本功能相关表，保留账号基线数据，保证用例相互隔离
 with engine.begin() as conn:
  for name in RESET_TABLES:
   conn.execute(_text(f'DELETE FROM "{name}"'))
 with TestSession() as session:
  yield session


@pytest.fixture(scope="session")
def client():
 with TestSession() as db:
  for role in ("admin", "analyst", "viewer"):
   db.add(User(id="user-" + role, email=role + "@probe.demo", role=role,
               password_hash=hash_password("ProbeDemo2026!")))
  db.commit()
 with TestClient(app) as c:
  yield c


def auth_headers(client, role):
 resp = client.post("/auth/login",
                    json={"email": role + "@probe.demo", "password": "ProbeDemo2026!"})
 assert resp.status_code == 200
 return {"Authorization": "Bearer " + resp.json()["token"]}


@pytest.fixture
def admin_headers(client):
 return auth_headers(client, "admin")


@pytest.fixture
def analyst_headers(client):
 return auth_headers(client, "analyst")


@pytest.fixture
def viewer_headers(client):
 return auth_headers(client, "viewer")
