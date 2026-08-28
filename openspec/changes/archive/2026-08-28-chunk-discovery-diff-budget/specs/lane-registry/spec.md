## ADDED Requirements

### Requirement: Plan exposes chunk-expanded execution counts

`rvw plan` MUST apply the shared diff chunk planner, MUST display the resulting chunk count, and MUST report total runs as active lanes multiplied by replicas multiplied by chunks.

#### Scenario: Three lanes span two chunks

- **WHEN** planning uses three replicas for three active lanes and the target diff produces two chunks
- **THEN** plan displays two chunks and 18 total runs

## MODIFIED Requirements

### Requirement: Review ontology has five execution concepts

The system MUST model a Rule as one atomic check, a Lane as a named rule bundle plus prompt and output contract, a Layer as the activation owner of lanes, a Runtime as the lane execution engine, and a Run as one lane-runtime-replica-chunk execution.

#### Scenario: Plan resolves executions

- **WHEN** a plan activates two lanes with three replicas on one runtime over two chunks
- **THEN** it represents 12 runs while retaining each lane's owning layer and rule bundle
