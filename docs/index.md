# specprism

**Normalize OpenAPI 3.x specs to a stable IR and diff them as plain YAML.**
Annotate known changes, surface the rest.

---

## What it does

specprism resolves all `$ref` references, normalizes combiners (`oneOf`, `anyOf`, `allOf`),
and unifies nullable patterns into a typed intermediate representation (IR).
The IR serializes to YAML in deterministic key order, so two specs that are
semantically identical produce an empty diff regardless of formatting.

```
OpenAPI JSON/YAML  ->  SpecIR (Pydantic)  ->  stable YAML  ->  unified diff
```

A **know-how file** lets you annotate IR paths with domain knowledge:
explain what a node is, mark a change as intentional, declare two paths
equivalent across versions, or suppress internal schemas from the diff.

---

## Quick start

```bash
git clone https://github.com/your-username/specprism
cd specprism
uv sync
uv run specprism diff examples/payments_v1.yaml examples/payments_v2.yaml
```

With annotations:

```bash
uv run specprism diff \
  examples/payments_v1.yaml \
  examples/payments_v2.yaml \
  --no-descriptions \
  --knowhow examples/payments.knowhow.yaml
```

See the [Tutorial](tutorial.md) for full documentation.

---

## Install as a tool

```bash
uv tool install git+https://github.com/your-username/specprism
specprism --help
```
