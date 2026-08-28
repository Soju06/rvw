# Changelog

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
