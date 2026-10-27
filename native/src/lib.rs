//! Native atom-block parser for lammps_post.parsers.DumpReader.
//!
//! The Python side keeps np.loadtxt as the reference implementation and falls
//! back to it whenever this parser reports an error, so error messages and
//! edge-case behaviour are defined there.

use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;
use pyo3::types::{PyByteArray, PyList};

/// Owned parser output: native-endian numeric bytes, copied UTF-8 labels and
/// the observed row count. No field borrows the caller's input buffer.
struct Parsed {
    values: Vec<u8>,
    elements: Vec<String>,
    rows: usize,
}

/// Parse a borrowed atom payload without calling Python APIs.
///
/// `usecols` comes from the Python reader in file order; `element_col`, when
/// present, must be one of those selected columns. Header/geometry checks and
/// exact integer-ID/type precision checks belong to that reader, not this helper.
/// Conversion failures return a message for the Python reference-path fallback.
fn parse(
    buf: &[u8],
    natoms: usize,
    usecols: &[usize],
    element_col: Option<usize>,
    single: bool,
) -> Result<Parsed, String> {
    // Build a compact numeric output order, excluding the selected string column.
    // Unselected tokens are scanned only far enough to reach the last selection.
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
    // Allocate owned, row-major storage up front. The wrapper exposes only the
    // prefix for parsed rows, and the caller compares rows with the expected count.
    let mut values = vec![0u8; natoms * ncols * itemsize];
    let mut elements = Vec::with_capacity(if element_col.is_some() { natoms } else { 0 });

    // Column -> output slot, or usize::MAX for unused columns.
    let mut slot_of = vec![usize::MAX; max_col + 1];
    for &(c, slot) in &numeric {
        slot_of[c] = slot;
    }

    let mut rows = 0usize;
    // Split borrowed bytes on LF and ASCII whitespace; do not decode/copy entire
    // rows. Python validates complete row counts before invoking this fast path.
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
            // Only retained labels/numbers need UTF-8 validation. Labels become
            // owned Strings, so returned Python objects outlive the borrowed input.
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
            // Parse via f64, then narrow for single precision. Native-endian bytes
            // match NumPy's requested float dtype; no integer identity guarantees
            // arise here from using a homogeneous floating-point representation.
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
/// `usecols`, in file order. Raises ValueError on selected tokens it cannot parse.
///
/// The GIL is detached only for Rust parsing; input is borrowed during that call,
/// while result bytes/labels are owned. PyByteArray copies the numeric prefix and
/// NumPy later retains that Python bytearray as its backing allocation. This API
/// assumes the Python reader's selected-column contract, not arbitrary layouts.
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
    // Map parser messages to ValueError so DumpReader can retry np.loadtxt for
    // reference diagnostics; constructing Python containers requires the GIL.
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

/// Register the extension's sole Python API. The exported module name must match
/// the `_dumpparse` import and filename installed by native/build.sh.
#[pymodule]
fn _dumpparse(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(parse_block, m)?)
}
