import logging
import time

from app.core.config import settings
from app.core.rag_engine import get_engine


logger = logging.getLogger(__name__)


def run_forever() -> None:
    engine = get_engine()
    logger.info("index worker started")
    while True:
        result = engine.process_next_index_job()
        if result is None:
            time.sleep(settings.INDEX_JOB_POLL_SECONDS)
            continue
        logger.info(
            "index job processed: job_id=%s doc_id=%s status=%s",
            result.get("job_id"),
            result.get("doc_id"),
            result.get("status"),
        )


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run_forever()
