import ipaddress
import pandas as pd
from pathlib import Path
from datetime import datetime, timezone
from typing import Dict, List, Any, Optional


# ============================================================================
# HELPER FUNCTIONS FOR IP MATCHING
# ============================================================================

def find_exact_match(ip_addr: ipaddress.ip_address, dim_slice: pd.DataFrame) -> List[Dict]:
    """
    Find exact match for a full IP address in the dimension slice.
    
    Args:
        ip_addr: ipaddress.ip_address object
        dim_slice: DataFrame containing dimension data for a specific timestamp
    
    Returns:
        List of matching rows as dictionaries
    """
    # Convert IP to string for comparison
    ip_str = str(ip_addr)
    
    # Check both ipv4 and ipv6 columns
    if ip_addr.version == 4:
        matches = dim_slice[dim_slice["ipv4"] == ip_str]
    else:  # IPv6
        matches = dim_slice[dim_slice["ipv6"] == ip_str]
    
    return matches.to_dict("records")


def find_all_ips_in_network(network: ipaddress.ip_network, dim_slice: pd.DataFrame) -> List[Dict]:
    """
    Find all IPs in the dimension slice that fall within the given network.
    
    Args:
        network: ipaddress.ip_network object
        dim_slice: DataFrame containing dimension data for a specific timestamp
    
    Returns:
        List of matching rows as dictionaries
    """
    candidates = []
    
    for idx, row in dim_slice.iterrows():
        try:
            if network.version == 4:
                # Check IPv4 column
                if pd.notna(row["ipv4"]):
                    ip = ipaddress.ip_address(row["ipv4"])
                    if ip in network:
                        candidates.append(row.to_dict())
            else:  # IPv6
                # Check IPv6 column
                if pd.notna(row["ipv6"]):
                    ip = ipaddress.ip_address(row["ipv6"])
                    if ip in network:
                        candidates.append(row.to_dict())
        except (ValueError, AttributeError):
            # Skip invalid IP addresses
            continue
    
    return candidates


# ============================================================================
# CORE PROCESSING FUNCTIONS
# ============================================================================

def parse_ip(ip_str: str) -> Dict[str, Any]:
    """
    Parse IP string and determine if it's a full address or CIDR network.
    
    Args:
        ip_str: IP address or CIDR notation string
    
    Returns:
        Dictionary with parse results: either {"type": "full"|"masked", ...} or {"invalid": True}
    """
    try:
        if "/" in str(ip_str):
            network = ipaddress.ip_network(ip_str, strict=False)

            if network.version == 4 and network.prefixlen != 24:
                return {
                    "type": "masked",
                    "family": "ipv4",
                    "invalid": True,
                    "invalid_reason": "INVALID_MASK_LENGTH",
                    "invalid_comment": f"Expected IPv4 /24, got /{network.prefixlen}",
                }

            if network.version == 6 and network.prefixlen != 48:
                return {
                    "type": "masked",
                    "family": "ipv6",
                    "invalid": True,
                    "invalid_reason": "INVALID_MASK_LENGTH",
                    "invalid_comment": f"Expected IPv6 /48, got /{network.prefixlen}",
                }

            return {
                "type": "masked",
                "network": network,
                "family": "ipv6" if network.version == 6 else "ipv4",
                "invalid": False
            }
        else:
            ip = ipaddress.ip_address(ip_str)
            return {
                "type": "full",
                "ip": ip,
                "family": "ipv6" if ip.version == 6 else "ipv4",
                "invalid": False
            }
    except (ValueError, TypeError):
        return {
            "invalid": True,
            "invalid_reason": "INVALID_IP",
            "invalid_comment": f"Failed to parse IP value: {ip_str}",
        }


def handle_full_ip(event: pd.Series, parsed: Dict, dim_slice: pd.DataFrame) -> Dict[str, Any]:
    """
    Handle enrichment for a full IP address.
    Must find exactly 1 match in dim_slice, otherwise drop.
    
    Args:
        event: Fact event row
        parsed: Parsed IP information dictionary
        dim_slice: DataFrame containing dimension data for this timestamp
    
    Returns:
        Result dictionary with status and enrichment data
    """
    matches = find_exact_match(parsed["ip"], dim_slice)
    
    if len(matches) == 0:
        return drop(event, "NO_DIM_MATCH", ip_type=parsed.get("type"))
    
    if len(matches) > 1:
        return drop(
            event,
            "NON_UNIQUE_MATCH",
            ip_type=parsed.get("type"),
            drop_reason_comments=f"Exact match returned {len(matches)} rows for IP {event.get('ip')}"
        )
    
    return enrich(event, matches[0], ip_type=parsed.get("type"))


def handle_masked_ip(event: pd.Series, parsed: Dict, dim_slice: pd.DataFrame) -> Dict[str, Any]:
    """
    Handle enrichment for a masked IP (CIDR).
    Find all matching IPs; enrich only if all candidates agree on (lat, lon).
    
    Args:
        event: Fact event row
        parsed: Parsed IP information dictionary
        dim_slice: DataFrame containing dimension data for this timestamp
    
    Returns:
        Result dictionary with status and enrichment data
    """
    candidates = find_all_ips_in_network(parsed["network"], dim_slice)
    
    if len(candidates) == 0:
        return drop(event, "NO_DIM_MATCH", ip_type=parsed.get("type"))
    
    # For masked inputs, require a single geo outcome only.
    # Normalize pandas missing values (NaN/NaT) to None so equality is stable.
    def _norm(value: Any) -> Any:
        return None if pd.isna(value) else value

    unique_lat = set()
    unique_lon = set()
    for candidate in candidates:
        n_lat = _norm(candidate.get("lat"))
        n_lon = _norm(candidate.get("lon"))

        unique_lat.add(n_lat)
        unique_lon.add(n_lon)
    
    if len(unique_lat) == 1 and len(unique_lon) == 1:
        if len(candidates) == 1:
            # A single candidate is unambiguous, so include both partner IPs.
            return enrich(
                event,
                {
                    "ipv4": _norm(candidates[0].get("ipv4")),
                    "ipv6": _norm(candidates[0].get("ipv6")),
                    "lat": _norm(candidates[0].get("lat")),
                    "lon": _norm(candidates[0].get("lon")),
                },
                ip_type=parsed.get("type")
            )

        # Multiple candidates can still agree on geo but remain identity-ambiguous.
        # In that case emit geo only and keep partner IP columns null.
        return enrich(
            event,
            {
                "ipv4": None,
                "ipv6": None,
                "lat": _norm(candidates[0].get("lat")),
                "lon": _norm(candidates[0].get("lon")),
            },
            ip_type=parsed.get("type")
        )

    conflicting_fields = []
    if len(unique_lat) > 1:
        conflicting_fields.append("lat")
    if len(unique_lon) > 1:
        conflicting_fields.append("lon")

    if any(field in conflicting_fields for field in ["lat", "lon"]):
        drop_reason = "AMBIGUOUS_PREFIX_GEO_CONFLICT"
    else:
        drop_reason = "AMBIGUOUS_PREFIX"

    return drop(
        event,
        drop_reason,
        ip_type=parsed.get("type"),
        drop_reason_comments=(
            f"network={parsed.get('network')}; candidates={len(candidates)}; "
            f"conflicting_fields={','.join(conflicting_fields) if conflicting_fields else 'unknown'}"
        ),
    )


def get_latest_dim_slice(event_timestamp: Any, dim_slices: Dict[Any, pd.DataFrame]) -> Optional[pd.DataFrame]:
    """
    Get the latest dimension slice where slice timestamp <= event timestamp.
    
    Args:
        event_timestamp: Timestamp from fact event
        dim_slices: Dictionary of {timestamp: DataFrame} for all dimension slices
    
    Returns:
        DataFrame slice or None if no matching slice exists
    """
    valid_slices = [ts for ts in dim_slices.keys() if ts <= event_timestamp]
    
    if not valid_slices:
        return None
    
    latest_timestamp = max(valid_slices)
    return dim_slices[latest_timestamp]


def to_iso_utc(timestamp_ms: Any) -> Optional[str]:
    """
    Convert epoch milliseconds to ISO-8601 UTC string.

    Returns None for null/invalid values.
    """
    if pd.isna(timestamp_ms):
        return None

    try:
        return datetime.fromtimestamp(float(timestamp_ms) / 1000.0, tz=timezone.utc).isoformat()
    except (TypeError, ValueError, OSError, OverflowError):
        return None


def enrich(event: pd.Series, dim_row: Dict[str, Any], ip_type: Optional[str] = None) -> Dict[str, Any]:
    """
    Create an enriched result record.
    
    Args:
        event: Fact event row
        dim_row: Dimension row dictionary with enrichment data
    
    Returns:
        Enriched result record
    """
    return {
        "timestamp": event.get("timestamp"),
        "timestamp_iso_utc": to_iso_utc(event.get("timestamp")),
        "user_id": event.get("user_id"),
        "ip": event.get("ip"),
        "ip_type": ip_type,
        "status": "ENRICHED",
        "ipv4": dim_row.get("ipv4"),
        "ipv6": dim_row.get("ipv6"),
        "lat": dim_row.get("lat"),
        "lon": dim_row.get("lon"),
        "drop_reason": None,
        "drop_reason_comments": None,
    }


def drop(
    event: pd.Series,
    reason: str,
    ip_type: Optional[str] = None,
    drop_reason_comments: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Create a dropped result record.
    
    Args:
        event: Fact event row
        reason: Reason for dropping (string constant)
    
    Returns:
        Dropped result record
    """
    return {
        "timestamp": event.get("timestamp"),
        "timestamp_iso_utc": to_iso_utc(event.get("timestamp")),
        "user_id": event.get("user_id"),
        "ip": event.get("ip"),
        "ip_type": ip_type,
        "status": "DROPPED",
        "ipv4": None,
        "ipv6": None,
        "lat": None,
        "lon": None,
        "drop_reason": reason,
        "drop_reason_comments": drop_reason_comments,
    }


# ============================================================================
# DATA I/O FUNCTIONS
# ============================================================================

def load_parquet(filepath: str) -> pd.DataFrame:
    """Load parquet file into DataFrame."""
    return pd.read_parquet(filepath)


def write_parquet(filepath: str, results: List[Dict]) -> None:
    """Write results to parquet file."""
    df = pd.DataFrame(results)
    Path(filepath).parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(filepath, index=False)


def group_dim_by_timestamp(dim_df: pd.DataFrame) -> Dict[Any, pd.DataFrame]:
    """
    Group dimension data by timestamp for efficient lookup.
    
    Args:
        dim_df: Full dimension DataFrame
    
    Returns:
        Dictionary of {timestamp: DataFrame} for each unique timestamp
    """
    dim_slices = {}
    for timestamp, group in dim_df.groupby("timestamp"):
        dim_slices[timestamp] = group.reset_index(drop=True)
    return dim_slices


# ============================================================================
# MAIN PROCESSING PIPELINE
# ============================================================================

def process_events() -> None:
    """
    Main processing pipeline: load data, enrich events, save results.
    """
    # 1. Load data
    print("Loading data...")
    dim_df = load_parquet("./data/dim.parquet")
    fact_df = load_parquet("./data/fact.parquet")
    
    # 2. Sort DIM by timestamp and group into slices
    print("Organizing dimension data by timestamp...")
    dim_df = dim_df.sort_values("timestamp").reset_index(drop=True)
    dim_slices = group_dim_by_timestamp(dim_df)
    
    # Sort fact data by timestamp for efficient slice lookup
    fact_df = fact_df.sort_values("timestamp").reset_index(drop=True)
    
    # 3. Process FACT events
    print("Processing fact events...")
    results = []
    
    for idx, event in fact_df.iterrows():
        if idx % 10000 == 0:
            print(f"  Progress: {idx}/{len(fact_df)}")
        
        # 3.1 Get latest dimension slice for this event's timestamp
        current_dim_slice = get_latest_dim_slice(event.get("timestamp"), dim_slices)
        
        if current_dim_slice is None:
            results.append(drop(event, "NO_DIM_SLICE"))
            continue
        
        # 3.2 Parse IP
        parsed = parse_ip(event.get("ip"))
        
        if parsed.get("invalid"):
            results.append(
                drop(
                    event,
                    parsed.get("invalid_reason", "INVALID_IP"),
                    ip_type=parsed.get("type", "invalid"),
                    drop_reason_comments=parsed.get(
                        "invalid_comment",
                        f"Failed to parse IP value: {event.get('ip')}"
                    )
                )
            )
            continue
        
        # 3.3 Process event based on IP type
        if parsed.get("type") == "full":
            result = handle_full_ip(event, parsed, current_dim_slice)
        elif parsed.get("type") == "masked":
            result = handle_masked_ip(event, parsed, current_dim_slice)
        else:
            result = drop(
                event,
                "INVALID_IP_TYPE",
                ip_type=parsed.get("type"),
                drop_reason_comments=f"Unsupported parsed type: {parsed.get('type')}"
            )
        
        results.append(result)
    
    # 4. Save output
    print("Saving results...")
    write_parquet("./output/result.parquet", results)
    
    # Summary statistics
    results_df = pd.DataFrame(results)
    print("\n=== PROCESSING SUMMARY ===")
    print(f"Total events processed: {len(results_df)}")
    print(f"Enriched: {(results_df['status'] == 'ENRICHED').sum()}")
    print(f"Dropped: {(results_df['status'] == 'DROPPED').sum()}")
    print("\nDrop reasons breakdown:")
    print(results_df[results_df['status'] == 'DROPPED']['drop_reason'].value_counts())
    print(f"\nResults saved to: ./output/result.parquet")


if __name__ == "__main__":
    process_events()
