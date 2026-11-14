from ..services import acquisition_service as service


def list_groups(db):
 return service.list_groups(db)


def list_batches(db):
 return service.list_batches(db)


def detail(db, code):
 return service.detail(db, code)


def ingest(db, body):
 return service.ingest(db, body)


def preview(db, code, body):
 return service.compute_preview(db, code, body.max_time_diff)


def get_preview(db, code):
 return service.get_preview(db, code)


def publish(db, code, body):
 return service.publish(db, code, body)


def list_pairings(db):
 return service.list_pairings(db)


def get_pairing(db, pairing_id):
 return service.get_pairing(db, pairing_id)
