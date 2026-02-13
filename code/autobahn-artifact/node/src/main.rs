// Copyright(C) Facebook, Inc. and its affiliates.
use anyhow::{Context, Result};
use clap::{crate_name, crate_version, App, AppSettings, ArgMatches, SubCommand};
use config::Export as _;
use config::Import as _;
use config::{Committee, KeyPair, Parameters, WorkerId};
use env_logger::Env;
use primary::{Certificate, Primary, Header};
use store::Store;
use tokio::sync::mpsc::{channel, Receiver, Sender};
use worker::Worker;
use crypto::SignatureService;

/// The default channel capacity.
pub const CHANNEL_CAPACITY: usize = 1_000;

#[tokio::main]
async fn main() -> Result<()> {
    // ... (rest of main remains same)
    let matches = App::new(crate_name!())
        .version(crate_version!())
        .about("A research implementation of the Autobahn protocol.")
        .args_from_usage("-v... 'Sets the level of verbosity'")
        .subcommand(
            SubCommand::with_name("generate_keys")
                .about("Print a fresh key pair to file")
                .args_from_usage("--filename=<FILE> 'The file where to print the new key pair'"),
        )
        .subcommand(
            SubCommand::with_name("run")
                .about("Run a node")
                .args_from_usage("--keys=<FILE> 'The file containing the node keys'")
                .args_from_usage("--committee=<FILE> 'The file containing committee information'")
                .args_from_usage("--parameters=[FILE] 'The file containing the node parameters'")
                .args_from_usage("--store=<PATH> 'The path where to create the data store'")
                .subcommand(SubCommand::with_name("primary").about("Run a single primary"))
                .subcommand(
                    SubCommand::with_name("worker")
                        .about("Run a single worker")
                        .args_from_usage("--id=<INT> 'The worker id'"),
                )
                .setting(AppSettings::SubcommandRequiredElseHelp),
        )
        .setting(AppSettings::SubcommandRequiredElseHelp)
        .get_matches();

    let log_level = match matches.occurrences_of("v") {
        0 => "error",
        1 => "warn",
        2 => "info",
        3 => "debug",
        _ => "trace",
    };
    let mut logger = env_logger::Builder::from_env(Env::default().default_filter_or(log_level));
    #[cfg(feature = "benchmark")]
    logger.format_timestamp_millis();
    logger.init();

    match matches.subcommand() {
        ("generate_keys", Some(sub_matches)) => KeyPair::new()
            .export(sub_matches.value_of("filename").unwrap())
            .context("Failed to generate key pair")?,
        ("run", Some(sub_matches)) => run(sub_matches).await?,
        _ => unreachable!(),
    }
    Ok(())
}

// Runs either a worker or a primary.
async fn run(matches: &ArgMatches<'_>) -> Result<()> {
    let key_file = matches.value_of("keys").unwrap();
    let committee_file = matches.value_of("committee").unwrap();
    let parameters_file = matches.value_of("parameters");
    let store_path = matches.value_of("store").unwrap();

    // Read the committee and node's keypair from file.
    let keypair = KeyPair::import(key_file).context("Failed to load the node's keypair")?;
    let committee =
        Committee::import(committee_file).context("Failed to load the committee information")?;

    // Load default parameters if none are specified.
    let mut parameters = match parameters_file {
        Some(filename) => {
            Parameters::import(filename).context("Failed to load the node's parameters")?
        }
        None => Parameters::default(),
    };

    // Override parameters from environment variables if set (for experiment sweeps)
    if let Ok(k_str) = std::env::var("AUTOBAHN_K") {
        if let Ok(k) = k_str.parse::<u64>() {
            log::info!("🔧 Override: AUTOBAHN_K={}", k);
            parameters.k = k;
        }
    }
    if let Ok(timeout_str) = std::env::var("AUTOBAHN_FAST_PATH_TIMEOUT") {
        if let Ok(timeout) = timeout_str.parse::<u64>() {
            log::info!("🔧 Override: AUTOBAHN_FAST_PATH_TIMEOUT={}", timeout);
            parameters.fast_path_timeout = timeout;
        }
    }
    if let Ok(use_fp_str) = std::env::var("AUTOBAHN_USE_FAST_PATH") {
        let use_fp = use_fp_str.to_lowercase() == "true";
        log::info!("🔧 Override: AUTOBAHN_USE_FAST_PATH={}", use_fp);
        parameters.use_fast_path = use_fp;
    }

    // Make the data store.
    let store = Store::new(store_path).context("Failed to create a store")?;

    // Channels the sequence of headers.
    let (tx_output, rx_output) = channel(CHANNEL_CAPACITY);

    // Check whether to run a primary, a worker, or an entire authority.
    match matches.subcommand() {
        // Spawn the primary core.
        ("primary", _) => {
            let (tx_new_certificates, _rx_new_certificates) = channel(CHANNEL_CAPACITY);
            let (tx_feedback, rx_feedback) = channel(CHANNEL_CAPACITY);
            let (tx_committer, rx_committer) = channel(CHANNEL_CAPACITY);
            let (tx_sailfish, _rx_sailfish) = channel(CHANNEL_CAPACITY);
            let (tx_pushdown_cert, rx_pushdown_cert) = channel(CHANNEL_CAPACITY);
            let (tx_request_header_sync, rx_request_header_sync) = channel(CHANNEL_CAPACITY);
            
            // Proxy channel to bridge Committer's output to both tx_output (for analysis) 
            // and tx_feedback (for GarbageCollector loopback)
            let (tx_committer_out, mut rx_committer_out) = channel::<Header>(CHANNEL_CAPACITY);
            let tx_output_clone = tx_output.clone();
            let tx_feedback_clone = tx_feedback.clone();

            tokio::spawn(async move {
                while let Some(header) = rx_committer_out.recv().await {
                    let _ = tx_output_clone.send(header.clone()).await;
                    let _ = tx_feedback_clone.send(header).await;
                }
            });

            let signature_service = SignatureService::new(keypair.secret);

            Primary::spawn(
                keypair.name,
                committee.clone(),
                parameters.clone(),
                signature_service,
                store,
                /* tx_consensus */ tx_new_certificates,
                /* tx_committer */ tx_committer,
                /* rx_committer */ rx_committer,
                /* rx_feedback (to GC) */ rx_feedback,
                /* tx_sailfish */ tx_sailfish,
                /* rx_pushdown_cert */ rx_pushdown_cert,
                /* rx_request_header_sync */ rx_request_header_sync,
                /* tx_output */ tx_committer_out,
            );
        }

        // Spawn a single worker.
        ("worker", Some(sub_matches)) => {
            let id = sub_matches
                .value_of("id")
                .unwrap()
                .parse::<WorkerId>()
                .context("The worker id must be a positive integer")?;
            Worker::spawn(keypair.name, id, committee, parameters, store);
        }
        _ => unreachable!(),
    }

    // Analyze the consensus' output.
    analyze(rx_output).await;

    // If this expression is reached, the program ends and all other tasks terminate.
    unreachable!();
}

/// Receives an ordered list of headers and apply any application-specific logic.
async fn analyze(mut rx_output: Receiver<Header>) {
    while let Some(_header) = rx_output.recv().await {
        // NOTE: Here goes the application logic.
    }
}
