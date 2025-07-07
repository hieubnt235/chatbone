import os
from argparse import ArgumentParser
from pathlib import Path

from alembic import command
from alembic.config import Config
from dotenv import find_dotenv, load_dotenv

from utilities.func import utc_now
from utilities.logger import logger


def run_setup(args):
    """
    Runs Alembic migrations programmatically.
    """
    if env_file := find_dotenv(".env.datastore"):
        load_dotenv(env_file)
        script_location = (
            os.getenv("MIGRATION_DIR")
            or (Path(env_file).parent / "migrations").as_posix()
        )
    else:
        script_location = os.environ["MIGRATION_DIR"]

    message = args.message
    upgrade_only = args.upgrade_only
    upgrade_head = not args.no_upgrade
    ini_section = "datastore_db"  # the tag in alembic,ini, args.ini_section always datastore_db for now.

    alembic_ini_path = Path(script_location) / "alembic.ini"  # args.config
    version_locations = Path(script_location) / f"{ini_section}_version"

    logger.info(
        f"\nRunning setup datastore:\n"
        # f"Config file: '{alembic_ini_path}'.\n"
        # f"Scripts location: '{script_location}'.\n"
        # f"Main option name: '{ini_section}'.\n"
        f"Only upgrade: {upgrade_only}\n"
        f"Will Upgrade head: {upgrade_head}",
    )

    config = Config(alembic_ini_path.as_posix(), ini_section=ini_section)
    config.set_main_option("script_location", script_location)
    config.set_main_option("version_locations", version_locations.as_posix())

    # If both upgrade_head and upgrade_only is set, ignore upgrade_head.
    if upgrade_only:
        logger.info("Running 'alembic upgrade head'...")
        command.upgrade(config, "head")
        logger.info("Complete Upgrade.")
    else:
        logger.info("Running 'alembic revision --autogenerate=True'...")
        command.revision(config, autogenerate=True, message=message)
        logger.info("Complete Revision.")
        if upgrade_head:
            logger.info("Running 'alembic upgrade head'...")
            command.upgrade(config, "head")
            logger.info("Complete Upgrade.")


def run_app(args):
    host = args.host
    port = args.port
    workers = args.workers

    import uvicorn
    from datastore.app import app

    uvicorn.run(app, host=host, port=port, workers=workers)


def config_parser(parser_or_subparser):
    if  isinstance(parser_or_subparser, ArgumentParser):
        datastore_parser = parser_or_subparser
    else:
        datastore_parser: ArgumentParser = parser_or_subparser.add_parser(
            "datastore",
            help="Commands for managing the datastore.",
            description="A tool to set up and run the datastore service.",
        )

    datastore_subparsers = datastore_parser.add_subparsers(
        dest="datastore_command", required=True, help="Available datastore subcommands"
    )

    # ---setup command---
    parser_setup = datastore_subparsers.add_parser(
        "setup", help="Configure and initialize the datastore environment."
    )

    parser_setup.add_argument(
        "-m",
        "--message",
        default=f"Upgrade at {utc_now()}",
        help="Message for the revision.",
    )
    parser_setup.add_argument(
        "--no-upgrade",
        action="store_true",
        help="Disable run 'alembic upgrade head' after creating a revision. If both upgrade_head and upgrade_only is set, ignore upgrade_head.",
    )
    parser_setup.add_argument(
        "--upgrade-only",
        action="store_true",
        help="Run only 'alembic upgrade head', without creating a revision. If both upgrade_head and upgrade_only is set, ignore upgrade_head.",
    )
    parser_setup.set_defaults(func=run_setup)

    # ---run command---
    parser_run = datastore_subparsers.add_parser(
        "run", help="Start the datastore service."
    )

    parser_run.add_argument("--host", "-H", type=str, default="localhost")

    parser_run.add_argument("--port", "-P", type=int, default=8000)

    parser_run.add_argument("--workers", type=int, default=None)

    parser_run.set_defaults(func=run_app)
