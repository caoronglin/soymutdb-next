//! One JSON document through EOF: [[N,K,n,k], ...] -> [p, ...].
use soymutdb_enrichment_core::{Case, MAX_ROWS, compute};
use std::io::{self, Read};
const MAX_BYTES: u64 = 16 * 1024 * 1024;
fn run() -> Result<(), String> {
    let mut input = Vec::new();
    io::stdin()
        .take(MAX_BYTES + 1)
        .read_to_end(&mut input)
        .map_err(|e| e.to_string())?;
    if input.len() as u64 > MAX_BYTES {
        return Err("resource cap: 16 MiB stdin".into());
    }
    let json: serde_json::Value = serde_json::from_slice(&input).map_err(|e| e.to_string())?;
    let rows = json.as_array().ok_or("batch must be an array")?;
    if rows.len() > MAX_ROWS {
        return Err("resource cap: 100000 rows".into());
    }
    let cases: Vec<Case> = rows
        .iter()
        .map(|row| {
            let row = row
                .as_array()
                .filter(|r| r.len() == 4)
                .ok_or("each row must contain four counts")?;
            let mut result = [0; 4];
            for i in 0..4 {
                result[i] = row[i]
                    .as_u64()
                    .ok_or("counts must be nonnegative u64 integers")?;
            }
            Ok(result)
        })
        .collect::<Result<_, String>>()?;
    let result = compute(&cases, || Ok(()))?;
    println!(
        "{}",
        serde_json::to_string(&result).map_err(|e| e.to_string())?
    );
    Ok(())
}
fn main() {
    if let Err(error) = run() {
        eprintln!("enrichment-sf: {error}");
        std::process::exit(2);
    }
}
