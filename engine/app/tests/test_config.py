import pytest

from config import ConfigError, InstanceConfig, load_config


def test_minimal_config():
    c = load_config({"RECALL_LOGIN_PASSWORD": "t", "RECALL_INSTANCES": "marcel",
                     "TRILIUM_MARCEL_URL": "http://trilium-marcel:8080",
                     "TRILIUM_MARCEL_TOKEN": "e"})
    assert c.instances == [InstanceConfig("marcel", "http://trilium-marcel:8080/etapi", "e")]
    assert (c.poll_seconds, c.reconcile_seconds, c.port) == (60, 1800, 8082)


def test_missing_password_raises():
    with pytest.raises(ConfigError, match="RECALL_LOGIN_PASSWORD"):
        load_config({"RECALL_INSTANCES": "marcel"})


def test_old_token_name_says_it_was_renamed():
    with pytest.raises(ConfigError, match="renamed to RECALL_LOGIN_PASSWORD"):
        load_config({"RECALL_TOKEN": "t", "RECALL_INSTANCES": "marcel"})


MARCEL = {"RECALL_LOGIN_PASSWORD": "t", "RECALL_INSTANCES": "marcel",
          "TRILIUM_MARCEL_URL": "http://m", "TRILIUM_MARCEL_TOKEN": "e"}


def test_oauth_off_without_base_url():
    assert load_config(MARCEL).base_url is None


def test_base_url_turns_oauth_on_and_drops_trailing_slash():
    c = load_config({**MARCEL, "RECALL_BASE_URL": "https://recall.example/"})
    assert (c.password, c.base_url) == ("t", "https://recall.example")


@pytest.mark.parametrize("url", ["http://recall.example", "recall.example", "https://recall.example/x#y"])
def test_base_url_must_be_a_valid_issuer(url):
    with pytest.raises(ConfigError, match="RECALL_BASE_URL"):
        load_config({**MARCEL, "RECALL_BASE_URL": url})


def test_instance_without_url_raises():
    with pytest.raises(ConfigError, match="TRILIUM_BILLE_URL"):
        load_config({"RECALL_LOGIN_PASSWORD": "t", "RECALL_INSTANCES": "bille"})


def test_hyphenated_instance_name():
    c = load_config({"RECALL_LOGIN_PASSWORD": "t", "RECALL_INSTANCES": "gemein-sam",
                     "TRILIUM_GEMEIN_SAM_URL": "http://x/etapi", "TRILIUM_GEMEIN_SAM_TOKEN": "e"})
    assert c.instances[0].url == "http://x/etapi"


def test_no_instances_raises():
    with pytest.raises(ConfigError, match="RECALL_INSTANCES"):
        load_config({"RECALL_LOGIN_PASSWORD": "t"})
