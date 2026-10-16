"""Import exactly one NFA interpretation URL into the local SQLite RAG."""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.nfa_interpretation import InterpretationImportError, import_interpretation


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("url", help="One direct https://law.nfa.gov.tw/GNFA/FINT/FINTQRY04.aspx?EID=... URL")
    parser.add_argument("--html-file", type=Path, help="Previously saved official page; makes no network request")
    parser.add_argument("--preview", action="store_true", help="Parse and report only; do not write the index")
    args = parser.parse_args()
    try:
        html = args.html_file.read_text(encoding="utf-8") if args.html_file else None
        result = import_interpretation(args.url, html=html, apply=not args.preview)
    except (InterpretationImportError, OSError, UnicodeError) as exc:
        print(json.dumps({"status": "error", "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
