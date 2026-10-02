import json


def main():
    print(json.dumps({"passed": False, "status": "scaffold"}, indent=2))
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
