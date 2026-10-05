//! Native atom-block parser for lammps_post.parsers.DumpReader.
//!
//! The Python side keeps np.loadtxt as the reference implementation and falls
//! back to it whenever this parser reports an error, so error messages and
//! edge-case behaviour are defined there.

use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;
use pyo3::types::{PyByteArray, PyList};

struct Parsed {
    values: Vec<u8>,
    elements: Vec<String>,
    rows: usize,
}

fn parse(
    buf: &[u8],
    natoms: usize,
    usecols: &[usize],
    element_col: Option<usize>,
    single: bool,
) -> Result<Parsed, String> {
    let max_col = usecols.iter().copied().max().unwrap_or(0);
    let numeric: Vec<(usize, usize)> = usecols
        .iter()
        .copied()
        .filter(|&c| Some(c) != element_col)
        .enumerate()
        .map(|(slot, c)| (c, slot))
        .collect();
    let ncols = numeric.len();
    let itemsize = if single { 4 } else { 8 };
    let mut values = vec![0u8; natoms * ncols * itemsize];
    let mut elements = Vec::with_capacity(if element_col.is_some() { natoms } else { 0 });

    // Column -> output slot, or usize::MAX for unused columns.
    let mut slot_of = vec![usize::MAX; max_col + 1];
    for &(c, slot) in &numeric {
        slot_of[c] = slot;
    }

    let mut rows = 0usize;
    for line in buf.split(|&b| b == b'\n').take(natoms) {
        let mut tokens = line
            .split(|b| b.is_ascii_whitespace())
            .filter(|t| !t.is_empty());
        let mut seen = 0usize;
        for col in 0..=max_col {
            let Some(tok) = tokens.next() else {
                if col == 0 {
                    break;
                }
                return Err(format!("row {rows} has {col} columns, need {}", max_col + 1));
            };
            seen = col + 1;
            if Some(col) == element_col {
                let s = std::str::from_utf8(tok).map_err(|e| e.to_string())?;
                elements.push(s.to_owned());
                continue;
            }
            let slot = slot_of[col];
            if slot == usize::MAX {
                continue;
            }
            let s = std::str::from_utf8(tok).map_err(|e| e.to_string())?;
            let v: f64 = s.parse().map_err(|_| format!("could not convert {s:?} to float"))?;
            let at = (rows * ncols + slot) * itemsize;
            if single {
                values[at..at + 4].copy_from_slice(&(v as f32).to_ne_bytes());
            } else {
                values[at..at + 8].copy_from_slice(&v.to_ne_bytes());
            }
        }
        if seen == 0 {
            // Blank line: np.loadtxt skips it, so it does not count as a row.
            continue;
        }
        rows += 1;
    }
    Ok(Parsed { values, elements, rows })
}

/// parse_block(buf, natoms, usecols, element_col, single)
///     -> (bytearray, list[str] | None, rows)
///
/// Parses the first `natoms` lines of `buf`. `bytearray` holds a C-order
/// (rows, n_numeric) float64 array (float32 if `single`) of the numeric
/// `usecols`, in file order. Raises ValueError on any token it cannot parse.
#[pyfunction]
#[pyo3(signature = (buf, natoms, usecols, element_col=None, single=false))]
fn parse_block<'py>(
    py: Python<'py>,
    buf: &[u8],
    natoms: usize,
    usecols: Vec<usize>,
    element_col: Option<usize>,
    single: bool,
) -> PyResult<(Bound<'py, PyByteArray>, Option<Bound<'py, PyList>>, usize)> {
    let parsed = py
        .detach(|| parse(buf, natoms, &usecols, element_col, single))
        .map_err(PyValueError::new_err)?;
    let ncols = usecols.len() - usize::from(element_col.is_some());
    let itemsize = if single { 4 } else { 8 };
    let values = PyByteArray::new(py, &parsed.values[..parsed.rows * ncols * itemsize]);
    let elements = match element_col {
        Some(_) => Some(PyList::new(py, parsed.elements)?),
        None => None,
    };
    Ok((values, elements, parsed.rows))
}

#[pymodule]
fn _dumpparse(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(parse_block, m)?)
}
