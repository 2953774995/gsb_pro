import os
import platform


def platform_info():
    return {"hostname": platform.node(), "pid": os.getpid(), "platform": platform.platform()}
