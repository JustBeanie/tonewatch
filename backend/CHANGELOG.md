# Changelog

## [0.2.0](https://github.com/JustBeanie/tonewatch/compare/v0.1.0...v0.2.0) (2026-09-12)


### Features

* **alerts:** M7 dispatcher, MQTT + HA discovery, webhook, script ([37e7f42](https://github.com/JustBeanie/tonewatch/commit/37e7f4227542eeb87477a0f5d67528693939eeee))
* **api:** M5a FastAPI core, auth and REST (M5.1-M5.3) ([913eaca](https://github.com/JustBeanie/tonewatch/commit/913eaca3cf231a42ecd850de0592e2ff7f1a726f))
* **api:** M5b WebSocket, discovery and generated client (M5.4-M5.6) ([610cec4](https://github.com/JustBeanie/tonewatch/commit/610cec42c4c59c69b7dc096ee240dbbda25191c5))
* **config,storage,events:** M1 domain, config and storage (M1.1-M1.4) ([dc11960](https://github.com/JustBeanie/tonewatch/commit/dc11960aaacc18be569b84bf8878c6aefc81a442))
* **docker:** M8 multi-arch image, hardened compose, signed release pipeline ([d05564e](https://github.com/JustBeanie/tonewatch/commit/d05564e7b017b1f55c0f52ed0f28855188a00169))
* **dsp:** M2 detection engine (M2.1-M2.7) ([f5f10a9](https://github.com/JustBeanie/tonewatch/commit/f5f10a919c143559e9f3ba940838b4c7225fcb3f))
* M0 bootstrap (M0.1-M0.6, M0.7 script) ([6376b07](https://github.com/JustBeanie/tonewatch/commit/6376b07fb749cc7eb65756a831851a26769ad094))
* **pipeline:** M3b channels, supervisor, persistence and watchdog (M3.6-M3.7) ([68eacd3](https://github.com/JustBeanie/tonewatch/commit/68eacd335d9409c520853c3136e78633c14f3e21))
* **pipeline:** W1a wire recorder, watchdog and retention into the app ([be9c198](https://github.com/JustBeanie/tonewatch/commit/be9c198059e0552017ecef28fd4da7823fdf3c89))
* **recording:** M4 call recording, encoding and retention (M4.1-M4.4) ([3fda355](https://github.com/JustBeanie/tonewatch/commit/3fda355d4456292dd16f45d7c5b078191b878208))
* **security:** S1 baseline OWASP SAMM v2 + DSOMM assessment ([bb5ef72](https://github.com/JustBeanie/tonewatch/commit/bb5ef72f0b867b969bc45304eac7f03dbc20b95b))
* **security:** S2 DSOMM L1-2 pipeline controls ([3235dfc](https://github.com/JustBeanie/tonewatch/commit/3235dfcdce11cce81d72efa99378b2ec0edc3c32))
* **security:** S4 OWASP ASVS 5.0 L2 audit, stream SSRF hardening, audit trail ([45850f9](https://github.com/JustBeanie/tonewatch/commit/45850f9bf9493f19827290c6d3e73105b17b4b83))
* **security:** S5 DAST, compose hardening, ASVS evidence snippets, exact action pins ([d3643d5](https://github.com/JustBeanie/tonewatch/commit/d3643d532c6f3a081141f759638c2d6e5d816b61))
* **sources:** M3a audio sources (M3.1-M3.5) + working license gate ([7a86152](https://github.com/JustBeanie/tonewatch/commit/7a8615267623c20e40696ec1cfc5a8f75f0548f0))
* **web:** M6a app shell, dashboard, calls and tone sets (M6.1-M6.4) ([afb2ed0](https://github.com/JustBeanie/tonewatch/commit/afb2ed0d47c7658e9fcba40b2104e4bba258906a))
* **web:** W1b backend serves the SPA; real single-port Playwright e2e (M6.9) ([20338c2](https://github.com/JustBeanie/tonewatch/commit/20338c267190f7316b2d6058cfc999dd5f77bd0c))


### Bug Fixes

* **alerts:** W1a-fix persisted recording URLs, tone-set hot reload, shutdown finalize ([9ef8f0c](https://github.com/JustBeanie/tonewatch/commit/9ef8f0cfb0ddb75d4fa5ff22d351fef11f209441))
* **api:** S5 DAST findings - login 500 on malformed bodies, CSP and cross-origin headers ([20d70e3](https://github.com/JustBeanie/tonewatch/commit/20d70e3e6287c764fd9f26bc9002536e15ce7cfe))
* **api:** validate the trusted ingress path before building the SPA base ([37190b8](https://github.com/JustBeanie/tonewatch/commit/37190b8fa65737261a6be7d59ad4088570f00aab))
* **docker:** M8-fix2 runtime dependency closure, slimmer and trivy-clean image ([4d392c2](https://github.com/JustBeanie/tonewatch/commit/4d392c2d03c6894c93cc9915148858bc3435f217))
* **pipeline:** W1a-fix2/3 bounded shutdown, no task leaks, safe orphan reconcile ([e352849](https://github.com/JustBeanie/tonewatch/commit/e3528490bae847f3228b957369d8335065b207fc))
* **recording:** W1a-fix4 propagate cancellation after finalizing a recording ([c5ec841](https://github.com/JustBeanie/tonewatch/commit/c5ec84169891afe746890f8cadff7d284e3c75d2))


### Documentation

* **security:** S3 STRIDE threat model ([9ea239a](https://github.com/JustBeanie/tonewatch/commit/9ea239a58c3174397754eee7268e6cda8bcfcef4))
