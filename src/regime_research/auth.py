"""License authentication without putting credentials in diagnostics or files."""
from contextlib import redirect_stderr, redirect_stdout
from fnmatch import fnmatchcase
from pathlib import Path
from urllib.parse import urlsplit
import json
import os
import warnings

HOST = "rqdatad-pro.ricequant.com"
PORT = 16011


class _Discard:
    def write(self, text):
        return len(text)

    def flush(self):
        pass


def credential_status():
    """Names and presence only; never return values."""
    names = ["RQDATAC_LICENSE_KEY", "RQDATAC_USERNAME", "RQDATAC_PASSWORD",
             "RQDATAC_CONF", "RQDATAC2_CONF", "RQDATAC_PROXY"]
    return {name: bool(os.getenv(name)) for name in names}


def cloud_transport(policy_path=Path("/etc/codex/network-policy.json")):
    """Use the declared CONNECT proxy only after a matching platform TCP grant.

    Never fall back to direct Internet access in a managed proxy-only environment.
    Outside that environment, the SDK keeps its normal transport configuration.
    """
    if not policy_path.exists():
        return None
    policy = json.loads(policy_path.read_text())
    if policy.get("version") != 1:
        raise RuntimeError("Unsupported cloud network policy version; TCP readiness is unknown")
    uri = os.getenv("RQDATAC2_CONF") or os.getenv("RQDATAC_CONF")
    host = (urlsplit(uri).hostname if uri else None) or HOST
    grants = policy.get("tcp_network_access", {}).get("domains", [])
    if not any(isinstance(rule, str) and fnmatchcase(host, rule) for rule in grants):
        raise RuntimeError("Cloud TCP policy does not grant the Ricequant service; HTTPS domain access is insufficient")
    proxy = policy.get("tcp_connect_proxy")
    if not proxy:
        raise RuntimeError("Cloud TCP CONNECT proxy is unavailable; do not bypass the network policy")
    if os.getenv("RQDATAC_PROXY") and os.environ["RQDATAC_PROXY"] != proxy:
        raise RuntimeError("RQDATAC_PROXY differs from the platform TCP proxy; verify the supported transport")
    return proxy


def initialize(client=None, policy_path=Path("/etc/codex/network-policy.json")):
    if client is None:
        try:
            import rqdatac as client
        except ImportError:
            raise RuntimeError("Install .[ricequant] in an isolated environment") from None
    key = os.getenv("RQDATAC_LICENSE_KEY")
    username, password = os.getenv("RQDATAC_USERNAME"), os.getenv("RQDATAC_PASSWORD")
    uri = bool(os.getenv("RQDATAC_CONF") or os.getenv("RQDATAC2_CONF"))
    if not key and not (username and password) and not uri:
        raise RuntimeError("Set RQDATAC_LICENSE_KEY securely in environment settings; never paste it into Git or logs")
    proxy = cloud_transport(policy_path)
    common = {"auto_load_plugins": False, "connect_timeout": 8, "timeout": 60}
    if proxy:
        parsed = urlsplit(proxy)
        common["proxy_info"] = (parsed.scheme, parsed.hostname, parsed.port, None, None)
    sink = _Discard()
    try:
        # SDK/third-party diagnostics can echo the password or license via info().
        with redirect_stdout(sink), redirect_stderr(sink), warnings.catch_warnings():
            warnings.simplefilter("ignore")
            if key:
                client.init("license", key, addr=(HOST, PORT), **common)
            elif username and password:
                client.init(username, password, **common)
            else:
                client.init(**common)
            # Ordinary password/URI init is lazy, so verify authentication explicitly.
            client.get_trading_dates("2024-01-02", "2024-01-03")
    except Exception:
        raise RuntimeError("Ricequant authentication/transport failed; credential details were suppressed") from None
    return client
