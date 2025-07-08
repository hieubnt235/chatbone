import importlib
import importlib.resources as import_resource
import os
from argparse import ArgumentParser
from pathlib import Path
from typing import Self

import yaml
from dotenv import load_dotenv, find_dotenv
from pydantic import (
    model_validator,
    BaseModel,
    PositiveInt,
    NonNegativeInt,
    NonNegativeFloat,
)
from ray import serve
from ray.serve.schema import (
    ServeApplicationSchema,
    DeploymentSchema,
    ServeDeploySchema,
)

from chatbone.assistant import BaseAssistant
from chatbone_apps.commons import _make_deployment_name_from_real_import_path
from utilities.func import base64_encode
from utilities.settings import Config


class AutoscalingConfig(BaseModel):
    min_replicas: NonNegativeInt = 1
    initial_replicas: NonNegativeInt = None
    max_replicas: PositiveInt = 1


class RayActorOptionsConfig(BaseModel):
    num_cpus: NonNegativeInt = 1
    num_gpus: NonNegativeInt = 0
    memory: NonNegativeFloat = None


class DeploymentConfig(BaseModel):
    num_replicas: PositiveInt = None
    max_ongoing_requests: int = None
    max_queued_requests: int = None
    autoscaling_config: AutoscalingConfig = None  # if set, num_replicas must be non-set
    ray_actor_options: RayActorOptionsConfig = RayActorOptionsConfig()


class ApplicationConfig(BaseModel):
    """For user config"""

    import_path: str
    deployment_config: DeploymentConfig = DeploymentConfig()

    @model_validator(mode="after")
    def validate_import_path(self) -> Self:
        path = self.import_path.split(":")
        assert len(path) == 2 and path[0] and path[1]
        return self


class AssistantApplicationConfig(ApplicationConfig):
    _real_import_path: str
    _module_name: str
    _assistant_name: str
    _app_name: str

    @model_validator(mode="after")
    def validate_assistant(self) -> Self:
        module_name, assistant_name = self.import_path.split(":")
        module = importlib.import_module(module_name)
        assistant = getattr(module, assistant_name)
        assert isinstance(assistant, BaseAssistant)

        self._module_name = module_name
        self._assistant_name = assistant_name
        self._real_import_path = self.import_path
        self._app_name = module_name + "_" + assistant_name
        self.import_path = (
            f"chatbone_apps.assistant_apps:{base64_encode(self.import_path)}"
        )
        return self


class AssistantsComposeConfig(Config):
    assistants: list[AssistantApplicationConfig]

    @model_validator(mode="after")
    def check_duplicate(self):
        paths = []
        for a in self.assistants:
            if (p := a._real_import_path) not in paths:
                paths.append(p)
            else:
                raise ValueError(f"Multiple import path '{p}'.")
        return self


class ChatboneAppConfig(Config):
    chatbone: ApplicationConfig


def build(args):
    host = args.host
    port = args.port
    output_file = args.output_file

    # --- Assistants ---
    config_path = import_resource.files("assistants").joinpath(
        "assistants-compose.toml"
    )
    app_configs: list[ServeApplicationSchema] = []
    as_config = AssistantsComposeConfig(file=config_path)

    for a in as_config.assistants:
        deployment = DeploymentSchema(
            name=_make_deployment_name_from_real_import_path(a._real_import_path),
            **a.deployment_config.model_dump(exclude_none=True),
        )

        app_configs.append(
            ServeApplicationSchema(
                name=a._app_name,
                route_prefix=None,
                import_path=a.import_path,
                deployments=[deployment],
            ).dict(exclude_unset=True)
        )

    # --- Chat app ---
    # TODO: Change mechanism the found chatbone root path by env or the dir of .env file. Then infer relative path from it.
    #  Currently, this collecting paths does not consistency with entire project.
    cfg_file = None
    env_file = find_dotenv(".env.chatbone")

    file = os.getenv("CHATBONE_BUILDING_CONFIG_FILE")
    if not file:
        load_dotenv(env_file)
        if not (file := os.getenv("CHATBONE_BUILDING_CONFIG_FILE")):
            raise ValueError(f"CHATBONE_BUILDING_CONFIG_FILE not found.")

    if not file.startswith("/"):
        cfg_file = Path(env_file).parent.joinpath(file).as_posix()
    else:
        cfg_file = file

    chat_config = ChatboneAppConfig(file=cfg_file)
    module_name, app_name = chat_config.chatbone.import_path.split(":")
    chat_app = getattr(importlib.import_module(module_name), app_name)
    assert isinstance(chat_app, serve.Application)
    deployment_name = chat_app._bound_deployment.name

    app_configs.append(
        ServeApplicationSchema(
            name="chatbone_app",
            route_prefix="/",
            import_path=chat_config.chatbone.import_path,
            deployments=[
                DeploymentSchema(
                    name=deployment_name,
                    **chat_config.chatbone.deployment_config.model_dump(
                        exclude_none=True
                    ),
                )
            ],
        ).dict(exclude_unset=True)
    )

    deploy_config = {
        "proxy_location": "EveryNode",
        "http_options": {
            "host": host,
            "port": port,
        },
        "applications": app_configs,
    }
    ServeDeploySchema.parse_obj(deploy_config)  # pydantic v1
    with open(output_file, "w") as f:
        yaml.dump(deploy_config, f, sort_keys=False)


def config_parser(parser: ArgumentParser):

    parser.add_argument("--host", "-H", type=str, default="localhost",help="default='localhost'")

    parser.add_argument("--port", "-P", type=int, default=9999, help="default=9999")

    parser.add_argument(
        "--output-file",
        "-o",
        type=str,
        default="chatbone_serve.yaml",
        help="default='chatbone_serve.yaml'.",
    )

    parser.set_defaults(func=build)
