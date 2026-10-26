# Moving from trilium-llm-wiki

Up to 0.4.x the engine and the hook were part of
[trilium-llm-wiki](https://trilium-llm-wiki.marceltov.de/), and the image was
`ghcr.io/marceltov/trilium-llm-wiki-recall`. From 0.5.0:

- change the image to `ghcr.io/marceltov/trilium-recall`; the settings and the index volume stay
  the same;
- install this plugin. Its hook keeps reading the `recall.json` the old plugin wrote, and the
  `wiki-recall` MCP server registration stays as it is.
- the `recall` tool's description no longer names one person's wiki. To keep a description that
  tells the assistant what your notes cover, set `RECALL_TOOL_DESCRIPTION`
  ([Settings](install.md#settings));
- once trilium-llm-wiki is on 0.5.0 it no longer ships the hook. Until then, with both plugins
  active, a prompt may get its passages twice.
