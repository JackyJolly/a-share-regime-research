import json
import pytest
from regime_research.auth import initialize, credential_status, cloud_transport


@pytest.fixture(autouse=True)
def clear_rq_environment(monkeypatch):
    for name in credential_status():
        monkeypatch.delenv(name, raising=False)


def test_license_mode_never_prints_key(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("RQDATAC_LICENSE_KEY", "TEST_ONLY_FAKE_LICENSE")
    class Client:
        def init(self, user, key, **kwargs):
            assert user == "license" and key == "TEST_ONLY_FAKE_LICENSE"
            assert kwargs["auto_load_plugins"] is False
            print(key)
        def get_trading_dates(self, *args): return []
    initialize(Client(), tmp_path/"no-cloud-policy")
    assert "TEST_ONLY_FAKE_LICENSE" not in capsys.readouterr().out
    assert credential_status()["RQDATAC_LICENSE_KEY"] is True


def test_exception_redaction(monkeypatch, tmp_path):
    monkeypatch.setenv("RQDATAC_LICENSE_KEY", "TEST_ONLY_FAKE_LICENSE")
    class Client:
        def init(self, *args, **kwargs):
            raise RuntimeError("SDK echoed TEST_ONLY_FAKE_LICENSE")
    with pytest.raises(RuntimeError) as error:
        initialize(Client(), tmp_path/"no-cloud-policy")
    assert "TEST_ONLY_FAKE_LICENSE" not in str(error.value)


def test_cloud_policy_blocks_before_authentication(monkeypatch, tmp_path):
    monkeypatch.setenv("RQDATAC_LICENSE_KEY", "TEST_ONLY_FAKE_LICENSE")
    policy = tmp_path/"policy.json"
    policy.write_text(json.dumps({"version": 1, "tcp_network_access": {"domains": []},
                                  "tcp_connect_proxy": "http://proxy:8088"}))
    class Client:
        def init(self, *a, **k): pytest.fail("Must not send credentials before a TCP grant")
    with pytest.raises(RuntimeError, match="does not grant"):
        initialize(Client(), policy)


def test_platform_proxy_is_used_only_with_grant(monkeypatch, tmp_path):
    monkeypatch.setenv("RQDATAC_LICENSE_KEY", "TEST_ONLY_FAKE_LICENSE")
    policy = tmp_path/"policy.json"
    policy.write_text(json.dumps({"version": 1, "tcp_network_access": {"domains": ["*.ricequant.com"]},
                                  "tcp_connect_proxy": "http://proxy:8088"}))
    class Client:
        def init(self, *a, **kwargs):
            assert kwargs["proxy_info"] == ("http", "proxy", 8088, None, None)
        def get_trading_dates(self, *a): return []
    initialize(Client(), policy)


def test_missing_key_explains_secure_configuration(tmp_path):
    with pytest.raises(RuntimeError, match="RQDATAC_LICENSE_KEY"):
        initialize(object(), tmp_path/"missing")
