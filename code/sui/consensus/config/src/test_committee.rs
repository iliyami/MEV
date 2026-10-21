// Copyright (c) Mysten Labs, Inc.
// SPDX-License-Identifier: Apache-2.0

use std::net::{TcpListener, TcpStream};

use fastcrypto::traits::{KeyPair as _, ToFromBytes as _};
use mysten_network::Multiaddr;
use rand::{SeedableRng as _, rngs::StdRng};

use crate::{Authority, AuthorityName, Committee, Epoch, NetworkKeyPair, ProtocolKeyPair, Stake};

/// Creates a committee for local testing, and the corresponding key pairs for the authorities.
pub fn local_committee_and_keys(
    epoch: Epoch,
    authorities_stake: Vec<Stake>,
) -> (Committee, Vec<(NetworkKeyPair, ProtocolKeyPair)>) {
    local_committee_and_keys_with_test_options(epoch, authorities_stake, true)
}

pub fn local_committee_and_keys_with_test_options(
    epoch: Epoch,
    authorities_stake: Vec<Stake>,
    unused_port: bool,
) -> (Committee, Vec<(NetworkKeyPair, ProtocolKeyPair)>) {
    let mut authorities = vec![];
    let mut key_pairs = vec![];
    // PAPER-2 (measurement only; default path unchanged). The committee seed is fixed
    // upstream, so every "replicate" of a test draws the SAME validator keys and therefore
    // the same committee order. COMMITTEE_SEED makes the seed the replicate, so intervals
    // reflect variation in the committee rather than only tokio scheduling jitter.
    let mut seed = [0u8; 32];
    if let Ok(v) = std::env::var("COMMITTEE_SEED") {
        if let Ok(x) = v.parse::<u64>() {
            seed[..8].copy_from_slice(&x.to_le_bytes());
        }
    }
    let mut rng = StdRng::from_seed(seed);
    for (i, stake) in authorities_stake.into_iter().enumerate() {
        let authority_keypair = fastcrypto::bls12381::min_sig::BLS12381KeyPair::generate(&mut rng);
        let protocol_keypair = ProtocolKeyPair::generate(&mut rng);
        let network_keypair = NetworkKeyPair::generate(&mut rng);
        authorities.push(Authority {
            stake,
            address: if unused_port {
                get_available_local_address()
            } else {
                "/ip4/127.0.0.1/udp/8081".parse().unwrap()
            },
            hostname: format!("test_host_{i}").to_string(),
            authority_name: AuthorityName::from_bytes(authority_keypair.public().as_bytes()),
            protocol_key: protocol_keypair.public(),
            network_key: network_keypair.public(),
        });
        key_pairs.push((network_keypair, protocol_keypair));
    }

    // PAPER-2 (measurement only; default path unchanged). Production builds its committee
    // in get_consensus_committee by SORTING validators on authority_name, which is the
    // 96-byte BLS protocol_pubkey (epoch_start_sui_system_state.rs:204). Committee::new
    // performs no sort, and this helper pushes authorities in generation order, so by
    // default a test committee's index is enumeration order and the key -> index step is
    // never exercised. KEY_SORTED_COMMITTEE=1 reproduces production's ordering.
    //
    // GRIND_RANK=k additionally runs the attack of the paper's cost model: it replaces the
    // LAST authority's key with one generated until it sorts below the incumbent at rank k
    // among the others, which is exactly what an entrant must do to occupy that rank. The
    // number of draws is reported so the measured cost can be compared with the model.
    if std::env::var("KEY_SORTED_COMMITTEE").ok().filter(|v| v != "0").is_some() {
        if let Ok(rv) = std::env::var("GRIND_RANK") {
            if let Ok(k) = rv.parse::<usize>() {
                let last = authorities.len() - 1;
                let mut incumbents: Vec<_> =
                    authorities[..last].iter().map(|a| a.authority_name.clone()).collect();
                incumbents.sort();
                let target = incumbents[k.min(incumbents.len() - 1)].clone();
                // GRIND_SEED makes the search reproducible; without it the draw count is
                // not repeatable, which matters because we report draw counts.
                let mut grind_rng = match std::env::var("GRIND_SEED")
                    .ok()
                    .and_then(|v| v.parse::<u64>().ok())
                {
                    Some(gs) => {
                        let mut gseed = [0u8; 32];
                        gseed[..8].copy_from_slice(&gs.to_le_bytes());
                        StdRng::from_seed(gseed)
                    }
                    None => StdRng::from_entropy(),
                };
                let mut draws: u64 = 0;
                loop {
                    draws += 1;
                    let kp = fastcrypto::bls12381::min_sig::BLS12381KeyPair::generate(&mut grind_rng);
                    let name = AuthorityName::from_bytes(kp.public().as_bytes());
                    if name < target {
                        authorities[last].authority_name = name;
                        break;
                    }
                }
                println!("GRIND_RESULT: rank={k} draws={draws}");
            }
        }
        // Sort authorities and their keypairs together, as production orders the committee.
        let mut idx: Vec<usize> = (0..authorities.len()).collect();
        idx.sort_by(|&a, &b| authorities[a].authority_name.cmp(&authorities[b].authority_name));
        let sorted_auth: Vec<_> = idx.iter().map(|&i| authorities[i].clone()).collect();
        let mut taken: Vec<Option<(NetworkKeyPair, ProtocolKeyPair)>> =
            key_pairs.into_iter().map(Some).collect();
        let sorted_keys: Vec<_> = idx.iter().map(|&i| taken[i].take().unwrap()).collect();
        authorities = sorted_auth;
        key_pairs = sorted_keys;
    }

    let committee = Committee::new(epoch, authorities);
    (committee, key_pairs)
}

/// Returns a local address with an ephemeral port.
fn get_available_local_address() -> Multiaddr {
    let host = "127.0.0.1";
    let port = get_available_port(host);
    format!("/ip4/{}/udp/{}", host, port).parse().unwrap()
}

/// Returns an ephemeral, available port. On unix systems, the port returned will be in the
/// TIME_WAIT state ensuring that the OS won't hand out this port for some grace period.
/// Callers should be able to bind to this port given they use SO_REUSEADDR.
fn get_available_port(host: &str) -> u16 {
    const MAX_PORT_RETRIES: u32 = 1000;

    for _ in 0..MAX_PORT_RETRIES {
        if let Ok(port) = get_ephemeral_port(host) {
            return port;
        }
    }

    panic!("Error: could not find an available port");
}

fn get_ephemeral_port(host: &str) -> std::io::Result<u16> {
    // Request a random available port from the OS
    let listener = TcpListener::bind((host, 0))?;
    let addr = listener.local_addr()?;

    // Create and accept a connection (which we'll promptly drop) in order to force the port
    // into the TIME_WAIT state, ensuring that the port will be reserved from some limited
    // amount of time (roughly 60s on some Linux systems)
    let _sender = TcpStream::connect(addr)?;
    let _incoming = listener.accept()?;

    Ok(addr.port())
}
