# travel-tools - OmniTravel plugin marketplace

Claude Cowork / Claude Code plugin marketplace for B2B travel workflows.

## Install in Cowork

Cowork tab → Customize → Plugins → **+** → Add marketplace from GitHub:
`omnitravelrepo/travel-tools`, then install
**hotel-contract-extractor** from the catalog.

## Install in Claude Code

```
claude plugin marketplace add omnitravelrepo/travel-tools
claude plugin install hotel-contract-extractor@omnitravel-marketplace
```

## Install in OpenAI Codex (open SKILL.md standard)

```
cp -r plugins/hotel-contract-extractor/skills/hotel-contract-extractor ~/.codex/skills/
```

## Plugins

| Plugin | Description |
|---|---|
| [hotel-contract-extractor](plugins/hotel-contract-extractor/) | Hotel contract PDFs → validated JSON + agenda rate tables |
