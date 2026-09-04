# Changelog

## [0.11.5](https://github.com/Soju06/rvw/compare/v0.11.4...v0.11.5) (2026-09-04)


### Bug Fixes

* pin GitHub CLI in container images ([#67](https://github.com/Soju06/rvw/issues/67)) ([8167dfb](https://github.com/Soju06/rvw/commit/8167dfba55f1d34d280c2725de76dea486b7da87))

## [0.11.4](https://github.com/Soju06/rvw/compare/v0.11.3...v0.11.4) (2026-09-04)


### Bug Fixes

* **cloud:** preserve A1 process artifacts ([#64](https://github.com/Soju06/rvw/issues/64)) ([09ba6c0](https://github.com/Soju06/rvw/commit/09ba6c0900917ef935050db0ea8e6f2721bbae55))

## [0.11.3](https://github.com/Soju06/rvw/compare/v0.11.2...v0.11.3) (2026-09-04)


### Bug Fixes

* **cloud:** make the rollout/health gate observe real fields ([#62](https://github.com/Soju06/rvw/issues/62)) ([379ff5b](https://github.com/Soju06/rvw/commit/379ff5bc3c376cfda787f4903fc574c3393a8911))

## [0.11.2](https://github.com/Soju06/rvw/compare/v0.11.1...v0.11.2) (2026-09-04)


### Bug Fixes

* **cloud:** take the rvw repository as an input in rvw-deploy.yml ([#60](https://github.com/Soju06/rvw/issues/60)) ([17700f6](https://github.com/Soju06/rvw/commit/17700f653f22dfccaaaa9629468f21156dfaa568))

## [0.11.1](https://github.com/Soju06/rvw/compare/v0.11.0...v0.11.1) (2026-09-04)


### Bug Fixes

* **cloud:** check out rvw from the workflow-owning repo in rvw-deploy.yml ([#58](https://github.com/Soju06/rvw/issues/58)) ([91047db](https://github.com/Soju06/rvw/commit/91047db1863186ae4e782d87f5a61545251cae49))

## [0.11.0](https://github.com/Soju06/rvw/compare/v0.10.0...v0.11.0) (2026-09-03)


### Features

* **cloud:** publish reusable deployment artifacts ([#56](https://github.com/Soju06/rvw/issues/56)) ([4e19678](https://github.com/Soju06/rvw/commit/4e1967892260df3f3f9864e5128b297b3020f2ad))

## [0.10.0](https://github.com/Soju06/rvw/compare/v0.9.1...v0.10.0) (2026-09-03)


### Features

* **cloud:** add locked R2 terraform state ([#53](https://github.com/Soju06/rvw/issues/53)) ([7866f98](https://github.com/Soju06/rvw/commit/7866f987ddb864842648f2004ceb9cc9a57f062a))


### Bug Fixes

* **cloud:** remove deployer-specific defaults ([#54](https://github.com/Soju06/rvw/issues/54)) ([1ce668d](https://github.com/Soju06/rvw/commit/1ce668dc86de02a69147fd18276d53511825cb7f))

## [0.9.1](https://github.com/Soju06/rvw/compare/v0.9.0...v0.9.1) (2026-09-03)


### Bug Fixes

* **cloud:** drop implicit installation events from the App manifest ([#51](https://github.com/Soju06/rvw/issues/51)) ([5d4822c](https://github.com/Soju06/rvw/commit/5d4822c0e6f22580fb744fb19642754ee57c2ffc))

## [0.9.0](https://github.com/Soju06/rvw/compare/v0.8.1...v0.9.0) (2026-09-03)


### Features

* **cloud:** add durable GitHub review pipeline ([#49](https://github.com/Soju06/rvw/issues/49)) ([3e13639](https://github.com/Soju06/rvw/commit/3e136391d84ecf4c57feacb9dc441e1eaa9743e9))

## [0.8.1](https://github.com/Soju06/rvw/compare/v0.8.0...v0.8.1) (2026-09-03)


### Bug Fixes

* **cloud:** land A0-measured sandbox defects ([#46](https://github.com/Soju06/rvw/issues/46)) ([2320eab](https://github.com/Soju06/rvw/commit/2320eab520a915c780dfd7b7665aa7e74f74463a))

## [0.8.0](https://github.com/Soju06/rvw/compare/v0.7.1...v0.8.0) (2026-09-02)


### Features

* Cloudflare GitHub App platform IaC scaffold ([#43](https://github.com/Soju06/rvw/issues/43)) ([d1935de](https://github.com/Soju06/rvw/commit/d1935de3631cbfc0ecdd451026cfa00bb80fface))

## [0.7.1](https://github.com/Soju06/rvw/compare/v0.7.0...v0.7.1) (2026-09-02)


### Bug Fixes

* **registry:** honor project lane path activation ([#41](https://github.com/Soju06/rvw/issues/41)) ([6ef9aac](https://github.com/Soju06/rvw/commit/6ef9aac7055f3bbe194162c0d2f08d1882376acb))

## [0.7.0](https://github.com/Soju06/rvw/compare/v0.6.1...v0.7.0) (2026-09-02)


### Features

* **ci:** add containerized rvw review packaging ([#39](https://github.com/Soju06/rvw/issues/39)) ([bb26ff0](https://github.com/Soju06/rvw/commit/bb26ff070cd957e8a70b6b72b9e877984f26a635))
* **registry+discovery:** single-file lane SoT with in-repo .rvw/ + agentic discovery runtime ([#38](https://github.com/Soju06/rvw/issues/38)) ([d4f2869](https://github.com/Soju06/rvw/commit/d4f2869d85ff011e505bca13ee881ad15934add6))
* **release:** publish GHCR images from tags ([#40](https://github.com/Soju06/rvw/issues/40)) ([cccccaa](https://github.com/Soju06/rvw/commit/cccccaa292c2bb3b52f4bd756ec4e90e282ed146))
* **runtime:** bound review execution ([#29](https://github.com/Soju06/rvw/issues/29)) ([3c625a1](https://github.com/Soju06/rvw/commit/3c625a1b7d93556fb7fabe412c60548948bf1eda))

## [0.6.1](https://github.com/Soju06/rvw/compare/v0.6.0...v0.6.1) (2026-08-28)


### Bug Fixes

* **build:** keep the sdist-stamped commit when building the wheel ([#33](https://github.com/Soju06/rvw/issues/33)) ([55eccae](https://github.com/Soju06/rvw/commit/55eccaefa1ed661768b707f91ce630cc41241cd4))

## [0.6.0](https://github.com/Soju06/rvw/compare/v0.5.0...v0.6.0) (2026-08-28)


### Features

* **build:** embed honest build provenance ([#32](https://github.com/Soju06/rvw/issues/32)) ([f868c74](https://github.com/Soju06/rvw/commit/f868c743b6997edd6f03b3ab5871e26d5ff317d5))


### Bug Fixes

* **review:** fail closed on lost review execution ([#30](https://github.com/Soju06/rvw/issues/30)) ([38389cb](https://github.com/Soju06/rvw/commit/38389cb5953d6fc59fcc569c1f5ef8a484fc50fc))

## [0.5.0](https://github.com/Soju06/rvw/compare/v0.4.1...v0.5.0) (2026-08-28)


### Features

* **discover:** preserve attempt-level status across the retry wave ([#18](https://github.com/Soju06/rvw/issues/18)) ([9722d3f](https://github.com/Soju06/rvw/commit/9722d3fe4be9118610d82427b80e145ecb3be9fc))
* **dispatch:** gate runtime execution behind host-global flock slots ([#19](https://github.com/Soju06/rvw/issues/19)) ([a34801f](https://github.com/Soju06/rvw/commit/a34801f377e64b42d966f69aee0aa9f064d273c5))
* **gate:** inherit accepted dispositions across runs with --inherit ([#8](https://github.com/Soju06/rvw/issues/8)) ([e31908c](https://github.com/Soju06/rvw/commit/e31908c9bac3b60d97ea85b0826d3c882af7c2f4))
* **gate:** sticky accepted dispositions for unique non-blocker recurrences ([#20](https://github.com/Soju06/rvw/issues/20)) ([04dc4d6](https://github.com/Soju06/rvw/commit/04dc4d658e2ea2f4f73efd1416e6af763fba306d))
* **review:** 3-replica adjudication default + gate disposition auto-inherit ([#17](https://github.com/Soju06/rvw/issues/17)) ([00cefac](https://github.com/Soju06/rvw/commit/00cefac0c1f1a56494e328ee67c91ce6920a54a9))
* **review:** default to single-pass review (replicas=1) ([#7](https://github.com/Soju06/rvw/issues/7)) ([0deac24](https://github.com/Soju06/rvw/commit/0deac24d1f76d3c29c485410c161cfacd56c837b))
* **runtime:** expose configurable deadlines ([#22](https://github.com/Soju06/rvw/issues/22)) ([d1a7b9a](https://github.com/Soju06/rvw/commit/d1a7b9a50892e5fc4c735aef465158ff90a0eac6))
* **stack:** add explicit stacked PR review workflow ([#10](https://github.com/Soju06/rvw/issues/10)) ([5353e19](https://github.com/Soju06/rvw/commit/5353e191a701a044baf769c7e92e84c5c9f61aa4))


### Bug Fixes

* **cost:** stop sending discovery-excluded diff content to later stages ([#25](https://github.com/Soju06/rvw/issues/25)) ([9897672](https://github.com/Soju06/rvw/commit/9897672c58b2d5dbbab8942d51c3324b64225f88))
* **dispatch:** lower default runtime concurrency to 8 and expose --concurrency ([#13](https://github.com/Soju06/rvw/issues/13)) ([1e1e8cc](https://github.com/Soju06/rvw/commit/1e1e8cc428e6760380787b26a5ac00453284400c))
* **store,dispatch:** make concurrent same-target runs safe and preserve retry evidence ([#16](https://github.com/Soju06/rvw/issues/16)) ([962293a](https://github.com/Soju06/rvw/commit/962293af961b6be0d29b0c76d07f2c9f1318ccff))

## [0.4.1](https://github.com/Soju06/rvw/compare/v0.4.0...v0.4.1) (2026-07-29)


### Bug Fixes

* **sample:** pass unified-diff fixtures through and fail closed on empty review diffs ([b6b7704](https://github.com/Soju06/rvw/commit/b6b7704f25d2e3f2a4dedceff60350baab780e82))

## [0.4.0](https://github.com/Soju06/rvw/compare/v0.3.0...v0.4.0) (2026-07-29)


### Features

* **discovery:** replace the diff budget dead end with chunked discovery ([1d57691](https://github.com/Soju06/rvw/commit/1d5769194b0eef18122d5127de1d0fdeeb9d255e))


### Bug Fixes

* **release:** require RELEASE_PLEASE_TOKEN PAT and drop the reusable-workflow publish chain ([c913d18](https://github.com/Soju06/rvw/commit/c913d18f8a0e63fbb46eb76427be1c643ede54f5))

## [0.3.0](https://github.com/Soju06/rvw/compare/v0.2.0...v0.3.0) (2026-07-28)


### Features

* **registry:** support glob patterns and lists in layer repo predicate ([9cf6a69](https://github.com/Soju06/rvw/commit/9cf6a6998623c6b8a10c1d54f3193173bfa2cca0))
