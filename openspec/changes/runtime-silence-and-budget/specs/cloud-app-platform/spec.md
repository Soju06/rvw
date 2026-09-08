## ADDED Requirements

### Requirement: Review tool commands cannot reach remote git or arbitrary hosts

Both container images MUST place PATH shims for `git`, `gh`, `curl`, and `wget` in `/opt/rvw-shims` ahead of the real binaries for login and non-login shells. When `RVW_PHASE` is `review`, the `git` shim MUST refuse `fetch`, `pull`, `clone`, `ls-remote`, `push`, `remote add`/`set-url` and other remote mutations, `submodule add`/`update`/`sync`, `archive --remote`, the remote plumbing commands, and any argument that is an `https://`, `http://`, `ssh://`, `git://`, `git@`, or scp-style URL, printing exactly `rvw: remote git is disabled during review` on stderr with exit 2 while local `git` commands pass through unchanged; the `gh`, `curl`, and `wget` shims MUST refuse every invocation except version and help queries with the analogous one-line refusal and exit 2. Outside the review phase every shim MUST execute the real binary with the original arguments. The images MUST ship an in-image self-test that exercises these rules without network access and MUST run it during the image build. The images MUST keep selecting `danger-full-access` for Codex; the shims narrow tool commands and do not change the sandbox mode.

#### Scenario: Model runs git fetch during review

- **WHEN** a tool command spawned by Codex runs `git fetch origin main` while `RVW_PHASE=review`
- **THEN** the shim prints `rvw: remote git is disabled during review`, exits 2, and the real `git` is not invoked

#### Scenario: Model reads the checkout during review

- **WHEN** a tool command runs `git status`, `git diff`, or `git show` while `RVW_PHASE=review`
- **THEN** the real `git` runs with the original arguments

#### Scenario: CLI provisions the checkout

- **WHEN** rvw's own `git fetch` and `gh repo clone` run with `RVW_PHASE=checkout`
- **THEN** the shims execute the real binaries unchanged

#### Scenario: Model queries the GitHub API during review

- **WHEN** a tool command runs `gh api` or `curl` against any URL while `RVW_PHASE=review`
- **THEN** the shim refuses with `rvw: gh is disabled during review` or `rvw: curl is disabled during review` and exit 2

#### Scenario: Operator runs the self-test in the image

- **WHEN** an operator runs `/usr/local/lib/rvw/check-review-shims.sh` inside a built image
- **THEN** it exits 0 after verifying shim resolution in login and non-login shells and every refusal and pass-through rule without network access

### Requirement: Sandbox egress is allowlisted for the review

The Worker MUST restrict sandbox HTTP(S) egress for the whole run to the configured Codex proxy host, `api.github.com`, and `github.com` by setting the sandbox allowlist beside the credential-injecting per-host handlers, MUST apply the allowlist whether or not an installation token is present, MUST NOT remove `api.github.com` while publication runs inside the container, and MUST document that `github.com` remains reachable after the checkout completes because the clone runs inside the review process.

#### Scenario: Tool command fetches a third-party host

- **WHEN** a process in the sandbox requests any host other than the proxy host, `api.github.com`, or `github.com`
- **THEN** the Worker proxy answers with status 520 and injects no credential

#### Scenario: Codex reaches the proxy

- **WHEN** the Codex CLI requests the configured proxy host
- **THEN** the allowlist admits the request and the Codex credential handler injects the Bearer secret

#### Scenario: CLI clones and publishes

- **WHEN** rvw clones over `github.com` at the start of the run and publishes through `api.github.com` at the end
- **THEN** both hosts are admitted for the whole run with their installation-token handlers

## MODIFIED Requirements

### Requirement: Sandbox egress injects credentials at the proxy boundary

The Worker MUST export the SDK `ContainerProxy` integration, explicitly enable HTTPS interception on its Sandbox subclass, and configure `outboundByHost` at runtime for the required non-secret `CODEX_PROXY_HOST` without a committed fallback host. It MUST inject the `CODEX_API_KEY` Bearer credential only into requests for that configured host and emit a structured injection event that contains the hostname but no credential or authorization header value. The explicit environment passed when starting the sandbox review process MUST contain only a placeholder `CODEX_API_KEY` and the configured proxy `CODEX_BASE_URL`. Inherited endpoint and sandbox defaults MUST NOT override the adapter's explicit effective execution settings; the selected sandbox mode MUST be recorded in the Python process contract. The review allowlist MUST gate every proxied request before handler selection, so a host outside it is refused even when no handler matches.

#### Scenario: Proxied Codex request is made

- **WHEN** a Sandbox request targets the configured proxy host
- **THEN** HTTPS interception invokes the Worker egress hook, the Worker supplies the Bearer secret and logs only the injection event and hostname, and the sandbox-visible credential remains a placeholder

#### Scenario: Different deployers configure different proxy hosts

- **WHEN** two Worker configurations select different non-empty proxy hosts
- **THEN** each configuration registers credential injection only for its selected host
- **AND** an unconfigured environment registers no outbound host
