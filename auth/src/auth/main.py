import argparse
import sys

from auth.cli_parser import config_parser
from utilities import logger

logger.debug("This is main from auth app.")
def main():
    parser = argparse.ArgumentParser(
        prog="auth",
        description="A command-line tool for managing auth app.",
        epilog="For more help, run 'auth <command> --help'",
    )
    
    config_parser(parser)
    try:
        args = parser.parse_args()
        args.func(args)
    except argparse.ArgumentError as e:
        print(f"Error: {e}")
        parser.print_help()
        sys.exit(2)

if __name__ == "__main__":
    main()
