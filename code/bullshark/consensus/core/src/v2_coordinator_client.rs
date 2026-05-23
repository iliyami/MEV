// Paper 2 (v2) coordinator client.
//
// Invariant: this module reads policy assignments from an out-of-protocol
// Byzantine-only HTTP service. It never modifies consensus, validity, or
// signature logic; it only supplies per-node attacker-hook configuration that
// previously came from a single global ATTACK_MODE environment variable.
//
// The Coordinator service is documented in scripts/v2/coordinator.py.
// When V2_COORDINATOR_URL is unset, this module is not invoked and the
// paper-1 env-var-driven path runs unchanged.

use std::time::Duration;

#[derive(Debug, Clone)]
pub struct PolicyResponse {
    pub group_id: String,
    /// MEV attack family: "frontrun" | "backrun" | "sandwich".
    pub family: String,
    /// DAG attacker strategy: "fissure" | "speculative" | "sluggish".
    pub strategy: String,
    pub params: serde_json::Map<String, serde_json::Value>,
}

/// HTTP-POST `/policy/lookup` to the running coordinator.
///
/// Returns:
///   * `Ok(Some(policy))` -- this node is Byzantine; use the returned policy.
///   * `Ok(None)`         -- this node is honest (coordinator returned 404).
///   * `Err(msg)`         -- transport/parse failure; caller should fail loudly.
pub fn lookup_policy(url: &str, node_id: usize) -> Result<Option<PolicyResponse>, String> {
    let endpoint = format!("{}/policy/lookup", url.trim_end_matches('/'));
    let body = serde_json::json!({ "node_id": node_id }).to_string();
    let req = ureq::post(&endpoint)
        .timeout(Duration::from_secs(5))
        .set("Content-Type", "application/json");
    match req.send_string(&body) {
        Ok(resp) => {
            let body_str = resp
                .into_string()
                .map_err(|e| format!("coord response read error: {e}"))?;
            let json: serde_json::Value = serde_json::from_str(&body_str)
                .map_err(|e| format!("coord response parse error: {e}"))?;
            let family = json["family"]
                .as_str()
                .ok_or_else(|| "coord response missing 'family'".to_string())?
                .to_string();
            let strategy = json["strategy"]
                .as_str()
                .ok_or_else(|| "coord response missing 'strategy'".to_string())?
                .to_string();
            Ok(Some(PolicyResponse {
                group_id: json["group_id"].as_str().unwrap_or("").to_string(),
                family,
                strategy,
                params: json["params"].as_object().cloned().unwrap_or_default(),
            }))
        }
        Err(ureq::Error::Status(404, _)) => Ok(None),
        Err(e) => Err(format!("coord HTTP error: {e}")),
    }
}

/// Full coordination decision returned by `/coordinate/decision`. Captures
/// both the legacy P3 `shared_exclusion_seed` and the v3-added `role`
/// field used by R-P3.3 (rr_slot / leader-aware) for per-round
/// active/passive dispatch.
#[derive(Debug, Clone, Default)]
pub struct CoordDecision {
    pub shared_exclusion_seed: Option<u64>,
    pub role: Option<String>,
}

/// HTTP-POST `/coordinate/decision` to fetch the per-round coordination
/// decision for `node_id` at `round`. Used by the P3 collusion campaign.
pub fn query_coordinate_decision(
    url: &str,
    node_id: usize,
    round: u64,
) -> Result<CoordDecision, String> {
    let endpoint = format!("{}/coordinate/decision", url.trim_end_matches('/'));
    let body = serde_json::json!({ "node_id": node_id, "round": round }).to_string();
    let req = ureq::post(&endpoint)
        .timeout(Duration::from_secs(2))
        .set("Content-Type", "application/json");
    match req.send_string(&body) {
        Ok(resp) => {
            let body_str = resp
                .into_string()
                .map_err(|e| format!("coord decision response read error: {e}"))?;
            let json: serde_json::Value = serde_json::from_str(&body_str)
                .map_err(|e| format!("coord decision response parse error: {e}"))?;
            Ok(CoordDecision {
                shared_exclusion_seed: json["shared_exclusion_seed"].as_u64(),
                role: json["role"].as_str().map(|s| s.to_string()),
            })
        }
        Err(e) => Err(format!("coord decision HTTP error: {e}")),
    }
}

/// HTTP-POST `/victim/profit` to fetch the deterministic profit value for a
/// victim block at (round, author). Used by attacker hooks for observability
/// (P1.X.2 log marker) and -- once wired in P5 -- for adaptive targeting.
///
/// Returns:
///   * `Ok(Some(profit))` -- coordinator returned the profit.
///   * `Ok(None)`         -- coordinator returned 409 (no victim_profile is
///                            configured this run; common for paper-1-style
///                            uniform-victim runs).
///   * `Err(msg)`         -- transport/parse failure.
pub fn query_victim_profit(
    url: &str,
    round: u64,
    author: u64,
) -> Result<Option<f64>, String> {
    let endpoint = format!("{}/victim/profit", url.trim_end_matches('/'));
    let body = serde_json::json!({ "round": round, "author": author }).to_string();
    let req = ureq::post(&endpoint)
        .timeout(Duration::from_secs(2))
        .set("Content-Type", "application/json");
    match req.send_string(&body) {
        Ok(resp) => {
            let body_str = resp
                .into_string()
                .map_err(|e| format!("coord profit response read error: {e}"))?;
            let json: serde_json::Value = serde_json::from_str(&body_str)
                .map_err(|e| format!("coord profit response parse error: {e}"))?;
            Ok(json["profit"].as_f64())
        }
        Err(ureq::Error::Status(409, _)) => Ok(None),
        Err(e) => Err(format!("coord profit HTTP error: {e}")),
    }
}

/// v3 R-P4.1: a bribery offer fetched from `/bribery/pending`.
#[derive(Debug, Clone)]
pub struct BriberyOffer {
    pub offer_id: String,
    pub infraction: String,
    /// Optional target node id (used by `omit_reference_once`).
    pub target_victim_id: Option<usize>,
    /// Optional attacker set (used by `prefer_attacker_block`).
    pub target_attacker_set: Vec<usize>,
    pub payment: f64,
}

/// HTTP-POST `/bribery/pending`. Returns the first pending offer for
/// `node_id` or None on 404 (no offer, or no briber configured).
pub fn query_pending_bribery_offer(
    url: &str,
    node_id: usize,
) -> Result<Option<BriberyOffer>, String> {
    let endpoint = format!("{}/bribery/pending", url.trim_end_matches('/'));
    let body = serde_json::json!({ "node_id": node_id }).to_string();
    let req = ureq::post(&endpoint)
        .timeout(Duration::from_secs(2))
        .set("Content-Type", "application/json");
    match req.send_string(&body) {
        Ok(resp) => {
            let body_str = resp
                .into_string()
                .map_err(|e| format!("bribery_pending response read error: {e}"))?;
            let json: serde_json::Value = serde_json::from_str(&body_str)
                .map_err(|e| format!("bribery_pending parse error: {e}"))?;
            let target = json["target"].as_object();
            let target_victim_id = target
                .and_then(|t| t.get("target_victim_id"))
                .and_then(|v| v.as_u64())
                .map(|x| x as usize);
            let target_attacker_set: Vec<usize> = target
                .and_then(|t| t.get("target_attacker_set"))
                .and_then(|v| v.as_array())
                .map(|arr| {
                    arr.iter()
                        .filter_map(|x| x.as_u64().map(|n| n as usize))
                        .collect()
                })
                .unwrap_or_default();
            Ok(Some(BriberyOffer {
                offer_id: json["offer_id"]
                    .as_str()
                    .ok_or_else(|| "missing offer_id".to_string())?
                    .to_string(),
                infraction: json["infraction"]
                    .as_str()
                    .ok_or_else(|| "missing infraction".to_string())?
                    .to_string(),
                target_victim_id,
                target_attacker_set,
                payment: json["payment"].as_f64().unwrap_or(0.0),
            }))
        }
        Err(ureq::Error::Status(404, _)) => Ok(None),
        Err(e) => Err(format!("bribery_pending HTTP error: {e}")),
    }
}

/// HTTP-POST `/bribery/decide` to ask whether the honest node should accept.
pub fn bribery_decide(
    url: &str,
    offer_id: &str,
    node_id: usize,
) -> Result<bool, String> {
    let endpoint = format!("{}/bribery/decide", url.trim_end_matches('/'));
    let body = serde_json::json!({ "offer_id": offer_id, "node_id": node_id }).to_string();
    let req = ureq::post(&endpoint)
        .timeout(Duration::from_secs(2))
        .set("Content-Type", "application/json");
    match req.send_string(&body) {
        Ok(resp) => {
            let body_str = resp
                .into_string()
                .map_err(|e| format!("bribery_decide response read error: {e}"))?;
            let json: serde_json::Value = serde_json::from_str(&body_str)
                .map_err(|e| format!("bribery_decide parse error: {e}"))?;
            Ok(json["accept"].as_bool().unwrap_or(false))
        }
        Err(e) => Err(format!("bribery_decide HTTP error: {e}")),
    }
}

/// HTTP-POST `/bribery/accept` to record acceptance.
pub fn bribery_accept(url: &str, offer_id: &str, node_id: usize) -> Result<(), String> {
    let endpoint = format!("{}/bribery/accept", url.trim_end_matches('/'));
    let body = serde_json::json!({ "offer_id": offer_id, "node_id": node_id }).to_string();
    let req = ureq::post(&endpoint)
        .timeout(Duration::from_secs(2))
        .set("Content-Type", "application/json");
    match req.send_string(&body) {
        Ok(_) => Ok(()),
        Err(e) => Err(format!("bribery_accept HTTP error: {e}")),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parse_response_extracts_fields() {
        // Standalone parsing test; no network. Exercises the JSON layout
        // emitted by scripts/v2/coordinator.py /policy/lookup.
        let raw = serde_json::json!({
            "node_id": 3,
            "group_id": "g1",
            "family": "frontrun",
            "strategy": "fissure",
            "params": {"p_exclusion": 0.7}
        });
        let family = raw["family"].as_str().unwrap().to_string();
        let strategy = raw["strategy"].as_str().unwrap().to_string();
        assert_eq!(family, "frontrun");
        assert_eq!(strategy, "fissure");
        let params = raw["params"].as_object().cloned().unwrap();
        assert!(params.contains_key("p_exclusion"));
    }
}
