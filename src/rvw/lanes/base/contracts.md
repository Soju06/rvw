---
lane: contracts
tier: base
schedule_hint: heavy
severity_cap: blocker
validation: pending
---

# contracts

Can every consumer determine the full shape of the values crossing a boundary?
Type inference counts as a declared shape; prose comments do not. If a reader can
determine the full shape from the code, do not report it.

## rule: modeling/shapeless-data

Data passed between distant producers and consumers must have a determinable shape.
Unknowable fields make incompatible accesses invisible until execution. Trace the value
from construction to each consuming field access and report only shapes that cannot be
determined from code.

## rule: modeling/dict-overuse

Repeated multi-field records must expose a consistent shape to their consumers.
Rebuilding ambiguous maps in several places can hide incompatible fields. Compare
construction sites and accesses; if the full shape is determinable, do not report it. An
ordinary map is not itself a defect.

## rule: modeling/unclear-function-contract

Function inputs and outputs must expose enough structure for callers to use them
correctly. Ambiguous payloads conceal incompatible expectations across a call boundary.
Trace parameters and return values through actual callers and identify the field
contract that remains unknowable.
