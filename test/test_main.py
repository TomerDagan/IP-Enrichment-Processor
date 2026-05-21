import sys
import os
import ipaddress
import pandas as pd
import pytest

# Allow importing from src/ without installing the package
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from main import (
    parse_ip,
    handle_full_ip,
    handle_masked_ip,
    get_latest_dim_slice,
    group_dim_by_timestamp,
)

# ============================================================================
# SYNTHETIC DATA HELPERS
# ============================================================================

def make_event(ip: str, timestamp=100, user_id="u1") -> pd.Series:
    return pd.Series({"timestamp": timestamp, "user_id": user_id, "ip": ip})


def make_dim_slice(*rows) -> pd.DataFrame:
    """
    Build a dim_slice DataFrame from row dicts.
    Each dict should contain: ipv4, ipv6, lat, lon.
    """
    return pd.DataFrame(rows)


def make_dim_df(rows_by_timestamp: dict) -> pd.DataFrame:
    """
    Build a full dim DataFrame for temporal tests.
    rows_by_timestamp: {timestamp: [row_dicts]}
    """
    all_rows = []
    for ts, rows in rows_by_timestamp.items():
        for row in rows:
            all_rows.append({"timestamp": ts, **row})
    return pd.DataFrame(all_rows)


# ============================================================================
# parse_ip TESTS
# ============================================================================

class TestParseIp:
    def test_valid_ipv4_full(self):
        result = parse_ip("192.168.1.1")
        assert result["type"] == "full"
        assert result["family"] == "ipv4"
        assert result["invalid"] is False
        assert result["ip"] == ipaddress.ip_address("192.168.1.1")

    def test_valid_ipv6_full(self):
        result = parse_ip("2001:db8::1")
        assert result["type"] == "full"
        assert result["family"] == "ipv6"
        assert result["invalid"] is False

    def test_valid_ipv4_cidr(self):
        result = parse_ip("10.0.0.0/24")
        assert result["type"] == "masked"
        assert result["family"] == "ipv4"
        assert result["invalid"] is False
        assert result["network"] == ipaddress.ip_network("10.0.0.0/24")

    def test_valid_ipv6_cidr(self):
        result = parse_ip("2001:db8::/48")
        assert result["type"] == "masked"
        assert result["family"] == "ipv6"
        assert result["invalid"] is False

    def test_invalid_ipv4_cidr_not_24(self):
        result = parse_ip("10.0.0.0/16")
        assert result["invalid"] is True
        assert result["invalid_reason"] == "INVALID_MASK_LENGTH"

    def test_invalid_ipv6_cidr_not_48(self):
        result = parse_ip("2001:db8::/32")
        assert result["invalid"] is True
        assert result["invalid_reason"] == "INVALID_MASK_LENGTH"

    def test_invalid_ip(self):
        result = parse_ip("not-an-ip")
        assert result["invalid"] is True

    def test_invalid_empty_string(self):
        result = parse_ip("")
        assert result["invalid"] is True

    def test_invalid_partial_ip(self):
        result = parse_ip("999.999.999.999")
        assert result["invalid"] is True


# ============================================================================
# handle_full_ip TESTS
# ============================================================================

class TestHandleFullIp:

    def _dim_slice(self):
        return make_dim_slice(
            {"ipv4": "192.168.1.1", "ipv6": None,           "lat": 51.5, "lon": -0.1},
            {"ipv4": "10.0.0.1",    "ipv6": None,           "lat": 48.8, "lon": 2.3},
            {"ipv4": None,          "ipv6": "2001:db8::1",  "lat": 40.7, "lon": -74.0},
        )

    def test_full_ip_match_enriched(self):
        event = make_event("192.168.1.1")
        parsed = parse_ip("192.168.1.1")
        result = handle_full_ip(event, parsed, self._dim_slice())

        assert result["status"] == "ENRICHED"
        assert result["ip_type"] == "full"
        assert result["lat"] == 51.5
        assert result["lon"] == -0.1
        assert result["drop_reason"] is None

    def test_full_ip_no_match_dropped(self):
        event = make_event("172.16.0.1")
        parsed = parse_ip("172.16.0.1")
        result = handle_full_ip(event, parsed, self._dim_slice())

        assert result["status"] == "DROPPED"
        assert result["ip_type"] == "full"
        assert result["drop_reason"] == "NO_DIM_MATCH"

    def test_full_ip_non_unique_dropped(self):
        # Two rows with the same IP
        dim_slice = make_dim_slice(
            {"ipv4": "192.168.1.1", "ipv6": None, "lat": 51.5, "lon": -0.1},
            {"ipv4": "192.168.1.1", "ipv6": None, "lat": 99.0, "lon": 99.0},
        )
        event = make_event("192.168.1.1")
        parsed = parse_ip("192.168.1.1")
        result = handle_full_ip(event, parsed, dim_slice)

        assert result["status"] == "DROPPED"
        assert result["ip_type"] == "full"
        assert result["drop_reason"] == "NON_UNIQUE_MATCH"
        assert "Exact match returned" in result["drop_reason_comments"]

    def test_full_ipv6_match_enriched(self):
        event = make_event("2001:db8::1")
        parsed = parse_ip("2001:db8::1")
        result = handle_full_ip(event, parsed, self._dim_slice())

        assert result["status"] == "ENRICHED"
        assert result["lat"] == 40.7
        assert result["drop_reason"] is None


# ============================================================================
# handle_masked_ip TESTS
# ============================================================================

class TestHandleMaskedIp:

    def test_masked_same_geo_enriched(self):
        # Different concrete IP rows are allowed as long as geo agrees.
        dim_slice = make_dim_slice(
            {"ipv4": "10.0.0.1", "ipv6": None, "lat": 48.8, "lon": 2.3},
            {"ipv4": "10.0.0.2", "ipv6": None, "lat": 48.8, "lon": 2.3},
            {"ipv4": "10.0.0.3", "ipv6": None, "lat": 48.8, "lon": 2.3},
        )
        event = make_event("10.0.0.0/24")
        parsed = parse_ip("10.0.0.0/24")
        result = handle_masked_ip(event, parsed, dim_slice)

        assert result["status"] == "ENRICHED"
        assert result["ip_type"] == "masked"
        assert result["ipv4"] is None
        assert result["ipv6"] is None
        assert result["lat"] == 48.8
        assert result["lon"] == 2.3
        assert result["drop_reason"] is None

    def test_masked_conflicting_candidates_dropped(self):
        # IPs in same prefix but different enrichment values
        dim_slice = make_dim_slice(
            {"ipv4": "10.0.0.1", "ipv6": None, "lat": 48.8, "lon": 2.3},
            {"ipv4": "10.0.0.2", "ipv6": None, "lat": 51.5, "lon": -0.1},  # different
        )
        event = make_event("10.0.0.0/24")
        parsed = parse_ip("10.0.0.0/24")
        result = handle_masked_ip(event, parsed, dim_slice)

        assert result["status"] == "DROPPED"
        assert result["ip_type"] == "masked"
        assert result["drop_reason"] == "AMBIGUOUS_PREFIX_GEO_CONFLICT"
        assert "conflicting_fields=lat,lon" in result["drop_reason_comments"]

    def test_masked_no_match_dropped(self):
        # No IPs in slice fall within the requested network
        dim_slice = make_dim_slice(
            {"ipv4": "192.168.1.1", "ipv6": None, "lat": 51.5, "lon": -0.1},
        )
        event = make_event("10.0.0.0/24")
        parsed = parse_ip("10.0.0.0/24")
        result = handle_masked_ip(event, parsed, dim_slice)

        assert result["status"] == "DROPPED"
        assert result["ip_type"] == "masked"
        assert result["drop_reason"] == "NO_DIM_MATCH"

    def test_masked_single_candidate_enriched(self):
        # Only one IP in network → uniqueness is trivially satisfied
        dim_slice = make_dim_slice(
            {"ipv4": "10.0.0.5",  "ipv6": "2001:db8::5", "lat": 35.6, "lon": 139.7},
            {"ipv4": "172.16.0.1","ipv6": None, "lat": 99.0, "lon":  99.0},
        )
        event = make_event("10.0.0.0/24")
        parsed = parse_ip("10.0.0.0/24")
        result = handle_masked_ip(event, parsed, dim_slice)

        assert result["status"] == "ENRICHED"
        assert result["ip_type"] == "masked"
        assert result["ipv4"] == "10.0.0.5"
        assert result["ipv6"] == "2001:db8::5"
        assert result["lat"] == 35.6


class TestMaskedTemporalBehavior:

    def test_masked_uses_only_selected_timestamp_slice(self):
        """Masked matching must evaluate candidates only inside latest dim slice <= event timestamp."""
        dim_df = make_dim_df(
            {
                # Older slice: same prefix but conflicting geo
                100: [
                    {"ipv4": "10.0.0.1", "ipv6": None, "lat": 1.0, "lon": 1.0},
                    {"ipv4": "10.0.0.2", "ipv6": None, "lat": 2.0, "lon": 2.0},
                ],
                # Current slice for event timestamp: single candidate only
                200: [
                    {"ipv4": "10.0.0.1", "ipv6": None, "lat": 9.0, "lon": 9.0},
                ],
            }
        )
        dim_slices = group_dim_by_timestamp(dim_df)
        event = make_event("10.0.0.0/24", timestamp=250)
        parsed = parse_ip(event["ip"])

        selected_slice = get_latest_dim_slice(event["timestamp"], dim_slices)
        result = handle_masked_ip(event, parsed, selected_slice)

        assert result["status"] == "ENRICHED"
        assert result["ip_type"] == "masked"
        assert result["lat"] == 9.0
        assert result["lon"] == 9.0


# ============================================================================
# get_latest_dim_slice TESTS (TEMPORAL CORRECTNESS)
# ============================================================================

class TestGetLatestDimSlice:

    def _dim_slices(self):
        dim_df = make_dim_df({
            50:  [{"ipv4": "1.1.1.1", "ipv6": None, "lat": 10.0, "lon": 10.0}],
            100: [{"ipv4": "1.1.1.1", "ipv6": None, "lat": 20.0, "lon": 20.0}],
            200: [{"ipv4": "1.1.1.1", "ipv6": None, "lat": 30.0, "lon": 30.0}],
        })
        return group_dim_by_timestamp(dim_df)

    def test_picks_latest_slice_before_event(self):
        slices = self._dim_slices()
        # Event at 150 → should pick slice at 100, not 200
        result = get_latest_dim_slice(150, slices)
        assert result is not None
        assert result.iloc[0]["lat"] == 20.0

    def test_picks_exact_match_slice(self):
        slices = self._dim_slices()
        # Event at exactly 100 → should pick slice at 100
        result = get_latest_dim_slice(100, slices)
        assert result is not None
        assert result.iloc[0]["lat"] == 20.0

    def test_picks_most_recent_slice(self):
        slices = self._dim_slices()
        # Event at 999 → should pick slice at 200
        result = get_latest_dim_slice(999, slices)
        assert result is not None
        assert result.iloc[0]["lat"] == 30.0

    def test_no_slice_before_event_returns_none(self):
        slices = self._dim_slices()
        # Event at 10 → no slice with timestamp <= 10 exists
        result = get_latest_dim_slice(10, slices)
        assert result is None


# ============================================================================
# INVALID IP INTEGRATION TEST
# ============================================================================

class TestInvalidIp:

    def test_invalid_ip_drop_reason(self):
        """Simulate the main loop path for an invalid IP."""
        from main import drop

        event = make_event("bad-ip-address")
        parsed = parse_ip("bad-ip-address")

        assert parsed.get("invalid") is True

        result = drop(event, "INVALID_IP")
        assert result["status"] == "DROPPED"
        assert result["ip_type"] is None
        assert result["drop_reason"] == "INVALID_IP"
        assert result["drop_reason_comments"] is None
        assert result["ipv4"] is None
        assert result["ipv6"] is None
