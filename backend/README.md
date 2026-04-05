# Backend Layout

`backend/app` is now organized by responsibility:

- `main.py`: FastAPI app wiring + route handlers
- `core/config.py`: environment and path configuration
- `api/schemas.py`: Pydantic request models
- `services/dataset.py`: YOLO dataset/export and bbox helpers
- `services/state.py`: training/upload runtime state
- `services/file_utils.py`: filename/hash helpers
- `pipeline/`: plate recognition pipeline modules

This keeps shared logic out of route handlers and makes future route extraction into `routers/` straightforward.
