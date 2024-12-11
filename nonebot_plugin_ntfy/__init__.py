from . import worker

try:
    from nonebot.plugin import PluginMetadata

    __plugin_meta__ = PluginMetadata(
        name="ntfy_forward",
        description="Forward messages between ntfy channels and QQ groups/users",
        usage="Configure the forwarding pairs in the plugin config",
    )
except ImportError:
    pass
