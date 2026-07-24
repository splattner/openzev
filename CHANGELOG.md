# Changelog

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
