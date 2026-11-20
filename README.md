# Registry for ITS Ontologies

[This site](https://isotc204.org/ritso) is the master registry for TC 204 ontology documentation. Each ontology is maintained and published from its own repository; RITSO links those published sites together.

## Published vs local preview

| Environment | Host | Example |
| ----------- | ---- | ------- |
| Published | `https://isotc204.org` | `https://isotc204.org/ritso/`, `https://isotc204.org/ontology-its-core-v1/` |
| Local preview | `http://127.0.0.1:8080` | `http://127.0.0.1:8080/ritso/`, `http://127.0.0.1:8080/ontology-its-core-v1/` |

Mesh links use the `{{ site_base }}` placeholder (substituted at publish/preview time). The catalog at [`catalog/ontologies.yml`](catalog/ontologies.yml) is the source of truth for ontology titles, published paths, and sibling repo names.

## Local multi-site preview

From this repository (with sibling ontology checkouts next to it under the same parent folder):

```bash
# Build RITSO + every catalogued ontology that is checked out locally, then serve
python3 scripts/local_preview.py

# Or via the shell wrapper
./scripts/local_preview.sh

# Build only selected sites
python3 scripts/local_preview.py --only ritso,ontology-its-core-v1 --build-only

# Serve an existing .local-preview tree
python3 scripts/local_preview.py --serve
```

Open [http://127.0.0.1:8080/ritso/](http://127.0.0.1:8080/ritso/). Ontology nav entries and registry links resolve to local sibling builds when those repos are present; missing checkouts are skipped with a warning.

Preview builds copy each site into a temp directory, rewrite mesh URLs there, and leave your checkouts untouched. Output is written to `.local-preview/` (gitignored).

### Adding an ontology to the registry

1. Add an entry to [`catalog/ontologies.yml`](catalog/ontologies.yml) (`title`, `group`, `path`, `repo`, `enabled`).
2. Point RITSO nav / registry links at `{{ site_base }}/<path>`.
3. Ensure the sibling ontology repo is checked out beside `ritso`.
4. Re-run `python3 scripts/local_preview.py` to verify the mesh before publishing.
