import pytest

from config import ConfigError, InstanceConfig, load_config


def test_minimal_config():
    c = load_config({"RECALL_TOKEN": "t", "RECALL_INSTANCES": "marcel",
                     "TRILIUM_MARCEL_URL": "http://trilium-marcel:8080",
                     "TRILIUM_MARCEL_TOKEN": "e"})
    assert c.instances == [InstanceConfig("marcel", "http://trilium-marcel:8080/etapi", "e")]
    assert (c.poll_seconds, c.reconcile_seconds, c.port) == (60, 1800, 8082)


def test_missing_token_raises():
    with pytest.raises(ConfigError, match="RECALL_TOKEN"):
        load_config({"RECALL_INSTANCES": "marcel"})


def test_instance_without_url_raises():
    with pytest.raises(ConfigError, match="TRILIUM_BILLE_URL"):
        load_config({"RECALL_TOKEN": "t", "RECALL_INSTANCES": "bille"})


def test_hyphenated_instance_name():
    c = load_config({"RECALL_TOKEN": "t", "RECALL_INSTANCES": "gemein-sam",
                     "TRILIUM_GEMEIN_SAM_URL": "http://x/etapi", "TRILIUM_GEMEIN_SAM_TOKEN": "e"})
    assert c.instances[0].url == "http://x/etapi"


def test_no_instances_raises():
    with pytest.raises(ConfigError, match="RECALL_INSTANCES"):
        load_config({"RECALL_TOKEN": "t"})
