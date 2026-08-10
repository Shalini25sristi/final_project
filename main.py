import sys

from memory_leak_detector.app import run_app


def main() -> None:
    if "--web" in sys.argv:
        from memory_leak_detector.web_server import main as web_main

        args = [a for a in sys.argv[1:] if a != "--web"]
        web_main(args)
        return

    if len(sys.argv) > 1:
        print(__doc__ or "usage: python main.py [--web]")

    run_app()


if __name__ == "__main__":
    main()