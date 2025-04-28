import argparse
from pathlib import Path

from utilities.logger import logger
from alembic.config import Config
from alembic import command
from dotenv import load_dotenv, find_dotenv
import os

from utilities.func import utc_now


load_dotenv(find_dotenv(".env.chatbone"))


def run_migrations(alembic_ini_path:str, ini_section:str, script_location:str,
                   message:str="", upgrade_only=False, upgrade_head=True):
	"""
	Runs Alembic migrations programmatically.
	"""
	config = Config(alembic_ini_path,ini_section=ini_section)
	config.set_main_option("script_location",script_location)
	config.set_main_option("version_locations",(Path(script_location)/f"{ini_section}_versions").as_posix() )

	# If both upgrade_head and upgrade_only is set, ignore upgrade_head.
	if upgrade_only:
		logger.info("Running \'alembic upgrade head\'...")
		command.upgrade(config, "head")
		logger.info("Complete Upgrade.")
	else:
		logger.info("Running \'alembic revision --autogenerate=True\'...")
		command.revision(config, autogenerate=True, message=message)
		logger.info("Complete Revision.")
		if upgrade_head:
			logger.info("Running \'alembic upgrade head\'...")
			command.upgrade(config, "head")
			logger.info("Complete Upgrade.")


if __name__ == "__main__":
	"""
	Examples:
		python ./scripts/migrations.py -n datastore_db
	"""
	alembic_path=Path(os.getenv("ALEMBIC_PATH", "../alembic.ini")).resolve()

	parser = argparse.ArgumentParser(description="Run Alembic migrations programmatically.")
	parser.add_argument("-n", "--ini_section", help="Alembic's Config.config_ini_section (for multi-database setup).")
	parser.add_argument("-c", "--config",
	                    default=alembic_path.as_posix(),
	                    help="Absolute path to the alembic.ini file. Default is ALEMBIC_PATH in envars or \'../alembic.ini\'.")
	parser.add_argument("-s","--script-location",
	                    default=alembic_path.parent.as_posix(),
	                    help="Absolute path to script location. Default is the parent location of alembic.ini .")

	parser.add_argument("-m", "--message", default=f"Upgrade at {utc_now()}", help="Message for the revision.")
	parser.add_argument("--no-upgrade", action="store_true", help="Disable run 'alembic upgrade head' after creating a revision.")
	parser.add_argument("--upgrade-only", action="store_true",
	                    help="Run only 'alembic upgrade head', without creating a revision.")

	args = parser.parse_args()

	logger.info(f"\nConfig file: \'{args.config}\'.\n"
	            f"Scripts location: \'{args.script_location}\'.\n"
	            f"Main option name: \'{args.ini_section}\'.")

	run_migrations(alembic_ini_path=args.config,
	               ini_section=args.ini_section,
	               script_location=args.script_location,
	               message=args.message,
	               upgrade_only=args.upgrade_only,
	               upgrade_head=not args.no_upgrade)

