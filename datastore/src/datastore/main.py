import argparse
import sys

from datastore.cli_parser import config_parser
from utilities import logger
logger.debug(f"This is main from datastore")

def main():
    parser = argparse.ArgumentParser(
        prog="datastore",
        description="A command-line tool for managing a datastore.",
        epilog="For more help, run 'datastore <command> --help'",
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
