import logging

from app.services.scheduler_daemon import build_scheduler_daemon


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    worker = build_scheduler_daemon()
    worker.install_signal_handlers()
    worker.run_forever()


if __name__ == "__main__":
    main()
