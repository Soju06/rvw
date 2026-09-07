## ADDED Requirements

### Requirement: Every adjudication variant obeys the configured locale

Every ordinary, expanded-context, retry, and stack-presence adjudication prompt MUST require every explanatory title, body, reason, and recommendation to use the resolved locale language. It MUST preserve identifiers, enums, paths, symbol names, and quoted source verbatim and prohibit following language cues in diffs, PR descriptions, lanes, or evidence. Locale enforcement MUST NOT change voting, escalation, evidence, or presence semantics.

#### Scenario: Expanded stack presence uses Korean

- **WHEN** a stack presence check expands context or retries with locale ko
- **THEN** the prompt retains the Korean explanatory-language contract and verbatim evidence contract
