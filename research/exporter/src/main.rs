use sakura_core::conversion::ResearchSearchStatus;
use sakura_core::{ConversionCandidate, ConversionOptions, Converter, Dictionary};
use serde_json::{Map, Value};
use sha2::{Digest, Sha256};
use std::collections::{BTreeMap, BTreeSet};
use std::env;
use std::fs::{self, File, OpenOptions};
use std::io::{self, Read, Write};
use std::path::{Path, PathBuf};

const CONTRACT_SCHEMA_VERSION: u64 = 3;
const CONVERTER_FEATURE_CONTRACT_VERSION: u64 = 1;
const RESEARCH_EXPORTER_CONTRACT_VERSION: u64 = 1;
const REQUESTED_LIMIT: usize = 32;
const EFFECTIVE_CONVERTER_BOUND: usize = 32;
const PRODUCTION_LIMIT: usize = 6;
const MAX_INPUT_LINE_BYTES: usize = 8 * 1024;
const MAX_INPUT_RECORDS: usize = 4_096;
const MAX_INPUT_BYTES: usize = 64 * 1024 * 1024;
const MAX_EXPORT_BYTES: usize = 256 * 1024 * 1024;
const PINNED_SAKURA_INPUT_HEAD: &str = "8e966dff456e4e7165e025f97c1f73327ff3f550";
const PINNED_DICTIONARY_SHA256: &str =
    "6d34364b5354d3c67efefaf15b50142b1365b21140ec8eee0f77570d828544ad";
const EXPORTER_MANIFEST_SCHEMA_VERSION: u64 = 2;
const EXPECTED_RUSTC_VERSION: &str = "rustc 1.96.0 (ac68faa20 2026-05-25)";
const EXPECTED_CARGO_VERSION: &str = "cargo 1.96.0 (30a34c682 2026-05-25)";
const EXPECTED_TARGET_TRIPLE: &str = "x86_64-pc-windows-msvc";
const EXPECTED_PROFILE: &str = "release";
const EXPECTED_BUILD_FLAGS: [&str; 3] = [
    "--remap-path-prefix=<WORKSPACE>=/sakura-input",
    "-C",
    "link-arg=/Brepro",
];
const EXPECTED_BUILD_ENVIRONMENT: [(&str, &str); 11] = [
    ("CARGO_BUILD_TARGET", "x86_64-pc-windows-msvc"),
    ("CARGO_INCREMENTAL", "0"),
    ("CARGO_NET_OFFLINE", "true"),
    ("CARGO_PROFILE_RELEASE_CODEGEN_UNITS", "1"),
    ("CARGO_PROFILE_RELEASE_DEBUG", "0"),
    ("CARGO_PROFILE_RELEASE_LTO", "fat"),
    ("CARGO_PROFILE_RELEASE_OPT_LEVEL", "3"),
    ("CARGO_PROFILE_RELEASE_PANIC", "abort"),
    ("CARGO_PROFILE_RELEASE_STRIP", "true"),
    ("RUSTUP_TOOLCHAIN", "stable-x86_64-pc-windows-msvc"),
    ("SOURCE_DATE_EPOCH", "0"),
];

#[derive(Debug)]
struct ExportError(&'static str);

impl std::fmt::Display for ExportError {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        formatter.write_str(self.0)
    }
}

impl std::error::Error for ExportError {}

#[derive(Debug)]
struct Args {
    input: PathBuf,
    dictionary: PathBuf,
    output: PathBuf,
    report: PathBuf,
    identity_manifest: PathBuf,
    limit: usize,
}

#[derive(Debug, Clone)]
struct InputRecord {
    stable_id: String,
    reading: String,
}

#[derive(Debug, Clone)]
struct Identity {
    verification_status: String,
    exporter_git_sha: String,
    exporter_binary_sha256: String,
    sakura_input_head: String,
    dictionary_sha256: String,
    instrumentation_patch_sha256: String,
    cargo_lock_sha256: String,
    rustc_version: String,
    cargo_version: String,
    target_triple: String,
    profile: String,
    build_flags: Vec<String>,
    build_environment: BTreeMap<String, String>,
    requested_limit: usize,
    effective_converter_bound: usize,
    user_dictionary_enabled: bool,
}

#[derive(Debug)]
struct Summary {
    record_count: usize,
    requested_limit: usize,
    effective_converter_bound: usize,
    total_candidate_count: usize,
    truncated_record_count: usize,
    search_exhausted_record_count: usize,
    input_sha256: String,
    output_sha256: String,
    dictionary_sha256: String,
    exporter_git_sha: String,
    exporter_binary_sha256: String,
    verification_status: String,
}

fn main() {
    if let Err(error) = run() {
        eprintln!("research exporter failed: {error}");
        std::process::exit(2);
    }
}

fn run() -> Result<(), ExportError> {
    let arguments = parse_args(env::args().skip(1))?;
    reject_path_collisions(&arguments)?;
    let identity = load_identity(&arguments.identity_manifest)?;
    validate_embedded_identity(&identity)?;
    let embedded_git_sha = option_env!("SAKURA_RERANK_EXPORTER_GIT_SHA")
        .ok_or(ExportError("missing embedded exporter Git identity"))?;
    validate_git_identity(&identity, embedded_git_sha)?;
    validate_sakura_input_head(&identity)?;
    if identity.requested_limit != REQUESTED_LIMIT
        || identity.effective_converter_bound != EFFECTIVE_CONVERTER_BOUND
    {
        return Err(ExportError(
            "exporter bound is not the pinned research bound",
        ));
    }
    if identity.user_dictionary_enabled {
        return Err(ExportError("user dictionary input is not allowed"));
    }

    let binary_sha256 = sha256_file(
        &env::current_exe().map_err(|_| ExportError("cannot locate exporter binary"))?,
    )?;
    validate_binary_identity(&identity, &binary_sha256)?;
    let dictionary_bytes = read_bounded_file(&arguments.dictionary, MAX_INPUT_BYTES)?;
    let dictionary_sha256 = sha256_bytes(&dictionary_bytes);
    validate_dictionary_identity(&identity, &dictionary_sha256)?;
    maybe_inject_failure("input")?;
    let input_bytes = read_bounded_file(&arguments.input, MAX_INPUT_BYTES)?;
    let input_sha256 = sha256_bytes(&input_bytes);
    let input_records = parse_input(&input_bytes)?;
    let dictionary = Dictionary::parse(&dictionary_bytes)
        .map_err(|_| ExportError("dictionary image failed validation"))?;

    let mut converter = Converter::new();
    let mut output_records = Vec::with_capacity(input_records.len());
    let mut total_candidate_count = 0usize;
    let mut truncated_record_count = 0usize;
    let mut search_exhausted_record_count = 0usize;
    for record in input_records {
        let conversion = converter
            .convert_research(
                &dictionary,
                &record.reading,
                ConversionOptions {
                    max_candidates: arguments.limit,
                    ..ConversionOptions::default()
                },
            )
            .map_err(|_| ExportError("converter execution failed"))?;
        let candidates = conversion.candidates();
        total_candidate_count = total_candidate_count.saturating_add(candidates.len());
        match conversion.result_status() {
            ResearchSearchStatus::Truncated => truncated_record_count += 1,
            ResearchSearchStatus::SearchExhausted => search_exhausted_record_count += 1,
        }
        output_records.push(make_record(
            &record,
            candidates,
            conversion.result_status(),
            &identity,
        )?);
    }
    let output_payload = canonical_jsonl_bytes(&output_records)?;
    if output_payload.len() > MAX_EXPORT_BYTES {
        return Err(ExportError(
            "export output exceeds the bounded artifact size",
        ));
    }
    let output_sha256 = sha256_bytes(&output_payload);
    let summary = Summary {
        record_count: output_records.len(),
        requested_limit: REQUESTED_LIMIT,
        effective_converter_bound: EFFECTIVE_CONVERTER_BOUND,
        total_candidate_count,
        truncated_record_count,
        search_exhausted_record_count,
        input_sha256,
        output_sha256,
        dictionary_sha256,
        exporter_git_sha: identity.exporter_git_sha.clone(),
        exporter_binary_sha256: identity.exporter_binary_sha256.clone(),
        verification_status: identity.verification_status.clone(),
    };
    let report_payload = canonical_json_bytes(&summary_value(&summary))?;
    maybe_inject_failure("output")?;
    write_pair_atomic(
        &arguments.output,
        &output_payload,
        &arguments.report,
        &report_payload,
    )?;
    println!("{}", canonical_json_string(&summary_value(&summary))?);
    Ok(())
}

fn parse_args<I>(arguments: I) -> Result<Args, ExportError>
where
    I: IntoIterator,
    I::Item: Into<String>,
{
    let mut values = BTreeMap::<String, String>::new();
    let mut iter = arguments.into_iter().map(Into::into);
    while let Some(argument) = iter.next() {
        if argument == "--help" {
            println!("sakura-research-top32-exporter --input PATH --dictionary PATH --output PATH --report PATH --identity-manifest PATH [--limit 32]");
            std::process::exit(0);
        }
        if !argument.starts_with("--") {
            return Err(ExportError("unknown command-line argument"));
        }
        let value = iter
            .next()
            .ok_or(ExportError("command-line option is missing a value"))?;
        if value.starts_with("--") {
            return Err(ExportError("command-line option is missing a value"));
        }
        if values.insert(argument, value).is_some() {
            return Err(ExportError("duplicate command-line option"));
        }
    }
    let required = [
        "--input",
        "--dictionary",
        "--output",
        "--report",
        "--identity-manifest",
    ];
    if required.iter().any(|key| !values.contains_key(*key)) {
        return Err(ExportError("required command-line option is missing"));
    }
    let limit = values
        .get("--limit")
        .map(|value| {
            value
                .parse::<usize>()
                .map_err(|_| ExportError("limit is not an integer"))
        })
        .transpose()?
        .unwrap_or(REQUESTED_LIMIT);
    if limit != REQUESTED_LIMIT {
        return Err(ExportError(
            "only the pinned requested limit 32 is supported",
        ));
    }
    if values
        .keys()
        .any(|key| !required.contains(&key.as_str()) && key != "--limit")
    {
        return Err(ExportError("unknown command-line option"));
    }
    Ok(Args {
        input: PathBuf::from(values.get("--input").ok_or(ExportError("missing input"))?),
        dictionary: PathBuf::from(
            values
                .get("--dictionary")
                .ok_or(ExportError("missing dictionary"))?,
        ),
        output: PathBuf::from(
            values
                .get("--output")
                .ok_or(ExportError("missing output"))?,
        ),
        report: PathBuf::from(
            values
                .get("--report")
                .ok_or(ExportError("missing report"))?,
        ),
        identity_manifest: PathBuf::from(
            values
                .get("--identity-manifest")
                .ok_or(ExportError("missing identity manifest"))?,
        ),
        limit,
    })
}

fn validate_git_identity(identity: &Identity, embedded_git_sha: &str) -> Result<(), ExportError> {
    require_git_sha(embedded_git_sha)?;
    if identity.exporter_git_sha != embedded_git_sha {
        return Err(ExportError(
            "exporter Git identity does not match the binary",
        ));
    }
    Ok(())
}

fn validate_binary_identity(
    identity: &Identity,
    actual_binary_sha256: &str,
) -> Result<(), ExportError> {
    if identity.exporter_binary_sha256 != actual_binary_sha256 {
        return Err(ExportError(
            "exporter binary hash does not match the manifest",
        ));
    }
    Ok(())
}

fn validate_sakura_input_head(identity: &Identity) -> Result<(), ExportError> {
    if identity.sakura_input_head != PINNED_SAKURA_INPUT_HEAD {
        return Err(ExportError("Sakura Input HEAD is not the pinned revision"));
    }
    Ok(())
}

fn validate_dictionary_identity(
    identity: &Identity,
    actual_dictionary_sha256: &str,
) -> Result<(), ExportError> {
    if actual_dictionary_sha256 != PINNED_DICTIONARY_SHA256
        || identity.dictionary_sha256 != actual_dictionary_sha256
    {
        return Err(ExportError(
            "dictionary hash does not match the pinned input",
        ));
    }
    Ok(())
}

fn load_identity(path: &Path) -> Result<Identity, ExportError> {
    let bytes = read_bounded_file(path, 64 * 1024)?;
    let value: Value = serde_json::from_slice(&bytes)
        .map_err(|_| ExportError("identity manifest is invalid JSON"))?;
    let object = value
        .as_object()
        .ok_or(ExportError("identity manifest is not an object"))?;
    let expected = [
        "schema_version",
        "manifest_kind",
        "verification_status",
        "exporter_git_sha",
        "exporter_binary_sha256",
        "sakura_input_head",
        "dictionary_sha256",
        "instrumentation_patch_sha256",
        "cargo_lock_sha256",
        "rustc_version",
        "cargo_version",
        "target_triple",
        "profile",
        "build_flags",
        "build_environment",
        "requested_limit",
        "effective_converter_bound",
        "user_dictionary_enabled",
    ];
    if object.len() != expected.len() || expected.iter().any(|key| !object.contains_key(*key)) {
        return Err(ExportError("identity manifest fields are incomplete"));
    }
    if object.get("schema_version").and_then(Value::as_u64)
        != Some(EXPORTER_MANIFEST_SCHEMA_VERSION)
        || object.get("manifest_kind").and_then(Value::as_str) != Some("research_top32_exporter")
    {
        return Err(ExportError("identity manifest schema is unsupported"));
    }
    let verification_status = require_string(object, "verification_status")?.to_owned();
    if verification_status != "unverified" && verification_status != "verified" {
        return Err(ExportError("identity verification status is unsupported"));
    }
    let exporter_git_sha = require_string(object, "exporter_git_sha")?.to_owned();
    require_git_sha(&exporter_git_sha)?;
    let exporter_binary_sha256 = require_string(object, "exporter_binary_sha256")?.to_owned();
    require_sha256(&exporter_binary_sha256)?;
    let sakura_input_head = require_string(object, "sakura_input_head")?.to_owned();
    require_git_sha(&sakura_input_head)?;
    let dictionary_sha256 = require_string(object, "dictionary_sha256")?.to_owned();
    require_sha256(&dictionary_sha256)?;
    let instrumentation_patch_sha256 =
        require_string(object, "instrumentation_patch_sha256")?.to_owned();
    require_sha256(&instrumentation_patch_sha256)?;
    let cargo_lock_sha256 = require_string(object, "cargo_lock_sha256")?.to_owned();
    require_sha256(&cargo_lock_sha256)?;
    let rustc_version = require_string(object, "rustc_version")?.to_owned();
    let cargo_version = require_string(object, "cargo_version")?.to_owned();
    let target_triple = require_string(object, "target_triple")?.to_owned();
    for key in ["rustc_version", "cargo_version", "target_triple"] {
        if require_string(object, key)?.is_empty() {
            return Err(ExportError("identity toolchain field is empty"));
        }
    }
    let profile = require_string(object, "profile")?.to_owned();
    let build_flags = parse_build_flags(object.get("build_flags"))?;
    let build_environment = parse_build_environment(object.get("build_environment"))?;
    if profile != EXPECTED_PROFILE
        || object.get("requested_limit").and_then(Value::as_u64) != Some(REQUESTED_LIMIT as u64)
        || object
            .get("effective_converter_bound")
            .and_then(Value::as_u64)
            != Some(EFFECTIVE_CONVERTER_BOUND as u64)
        || object
            .get("user_dictionary_enabled")
            .and_then(Value::as_bool)
            != Some(false)
    {
        return Err(ExportError(
            "identity manifest does not pin the exporter invariants",
        ));
    }
    Ok(Identity {
        verification_status,
        exporter_git_sha,
        exporter_binary_sha256,
        sakura_input_head,
        dictionary_sha256,
        instrumentation_patch_sha256,
        cargo_lock_sha256,
        rustc_version,
        cargo_version,
        target_triple,
        profile,
        build_flags,
        build_environment,
        requested_limit: REQUESTED_LIMIT,
        effective_converter_bound: EFFECTIVE_CONVERTER_BOUND,
        user_dictionary_enabled: false,
    })
}

fn parse_build_flags(value: Option<&Value>) -> Result<Vec<String>, ExportError> {
    let values = value
        .and_then(Value::as_array)
        .ok_or(ExportError("identity build flags are not an array"))?;
    let flags = values
        .iter()
        .map(|value| {
            value
                .as_str()
                .filter(|flag| !flag.is_empty())
                .map(ToOwned::to_owned)
                .ok_or(ExportError("identity build flag is not a non-empty string"))
        })
        .collect::<Result<Vec<_>, _>>()?;
    if flags
        != EXPECTED_BUILD_FLAGS
            .iter()
            .map(|flag| (*flag).to_owned())
            .collect::<Vec<_>>()
    {
        return Err(ExportError("identity build flags are not pinned"));
    }
    Ok(flags)
}

fn parse_build_environment(value: Option<&Value>) -> Result<BTreeMap<String, String>, ExportError> {
    let object = value
        .and_then(Value::as_object)
        .ok_or(ExportError("identity build environment is not an object"))?;
    let environment = object
        .iter()
        .map(|(key, value)| {
            let value = value
                .as_str()
                .filter(|value| !value.is_empty())
                .ok_or(ExportError("identity build environment value is invalid"))?;
            Ok((key.clone(), value.to_owned()))
        })
        .collect::<Result<BTreeMap<_, _>, ExportError>>()?;
    let expected = EXPECTED_BUILD_ENVIRONMENT
        .into_iter()
        .map(|(key, value)| (key.to_owned(), value.to_owned()))
        .collect::<BTreeMap<_, _>>();
    if environment != expected {
        return Err(ExportError("identity build environment is not pinned"));
    }
    Ok(environment)
}

fn validate_embedded_identity(identity: &Identity) -> Result<(), ExportError> {
    let embedded_patch = option_env!("SAKURA_RERANK_PATCH_SHA256").ok_or(ExportError(
        "missing embedded instrumentation patch identity",
    ))?;
    let embedded_lock = option_env!("SAKURA_RERANK_CARGO_LOCK_SHA256")
        .ok_or(ExportError("missing embedded Cargo.lock identity"))?;
    let embedded_rustc = option_env!("SAKURA_RERANK_RUSTC_VERSION")
        .ok_or(ExportError("missing embedded rustc identity"))?;
    let embedded_cargo = option_env!("SAKURA_RERANK_CARGO_VERSION")
        .ok_or(ExportError("missing embedded cargo identity"))?;
    if identity.instrumentation_patch_sha256 != embedded_patch
        || identity.cargo_lock_sha256 != embedded_lock
        || identity.rustc_version != embedded_rustc
        || identity.cargo_version != embedded_cargo
        || identity.target_triple != EXPECTED_TARGET_TRIPLE
        || identity.profile != EXPECTED_PROFILE
    {
        return Err(ExportError(
            "identity metadata does not match the measured build",
        ));
    }
    if embedded_rustc != EXPECTED_RUSTC_VERSION || embedded_cargo != EXPECTED_CARGO_VERSION {
        return Err(ExportError("build toolchain is not the pinned toolchain"));
    }
    Ok(())
}

fn maybe_inject_failure(point: &str) -> Result<(), ExportError> {
    if env::var("SAKURA_RERANK_TEST_FAIL_AT").ok().as_deref() == Some(point) {
        return Err(ExportError("test failure injection"));
    }
    Ok(())
}

fn parse_input(payload: &[u8]) -> Result<Vec<InputRecord>, ExportError> {
    if payload.is_empty() || payload.len() > MAX_INPUT_BYTES {
        return Err(ExportError("input is empty or exceeds its byte bound"));
    }
    let mut records = Vec::new();
    let mut seen = BTreeSet::new();
    let has_trailing_newline = payload.last() == Some(&b'\n');
    let mut lines = payload.split(|byte| *byte == b'\n').peekable();
    while let Some(raw_line) = lines.next() {
        if raw_line.is_empty() && has_trailing_newline && lines.peek().is_none() {
            continue;
        }
        if raw_line.len() > MAX_INPUT_LINE_BYTES || raw_line.iter().all(u8::is_ascii_whitespace) {
            return Err(ExportError("input contains a blank or oversized line"));
        }
        let value: Value = serde_json::from_slice(raw_line)
            .map_err(|_| ExportError("input line is invalid JSON"))?;
        let object = value
            .as_object()
            .ok_or(ExportError("input line is not an object"))?;
        if object.len() != 2 || !object.contains_key("stable_id") || !object.contains_key("reading")
        {
            return Err(ExportError(
                "input line fields do not match the bounded schema",
            ));
        }
        let stable_id = require_string(object, "stable_id")?;
        require_stable_id(stable_id)?;
        let reading = require_string(object, "reading")?;
        require_reading(reading)?;
        if !seen.insert(stable_id.to_owned()) {
            return Err(ExportError("input stable IDs are not unique"));
        }
        records.push(InputRecord {
            stable_id: stable_id.to_owned(),
            reading: reading.to_owned(),
        });
        if records.len() > MAX_INPUT_RECORDS {
            return Err(ExportError("input exceeds the bounded record count"));
        }
    }
    if records.is_empty() {
        return Err(ExportError("input contains no records"));
    }
    records.sort_by(|left, right| left.stable_id.cmp(&right.stable_id));
    Ok(records)
}

fn make_record(
    input: &InputRecord,
    candidates: &[ConversionCandidate],
    result_status: ResearchSearchStatus,
    identity: &Identity,
) -> Result<Value, ExportError> {
    if candidates.is_empty() || candidates.len() > REQUESTED_LIMIT {
        return Err(ExportError("converter returned an invalid candidate count"));
    }
    let converter_provenance = object([
        (
            "dictionary_sha256",
            Value::String(identity.dictionary_sha256.clone()),
        ),
        (
            "feature_contract_version",
            Value::from(CONVERTER_FEATURE_CONTRACT_VERSION),
        ),
        (
            "kind",
            Value::String("sakura_input_converter_export".to_owned()),
        ),
        (
            "sakura_input_head",
            Value::String(identity.sakura_input_head.clone()),
        ),
    ]);
    let candidate_values = candidates
        .iter()
        .enumerate()
        .map(|(rank, candidate)| candidate_value(candidate, rank))
        .collect::<Result<Vec<_>, _>>()?;
    let exporter_run = object([
        (
            "contract_version",
            Value::from(RESEARCH_EXPORTER_CONTRACT_VERSION),
        ),
        (
            "effective_converter_bound",
            Value::from(EFFECTIVE_CONVERTER_BOUND),
        ),
        (
            "exporter_binary_sha256",
            Value::String(identity.exporter_binary_sha256.clone()),
        ),
        (
            "exporter_git_sha",
            Value::String(identity.exporter_git_sha.clone()),
        ),
        ("requested_limit", Value::from(REQUESTED_LIMIT)),
        (
            "result_status",
            Value::String(result_status.as_str().to_owned()),
        ),
        ("returned_count", Value::from(candidate_values.len())),
        (
            "verification_status",
            Value::String(identity.verification_status.clone()),
        ),
    ]);
    let top32_base = object([
        ("candidates", Value::Array(candidate_values.clone())),
        ("exporter_run", exporter_run),
        (
            "feature_contract_version",
            Value::from(CONVERTER_FEATURE_CONTRACT_VERSION),
        ),
        ("limit", Value::from(REQUESTED_LIMIT)),
        ("reading", Value::String(input.reading.clone())),
        (
            "source",
            Value::String("sakura_converter_full_reading_nbest".to_owned()),
        ),
    ]);
    let top32_hash = candidate_snapshot_hash(&top32_base, &converter_provenance)?;
    let top32 = insert_hash(top32_base, top32_hash)?;
    let top6_base = object([
        (
            "candidates",
            Value::Array(
                candidate_values
                    .into_iter()
                    .take(PRODUCTION_LIMIT)
                    .collect(),
            ),
        ),
        (
            "feature_contract_version",
            Value::from(CONVERTER_FEATURE_CONTRACT_VERSION),
        ),
        ("limit", Value::from(PRODUCTION_LIMIT)),
        ("reading", Value::String(input.reading.clone())),
        (
            "source",
            Value::String("sakura_converter_full_reading_nbest".to_owned()),
        ),
    ]);
    let top6_hash = candidate_snapshot_hash(&top6_base, &converter_provenance)?;
    let top6 = insert_hash(top6_base, top6_hash)?;
    Ok(object([
        (
            "candidate_snapshots",
            object([("production_top6", top6), ("training_top32", top32)]),
        ),
        ("converter_provenance", converter_provenance),
        ("reading", Value::String(input.reading.clone())),
        (
            "record_type",
            Value::String("research_converter_snapshot".to_owned()),
        ),
        ("schema_version", Value::from(CONTRACT_SCHEMA_VERSION)),
        ("stable_id", Value::String(input.stable_id.clone())),
    ]))
}

fn candidate_value(candidate: &ConversionCandidate, rank: usize) -> Result<Value, ExportError> {
    let mut categories = BTreeSet::new();
    let segments = candidate
        .segments()
        .iter()
        .map(|segment| {
            let category = segment.source_category.as_str();
            categories.insert(category);
            object([
                ("flags", Value::from(segment.flags.bits())),
                ("left_id", Value::from(segment.left_id)),
                ("reading_end", Value::from(segment.reading_end)),
                ("reading_start", Value::from(segment.reading_start)),
                ("right_id", Value::from(segment.right_id)),
                ("source_category", Value::String(category.to_owned())),
                ("text_end", Value::from(segment.text_end)),
                ("text_start", Value::from(segment.text_start)),
            ])
        })
        .collect::<Vec<_>>();
    if segments.is_empty() {
        return Err(ExportError(
            "converter returned a candidate without segments",
        ));
    }
    let source_category = if categories.len() == 1 {
        categories
            .first()
            .copied()
            .ok_or(ExportError("candidate source category is missing"))?
    } else {
        "mixed"
    };
    let system_entry_index = candidate
        .system_entry_index()
        .map(Value::from)
        .unwrap_or(Value::Null);
    Ok(object([
        (
            "fingerprint",
            Value::String(fingerprint(candidate.text(), candidate.cost)),
        ),
        ("local_cost", Value::from(candidate.cost)),
        ("rank", Value::from(rank)),
        ("segments", Value::Array(segments)),
        ("source_category", Value::String(source_category.to_owned())),
        ("surface", Value::String(candidate.text().to_owned())),
        ("system_entry_index", system_entry_index),
    ]))
}

fn candidate_snapshot_hash(
    snapshot: &Value,
    converter_provenance: &Value,
) -> Result<String, ExportError> {
    let object = snapshot
        .as_object()
        .ok_or(ExportError("snapshot is not an object"))?;
    let mut payload = BTreeMap::new();
    for key in [
        "limit",
        "source",
        "feature_contract_version",
        "reading",
        "candidates",
        "exporter_run",
    ] {
        if let Some(value) = object.get(key) {
            payload.insert(key.to_owned(), value.clone());
        }
    }
    payload.insert(
        "converter_provenance".to_owned(),
        converter_provenance.clone(),
    );
    canonical_hash(&Value::Object(payload.into_iter().collect()))
}

fn insert_hash(mut snapshot: Value, hash: String) -> Result<Value, ExportError> {
    snapshot
        .as_object_mut()
        .ok_or(ExportError("snapshot is not mutable"))?
        .insert("content_sha256".to_owned(), Value::String(hash));
    Ok(snapshot)
}

fn fingerprint(surface: &str, cost: i64) -> String {
    let mut hash = 0xcbf29ce484222325u64;
    for byte in surface.as_bytes().iter().copied().chain(cost.to_le_bytes()) {
        hash ^= u64::from(byte);
        hash = hash.wrapping_mul(0x00000100000001b3);
    }
    format!("{hash:016x}")
}

fn summary_value(summary: &Summary) -> Value {
    object([
        (
            "dictionary_sha256",
            Value::String(summary.dictionary_sha256.clone()),
        ),
        (
            "exporter_binary_sha256",
            Value::String(summary.exporter_binary_sha256.clone()),
        ),
        (
            "exporter_git_sha",
            Value::String(summary.exporter_git_sha.clone()),
        ),
        (
            "effective_converter_bound",
            Value::from(summary.effective_converter_bound),
        ),
        ("input_sha256", Value::String(summary.input_sha256.clone())),
        (
            "output_sha256",
            Value::String(summary.output_sha256.clone()),
        ),
        ("record_count", Value::from(summary.record_count)),
        ("requested_limit", Value::from(summary.requested_limit)),
        (
            "search_exhausted_record_count",
            Value::from(summary.search_exhausted_record_count),
        ),
        ("status", Value::String("exported".to_owned())),
        (
            "total_candidate_count",
            Value::from(summary.total_candidate_count),
        ),
        (
            "truncated_record_count",
            Value::from(summary.truncated_record_count),
        ),
        (
            "verification_status",
            Value::String(summary.verification_status.clone()),
        ),
    ])
}

fn object<I>(entries: I) -> Value
where
    I: IntoIterator<Item = (&'static str, Value)>,
{
    let mut map = Map::new();
    for (key, value) in entries {
        map.insert(key.to_owned(), value);
    }
    Value::Object(map)
}

fn canonical_json_bytes(value: &Value) -> Result<Vec<u8>, ExportError> {
    let mut bytes = Vec::new();
    write_canonical_json(value, &mut bytes)?;
    Ok(bytes)
}

fn canonical_json_string(value: &Value) -> Result<String, ExportError> {
    String::from_utf8(canonical_json_bytes(value)?)
        .map_err(|_| ExportError("JSON serialization was not UTF-8"))
}

fn canonical_hash(value: &Value) -> Result<String, ExportError> {
    Ok(sha256_bytes(&canonical_json_bytes(value)?))
}

fn canonical_jsonl_bytes(records: &[Value]) -> Result<Vec<u8>, ExportError> {
    let mut bytes = Vec::new();
    for record in records {
        write_canonical_json(record, &mut bytes)?;
        bytes.push(b'\n');
    }
    Ok(bytes)
}

fn write_canonical_json(value: &Value, output: &mut Vec<u8>) -> Result<(), ExportError> {
    match value {
        Value::Null | Value::Bool(_) | Value::Number(_) | Value::String(_) => {
            serde_json::to_writer(output, value)
                .map_err(|_| ExportError("JSON serialization failed"))?;
        }
        Value::Array(values) => {
            output.push(b'[');
            for (index, value) in values.iter().enumerate() {
                if index != 0 {
                    output.push(b',');
                }
                write_canonical_json(value, output)?;
            }
            output.push(b']');
        }
        Value::Object(values) => {
            output.push(b'{');
            let mut entries = values.iter().collect::<Vec<_>>();
            entries.sort_by(|left, right| left.0.cmp(right.0));
            for (index, (key, value)) in entries.into_iter().enumerate() {
                if index != 0 {
                    output.push(b',');
                }
                serde_json::to_writer(&mut *output, key)
                    .map_err(|_| ExportError("JSON serialization failed"))?;
                output.push(b':');
                write_canonical_json(value, output)?;
            }
            output.push(b'}');
        }
    }
    Ok(())
}

fn read_bounded_file(path: &Path, maximum: usize) -> Result<Vec<u8>, ExportError> {
    let metadata =
        fs::metadata(path).map_err(|_| ExportError("required input cannot be inspected"))?;
    if !metadata.is_file() || metadata.len() > maximum as u64 {
        return Err(ExportError("required input is not a bounded regular file"));
    }
    let file = File::open(path).map_err(|_| ExportError("required input cannot be opened"))?;
    let mut bytes = Vec::new();
    file.take(maximum as u64 + 1)
        .read_to_end(&mut bytes)
        .map_err(|_| ExportError("required input cannot be read"))?;
    if bytes.len() > maximum {
        return Err(ExportError("required input exceeded its byte bound"));
    }
    Ok(bytes)
}

fn sha256_file(path: &Path) -> Result<String, ExportError> {
    let mut file = File::open(path).map_err(|_| ExportError("file hash input cannot be opened"))?;
    let mut hasher = Sha256::new();
    let mut buffer = [0u8; 64 * 1024];
    loop {
        let count = file
            .read(&mut buffer)
            .map_err(|_| ExportError("file hash input cannot be read"))?;
        if count == 0 {
            break;
        }
        hasher.update(&buffer[..count]);
    }
    Ok(hex_digest(hasher.finalize()))
}

fn sha256_bytes(bytes: &[u8]) -> String {
    let mut hasher = Sha256::new();
    hasher.update(bytes);
    hex_digest(hasher.finalize())
}

fn hex_digest(digest: impl AsRef<[u8]>) -> String {
    digest
        .as_ref()
        .iter()
        .map(|byte| format!("{byte:02x}"))
        .collect()
}

fn require_string<'a>(object: &'a Map<String, Value>, key: &str) -> Result<&'a str, ExportError> {
    object
        .get(key)
        .and_then(Value::as_str)
        .ok_or(ExportError("required manifest/input field is not a string"))
}

fn require_sha256(value: &str) -> Result<(), ExportError> {
    if value.len() != 64
        || !value
            .bytes()
            .all(|byte| byte.is_ascii_hexdigit() && !byte.is_ascii_uppercase())
    {
        return Err(ExportError("SHA-256 field is not lowercase hexadecimal"));
    }
    Ok(())
}

fn require_git_sha(value: &str) -> Result<(), ExportError> {
    if value.len() != 40
        || !value
            .bytes()
            .all(|byte| byte.is_ascii_hexdigit() && !byte.is_ascii_uppercase())
    {
        return Err(ExportError("Git identity is not lowercase hexadecimal"));
    }
    Ok(())
}

fn require_stable_id(value: &str) -> Result<(), ExportError> {
    let mut bytes = value.bytes();
    let Some(first) = bytes.next() else {
        return Err(ExportError("stable ID is empty"));
    };
    if !(first.is_ascii_alphanumeric())
        || value.len() > 128
        || !bytes.all(|byte| byte.is_ascii_alphanumeric() || b"._:-".contains(&byte))
    {
        return Err(ExportError("stable ID is outside its bounded alphabet"));
    }
    Ok(())
}

fn require_reading(value: &str) -> Result<(), ExportError> {
    if value.is_empty()
        || value.chars().count() > 128
        || value.contains('\0')
        || value.contains('\r')
        || value.contains('\n')
    {
        return Err(ExportError("reading is outside its bounded text contract"));
    }
    Ok(())
}

fn normalized_path(path: &Path) -> Result<PathBuf, ExportError> {
    if path.as_os_str().is_empty() {
        return Err(ExportError("path is empty"));
    }
    if path.exists() {
        return fs::canonicalize(path).map_err(|_| ExportError("path cannot be canonicalized"));
    }
    let parent = path.parent().unwrap_or_else(|| Path::new("."));
    let parent =
        fs::canonicalize(parent).map_err(|_| ExportError("path parent cannot be canonicalized"))?;
    Ok(parent.join(
        path.file_name()
            .ok_or(ExportError("path has no file name"))?,
    ))
}

fn reject_path_collisions(arguments: &Args) -> Result<(), ExportError> {
    let paths = [
        &arguments.input,
        &arguments.dictionary,
        &arguments.output,
        &arguments.report,
        &arguments.identity_manifest,
    ];
    for left_index in 0..paths.len() {
        for right_index in (left_index + 1)..paths.len() {
            let left = normalized_path(paths[left_index])?;
            let right = normalized_path(paths[right_index])?;
            let same_name = if cfg!(windows) {
                left.to_string_lossy()
                    .eq_ignore_ascii_case(&right.to_string_lossy())
            } else {
                left == right
            };
            if same_name {
                return Err(ExportError(
                    "input, identity, output, and report paths collide",
                ));
            }
        }
    }
    for path in [&arguments.output, &arguments.report] {
        if path.exists() {
            return Err(ExportError("output or report already exists"));
        }
        let parent = path.parent().unwrap_or_else(|| Path::new("."));
        if !parent.is_dir() {
            return Err(ExportError("output or report parent directory is missing"));
        }
    }
    Ok(())
}

fn temp_path(path: &Path, suffix: &str, index: usize) -> PathBuf {
    let file_name = path
        .file_name()
        .and_then(|value| value.to_str())
        .unwrap_or("artifact");
    path.with_file_name(format!(
        ".{file_name}.research-exporter-{}-{suffix}-{index}.tmp",
        std::process::id()
    ))
}

fn write_pair_atomic(
    output_path: &Path,
    output: &[u8],
    report_path: &Path,
    report: &[u8],
) -> Result<(), ExportError> {
    let mut output_temp = None;
    let mut report_temp = None;
    for index in 0..16 {
        let candidate_output = temp_path(output_path, "output", index);
        let candidate_report = temp_path(report_path, "report", index);
        if !candidate_output.exists() && !candidate_report.exists() {
            output_temp = Some(candidate_output);
            report_temp = Some(candidate_report);
            break;
        }
    }
    let output_temp = output_temp.ok_or(ExportError("cannot allocate atomic output paths"))?;
    let report_temp = report_temp.ok_or(ExportError("cannot allocate atomic report paths"))?;
    let mut output_published = false;
    let mut report_published = false;
    let result = (|| {
        write_new_synced(&output_temp, output)?;
        maybe_inject_failure("report")?;
        write_new_synced(&report_temp, report)?;
        if output_path.exists() || report_path.exists() {
            return Err(ExportError("output or report appeared during export"));
        }
        fs::rename(&output_temp, output_path)
            .map_err(|_| ExportError("cannot publish output atomically"))?;
        output_published = true;
        if let Err(error) = fs::rename(&report_temp, report_path) {
            return Err(if error.kind() == io::ErrorKind::AlreadyExists {
                ExportError("report appeared during export")
            } else {
                ExportError("cannot publish report atomically")
            });
        }
        report_published = true;
        Ok(())
    })();
    if result.is_err() {
        let _ = fs::remove_file(&output_temp);
        let _ = fs::remove_file(&report_temp);
        if output_published {
            let _ = fs::remove_file(output_path);
        }
        if report_published {
            let _ = fs::remove_file(report_path);
        }
    }
    result
}

fn write_new_synced(path: &Path, bytes: &[u8]) -> Result<(), ExportError> {
    let mut file = OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(path)
        .map_err(|_| ExportError("cannot create atomic temporary output"))?;
    file.write_all(bytes)
        .map_err(|_| ExportError("cannot write atomic temporary output"))?;
    file.sync_all()
        .map_err(|_| ExportError("cannot flush atomic temporary output"))?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::{Mutex, OnceLock};

    fn test_lock() -> std::sync::MutexGuard<'static, ()> {
        static LOCK: OnceLock<Mutex<()>> = OnceLock::new();
        LOCK.get_or_init(|| Mutex::new(()))
            .lock()
            .expect("test lock")
    }

    fn test_root(name: &str) -> PathBuf {
        let root = env::temp_dir().join(format!(
            "sakura-research-exporter-{name}-{}",
            std::process::id()
        ));
        fs::create_dir_all(&root).expect("test directory");
        root
    }

    fn assert_empty(root: &Path) {
        assert_eq!(
            fs::read_dir(root).expect("test directory listing").count(),
            0,
            "temporary residue remained"
        );
    }

    fn test_identity() -> Identity {
        Identity {
            verification_status: "unverified".to_owned(),
            exporter_git_sha: "a".repeat(40),
            exporter_binary_sha256: "b".repeat(64),
            sakura_input_head: PINNED_SAKURA_INPUT_HEAD.to_owned(),
            dictionary_sha256: PINNED_DICTIONARY_SHA256.to_owned(),
            instrumentation_patch_sha256: "c".repeat(64),
            cargo_lock_sha256: "d".repeat(64),
            rustc_version: EXPECTED_RUSTC_VERSION.to_owned(),
            cargo_version: EXPECTED_CARGO_VERSION.to_owned(),
            target_triple: EXPECTED_TARGET_TRIPLE.to_owned(),
            profile: EXPECTED_PROFILE.to_owned(),
            build_flags: EXPECTED_BUILD_FLAGS
                .iter()
                .map(|value| (*value).to_owned())
                .collect(),
            build_environment: EXPECTED_BUILD_ENVIRONMENT
                .iter()
                .map(|(key, value)| ((*key).to_owned(), (*value).to_owned()))
                .collect(),
            requested_limit: REQUESTED_LIMIT,
            effective_converter_bound: EFFECTIVE_CONVERTER_BOUND,
            user_dictionary_enabled: false,
        }
    }

    #[test]
    fn wrong_git_binary_dictionary_and_sakura_identities_are_rejected() {
        let identity = test_identity();
        assert!(validate_git_identity(&identity, &"e".repeat(40)).is_err());
        assert!(validate_binary_identity(&identity, &"f".repeat(64)).is_err());
        assert!(validate_dictionary_identity(&identity, &"0".repeat(64)).is_err());
        let mut wrong_sakura = identity;
        wrong_sakura.sakura_input_head = "1".repeat(40);
        assert!(validate_sakura_input_head(&wrong_sakura).is_err());
    }

    #[test]
    fn production_limit_eighteen_cli_is_rejected() {
        let arguments = [
            "--input",
            "input",
            "--dictionary",
            "dictionary",
            "--output",
            "output",
            "--report",
            "report",
            "--identity-manifest",
            "identity",
            "--limit",
            "18",
        ];
        assert!(parse_args(arguments).is_err());
    }

    #[test]
    fn path_collision_is_rejected_before_publication() {
        let root = test_root("collision");
        let output = root.join("same");
        let arguments = Args {
            input: root.join("input"),
            dictionary: root.join("dictionary"),
            output: output.clone(),
            report: output,
            identity_manifest: root.join("identity"),
            limit: REQUESTED_LIMIT,
        };
        assert!(reject_path_collisions(&arguments).is_err());
        fs::remove_dir_all(root).expect("test cleanup");
    }

    #[test]
    fn input_failure_injection_has_no_publication() {
        let _guard = test_lock();
        let root = test_root("input-failure");
        env::set_var("SAKURA_RERANK_TEST_FAIL_AT", "input");
        assert!(maybe_inject_failure("input").is_err());
        env::remove_var("SAKURA_RERANK_TEST_FAIL_AT");
        assert_empty(&root);
        fs::remove_dir_all(root).expect("test cleanup");
    }

    #[test]
    fn output_and_report_failure_injection_leave_no_partial_or_temporary_files() {
        let _guard = test_lock();
        for point in ["output", "report"] {
            let root = test_root(point);
            let output = root.join("output.jsonl");
            let report = root.join("report.json");
            env::set_var("SAKURA_RERANK_TEST_FAIL_AT", point);
            let result = if point == "output" {
                maybe_inject_failure(point)
            } else {
                write_pair_atomic(&output, b"output", &report, b"report")
            };
            env::remove_var("SAKURA_RERANK_TEST_FAIL_AT");
            assert!(result.is_err());
            assert!(!output.exists());
            assert!(!report.exists());
            assert_empty(&root);
            fs::remove_dir_all(root).expect("test cleanup");
        }
    }

    #[test]
    fn report_and_summary_do_not_contain_raw_input_text() {
        let summary = Summary {
            record_count: 1,
            requested_limit: REQUESTED_LIMIT,
            effective_converter_bound: EFFECTIVE_CONVERTER_BOUND,
            total_candidate_count: 1,
            truncated_record_count: 0,
            search_exhausted_record_count: 1,
            input_sha256: "0".repeat(64),
            output_sha256: "1".repeat(64),
            dictionary_sha256: PINNED_DICTIONARY_SHA256.to_owned(),
            exporter_git_sha: "2".repeat(40),
            exporter_binary_sha256: "3".repeat(64),
            verification_status: "unverified".to_owned(),
        };
        let report = canonical_json_string(&summary_value(&summary)).expect("summary JSON");
        assert!(!report.contains("private-reading"));
        assert!(!report.contains("host-document"));
        assert!(report.contains("input_sha256"));
    }
}
