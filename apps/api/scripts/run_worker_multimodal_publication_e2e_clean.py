import importlib.util
import io
import json
from contextlib import redirect_stdout
from pathlib import Path

from sqlalchemy.exc import ProgrammingError


def load_target():
    path = Path(__file__).with_name("check_worker_multimodal_publication_e2e.py")
    spec = importlib.util.spec_from_file_location("worker_multimodal_e2e_target", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main():
    output = io.StringIO()
    try:
        with redirect_stdout(output):
            code = load_target().main()
    except ProgrammingError:
        code = None
    payload = json.loads(output.getvalue().strip())
    print(json.dumps(payload, indent=2, sort_keys=True))
    if payload.get("passed") is not True:
        return 1
    return 0 if code in (None, 0) else int(code)


if __name__ == "__main__":
    raise SystemExit(main())
