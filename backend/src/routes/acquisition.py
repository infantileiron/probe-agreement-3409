from fastapi import APIRouter, Depends
from ..config.database import get_db
from ..utils.auth import current, write_user
from ..schemas.acquisition import IngestRequest, PreviewRequest, PublishRequest
from ..controllers import acquisition_controller as controller

router = APIRouter(prefix="/acquisition", tags=["acquisition"])


@router.get("/batches")
def groups(db=Depends(get_db), user=Depends(current)):
 return controller.list_groups(db)


@router.get("/batches/flat")
def flat(db=Depends(get_db), user=Depends(current)):
 return controller.list_batches(db)


@router.get("/batches/{code}")
def detail(code: str, db=Depends(get_db), user=Depends(current)):
 return controller.detail(db, code)


@router.post("/ingest", status_code=201)
def ingest(body: IngestRequest, db=Depends(get_db), user=Depends(write_user)):
 return controller.ingest(db, body)


@router.post("/batches/{code}/preview")
def preview(code: str, body: PreviewRequest, db=Depends(get_db), user=Depends(write_user)):
 return controller.preview(db, code, body)


@router.get("/batches/{code}/preview")
def get_preview(code: str, db=Depends(get_db), user=Depends(current)):
 return controller.get_preview(db, code)


@router.post("/batches/{code}/publish")
def publish(code: str, body: PublishRequest, db=Depends(get_db), user=Depends(write_user)):
 return controller.publish(db, code, body)


@router.get("/pairings")
def pairings(db=Depends(get_db), user=Depends(current)):
 return controller.list_pairings(db)


@router.get("/pairings/{pairing_id}")
def pairing(pairing_id: str, db=Depends(get_db), user=Depends(current)):
 return controller.get_pairing(db, pairing_id)
