"""Run the designer:  python -m legohouse [design.json]
Or the site plan:    python -m legohouse layout [designs_dir] [layout.json]
"""

import sys

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "layout":
        from .layout import main
        sys.exit(main(sys.argv[2:]))
    from .app import main
    sys.exit(main())
