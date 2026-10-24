"""Seed the disposable fixture Trilium with a small, synthetic LLM wiki for the live tests.

Run once against a fresh fixture after skills/trilium-llm-wiki/setup.py has created the
structure, then stop Trilium and commit fixture/trilium-data. Every page has a fixed noteId,
so eval/fixture-cases.yaml can name the expected pages. No real content: this repo is public.

    python3 fixture/seed.py --url http://localhost:9190 --token "$(cat fixture/etapi.token)"
"""

import argparse
import json
import urllib.parse
import urllib.request


class Etapi:
    def __init__(self, url: str, token: str):
        self.base = url.rstrip("/") + "/etapi"
        self.token = token
        self.created: list[str] = []

    def call(self, method: str, path: str, body=None, raw: str | None = None):
        data, ctype = None, None
        if body is not None:
            data, ctype = json.dumps(body).encode(), "application/json"
        elif raw is not None:
            data, ctype = raw.encode(), "text/plain; charset=utf-8"
        req = urllib.request.Request(self.base + path, data=data, method=method,
                                     headers={"Authorization": self.token, **({"Content-Type": ctype} if ctype else {})})
        with urllib.request.urlopen(req) as r:
            text = r.read().decode()
        return json.loads(text) if text and r.headers.get_content_type() == "application/json" else text

    def search(self, query: str) -> list[dict]:
        return self.call("GET", "/notes?" + urllib.parse.urlencode({"search": query}))["results"]

    def owned(self, label: str, value: str) -> str:
        hits = [n for n in self.search(f"#{label}={value}")
                if any(a["name"] == label and a["value"] == value and a["noteId"] == n["noteId"]
                       for a in n["attributes"])]
        assert len(hits) == 1, (label, value, hits)
        return hits[0]["noteId"]

    def note(self, note_id, parent, title, content, labels=(), relations=(), template=None):
        # Create empty, then PUT the content: only a content save makes Trilium derive
        # ~internalLink relations from the links in it (as when an assistant writes a page).
        self.call("POST", "/create-note", {"noteId": note_id, "parentNoteId": parent, "title": title,
                                           "type": "text", "content": ""})
        self.call("PUT", f"/notes/{note_id}/content", raw=content)
        self.created.append(note_id)
        if template:
            relations = [("template", template), *relations]
        for name, value in labels:
            self.call("POST", "/attributes", {"noteId": note_id, "type": "label", "name": name, "value": value})
        for name, value in relations:
            self.call("POST", "/attributes", {"noteId": note_id, "type": "relation", "name": name, "value": value})
        return note_id


def link(note_id: str, title: str) -> str:
    return f'<a class="reference-link" href="#root/{note_id}">{title}</a>'


def seed(api: Etapi) -> None:
    wiki = api.owned("llmWikiPart", "wiki")
    year = api.owned("wikiSourceGroup", "2026")
    locks = api.owned("llmWikiPart", "locks")
    tpl = {t: api.owned("llmWikiTemplate", t) for t in ("hub", "concept", "entity", "summary")}

    def page(nid, parent, kind, title, html, topic, status="draft", relations=(), extra=()):
        labels = [("wikiTopic", topic), ("wikiStatus", status), ("aiAssisted", ""), *extra]
        return api.note(nid, parent, title, html, labels, relations, template=tpl[kind])

    # Hubs
    page("fxHubHomelab", wiki, "hub", "Homelab", "<p>The home servers.</p>", "homelab")
    page("fxHubTrilium", wiki, "hub", "Trilium", "<p>The notes app and its tooling.</p>", "trilium")
    page("fxHubReisen", wiki, "hub", "Reisen", "<p>Reisen und Planung.</p>", "reisen")

    # Homelab
    page("fxLxcMemory", "fxHubHomelab", "concept", "LXC memory limits",
         "<h2>Swap</h2><p>CT 101 has 1 GB of RAM and no swap; when memory runs out the OOM killer stops "
         "the database first.</p><h2>Fix</h2><p>Raise the limit in the Proxmox UI and restart the container. "
         f"See {link('fxBackups', 'Nightly backups')} before resizing.</p>", "homelab")
    page("fxBridges", "fxHubHomelab", "concept", "Network bridges",
         "<p>Bridge vmbr0 carries VLAN 20 for the IoT devices; vmbr1 is the storage network with jumbo "
         "frames (MTU 9000).</p>", "homelab")
    page("fxBackups", "fxHubHomelab", "concept", "Nightly backups",
         "<h2>Schedule</h2><p>Proxmox Backup Server snapshots every guest at 02:00. Retention keeps 7 daily "
         f"and 4 weekly snapshots.</p><h2>Offsite</h2><p>{link('fxRestic', 'restic')} copies the datastore "
         "to an S3 bucket every Sunday.</p>", "homelab", relations=[("relatesTo", "fxLxcMemory")])
    page("fxRestic", "fxHubHomelab", "entity", "restic",
         "<p>Backup tool used for the offsite copy; the repository password lives in the password "
         "manager.</p>", "homelab", extra=[("entityKind", "tool")])
    page("fxTailscale", "fxHubHomelab", "entity", "Tailscale", "<p>Mesh VPN; page still to be written.</p>",
         "homelab", status="stub", extra=[("entityKind", "tool")])

    # Trilium
    page("fxTrBackup", "fxHubTrilium", "concept", "Trilium backups",
         "<p>Trilium writes its own backup every day into the data folder. To restore, stop the container "
         "and replace document.db with the backup file.</p>", "trilium")
    page("fxEtapi", "fxHubTrilium", "entity", "ETAPI",
         "<p>Trilium's REST API. Tokens are created under Options → ETAPI and sent as the Authorization "
         "header.</p>", "trilium", extra=[("entityKind", "product")])

    # Reisen (German)
    page("fxJrPass", "fxHubReisen", "concept", "Zugpass für Japan",
         "<p>Der JR Pass lohnt sich ab etwa drei Fernreisen in sieben Tagen. Die Sitzplatzreservierung im "
         "Shinkansen ist mit dem Pass kostenlos.</p>", "reisen")
    page("fxPackliste", "fxHubReisen", "concept", "Packliste",
         "<ul><li>Reisepass</li><li>Steckdosenadapter Typ A</li><li>Bargeld in Yen</li></ul>", "reisen")

    # Hub page lists
    for hub, pages in {"fxHubHomelab": [("fxLxcMemory", "LXC memory limits"), ("fxBridges", "Network bridges"),
                                        ("fxBackups", "Nightly backups"), ("fxRestic", "restic"),
                                        ("fxTailscale", "Tailscale")],
                       "fxHubTrilium": [("fxTrBackup", "Trilium backups"), ("fxEtapi", "ETAPI")],
                       "fxHubReisen": [("fxJrPass", "Zugpass für Japan"), ("fxPackliste", "Packliste")]}.items():
        items = "".join(f"<li>{link(n, t)}</li>" for n, t in pages)
        api.call("PUT", f"/notes/{hub}/content", raw=f"<h2>Pages</h2><ul>{items}</ul>")

    # Sources: one summarised, one not
    api.note("fxSrcArticle", year, "Article: Sizing LXC containers",
             "<p>Most small services idle below 200 MB. Give databases twice their working set and never "
             "rely on swap inside a container.</p>")
    page("fxSumArticle", "fxHubHomelab", "summary", "Summary: Sizing LXC containers",
         "<h2>Summary</h2><p>The article argues for generous memory limits on database containers and "
         "against swap.</p>", "homelab", relations=[("wikiSource", "fxSrcArticle")])
    api.note("fxSrcClip", year, "Clip: Kubernetes ingress annotations",
             "<p>The nginx ingress controller reads the annotation proxy-body-size to raise the upload "
             "limit.</p>")

    # Journal day note with a wiki log entry
    day = api.call("GET", "/calendar/days/2026-10-24")["noteId"]
    api.call("PUT", f"/notes/{day}/content",
             raw=f"<h2>Wiki</h2><ul><li><strong>ingest</strong>: {link('fxSumArticle', 'Sizing LXC containers')}"
                 "</li></ul>")

    # Save every page again: a link becomes a relation only if its target existed at save time.
    for nid in api.created:
        api.call("PUT", f"/notes/{nid}/content", raw=api.call("GET", f"/notes/{nid}/content"))

    # Things recall must never return
    api.note("fxLockClaim", locks, "fixture-session: seeding", "<p>zebra lock claim</p>")
    api.note("fxArchived", "root", "Old firewall rules", "<p>zebra iptables legacy rules</p>",
             labels=[("archived", "")])


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--url", required=True)
    p.add_argument("--token", required=True)
    args = p.parse_args()
    seed(Etapi(args.url, args.token))
    print("seeded")


if __name__ == "__main__":
    main()
