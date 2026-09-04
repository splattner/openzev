# Changelog

## [1.9.0](https://github.com/splattner/openzev/compare/v1.8.1...v1.9.0) (2026-09-04)


### Features

* **docs:** crop a generated PDF down to a release-note figure ([#550](https://github.com/splattner/openzev/issues/550)) ([00ffb58](https://github.com/splattner/openzev/commit/00ffb585d20dfb919098ad14f535326c04a6988f))
* **docs:** screenshots in release notes ([#549](https://github.com/splattner/openzev/issues/549)) ([cced026](https://github.com/splattner/openzev/commit/cced026c046435e036f1749ef39f4c1de02ecbc5))
* **invoices:** itemise a multi-band tariff's bands on the invoice ([#547](https://github.com/splattner/openzev/issues/547)) ([6dc9edf](https://github.com/splattner/openzev/commit/6dc9edfd63ba16d2cecec695caa13e20db1fbebe)), closes [#546](https://github.com/splattner/openzev/issues/546)
* **invoices:** VAT mode with an "inclusive" treatment for non-registered ZEVs ([#543](https://github.com/splattner/openzev/issues/543)) ([6f55aa3](https://github.com/splattner/openzev/commit/6f55aa3296663777e74edb2c2cd8a927afeb2984))

## [1.8.1](https://github.com/splattner/openzev/compare/v1.8.0...v1.8.1) (2026-09-04)


### Bug Fixes

* **chart:** expose CSRF_TRUSTED_ORIGINS for domain deployments ([#540](https://github.com/splattner/openzev/issues/540)) ([d54226d](https://github.com/splattner/openzev/commit/d54226dbc44e0254bb9ca18c3f1bc506eafcb365))

## [1.8.0](https://github.com/splattner/openzev/compare/v1.7.0...v1.8.0) (2026-09-04)


### Features

* **accounts:** rate-limit public auth endpoints ([#433](https://github.com/splattner/openzev/issues/433)) ([b9b8a13](https://github.com/splattner/openzev/commit/b9b8a130ce036a980672dfb9a8f1723a92520380))
* **allocation,invoices,metering:** read-model + consumer migration for shared metering points ([#461](https://github.com/splattner/openzev/issues/461)) ([9fc340e](https://github.com/splattner/openzev/commit/9fc340eaf05bcaed4ca56940e1decd9a32fe7385))
* **frontend,docs:** shared metering points UI and baseline spec updates ([#464](https://github.com/splattner/openzev/issues/464)) ([2394524](https://github.com/splattner/openzev/commit/2394524da1f480917430f60d962ec102381b4eed)), closes [#387](https://github.com/splattner/openzev/issues/387)
* **i18n:** migrate hardcoded strings and add locale parity enforcement ([#452](https://github.com/splattner/openzev/issues/452)) ([86fae7c](https://github.com/splattner/openzev/commit/86fae7ce161feb43b5b5573f1914257d570ab4ec))
* **invoices,frontend:** split_key for SHARED_* fees ([#462](https://github.com/splattner/openzev/issues/462)) ([3dac9f0](https://github.com/splattner/openzev/commit/3dac9f00f9adeb2a29e2474ed1725db74253571b)), closes [#387](https://github.com/splattner/openzev/issues/387)
* **invoices:** allocation-weight primitive for shared metering points ([#460](https://github.com/splattner/openzev/issues/460)) ([63c804a](https://github.com/splattner/openzev/commit/63c804abb61c3890db89ed86bbef223c3786c5ea))
* **invoices:** community billing for shared metering points ([#463](https://github.com/splattner/openzev/issues/463)) ([d1e3d7d](https://github.com/splattner/openzev/commit/d1e3d7def488c654e88b178aa743e08dd5a3abf2)), closes [#387](https://github.com/splattner/openzev/issues/387)
* **invoices:** issue versioned contract snapshots on download ([#443](https://github.com/splattner/openzev/issues/443)) ([348df53](https://github.com/splattner/openzev/commit/348df53f2a5b7ea75ce5b68111feedb9a472af2a))
* **invoices:** redesign the participation contract PDF and harden template overrides ([#442](https://github.com/splattner/openzev/issues/442)) ([bce8bb1](https://github.com/splattner/openzev/commit/bce8bb13e933c8ae190e612a573f5d7feaec29db))
* **reports:** move document downloads to /reports and slim dashboard ([#503](https://github.com/splattner/openzev/issues/503)) ([402958c](https://github.com/splattner/openzev/commit/402958cc12d8f2064daab4485d7b0f1e89969d40))
* **tariffs:** import tariffs from a grid operator's Art. 7b publication ([#533](https://github.com/splattner/openzev/issues/533)) ([f440c8c](https://github.com/splattner/openzev/commit/f440c8c1da5840223df3d44a429a51fca34c2a05)), closes [#507](https://github.com/splattner/openzev/issues/507)
* **tariffs:** price bands can apply in only some months ([#531](https://github.com/splattner/openzev/issues/531)) ([b731a88](https://github.com/splattner/openzev/commit/b731a88bf767ad81911353457a70d9560ad3cf84))
* **tariffs:** tariffs can carry more than a high and a low price band ([#534](https://github.com/splattner/openzev/issues/534)) ([f364ae3](https://github.com/splattner/openzev/commit/f364ae358fb46fb05f434d0191af516da5b5f5ab)), closes [#528](https://github.com/splattner/openzev/issues/528)
* **tokens:** enforce brand-ramp luminance monotonicity ([#522](https://github.com/splattner/openzev/issues/522)) ([c542b2d](https://github.com/splattner/openzev/commit/c542b2d5cd58200060028164ef9efb2b6b8012f3))
* **ui:** print-parity redesign — single-source tokens, MUI retirement, real PDF previews ([#470](https://github.com/splattner/openzev/issues/470)) ([a26a27a](https://github.com/splattner/openzev/commit/a26a27ac82be3d6fe5afa607c1b94b9547b50e6c))
* **ui:** shared PageSkeleton variants and EmptyState factory ([#502](https://github.com/splattner/openzev/issues/502)) ([50016d5](https://github.com/splattner/openzev/commit/50016d58732e5863e7458943abe88dd553426383))
* **zev:** pick the grid operator from the official ElCom list ([#519](https://github.com/splattner/openzev/issues/519)) ([10f8815](https://github.com/splattner/openzev/commit/10f88153a29191c748aac483f8c9fe2f9b380536)), closes [#518](https://github.com/splattner/openzev/issues/518)


### Bug Fixes

* **accounts:** make OAuth client secret write-only ([#432](https://github.com/splattner/openzev/issues/432)) ([40caa3f](https://github.com/splattner/openzev/commit/40caa3f23d2ea5d962f4fd88373d1e108b9778fa))
* **accounts:** restrict /auth/users/ to admins ([#430](https://github.com/splattner/openzev/issues/430)) ([305d262](https://github.com/splattner/openzev/commit/305d262ea33ae7308f96f3ebabde35e112af6da2))
* **compose:** mount postgres_data at one path and pin PGDATA inside it ([#513](https://github.com/splattner/openzev/issues/513)) ([50b0e77](https://github.com/splattner/openzev/commit/50b0e7706c5cb1bc345a897150e9844f20a678b4)), closes [#492](https://github.com/splattner/openzev/issues/492)
* **compose:** proxy API same-origin to restore cookie CSRF ([#453](https://github.com/splattner/openzev/issues/453)) ([61a4aa8](https://github.com/splattner/openzev/commit/61a4aa8db37897d94a503fe27c4ac34b494bde70))
* **contracts:** move contract-PDF issuance from GET to POST ([#508](https://github.com/splattner/openzev/issues/508)) ([dec93e8](https://github.com/splattner/openzev/commit/dec93e8b4b28aad4460f8f9dc533471f987dc7ba)), closes [#448](https://github.com/splattner/openzev/issues/448)
* **css:** stop the global input width:100% from stretching checkboxes ([#510](https://github.com/splattner/openzev/issues/510)) ([0afc527](https://github.com/splattner/openzev/commit/0afc527e2a4a21ce352fc7164f0ff36d76583a39)), closes [#490](https://github.com/splattner/openzev/issues/490)
* **engine:** round total_feed_in_kwh with ROUND_HALF_UP like the sibling kWh totals ([#521](https://github.com/splattner/openzev/issues/521)) ([a75fb2d](https://github.com/splattner/openzev/commit/a75fb2d06c91bd190d9d8c3fc31781935c956755))
* **engine:** shared metering gap logging and CHF 0.00 line gates ([#479](https://github.com/splattner/openzev/issues/479)) ([b890cec](https://github.com/splattner/openzev/commit/b890cec3a29962dfb5505e2552f8a6d9908a11eb))
* **engine:** stop reading MeteringPoint.is_active when pricing a period ([#514](https://github.com/splattner/openzev/issues/514)) ([b1dcdd9](https://github.com/splattner/openzev/commit/b1dcdd9b8529d28d0bc6e29476c5efade3a79ad6)), closes [#408](https://github.com/splattner/openzev/issues/408)
* **frontend:** fetch every page of DRF-paginated list endpoints ([#484](https://github.com/splattner/openzev/issues/484)) ([6a26aa3](https://github.com/splattner/openzev/commit/6a26aa3e74ed1f789e9866d14cb5f938150b8a3b))
* **frontend:** let owners of multiple ZEVs switch between them ([#481](https://github.com/splattner/openzev/issues/481)) ([1c7467d](https://github.com/splattner/openzev/commit/1c7467df2451760b3c9e4da17b4134d942ef5bd3))
* **i18n:** translate confirm-dialog defaults, participant validation, and chart tooltip ([#525](https://github.com/splattner/openzev/issues/525)) ([0e58f51](https://github.com/splattner/openzev/commit/0e58f51cba1b9c692fa9ccbfc02d7da9c9dc94e8))
* **invoices:** clamp weight-split denominators to the tariff's own validity ([#466](https://github.com/splattner/openzev/issues/466)) ([d8e0c25](https://github.com/splattner/openzev/commit/d8e0c250e034334e18ed1d3998adc9a962c34770)), closes [#465](https://github.com/splattner/openzev/issues/465) [#387](https://github.com/splattner/openzev/issues/387)
* **invoices:** server-side status filter for the dashboard open-invoice list ([#485](https://github.com/splattner/openzev/issues/485)) ([bb4b755](https://github.com/splattner/openzev/commit/bb4b75520ba138792e8b4d407171542139af3e4b))
* **media:** close unauthenticated /media/ PDF path, use authenticated API endpoint URL ([#474](https://github.com/splattner/openzev/issues/474)) ([a81fdd3](https://github.com/splattner/openzev/commit/a81fdd39be3de2516935d9a92e7684baa44bdbc8))
* **media:** stop proxying unauthenticated /media/ PDFs in compose nginx ([#516](https://github.com/splattner/openzev/issues/516)) ([39c7ed8](https://github.com/splattner/openzev/commit/39c7ed80a526fe8d909d85e6e24c0d76038daefc))
* **models:** give every paginated list ordering a unique tiebreaker ([#512](https://github.com/splattner/openzev/issues/512)) ([388274c](https://github.com/splattner/openzev/commit/388274c1a1333970470cc531db3166d82fd616c4)), closes [#489](https://github.com/splattner/openzev/issues/489)
* **security:** enforce CSRF for cookie JWT sessions ([#446](https://github.com/splattner/openzev/issues/446)) ([ea8f91f](https://github.com/splattner/openzev/commit/ea8f91f8d2c3f70101742fdebd0af42a6dd94dd1))
* **security:** harden upload parsing against zip bombs and parse loops ([#449](https://github.com/splattner/openzev/issues/449)) ([b7a1b75](https://github.com/splattner/openzev/commit/b7a1b75935d18d820ba4952886989cfd7496c714))
* **security:** restrict render fetches and harden template preview ([#469](https://github.com/splattner/openzev/issues/469)) ([e51057b](https://github.com/splattner/openzev/commit/e51057bcd8ceb507286032bf071ba4420c02a257))
* **tariffs:** preserve split_key on new-version and duplicate ([#473](https://github.com/splattner/openzev/issues/473)) ([f3e33ee](https://github.com/splattner/openzev/commit/f3e33ee60927e6f8af2c224325aa23018259cd85))
* **ui:** migrate account page and admin overview to the page contract ([#486](https://github.com/splattner/openzev/issues/486)) ([6ea75b3](https://github.com/splattner/openzev/commit/6ea75b37f384ef41e6f52be1c6b78ba0cd1147bc))


### Performance Improvements

* **docker:** add a .dockerignore, shrinking the build context 930 MB -&gt; 8 MB ([#475](https://github.com/splattner/openzev/issues/475)) ([2b49dd7](https://github.com/splattner/openzev/commit/2b49dd75b5975bee6bb109976e43fb829fc6e61d))
* **invoices:** drop nested items and email logs from the invoice list ([#509](https://github.com/splattner/openzev/issues/509)) ([6258b5a](https://github.com/splattner/openzev/commit/6258b5a1d8a972613b5d275c980810dc939cff27)), closes [#488](https://github.com/splattner/openzev/issues/488)
* **tests:** parallelize suite with pytest-xdist, tag slow PDF tests ([#523](https://github.com/splattner/openzev/issues/523)) ([71892d8](https://github.com/splattner/openzev/commit/71892d887af74d92a6ad31c1b5fbcc03ccd80094))

## [1.7.0](https://github.com/splattner/openzev/compare/v1.6.0...v1.7.0) (2026-08-10)


### Features

* **accounts:** admin console for API key management ([#409](https://github.com/splattner/openzev/issues/409)) ([d665a68](https://github.com/splattner/openzev/commit/d665a680494e9d5142cd89461633a7e62b3a02e6))
* **accounts:** API keys for direct API access ([#395](https://github.com/splattner/openzev/issues/395)) ([5ce8145](https://github.com/splattner/openzev/commit/5ce814543fed7c105e9d7e0dab42f9ff366a5958))
* **allocation:** shared local-pool allocation service (ADR 0013) ([#383](https://github.com/splattner/openzev/issues/383)) ([9538663](https://github.com/splattner/openzev/commit/95386638245bd50bc2eada4988860f32f2c05975))
* **audit:** add scoped ZEV and actor filters ([#421](https://github.com/splattner/openzev/issues/421)) ([dde9f6f](https://github.com/splattner/openzev/commit/dde9f6fc0b82e6799af3254e264063a2b6d84113))
* **invoices:** redesign invoice PDF and split generation modules ([#379](https://github.com/splattner/openzev/issues/379)) ([1c3353e](https://github.com/splattner/openzev/commit/1c3353e5a91ad024f92f527fc1feea3059a9cd4f))
* **invoices:** remove three steps from the billing run ([#382](https://github.com/splattner/openzev/issues/382)) ([f687104](https://github.com/splattner/openzev/commit/f687104c19d92f80edd6c053a959720de9dc8ed1))
* **metering:** flag holder-less readings in data-quality status ([#396](https://github.com/splattner/openzev/issues/396)) ([7afe033](https://github.com/splattner/openzev/commit/7afe0336ae0aaf4fa84d3079b95152136cbdb15f))
* **zev:** whole-ZEV export and import, replacing the tariff-only transfer ([#410](https://github.com/splattner/openzev/issues/410)) ([b58c657](https://github.com/splattner/openzev/commit/b58c657a55bd59b7f4e069f8a643559ebf779129))


### Bug Fixes

* **allocation:** give allocation failures their own exception taxonomy ([#392](https://github.com/splattner/openzev/issues/392)) ([6a1c984](https://github.com/splattner/openzev/commit/6a1c98475c81f767d5f6cb2eff5fec89391ca392))
* **docker:** wait for migrations before seeding demo data ([#376](https://github.com/splattner/openzev/issues/376)) ([028d1e7](https://github.com/splattner/openzev/commit/028d1e7ee9e8a13b7ea27f4ba86c9329c6db159b))
* **i18n:** use RCP term in French and Italian UI ([#422](https://github.com/splattner/openzev/issues/422)) ([0726c99](https://github.com/splattner/openzev/commit/0726c99fe5aa480bddca4ef1a0e02b34e43c7a0e))
* **invoices:** isolate bulk generation failures per participant ([#394](https://github.com/splattner/openzev/issues/394)) ([549ce97](https://github.com/splattner/openzev/commit/549ce97cfda6a8017c140cf9f274f00f00aa71e0))
* **invoices:** make the annual-statement local pool physical ([#406](https://github.com/splattner/openzev/issues/406)) ([5bee49c](https://github.com/splattner/openzev/commit/5bee49cf78a1b03495824923e7b61bde6b939f20))
* **invoices:** scope invoice-number uniqueness to the ZEV ([#405](https://github.com/splattner/openzev/issues/405)) ([6ce3f79](https://github.com/splattner/openzev/commit/6ce3f79ee19eca4b8f3e4183f895bd255a7d6960)), closes [#401](https://github.com/splattner/openzev/issues/401)
* **zev:** enforce assignment non-overlap rule on save() ([#390](https://github.com/splattner/openzev/issues/390)) ([a16c5bc](https://github.com/splattner/openzev/commit/a16c5bc903e5bf9619e8a2c7ca026d8f765c47b7))
* **zev:** harden whole-ZEV transfer archives against malformed and inconsistent input ([#415](https://github.com/splattner/openzev/issues/415)) ([f29515f](https://github.com/splattner/openzev/commit/f29515f242aa9f9a75ff595cc8ba6dcc46bd0e6d))
* **zev:** honour ?zev_id= on the ZEV-scoped list endpoints ([#426](https://github.com/splattner/openzev/issues/426)) ([7101cf5](https://github.com/splattner/openzev/commit/7101cf554a093483a4887d4811cfa1bd5363cf62))
* **zev:** scope writes to the caller's own ZEV, not just reads ([#425](https://github.com/splattner/openzev/issues/425)) ([1521955](https://github.com/splattner/openzev/commit/1521955704a4d0843fe88bd41a3365ba86650264))

## [1.6.0](https://github.com/splattner/openzev/compare/v1.5.1...v1.6.0) (2026-07-30)


### Features

* **accounts:** audit the OAuth flows and provider configuration ([#342](https://github.com/splattner/openzev/issues/342)) ([03adef4](https://github.com/splattner/openzev/commit/03adef412e95508f6fc89ce1307b3507c9913a51))
* **audit:** show event details in a side drawer with a real diff ([#362](https://github.com/splattner/openzev/issues/362)) ([2f2626a](https://github.com/splattner/openzev/commit/2f2626aa8515c93d8fc78a0c46d4f9a491126c60))
* **tariffs:** add shared fee billing modes split across participants ([#356](https://github.com/splattner/openzev/issues/356)) ([cdfd200](https://github.com/splattner/openzev/commit/cdfd2009d374162713e8d411ff6e7be45b49351c))
* **tariffs:** chart the price history of a versioned tariff ([#371](https://github.com/splattner/openzev/issues/371)) ([d3a0034](https://github.com/splattner/openzev/commit/d3a0034cd3d157ffc63b878c32ce4e279ea3d306))
* **tariffs:** collapse tariff versions into one card per tariff ([#370](https://github.com/splattner/openzev/issues/370)) ([ca98544](https://github.com/splattner/openzev/commit/ca98544466c5dfbce8d434b605028a2aab7b6719))
* **tariffs:** show tariff validity as a badge on the card header ([#367](https://github.com/splattner/openzev/issues/367)) ([1839223](https://github.com/splattner/openzev/commit/1839223655fffb58c350b0a23450c58062ad00e3))
* **tariffs:** version tariffs by name with gap detection ([#369](https://github.com/splattner/openzev/issues/369)) ([d01afd2](https://github.com/splattner/openzev/commit/d01afd2ecce6b6b8da8da53a216b37954eca642d))
* **zev:** configurable invoice payment term and due date ([#365](https://github.com/splattner/openzev/issues/365)) ([6a284e4](https://github.com/splattner/openzev/commit/6a284e430ecc0f73f00ee49728d62ccd75a0e87e))


### Bug Fixes

* **accounts:** make IsZevOwnerOrAdmin check admin role explicitly ([#351](https://github.com/splattner/openzev/issues/351)) ([5d95337](https://github.com/splattner/openzev/commit/5d95337775e1049d6edc4bfc79631ef413eb298d))
* **accounts:** prevent deletion of the last admin ([#364](https://github.com/splattner/openzev/issues/364)) ([b5e8f49](https://github.com/splattner/openzev/commit/b5e8f49e5ad5022bd83248748cca67de830c6714))
* **accounts:** stop exposing feature flags to anonymous callers ([#353](https://github.com/splattner/openzev/issues/353)) ([b3b9257](https://github.com/splattner/openzev/commit/b3b9257b76b5f6a8c0033d9f241b4ae4c249b3c1))
* **frontend:** localize date pickers via app-level LocalizationProvider ([#363](https://github.com/splattner/openzev/issues/363)) ([413024e](https://github.com/splattner/openzev/commit/413024e593f055aa7578961a7f115029e9579502))
* **invoices:** close unauthorized invoice creation via generic POST endpoint ([#352](https://github.com/splattner/openzev/issues/352)) ([ab4e9d3](https://github.com/splattner/openzev/commit/ab4e9d3622b6110a85988e7745522469eb9d8116))
* **invoices:** make the PDF payment-terms line follow Zev.payment_term_days ([#373](https://github.com/splattner/openzev/issues/373)) ([ca81913](https://github.com/splattner/openzev/commit/ca81913a5625b9d068d208d41056311ce3447e4a))
* **settings:** reject insecure SECRET_KEY placeholders in production ([#349](https://github.com/splattner/openzev/issues/349)) ([a8c1148](https://github.com/splattner/openzev/commit/a8c11483759daf5b2542d1c2cef256067f36fb17))
* **tariffs:** key the overlap guard on tariff name, not category tuple ([#368](https://github.com/splattner/openzev/issues/368)) ([5be37ae](https://github.com/splattner/openzev/commit/5be37aeb983a40723d5d19289e5258d5fcd1083f))

## [1.5.1](https://github.com/splattner/openzev/compare/v1.5.0...v1.5.1) (2026-07-26)


### Bug Fixes

* **audit:** close audit-diff gaps left by incomplete tracked-field lists ([#327](https://github.com/splattner/openzev/issues/327)) ([9b22fc7](https://github.com/splattner/openzev/commit/9b22fc74e7a9f30b71464a9ed5916c9d4b5991d7))
* duplicate plus icon, cache outage crash, and Swiss number formatting ([#325](https://github.com/splattner/openzev/issues/325)) ([6a5cf07](https://github.com/splattner/openzev/commit/6a5cf07bacfd927fcb3bcc2f77227a4415b6b412))
* **frontend:** keep the sidebar nav from overflowing and needing dual scroll ([#324](https://github.com/splattner/openzev/issues/324)) ([fb7e0de](https://github.com/splattner/openzev/commit/fb7e0de089437558da6562f0778920f2a00fe591))
* **tariffs:** show the resolved CHF/kWh price for percentage-of-energy tariffs ([#326](https://github.com/splattner/openzev/issues/326)) ([27f287a](https://github.com/splattner/openzev/commit/27f287a4dd86dc65108ebb9105c2913052097f3f))
* **zev:** include all editable fields in participant.update audit diff ([#322](https://github.com/splattner/openzev/issues/322)) ([3c02a33](https://github.com/splattner/openzev/commit/3c02a335d990cd3b7ef325ddbb575b9f7aafa9a7))

## [1.5.0](https://github.com/splattner/openzev/compare/v1.4.0...v1.5.0) (2026-07-25)


### Features

* **zev:** show participant building footprints on an OpenStreetMap map ([#319](https://github.com/splattner/openzev/issues/319)) ([fa834f6](https://github.com/splattner/openzev/commit/fa834f6b0ab54e2ac6aba490ac72aca3269741be))


### Bug Fixes

* **frontend:** stop clipping participant rows in the feasibility calculator ([#317](https://github.com/splattner/openzev/issues/317)) ([4658af7](https://github.com/splattner/openzev/commit/4658af7aa0a9ee52a0986aa347cba562cdd8cf42))
* **zev:** let admins edit a ZEV owner's own participant record ([#320](https://github.com/splattner/openzev/issues/320)) ([f1449e7](https://github.com/splattner/openzev/commit/f1449e702dcf5233b680d6daaedab7e277d037db))

## [1.4.0](https://github.com/splattner/openzev/compare/v1.3.0...v1.4.0) (2026-07-24)


### Features

* **feasibility:** vZEV profitability & feasibility calculator ([#315](https://github.com/splattner/openzev/issues/315)) ([b13ab9a](https://github.com/splattner/openzev/commit/b13ab9ad5f4a2ab0056b811655178a2c0393da39))
* **invoices:** emit document PDFs as PDF/A-3b ([#313](https://github.com/splattner/openzev/issues/313)) ([64cc017](https://github.com/splattner/openzev/commit/64cc017b428d238885001941a2c2fcb3e99f825a))

## [1.3.0](https://github.com/splattner/openzev/compare/v1.2.0...v1.3.0) (2026-07-11)


### Features

* **frontend:** unify the period selector and move custom ranges into a popover ([#297](https://github.com/splattner/openzev/issues/297)) ([d33529c](https://github.com/splattner/openzev/commit/d33529c79d2e9aa83af3a19f8427551653c441ae))
* **metering:** redesign raw-data view as a drill-down with intraday grid ([#301](https://github.com/splattner/openzev/issues/301)) ([0d22dea](https://github.com/splattner/openzev/commit/0d22dea4f086c3c2157638b78531dab055fb632d))


### Bug Fixes

* **deps:** pin pandas to 3.0.3, away from the yanked 3.0.4 ([#295](https://github.com/splattner/openzev/issues/295)) ([f843d18](https://github.com/splattner/openzev/commit/f843d18a0cac0119ce8b7957321d2e7d3e479336))
* **deps:** update frontend-npm (major) ([#292](https://github.com/splattner/openzev/issues/292)) ([cc933e5](https://github.com/splattner/openzev/commit/cc933e5b1e00f51fd74fac0bf0396837dd12c3a4))
* **frontend:** migrate the Metering Data page to i18n ([#296](https://github.com/splattner/openzev/issues/296)) ([7b45e74](https://github.com/splattner/openzev/commit/7b45e74a3c0b133dff0e86f3de3703b863cb369b))
* **frontend:** migrate ZEV settings page to i18n and fix nav translation gaps ([#288](https://github.com/splattner/openzev/issues/288)) ([8c4608f](https://github.com/splattner/openzev/commit/8c4608f688b77af17eaa6acbaedc9957fe4c7ba6))
* **frontend:** ship the Inter font (and recapture screenshots) ([#300](https://github.com/splattner/openzev/issues/300)) ([e969362](https://github.com/splattner/openzev/commit/e9693624076aeb1ae527e5a9a32ebaa7094091ce))
* **screenshots:** repair PII blur, chart-data 500, empty demo data, and refresh all captures ([#294](https://github.com/splattner/openzev/issues/294)) ([ae6ff89](https://github.com/splattner/openzev/commit/ae6ff89112afbc310684a814a4e5d943f019185e))


### Performance Improvements

* **backend:** use a fast password hasher for tests ([#302](https://github.com/splattner/openzev/issues/302)) ([567f60f](https://github.com/splattner/openzev/commit/567f60f07e0552367bcaf6fd47e2306162e53575))

## [1.2.0](https://github.com/splattner/openzev/compare/v1.1.0...v1.2.0) (2026-07-05)


### Features

* **frontend:** improve tariffs page UX and add validity filter ([#280](https://github.com/splattner/openzev/issues/280)) ([a1de7bf](https://github.com/splattner/openzev/commit/a1de7bf37a1c72d770f0433dce135394611bc179))


### Bug Fixes

* **frontend:** translate invoice status labels and DataGrid chrome ([#276](https://github.com/splattner/openzev/issues/276)) ([7e14f4a](https://github.com/splattner/openzev/commit/7e14f4a2676846036becf0c05222769544974bd0))

## [1.1.0](https://github.com/splattner/openzev/compare/v1.0.3...v1.1.0) (2026-05-27)


### Features

* **audit:** add centralized audit log and operational traceability ([#184](https://github.com/splattner/openzev/issues/184)) ([0b04e31](https://github.com/splattner/openzev/commit/0b04e310224ffc60a41de12b5492a9a0d0a7a29b))

## [1.0.3](https://github.com/splattner/openzev/compare/v1.0.2...v1.0.3) (2026-04-18)


### Bug Fixes

* use correct tag in helm chart ([#152](https://github.com/splattner/openzev/issues/152)) ([7e16049](https://github.com/splattner/openzev/commit/7e16049c0683d2ab038eb1e219477e39190d6305))

## [1.0.2](https://github.com/splattner/openzev/compare/v1.0.1...v1.0.2) (2026-04-18)


### Bug Fixes

* sbom attachement to release failed ([#150](https://github.com/splattner/openzev/issues/150)) ([c2afea0](https://github.com/splattner/openzev/commit/c2afea0f6a2931db1c1610649adb7585fa8f490f))

## [1.0.1](https://github.com/splattner/openzev/compare/v1.0.0...v1.0.1) (2026-04-18)


### Bug Fixes

* first release failed, so I force a new version with this commit ([#148](https://github.com/splattner/openzev/issues/148)) ([55e9a0b](https://github.com/splattner/openzev/commit/55e9a0b0124c2c801f900237d6fdd5e32a690dff))

## 1.0.0 (2026-04-18)


### Features

* add a sample data generator ([#89](https://github.com/splattner/openzev/issues/89)) ([9c2d830](https://github.com/splattner/openzev/commit/9c2d8304612dd6f1866bd50df263dd66195d3b1a))
* add a sankey chart for the Energy Flow ([#88](https://github.com/splattner/openzev/issues/88)) ([7ceb666](https://github.com/splattner/openzev/commit/7ceb6664b3b8b2ba8c1f0050d839211ae0b48948))
* add a status check for participants ([#41](https://github.com/splattner/openzev/issues/41)) ([5b7b207](https://github.com/splattner/openzev/commit/5b7b2075289bc7c1e6a9e547489cd6ca60b492b6))
* add batch operations for invoices ([#100](https://github.com/splattner/openzev/issues/100)) ([28b974c](https://github.com/splattner/openzev/commit/28b974c5744fbff74f9b09908eef66a93ac4acf9))
* add details to contract pdf ([#90](https://github.com/splattner/openzev/issues/90)) ([d39045c](https://github.com/splattner/openzev/commit/d39045c784f4e5453ef38953abd69436c9ef3d51))
* add new tarif category for metering ([#54](https://github.com/splattner/openzev/issues/54)) ([febf34a](https://github.com/splattner/openzev/commit/febf34acc7efdcdf06bdd2e0c8c1a0efbca982fb))
* add new tarif type, percentage of all grid tarifs billed by energy ([#49](https://github.com/splattner/openzev/issues/49)) ([9968294](https://github.com/splattner/openzev/commit/996829402a4b7db8bef88338777c65f9a11096dd))
* add participant contract, savings in invoice + more visualizazions ([#50](https://github.com/splattner/openzev/issues/50)) ([ed20786](https://github.com/splattner/openzev/commit/ed20786de8eada69ab0715c57e6595c306c1881f))
* add the average consumption chart to the participant dashboard ([#97](https://github.com/splattner/openzev/issues/97)) ([a42e890](https://github.com/splattner/openzev/commit/a42e890596b9944d52b77eb684fc97706d560683))
* allow disabling zev self registration ([#91](https://github.com/splattner/openzev/issues/91)) ([bace01e](https://github.com/splattner/openzev/commit/bace01e6bdaf3948a07c111e04ffb3bf5f735c70))
* allow editing contract pdf and persist changes in db instead of disk ([#82](https://github.com/splattner/openzev/issues/82)) ([b1a09ca](https://github.com/splattner/openzev/commit/b1a09ca26bf11144afbea7e20f6af256167422a3))
* allow self registration and zev creation ([#38](https://github.com/splattner/openzev/issues/38)) ([83606c9](https://github.com/splattner/openzev/commit/83606c9aa6c2113acee4db234c8e75a001bec17e))
* create an annual financial report for taxes ([#102](https://github.com/splattner/openzev/issues/102)) ([4a5c731](https://github.com/splattner/openzev/commit/4a5c731d30dcdd0d42f504ee21e9d2efccc5c58c))
* implement annual report ([#101](https://github.com/splattner/openzev/issues/101)) ([9b1bbe2](https://github.com/splattner/openzev/commit/9b1bbe20a53fcf58c385ccb6d7c3504a63e38f12))
* implement oauth authentication ([#107](https://github.com/splattner/openzev/issues/107)) ([6171c83](https://github.com/splattner/openzev/commit/6171c834be1dddae10b47ddd5b02ae87c2a1e6a9))
* Implement VAT Management ([#28](https://github.com/splattner/openzev/issues/28)) ([8c18db9](https://github.com/splattner/openzev/commit/8c18db9bc2520138f1d437026c5006a4d709424e))
* intial code commit ([#1](https://github.com/splattner/openzev/issues/1)) ([efc9b51](https://github.com/splattner/openzev/commit/efc9b518f3df49da1ca39f2e601e19bb5d3fb622))
* only participant have an address ([#40](https://github.com/splattner/openzev/issues/40)) ([7f86cb1](https://github.com/splattner/openzev/commit/7f86cb17ac48f6462fc0c588ca653c5d3e5f1202))
* produced should get payed for the local energy ([#55](https://github.com/splattner/openzev/issues/55)) ([b261113](https://github.com/splattner/openzev/commit/b261113162b3af06644f890506742fe41b3a53ca))
* redesign invoicing page ([#30](https://github.com/splattner/openzev/issues/30)) ([c676749](https://github.com/splattner/openzev/commit/c676749c6ba136ed90948a2d08fe561eb647066e))
* remove valid_from/valid_to from metering point ([#57](https://github.com/splattner/openzev/issues/57)) ([8b29850](https://github.com/splattner/openzev/commit/8b298504884432037da48d598d81891cafc36f5e))
* show metering data quality for a period ([#60](https://github.com/splattner/openzev/issues/60)) ([033ba42](https://github.com/splattner/openzev/commit/033ba42851830d78ab19e319da178375ffb86df7))
* translations for invoices, visualization in invoice ([#44](https://github.com/splattner/openzev/issues/44)) ([7b713e4](https://github.com/splattner/openzev/commit/7b713e418a56bf92362ccb18b015bb41c806bd1e))
* use the email address as identifier for authentication instead of username ([#81](https://github.com/splattner/openzev/issues/81)) ([86dfd28](https://github.com/splattner/openzev/commit/86dfd28b678f231721e3c53566a6951ab2e82fda))


### Bug Fixes

* allow to overwrite redirect url for a oauth provider ([#112](https://github.com/splattner/openzev/issues/112)) ([3731430](https://github.com/splattner/openzev/commit/37314306dbd4f04d33ab1875b6e63740bdfa9dca))
* backend how backend url is used ([#76](https://github.com/splattner/openzev/issues/76)) ([ef02024](https://github.com/splattner/openzev/commit/ef020244285fe91d108f5385795e53f2b28ecb08))
* backend url in helm chart ([#75](https://github.com/splattner/openzev/issues/75)) ([7f2d986](https://github.com/splattner/openzev/commit/7f2d9869c8956fc8cb2d25561073628b3128d59a))
* dashboard not showing approved/sent invoices ([#123](https://github.com/splattner/openzev/issues/123)) ([772a237](https://github.com/splattner/openzev/commit/772a2379c1cb057d7b29db9ebd7e346aa47ba37d))
* frontend table aligenent of action column ([#124](https://github.com/splattner/openzev/issues/124)) ([5b2ae1c](https://github.com/splattner/openzev/commit/5b2ae1c9e9ca34aea39cb8d60ceb44755f769af9))
* handle timestamps from data correctly in dashboards ([#27](https://github.com/splattner/openzev/issues/27)) ([7562e0f](https://github.com/splattner/openzev/commit/7562e0ffaaaca25f06f9a65121f5466df64ca939))
* metering data completeness check not using correct participant assignement ([#32](https://github.com/splattner/openzev/issues/32)) ([cd3eba2](https://github.com/splattner/openzev/commit/cd3eba20c4a6c7b8b5e7ddc52f4e17757e135a99))
* missing percentage for type percentage of energy in json export ([#80](https://github.com/splattner/openzev/issues/80)) ([1a128d7](https://github.com/splattner/openzev/commit/1a128d77b916bc108a4cbc645baaa512d87e96f0))
* superadmin should have role admin ([#78](https://github.com/splattner/openzev/issues/78)) ([773bd4a](https://github.com/splattner/openzev/commit/773bd4abdf751c4be39035da2827096ace68eb66))
* ui fixes ([#79](https://github.com/splattner/openzev/issues/79)) ([ff6512f](https://github.com/splattner/openzev/commit/ff6512f811f3e489192a625f5c8fa4863a78d704))
* use correct oauth redirect url ([#111](https://github.com/splattner/openzev/issues/111)) ([6ba8b2f](https://github.com/splattner/openzev/commit/6ba8b2f623e79bc81b8021803fe35905f46267c3))
* zev wizard does not show final review step ([#36](https://github.com/splattner/openzev/issues/36)) ([5b129d9](https://github.com/splattner/openzev/commit/5b129d923350d41f8d444b61d5c8279f3c60aa05))
