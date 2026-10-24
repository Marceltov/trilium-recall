import pytest

from embed import HashEmbedder
from index import Index
from sync import Syncer
from trilium import EtapiClient
from tests.fake_etapi import build_world


@pytest.fixture
def world():
    return build_world()


@pytest.fixture
def idx(tmp_path):
    e = HashEmbedder()
    return Index(tmp_path / "i.db", e.name, e.dim)


@pytest.fixture
def syncer(world, idx):
    client = EtapiClient("http://fake/etapi", "tok", transport=world.etapi.transport())
    return Syncer("marcel", client, idx, HashEmbedder())


def test_full_build_classifies_areas(world, syncer, idx):
    syncer.full_build()
    assert idx.note(world.wiki_page).area == "wiki"
    assert idx.note(world.source).area == "source"
    assert idx.note(world.day_note).area == "journal"
    assert idx.note(world.other_note).area == "other"
    assert idx.note(world.lock_claim) is None and idx.note(world.template) is None
    assert idx.fts_search("rules")[0].note_id == world.schema and idx.note(world.schema).area == "wiki"


def test_full_build_skips_plumbing_hidden_archived_and_non_text(world, syncer, idx):
    syncer.full_build()
    titles = {idx.note(n).title for n in idx.all_notes()}
    assert not titles & {"Locks", "Wiki Concept", "Old stuff", "Hidden thing", "A drawing"}


def test_full_build_reads_labels_and_links(world, syncer, idx):
    syncer.full_build()
    page = idx.note(world.wiki_page)
    assert (page.wiki_type, page.topics, page.status, page.path) == ("concept", ["homelab"], "draft", ["Homelab"])
    assert ("internalLink", world.wiki_page) in idx.neighbours(world.hub)
    assert idx.sources_summarised_by(world.source) == [world.summary]
    assert idx.fts_search("OOM killer")[0].note_id == world.wiki_page


def test_poll_picks_up_edit(world, syncer, idx):
    syncer.full_build()
    world.set_content(world.wiki_page, "<p>new words zebra</p>")
    assert syncer.poll() == 1 and idx.fts_search("zebra")


def test_poll_sends_date_filter_first(world, syncer):
    syncer.full_build()
    world.requests.clear()
    syncer.poll()
    searches = [p for m, p in world.requests if p.endswith("/notes")]
    assert searches  # the fake rejects any other query shape


def test_attribute_only_change_updates_meta(world, syncer, idx):
    syncer.full_build()
    world.add_label(world.wiki_page, "wikiStatus", "reviewed", bump_modified=False)
    assert syncer.reconcile() == 1
    assert idx.note(world.wiki_page).status == "reviewed"


def test_reconcile_removes_deleted_and_moved(world, syncer, idx):
    syncer.full_build()
    world.delete(world.wiki_page)
    world.move(world.other_note, under=world.locks)
    syncer.reconcile()
    assert idx.note(world.wiki_page) is None and idx.note(world.other_note) is None
    assert idx.fts_search("OOM killer") == []


def test_unchanged_reconcile_does_nothing(world, syncer):
    syncer.full_build()
    world.requests.clear()
    assert syncer.reconcile() == 0
    assert not [p for m, p in world.requests if p.endswith("/content")]


def test_trilium_down_keeps_index(world, syncer, idx):
    syncer.full_build()
    world.fail = True
    syncer.poll()
    assert syncer.status.last_error and idx.note(world.wiki_page) is not None
    world.fail = False
    syncer.poll()
    assert syncer.status.last_error is None


def test_status_counts(world, syncer):
    syncer.full_build()
    assert syncer.status.notes == 10 and syncer.status.sections == 7 and syncer.status.last_ok


def test_never_mutates(world, syncer):
    syncer.full_build(); syncer.poll(); syncer.reconcile()
    assert {m for m, _ in world.requests} == {"GET"}


def test_full_build_during_outage_keeps_old_index(world, syncer, idx):
    syncer.full_build()
    world.fail = True
    syncer.full_build()
    assert syncer.status.last_error and idx.note(world.wiki_page) is not None
