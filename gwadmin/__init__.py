"""gwadmin: local management agent for factory edge gateways.

Pure standard-library implementation, including its own HTTP/1.1
protocol layer (no http.server / BaseHTTPRequestHandler).
"""

from .app import GwAdminApp, VERSION
from .server import GatewayServer

__version__ = VERSION
__all__ = ["GwAdminApp", "GatewayServer", "VERSION"]
