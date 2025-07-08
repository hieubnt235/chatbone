import os
os.environ["CHATBONE_LOG_LEVEL"] = "INFO"
import argparse
import sys

from datastore.cli_parser import config_parser as config_datastore_parser
from auth.cli_parser import config_parser as config_auth_parser
from chatbone_apps.cli.build import config_parser as config_build_parser
from utilities import logger
logger.debug("This is main from chatbone root.")

def main():

    chatbone_parser = argparse.ArgumentParser(
        prog="chatbone",
        description="A command-line tool for managing chatbone app.",
        epilog="For more help, run 'chatbone <command> --help'",
    )
    chatbone_subparser = chatbone_parser.add_subparsers(
        dest="chatbone command", required=True
    )
    build_parser = chatbone_subparser.add_parser("build")
    config_build_parser(build_parser)
    
    auth_parser = chatbone_subparser.add_parser("auth")
    config_auth_parser(auth_parser)
    
    datastore_parser = chatbone_subparser.add_parser("datastore")
    config_datastore_parser(datastore_parser)
    
    try:
        args = chatbone_parser.parse_args()
        args.func(args)
        
    except argparse.ArgumentError as e:
        print(f"Error: {e}")
        chatbone_parser.print_help()
        sys.exit(2)


if __name__ == "__main__":
    main()
