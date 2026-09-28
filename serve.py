"""Single-process production entrypoint; keep the status updater alive."""
import os
from threading import Thread
from waitress import serve
from app import app, db, background_updater, ensure_primary_node

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
        ensure_primary_node()
    Thread(target=background_updater, daemon=True).start()
    serve(app, host=os.environ.get('BEENY_BIND', '127.0.0.1'),
          port=int(os.environ.get('BEENY_PORT', '8080')), threads=8)
