# Changelog

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
