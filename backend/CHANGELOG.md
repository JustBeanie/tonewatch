# Changelog

## [0.5.0](https://github.com/JustBeanie/tonewatch/compare/v0.4.0...v0.5.0) (2026-09-17)


### Features

* **admin:** M19.2 admin alerts ([a402246](https://github.com/JustBeanie/tonewatch/commit/a4022469b0c7a798e2dc6c40440b4c9f41878646))
* **alerts:** M18.4 Meshtastic alert-target form with byte-count preview ([3eacfd1](https://github.com/JustBeanie/tonewatch/commit/3eacfd18ef72c9a49ec15866f6f49a2d0fceddb6))


### Bug Fixes

* **deps:** bundle tzdata so IANA time zones work on Windows ([bf53af0](https://github.com/JustBeanie/tonewatch/commit/bf53af033a596af12d86062cd786c663560f2f15))

## [0.4.0](https://github.com/JustBeanie/tonewatch/compare/v0.3.0...v0.4.0) (2026-09-16)


### Features

* **admin:** M19.1 and M19.3 admin health API, delivery log and audited retry ([f0c43f9](https://github.com/JustBeanie/tonewatch/commit/f0c43f9d6defb21586618025f44b6498e8a8f9bc))
* **agencies:** M16.1-M16.3 agencies, GeoJSON API, call agency snapshot and map tiles ([8d4b5b5](https://github.com/JustBeanie/tonewatch/commit/8d4b5b5eaeaac3b7feb167551316301e28cb6843))
* **alerts:** M18.1-M18.3 Meshtastic alert target via MQTT JSON downlink ([f2885f1](https://github.com/JustBeanie/tonewatch/commit/f2885f19891ba3d896d62888232c594408ec4994))
* **live:** M14.1-M14.3, M14.6 live MP3 restream with signed URLs ([c0e2305](https://github.com/JustBeanie/tonewatch/commit/c0e2305e88d1bc729891aa517f465cbd4f38fcd7))
* **squelch:** M15.1-M15.4 software squelch, activity sensor and live-stream gate ([f643f97](https://github.com/JustBeanie/tonewatch/commit/f643f97a4c47f68a445558c473869cafc3ed6bb6))
* **squelch:** M15.6-M15.7 auto squelch, calibrate endpoint and squelch diagnostics ([ade9b0a](https://github.com/JustBeanie/tonewatch/commit/ade9b0a1b2d1dd1abfb417bb7c27676e3ee824f1))

## [0.3.0](https://github.com/JustBeanie/tonewatch/compare/v0.2.0...v0.3.0) (2026-09-12)


### Features

* **addon:** M10a add-on mode: Supervisor MQTT credentials, media recordings, discovery, db checkpoint (M10.2) ([3bd69f4](https://github.com/JustBeanie/tonewatch/commit/3bd69f46293194f35e96e8d9461eb37cb56bcbb3))
* **discovery:** M13 tone auto-discovery (M13.1-M13.7) ([a8962cc](https://github.com/JustBeanie/tonewatch/commit/a8962cc322379b9d8f5bac85a32a37c065fcdc98))
* **import:** M8.4 legacy tones.cfg importer with preview/apply API, CLI and UI ([7ca38fa](https://github.com/JustBeanie/tonewatch/commit/7ca38fa7e3aebc1231cf43289d07172f3a1c2d13))
* **windows:** M9 native Windows build, service wrapper and windows.yml (M9.1-M9.3) ([897fa56](https://github.com/JustBeanie/tonewatch/commit/897fa5627dd336f22196202341d9f02d6f488858))


### Bug Fixes

* **ci:** cross-platform uninstall test and windows.yml step exit code ([250221e](https://github.com/JustBeanie/tonewatch/commit/250221eb660b583172e9a67ed4426b2a24dd03a5))
* **ci:** keep the image under 350 MB and wait for Windows service state changes ([b743562](https://github.com/JustBeanie/tonewatch/commit/b743562de9b8c0a4b688ceced7fc0986a67eaa5e))
* **ci:** Windows service logging, marker-aware runtime export check, Debian security upgrades ([9d5e0ef](https://github.com/JustBeanie/tonewatch/commit/9d5e0ef954bf0ad2c507f13bb21676ee425c2b64))
* **sources:** looping file source rewound stream time and lost realtime pacing ([89b3795](https://github.com/JustBeanie/tonewatch/commit/89b3795e0028d941eadbd60affb42369493c36c5))
* **windows:** open the service with win32con.DELETE for uninstall ([32a9768](https://github.com/JustBeanie/tonewatch/commit/32a97686cee000f9af5332f0490b147397c69f33))


### Documentation

* M12.1 documentation site and M12.3 radio-recording disclaimer ([0801228](https://github.com/JustBeanie/tonewatch/commit/08012281132f1847403ea58a27f7da074cc31e0f))

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
