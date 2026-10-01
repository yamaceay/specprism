# specprism tutorial

Normalize OpenAPI 3.x specs to a stable intermediate representation (IR)
and diff them as plain YAML  -  with a know-how file that turns raw diffs into
explained, annotated changelogs.

---

## Contents

1. [Installation](#1-installation)
2. [Core concepts](#2-core-concepts)
3. [CLI quick start](#3-cli-quick-start)
4. [Python API](#4-python-api)
5. [The know-how file](#5-the-know-how-file)
   - [note](#51-note)
   - [known_change](#52-known_change)
   - [equivalence](#53-equivalence)
   - [suppress](#54-suppress)
6. [Real-world example  -  Payments API](#6-real-world-example--payments-api)
7. [Reference](#7-reference)

---

## 1. Installation

```bash
git clone <this-repo>
cd specprism
uv sync
```

Requires Python 3.11+. uv resolves and pins all dependencies from `uv.lock`.
No manual venv or pip commands needed.

Run any command with `uv run <cmd>`  -  uv manages the environment automatically:

```bash
uv run specprism --help
uv run pytest
```

---

## 2. Core concepts

### Intermediate Representation (IR)

specprism does not diff raw OpenAPI JSON. It first resolves every `$ref`,
flattens combiners (`oneOf`, `anyOf`, `allOf`), and normalizes nullable
patterns into a typed Pydantic tree called the **IR**. The IR is then
serialized to YAML with deterministic key order so that `diff` is meaningful.

```
OpenAPI JSON/YAML  ──resolve──▶  SpecIR (Pydantic)  ──serialize──▶  stable YAML  ──diff──▶  patch
```

The YAML is the diffable artifact. Two specs that are semantically identical
but formatted differently will produce an empty diff.

### Know-how file

A YAML file that annotates IR paths with domain knowledge. It does not mutate
the IR  -  it injects comment lines into the serialized YAML before diffing.
Four annotation kinds: `note`, `known_change`, `equivalence`, `suppress`.

---

### Scope and what the meta block captures

The IR models the structural shape of a schema: its kind, properties, variants,
scalar bounds, and array constraints. It intentionally does not model every
OpenAPI field.

Fields that are not structural are preserved verbatim in an optional `meta`
sub-block on each `SchemaNode`. This means changes to these fields are still
visible in diffs, but they appear under `meta:` rather than as first-class IR
fields.

| Meta field | What it means |
|---|---|
| `pattern` | Regex constraint on a string |
| `default` | Default value when the field is absent |
| `readOnly` | Field may only appear in responses |
| `writeOnly` | Field may only appear in requests |
| `deprecated` | Field or schema is marked for removal |
| `const` | Field must equal exactly one value |
| `discriminator` | oneOf/anyOf discriminator hint |
| `uniqueItems` | Array items must be unique |
| `multipleOf` | Number must be a multiple of this value |
| `exclusiveMinimum` / `exclusiveMaximum` | Strict numeric bounds |
| `example` / `examples` | Documentation examples |
| `externalDocs` | Link to external documentation |
| `patternProperties` | Regex-keyed additional property schemas |
| `propertyNames` | Schema constraining property name strings |
| `contains` | Array must contain at least one matching item |
| `xml` | XML serialization hints |

A node with no extra fields has no `meta` block at all, keeping the YAML clean.

Example: a string field with a regex and a default:

```yaml
Token:
  kind: scalar
  scalar_type: string
  meta:
    default: ABC
    pattern: ^[A-Z]+$
    readOnly: true
```

If `pattern` changes between versions, the diff shows it under `meta.pattern`
just like any other field change.

---

## 3. CLI quick start

The examples below use the bundled catalog specs in `examples/`.

### Parse a spec to IR YAML

```bash
uv run specprism parse examples/catalog_v1.yaml
```

Save to file:
```bash
uv run specprism parse examples/catalog_v1.yaml --output /tmp/catalog_v1.ir.yaml
```

Strip descriptions to reduce noise:
```bash
uv run specprism parse examples/catalog_v1.yaml --no-descriptions
```

### Inspect a single schema

```bash
uv run specprism show examples/catalog_v1.yaml --schema Pricing
```

Output:
```yaml
kind: union
source_keyword: oneOf
variants:
- kind: object
  required:
  - fixed
  properties:
    fixed:
      kind: scalar
      scalar_type: number
- kind: object
  required:
  - range_min
  - range_max
  properties:
    range_min:
      kind: scalar
      scalar_type: number
    range_max:
      kind: scalar
      scalar_type: number
```

### Diff two specs

```bash
uv run specprism diff examples/catalog_v1.yaml examples/catalog_v2.yaml
```

Schema-only, no description noise:
```bash
uv run specprism diff examples/catalog_v1.yaml examples/catalog_v2.yaml \
  --no-endpoints --no-descriptions
```

Save the patch:
```bash
uv run specprism diff examples/catalog_v1.yaml examples/catalog_v2.yaml \
  --output /tmp/catalog.diff
```

### Diff with know-how annotations

```bash
uv run specprism diff examples/catalog_v1.yaml examples/catalog_v2.yaml \
  --no-descriptions \
  --knowhow examples/catalog.knowhow.yaml
```

---

## 4. Python API

```python
import json
from openapi_comparator.resolver import resolve_file
from openapi_comparator.serializer import serialize
from openapi_comparator.differ import diff_yaml
from openapi_comparator.knowhow import KnowhowFile, annotate_yaml
```

### Parse a spec

```python
with open("examples/catalog_v1.yaml") as f:
    import yaml
    raw = yaml.safe_load(f)

ir = resolve_file(raw)

print(ir.title)      # "Catalog API"
print(ir.version)    # "1.0.0"
print(ir.base_path)  # "/v1"

# Walk schemas
for name, node in ir.schemas.items():
    print(name, node.kind)
```

### Serialize to stable YAML

```python
yaml_text = serialize(ir)
print(yaml_text)
```

### Diff two specs

```python
with open("examples/catalog_v1.yaml") as f:
    raw_a = yaml.safe_load(f)
with open("examples/catalog_v2.yaml") as f:
    raw_b = yaml.safe_load(f)

ir_a = resolve_file(raw_a)
ir_b = resolve_file(raw_b)

patch = diff_yaml(
    serialize(ir_a),
    serialize(ir_b),
    label_a=f"{ir_a.title} {ir_a.version}",
    label_b=f"{ir_b.title} {ir_b.version}",
)
print(patch)
```

### Apply a know-how file

```python
kh = KnowhowFile.from_file("examples/catalog.knowhow.yaml")

yaml_a = annotate_yaml(serialize(ir_a), kh)
yaml_b = annotate_yaml(serialize(ir_b), kh)

patch = diff_yaml(yaml_a, yaml_b)
print(patch)
```

### Inspect a specific schema node

```python
node = ir.schemas["Pricing"]

print(node.kind)           # NodeKind.UNION
print(node.source_keyword) # "oneOf"
print(len(node.variants))  # 2
```

---

## 5. The know-how file

The know-how file is a YAML file with a list of `annotations`. Each annotation
has a `kind` field that controls what it does.

Path syntax uses dot notation matching the serialized IR YAML structure:

```
schemas.Foo                               top-level schema
schemas.Foo.properties.bar                property of an object
schemas.Foo.variants[0]                   first variant of a union
schemas.Foo.variants[0].properties.baz    property inside a variant
```

### 5.1 `note`

Explains what a node IS. Injected as `# note:` comments in the serialized YAML
before diffing. Visible on both sides of the diff.

```yaml
- kind: note
  path: schemas.Pricing
  note: >
    oneOf pricing strategy: fixed, range, or discounted.
    v2 added the discount variant.
  sdk_equivalent: Price     # optional  -  shown as "# sdk: Price"
```

Diff output:
```diff
+  # note: oneOf pricing strategy: fixed, range, or discounted. v2 added the discount variant.
+  # sdk: Price
   Pricing:
     kind: union
```

### 5.2 `known_change`

Marks a diff hunk as intentional and explained. Annotated hunks get a
`# ✓ known` marker. Everything **without** that marker is unexplained  -  that
is the signal for what still needs investigation.

```yaml
- kind: known_change
  path: schemas.Category
  from_version: "1.0.0"
  to_version: "2.0.0"
  reason: >
    Non-breaking additive change. Two new categories (clothing, sports) added.
    Existing values preserved.
```

Diff output:
```diff
+  # ✓ known (1.0.0 → 2.0.0): Non-breaking additive change. Two new categories ...
   Category:
     kind: enum
     enum_values:
     - books
+    - clothing
     - electronics
+    - sports
```

### 5.3 `equivalence`

Documents that two paths mean the same thing across versions. Adds a
`# ≡ <other-path>` cross-reference on both sides of the diff so reviewers
know a field didn't vanish  -  it was renamed or moved.

```yaml
- kind: equivalence
  path_a: schemas.Product.properties.status
  path_b: schemas.Product.properties.availability
  note: >
    status (v1) renamed to availability (v2)  -  same semantics, clearer name.
```

Diff output (v1 side):
```diff
-    # ≡ schemas.Product.properties.availability: status (v1) renamed to availability (v2)
-    status:
-      kind: scalar
-      scalar_type: string
```

Diff output (v2 side):
```diff
+    # ≡ schemas.Product.properties.status: status (v1) renamed to availability (v2)
+    availability:
+      kind: scalar
+      scalar_type: string
```

### 5.4 `suppress`

Removes a path from both IRs before diffing. Use for internal schemas that are
not part of the public contract. A `# suppressed:` tombstone is always printed
so nothing is hidden silently.

```yaml
- kind: suppress
  path: schemas.DebugTrace
  reason: >
    Internal debug payload. Not part of the public API contract.
```

Diff output:
```diff
   # suppressed: Internal debug payload. Not part of the public API contract.
   DebugTrace:
     kind: object
     ...
```

> **Note:** Full block removal (dropping the DebugTrace diff entirely) is a
> planned feature. The current implementation adds the tombstone comment but
> still shows internal changes. Suppress is most useful today as a label that
> signals "this diff noise is intentional."

---

## 6. Real-world example  -  Payments API

The bundled Payments API specs show a realistic two-version evolution:
a v1 with a structural anti-pattern (merged-fields object) that v2 fixes
with a proper discriminated union, alongside additive and renaming changes.

Specs: `examples/payments_v1.yaml` (v1.0.0) and `examples/payments_v2.yaml` (v2.0.0).  
Know-how: `examples/payments.knowhow.yaml`.

### Raw diff  -  what you see without annotations

```bash
uv run specprism diff \
  examples/payments_v1.yaml \
  examples/payments_v2.yaml \
  --no-descriptions --no-endpoints
```

This shows everything: the `PaymentMethod` object replaced by a union, two
new `PaymentStatus` values, `status` renamed to `state`, `minimum: 0.01`
added to `Money.amount`, and noise from `InternalAuditEntry` internal fields.
Without context, it is hard to tell which changes are intentional.

### Annotated diff  -  with know-how

```bash
uv run specprism diff \
  examples/payments_v1.yaml \
  examples/payments_v2.yaml \
  --no-descriptions --no-endpoints \
  --knowhow examples/payments.knowhow.yaml
```

### Key changes documented in the know-how file

| Schema | Change | Kind |
|---|---|---|
| `PaymentMethod` | merged object → `oneOf(CardPayment \| BankTransfer \| DigitalWallet)` | `known_change` + `note` |
| `PaymentMethod.variants[0]` | CardPayment variant | `note` |
| `PaymentMethod.variants[1]` | BankTransfer variant | `note` |
| `PaymentMethod.variants[2]` | DigitalWallet  -  new in v2 | `note` |
| `PaymentMethod.properties.card_number` ↔ `variants[0].properties.card_number` | field migrated into variant | `equivalence` |
| `PaymentMethod.properties.iban` ↔ `variants[1].properties.iban` | field migrated into variant | `equivalence` |
| `Payment.properties.status` ↔ `Payment.properties.state` | renamed for clarity | `equivalence` |
| `PaymentStatus` | `refunded` + `disputed` added | `known_change` |
| `Money.properties.amount` | `minimum: 0.01` added | `known_change` |
| `Payment.properties.failure_reason` | new optional field | `known_change` |
| `InternalAuditEntry` | internal fields added | `suppress` |

### Python: load, annotate, and diff

```python
import yaml
from pathlib import Path
from openapi_comparator.resolver import resolve_file
from openapi_comparator.serializer import serialize
from openapi_comparator.differ import diff_yaml
from openapi_comparator.knowhow import KnowhowFile, annotate_yaml

def load_spec(path: str):
    text = Path(path).read_text()
    return resolve_file(yaml.safe_load(text))

ir_v1 = load_spec("examples/payments_v1.yaml")
ir_v2 = load_spec("examples/payments_v2.yaml")
kh    = KnowhowFile.from_file("examples/payments.knowhow.yaml")

yaml_v1 = annotate_yaml(serialize(ir_v1), kh)
yaml_v2 = annotate_yaml(serialize(ir_v2), kh)

patch = diff_yaml(yaml_v1, yaml_v2, label_a="v1.0.0", label_b="v2.0.0")
print(patch)
```

### Reading the annotated diff

Every `+` hunk preceded by `# ✓ known` is explained  -  you authored that
annotation. Every `+` hunk **without** it is a candidate for investigation
or a new annotation. That signal is the core value of the know-how file:
it converts a wall of diff noise into a list of things still to understand.

---

## 7. Reference

### CLI commands

```
specprism parse  <spec>               Normalize one spec to IR YAML
specprism diff   <spec_a> <spec_b>    Unified diff of two IR YAMLs
specprism show   <spec> --schema X    Print one resolved schema node
```

### CLI options

| Option | Description |
|---|---|
| `--output <file>` | Write output to file instead of stdout |
| `--knowhow <file>` | Know-how annotation YAML |
| `--no-endpoints` | Skip endpoint nodes (schema-only diff) |
| `--no-descriptions` | Strip descriptions before diff (reduce noise) |

### Annotation kinds

| Kind | Effect |
|---|---|
| `note` | `# note:` comment injected at the matched path |
| `known_change` | `# ✓ known(<from> → <to>):` marker  -  explained delta |
| `equivalence` | `# ≡ <other-path>:` cross-reference on both paths |
| `suppress` | `# suppressed:` tombstone; block removal is planned |

### IR node kinds

| Kind | OpenAPI source |
|---|---|
| `scalar` | `type: string/number/integer/boolean` |
| `object` | `type: object` or `properties` present |
| `array` | `type: array` |
| `union` | `oneOf` or general `anyOf` |
| `intersection` | `allOf` |
| `enum` | `enum: [...]` |
| `any` | no type constraint |

### Nullable normalization

Both OpenAPI 3.0 and 3.1 nullable patterns are normalized to `nullable: true`:

```yaml
# OpenAPI 3.0
score:
  type: number
  nullable: true

# OpenAPI 3.1
score:
  anyOf:
    - type: number
    - type: "null"
```

Both produce:
```yaml
score:
  kind: scalar
  scalar_type: number
  nullable: true
```
