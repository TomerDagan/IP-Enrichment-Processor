# Unit Test Readable Report

Generated at: 2026-05-21T10:56:54
Total tests: 23
Passed: 23
Failed: 0
Skipped: 0
Pytest exit status: 0

## Scenario Results

| Status | Group | Test | Scenario |
|---|---|---|---|
| PASSED | TestParseIp | test_valid_ipv4_full | Valid ipv4 full |
| PASSED | TestParseIp | test_valid_ipv6_full | Valid ipv6 full |
| PASSED | TestParseIp | test_valid_ipv4_cidr | Valid ipv4 cidr |
| PASSED | TestParseIp | test_valid_ipv6_cidr | Valid ipv6 cidr |
| PASSED | TestParseIp | test_invalid_ipv4_cidr_not_24 | Invalid ipv4 cidr not 24 |
| PASSED | TestParseIp | test_invalid_ipv6_cidr_not_48 | Invalid ipv6 cidr not 48 |
| PASSED | TestParseIp | test_invalid_ip | Invalid ip |
| PASSED | TestParseIp | test_invalid_empty_string | Invalid empty string |
| PASSED | TestParseIp | test_invalid_partial_ip | Invalid partial ip |
| PASSED | TestHandleFullIp | test_full_ip_match_enriched | Full ip match enriched |
| PASSED | TestHandleFullIp | test_full_ip_no_match_dropped | Full ip no match dropped |
| PASSED | TestHandleFullIp | test_full_ip_non_unique_dropped | Full ip non unique dropped |
| PASSED | TestHandleFullIp | test_full_ipv6_match_enriched | Full ipv6 match enriched |
| PASSED | TestHandleMaskedIp | test_masked_same_geo_enriched | Masked same geo enriched |
| PASSED | TestHandleMaskedIp | test_masked_conflicting_candidates_dropped | Masked conflicting candidates dropped |
| PASSED | TestHandleMaskedIp | test_masked_no_match_dropped | Masked no match dropped |
| PASSED | TestHandleMaskedIp | test_masked_single_candidate_enriched | Masked single candidate enriched |
| PASSED | TestMaskedTemporalBehavior | test_masked_uses_only_selected_timestamp_slice | Masked matching must evaluate candidates only inside latest dim slice <= event timestamp. |
| PASSED | TestGetLatestDimSlice | test_picks_latest_slice_before_event | Picks latest slice before event |
| PASSED | TestGetLatestDimSlice | test_picks_exact_match_slice | Picks exact match slice |
| PASSED | TestGetLatestDimSlice | test_picks_most_recent_slice | Picks most recent slice |
| PASSED | TestGetLatestDimSlice | test_no_slice_before_event_returns_none | No slice before event returns none |
| PASSED | TestInvalidIp | test_invalid_ip_drop_reason | Simulate the main loop path for an invalid IP. |

## Notes

- This file is generated automatically after each pytest run.
- Use --readable-report <path> to change its output location.