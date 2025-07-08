from argparse import ArgumentParser


def run_app(args):
    host = args.host
    port = args.port
    workers = args.workers

    import uvicorn
    from auth.app import app

    uvicorn.run(app, host=host, port=port, workers=workers)


def config_parser(parser: ArgumentParser):
    auth_subparser = parser.add_subparsers(
        dest="auth_command", required=True, help="Available auth subcommands"
    )

    # ---run command---
    parser_run = auth_subparser.add_parser("run", help="Start the auth service.")

    parser_run.add_argument("--host", "-H", type=str, default="localhost")

    parser_run.add_argument("--port", "-P", type=int, default=8000)

    parser_run.add_argument("--workers", type=int, default=None)

    parser_run.set_defaults(func=run_app)
