//! Experimental inclusive hypergeometric SF. No production wiring or BH owner.
pub type Case = [u64; 4];
pub const MAX_N: u64 = 2_000_000;
pub const MAX_ROWS: usize = 100_000;
pub const MAX_WORK: u64 = 50_000_000;

fn bounds([n_total, successes, draws, _]: Case) -> (u64, u64) {
    (
        draws.saturating_sub(n_total - successes),
        draws.min(successes),
    )
}

/// Validate the entire batch, including work, before any numerical computation.
pub fn validate(cases: &[Case]) -> Result<(), String> {
    if cases.len() > MAX_ROWS {
        return Err("resource cap: 100000 rows".into());
    }
    let mut work = 0u64;
    for (i, &c @ [n_total, successes, draws, k]) in cases.iter().enumerate() {
        if n_total == 0 || n_total > MAX_N || successes > n_total || draws > n_total {
            return Err(format!(
                "row {i}: require 1 <= N <= {MAX_N}, K <= N, n <= N"
            ));
        }
        let (lo, hi) = bounds(c);
        if k > lo && k <= hi {
            work += if k * n_total <= draws * successes {
                k - lo
            } else {
                hi - k + 1
            };
        }
        if work > MAX_WORK {
            return Err("resource cap: 50000000 support terms per batch".into());
        }
    }
    Ok(())
}

/// Constant-space scaled recurrence: full finite tail, compensated summation.
/// Caller must validate first. The explicit N cap keeps integer products exact/safe.
fn sf_validated(c: Case) -> f64 {
    let [n_total, successes, draws, k] = c;
    let (lo, hi) = bounds(c);
    if k <= lo {
        return 1.0;
    }
    if k > hi {
        return 0.0;
    }
    let lower = k * n_total <= draws * successes;
    let start = if lower { k - 1 } else { k };
    // Signed difference avoids unsigned N-K-n underflow for positive lower support.
    let gap = n_total as i64 - successes as i64 - draws as i64;
    let mut weight = 1.0;
    let mut sum = 1.0;
    let mut compensation = 0.0;
    let mut x = start;
    while if lower { x > lo } else { x < hi } {
        let (num, den) = if lower {
            (
                x * (gap + x as i64) as u64,
                (successes - x + 1) * (draws - x + 1),
            )
        } else {
            (
                (successes - x) * (draws - x),
                (x + 1) * (gap + x as i64 + 1) as u64,
            )
        };
        weight *= num as f64 / den as f64;
        let corrected = weight - compensation;
        let next = sum + corrected;
        compensation = (next - sum) - corrected;
        sum = next;
        if lower {
            x -= 1;
        } else {
            x += 1;
        }
    }
    let terms = [
        (successes + 1, 1.0),
        (start + 1, -1.0),
        (successes - start + 1, -1.0),
        (n_total - successes + 1, 1.0),
        (draws - start + 1, -1.0),
        ((gap + start as i64 + 1) as u64, -1.0),
        (n_total + 1, -1.0),
        (draws + 1, 1.0),
        (n_total - draws + 1, 1.0),
    ];
    let mut log_pmf = 0.0;
    let mut correction = 0.0;
    for (arg, sign) in terms {
        // Neumaier sum handles cancellation among log-gamma terms.
        let term = sign * libm::lgamma(arg as f64);
        let next = log_pmf + term;
        correction += if log_pmf.abs() >= term.abs() {
            (log_pmf - next) + term
        } else {
            (term - next) + log_pmf
        };
        log_pmf = next;
    }
    let log_p = (log_pmf + correction + sum.ln()).min(0.0);
    (if lower { -log_p.exp_m1() } else { log_p.exp() }).clamp(0.0, 1.0)
}

/// Poll cancellation between cases; errors never return partial values.
pub fn compute(
    cases: &[Case],
    mut checkpoint: impl FnMut() -> Result<(), String>,
) -> Result<Vec<f64>, String> {
    validate(cases)?;
    let mut result = Vec::with_capacity(cases.len());
    for &case in cases {
        checkpoint()?;
        result.push(sf_validated(case));
    }
    checkpoint()?;
    Ok(result)
}

#[cfg(feature = "python")]
mod python {
    use super::*;
    use pyo3::{
        exceptions::PyValueError,
        prelude::*,
        types::{PyBool, PyInt, PyList, PyTuple},
    };
    fn count(value: &Bound<'_, PyAny>) -> PyResult<u64> {
        if value.is_instance_of::<PyBool>() || !value.is_instance_of::<PyInt>() {
            return Err(PyValueError::new_err(
                "counts must be nonnegative u64 integers, not bool/float",
            ));
        }
        value
            .extract()
            .map_err(|_| PyValueError::new_err("count negative or exceeds u64"))
    }
    fn rows(value: &Bound<'_, PyAny>) -> PyResult<Vec<Case>> {
        if !(value.is_instance_of::<PyList>() || value.is_instance_of::<PyTuple>()) {
            return Err(PyValueError::new_err(
                "batch must be list/tuple of four-count rows",
            ));
        }
        if value.len()? > MAX_ROWS {
            return Err(PyValueError::new_err("resource cap: 100000 rows"));
        }
        let mut result = Vec::with_capacity(value.len()?);
        for row in value.try_iter()? {
            let row = row?;
            if !(row.is_instance_of::<PyList>() || row.is_instance_of::<PyTuple>())
                || row.len()? != 4
            {
                return Err(PyValueError::new_err(
                    "each row must be list/tuple [N,K,n,k]",
                ));
            }
            result.push([
                count(&row.get_item(0)?)?,
                count(&row.get_item(1)?)?,
                count(&row.get_item(2)?)?,
                count(&row.get_item(3)?)?,
            ]);
        }
        validate(&result).map_err(PyValueError::new_err)?;
        Ok(result)
    }
    #[pyfunction]
    fn sf_batch(py: Python<'_>, cases: &Bound<'_, PyAny>) -> PyResult<Vec<f64>> {
        let cases = rows(cases)?;
        // Detach the entire numerical batch, reacquiring only to poll Python signals.
        let mut signal_error = None;
        let result = py.detach(|| {
            compute(&cases, || {
                Python::attach(|py| py.check_signals()).map_err(|err| {
                    signal_error = Some(err);
                    "cancelled".into()
                })
            })
        });
        if let Some(err) = signal_error {
            return Err(err);
        }
        result.map_err(PyValueError::new_err)
    }
    #[pyfunction]
    #[pyo3(name = "hypergeom_sf")]
    fn scalar(
        py: Python<'_>,
        n_total: &Bound<'_, PyAny>,
        successes: &Bound<'_, PyAny>,
        draws: &Bound<'_, PyAny>,
        k: &Bound<'_, PyAny>,
    ) -> PyResult<f64> {
        let cases = [[count(n_total)?, count(successes)?, count(draws)?, count(k)?]];
        py.detach(|| compute(&cases, || Ok(())))
            .map(|v| v[0])
            .map_err(PyValueError::new_err)
    }
    #[pymodule]
    fn soymutdb_enrichment_core(m: &Bound<'_, PyModule>) -> PyResult<()> {
        m.add_function(wrap_pyfunction!(sf_batch, m)?)?;
        m.add_function(wrap_pyfunction!(scalar, m)?)?;
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn boundaries_and_order() {
        assert_eq!(
            compute(&[[10, 8, 4, 2], [10, 8, 4, 5], [10, 0, 4, 0]], || Ok(())).unwrap(),
            [1., 0., 1.]
        );
        assert!(compute(&[], || Ok(())).unwrap().is_empty());
    }
    #[test]
    fn known_exact() {
        assert!((compute(&[[20, 5, 4, 2]], || Ok(())).unwrap()[0] - 1205.0 / 4845.0).abs() < 1e-12);
    }
    #[test]
    fn deep_tail_positive() {
        assert!(compute(&[[56000, 100, 500, 60]], || Ok(())).unwrap()[0] > 0.0);
    }
    #[test]
    fn whole_batch_validation() {
        assert!(
            compute(&[[10, 5, 4, 2], [10, 11, 1, 0]], || panic!(
                "must validate before checkpoint"
            ))
            .is_err()
        );
    }
    #[test]
    fn resource_cap() {
        assert!(validate(&vec![[2_000_000, 1_000_000, 1_000_000, 500_000]; 101]).is_err());
    }
    #[test]
    fn cancellation_atomic() {
        assert!(compute(&[[10, 5, 4, 2]], || Err("cancelled".into())).is_err());
    }
}
