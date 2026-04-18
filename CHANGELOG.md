# Changelog

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
