from typing import Self

from pydantic import BaseModel, DirectoryPath, ConfigDict, model_validator


class DirSettings(BaseModel):
    """Model representing the settings for paths used in the application.
    The default paths is the directory in side rootdir.
    Attributes:
        configs (DirectoryPath): The directory path for configuration files.
        logs (DirectoryPath): The directory path for log files.
    """
    root: DirectoryPath
    configs: DirectoryPath|None=None
    logs: DirectoryPath|None=None


    model_config = ConfigDict(validate_default=True,
                              validate_assignment=True,)

    @model_validator(mode='after')
    def init_default_path(self)->Self:
        if self.configs is None:
            self.configs= self.root/"configs"
        if self.logs is None:
            self.logs=self.root/"logs"
        return self

