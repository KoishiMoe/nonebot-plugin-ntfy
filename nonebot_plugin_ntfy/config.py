from typing import Any, Dict, List

from pydantic import BaseModel, Field


class Config(BaseModel):
    # ntfy server configuration
    ntfy_server: str = Field(default="https://ntfy.sh", description="ntfy server URL")
    ntfy_token: str = Field(default="", description="ntfy server token")
    reconnect_interval: int = Field(
        default=10, description="Reconnect interval for ntfy listeners (seconds)"
    )
    cache_clean_interval: int = Field(
        default=60, description="Interval to clean media cache (minutes)"
    )
    # max_attachment_size: int = Field(
    #     default=5 * 1024 * 1024, description="Maximum size of attachments to upload to ntfy (in bytes)"
    # )

    # Mappings from ntfy channels to QQ targets
    # noinspection PyDataclass
    ntfy_to_qq_mapping: List[Dict[str, Any]] = Field(
        default=[
            {
                "ntfy_channel": "channel1",
                "qq_targets": ["group_123456", "user_654321"],
            },
            # Add more mappings as needed
        ],
        description="Mappings from ntfy channels to QQ groups/users",
    )

    # # Mappings from QQ sources to ntfy channels
    # # use "all" to forward all messages to ntfy
    # # noinspection PyDataclass
    # qq_to_ntfy_mapping: List[Dict[str, Any]] = Field(
    #     default=[
    #         {
    #             "qq_sources": ["group_123456", "user_654321"],
    #             "ntfy_channel": "channel1",
    #         },
    #         # Add more mappings as needed
    #     ],
    #     description="Mappings from QQ groups/users to ntfy channels",
    # )

    @classmethod
    def load(cls) -> "Config":
        try:
            from nonebot import get_plugin_config
            return get_plugin_config(cls)
        except ImportError:
            import os
            import yaml
            path = os.path.join(os.path.dirname(__file__), "config.yml")
            if os.path.exists(path):
                with open(path, "r") as f:
                    config = yaml.safe_load(f)
                    return cls.parse_obj(config)
            with open(path, "w") as f:
                default_config = cls().dict()
                yaml.dump(default_config, f)
                raise ValueError(f"Configuration file not found, created default config at {os.path.abspath(path)}")
