"""
═══════════════════════════════════════════════════════════════
Section 4: Plotting Functions
═══════════════════════════════════════════════════════════════
Each analysis type has a corresponding plot function that:
  1. Takes a result dict (from analysis functions)
  2. Creates matplotlib figures with consistent styling
  3. Saves to the output directory as PNG/PDF/SVG files
  4. Supports optional normalize and z_focus parameters

Requested plots require matplotlib and fail visibly when it is unavailable;
missing analysis data generally returns without writing a figure. Importing
this module selects a headless backend and applies global style defaults when
matplotlib is present. Each successful plot writes through _save_fig and closes
its figure; analysis dictionaries are read as supplied, except the thermo and
pressure views may add a missing scalar pressure from diagonal components.

Shared arguments: output_dir is the destination directory, dpi controls raster
resolution, and figsize overrides dimensions in inches. normalize selects
existing population fractions (usually shown as percent), not new scientific
normalization of the underlying analysis. z_focus crops display limits; it
does not recompute analyses. The penetration-profile plot additionally uses
that chosen z range for its display histograms. Times are already in ps in
analysis dictionaries; thermo plots reconstruct them through _thermo_time.
Plot labels and heuristic guides are not independent physical validation.
Except for snapshot frames and explicit pressure-slab metadata, these functions
receive reduced arrays, not cells: geometry eligibility must be established by
the caller before reduction. In particular, accepting a curve dictionary does
not imply support for a tilted slab or a correct slab-coordinate conversion.

Dependencies:
  Required : numpy; matplotlib is optional at import but required for plotting
  Uses     : WONG_PALETTE, BAR_TO_GPA, DENSITY_CONVERSION from __init__
             progress_msg, C from display
═══════════════════════════════════════════════════════════════
"""

import os
import warnings
import numpy as np

from lammps_post import WONG_PALETTE, BAR_TO_GPA, ATM_TO_GPA, DENSITY_CONVERSION
from lammps_post.display import C, progress_msg

# ── Semantic color aliases from Wong palette ──
# Maps physical meanings to color-blind-safe colors.
# WONG_PALETTE: [black, orange, sky blue, bluish green, yellow, blue, vermillion, reddish purple]
CLR = {
    'Fe':       WONG_PALETTE[5],   # blue — iron
    'O':        WONG_PALETTE[6],   # vermillion — oxygen
    'avg':      WONG_PALETTE[5],   # blue — running average / primary line
    'smooth':   WONG_PALETTE[0],   # black — smoothed overlay
    'temp':     WONG_PALETTE[6],   # vermillion — temperature
    'pe':       WONG_PALETTE[5],   # blue — potential energy
    'etotal':   WONG_PALETTE[3],   # bluish green — total energy
    'press':    WONG_PALETTE[7],   # reddish purple — pressure
    'vol':      WONG_PALETTE[2],   # sky blue — volume
    'density':  WONG_PALETTE[1],   # orange — density avg
    'oar':      WONG_PALETTE[3],   # bluish green — absorption
    'ads':      WONG_PALETTE[6],   # vermillion — adsorbed
    'near':     WONG_PALETTE[3],   # bluish green — near surface
    'frac':     WONG_PALETTE[7],   # reddish purple — fraction
    'o2':       WONG_PALETTE[3],   # bluish green — O2 molecules
    'diss':     WONG_PALETTE[6],   # vermillion — dissociated
    'up':       WONG_PALETTE[5],   # blue — spin up
    'down':     WONG_PALETTE[6],   # vermillion — spin down
    'max':      WONG_PALETTE[1],   # orange — maximum charge
    'oxidized': WONG_PALETTE[3],   # bluish green — oxidized count
}

# ── Lazy matplotlib import ──
# Uses the non-interactive 'Agg' backend so plots are saved to files
# without needing a display server (important for SSH/headless usage).
try:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    HAS_MPL = True
except ImportError:
    HAS_MPL = False

def _setup_plot_style(theme='default'):
    """
    Set global matplotlib rcParams for consistent plot appearance.
    Called once at module load time if matplotlib is available.
    These defaults can be partially overridden via 'set' commands
    (e.g., set dpi, set linewidth, set theme) at runtime.

    Themes:
        'default'      — Grid on, standard font sizes, good for interactive QC.
        'publication'  — No grid, bold axis labels, black borders, 10pt base font.
                         A publication-oriented preset, not journal compliance.
        'presentation' — Larger fonts, thicker lines, good for slides.
    """
    # Common base settings
    base = {
        'font.size': 11,
        'axes.labelsize': 12,
        'axes.titlesize': 13,
        'legend.fontsize': 9,
        'figure.dpi': 100,
        'savefig.dpi': 150,
        'axes.prop_cycle': plt.cycler('color', WONG_PALETTE),
    }

    if theme == 'publication':
        base.update({
            'font.family': 'sans-serif',
            'font.sans-serif': ['Arial', 'Helvetica', 'DejaVu Sans'],
            'font.size': 10,
            'axes.labelsize': 11,
            'axes.titlesize': 12,
            'axes.labelweight': 'bold',
            'axes.linewidth': 0.6,
            'axes.grid': False,
            'axes.spines.top': True,
            'axes.spines.right': True,
            'legend.fontsize': 8,
            'legend.framealpha': 1.0,
            'legend.edgecolor': '#CCCCCC',
            'xtick.direction': 'in',
            'ytick.direction': 'in',
            'xtick.major.width': 0.4,
            'ytick.major.width': 0.4,
            'lines.linewidth': 1.2,
            'lines.markersize': 4,
            'savefig.dpi': 300,
            'figure.dpi': 150,
        })
    elif theme == 'presentation':
        base.update({
            'font.size': 14,
            'axes.labelsize': 16,
            'axes.titlesize': 18,
            'axes.labelweight': 'bold',
            'legend.fontsize': 12,
            'lines.linewidth': 2.0,
            'lines.markersize': 6,
            'axes.grid': True,
            'grid.alpha': 0.3,
            'savefig.dpi': 200,
        })
    else:  # default
        base.update({
            'axes.grid': True,
            'grid.alpha': 0.3,
        })

    plt.rcParams.update(base)

if HAS_MPL:
    _setup_plot_style()


# Module-level default save format. Updated by SessionState.apply_plot_style()
# when the user changes `set save_format` or `set theme`.
_SAVE_FORMAT = 'png'


def _save_fig(fig, outpath, dpi=150, save_format=None):
    """
    Save a matplotlib figure to disk and close it to free memory.
    Creates the output directory if it doesn't exist.

    Supports multiple output formats including vector (PDF/SVG) for
    publication-quality figures.

    Format selection may replace outpath's extension; the legacy 'both' mode
    writes PNG, PDF and SVG despite its name. An unrecognized format retains
    the supplied path. Figure closing follows successful saves; write failures
    propagate rather than reporting success or swallowing filesystem errors.

    Args:
        fig:         matplotlib.Figure — The figure to save
        outpath:     str — Full file path (e.g., './output/rdf_Fe_O.png')
        dpi:         int — Resolution in dots per inch (default: 150)
        save_format: str or None — 'png', 'pdf', 'svg', or 'both' (png+pdf+svg).
                     None uses the module-level _SAVE_FORMAT default.
    """
    global _SAVE_FORMAT
    fmt = save_format or _SAVE_FORMAT

    outdir = os.path.dirname(outpath) if os.path.dirname(outpath) else '.'
    os.makedirs(outdir, exist_ok=True)

    base, _ = os.path.splitext(outpath)

    if fmt == 'png':
        fig.savefig(outpath, dpi=dpi, bbox_inches='tight')
        progress_msg(f"Saved: {C.ok(outpath)}")
    elif fmt == 'pdf':
        pdf_path = base + '.pdf'
        fig.savefig(pdf_path, bbox_inches='tight')
        progress_msg(f"Saved: {C.ok(pdf_path)}")
    elif fmt == 'svg':
        svg_path = base + '.svg'
        fig.savefig(svg_path, bbox_inches='tight')
        progress_msg(f"Saved: {C.ok(svg_path)}")
    elif fmt == 'both':
        fig.savefig(outpath, dpi=dpi, bbox_inches='tight')
        pdf_path = base + '.pdf'
        fig.savefig(pdf_path, bbox_inches='tight')
        svg_path = base + '.svg'
        fig.savefig(svg_path, bbox_inches='tight')
        progress_msg(f"Saved: {C.ok(outpath)} + {C.ok(pdf_path)} + {C.ok(svg_path)}")
    else:
        fig.savefig(outpath, dpi=dpi, bbox_inches='tight')
        progress_msg(f"Saved: {C.ok(outpath)}")

    plt.close(fig)


def _require_matplotlib():
    """Fail explicitly when a requested plot cannot use the optional backend.

    Most plot entry points call this before missing-data checks, so lack of
    plotting support is not silently disguised as an empty analysis result.
    Snapshot plotting instead returns for an empty frame collection and checks
    selected-frame geometry before reaching the backend requirement.
    """
    if not HAS_MPL:
        raise RuntimeError('matplotlib is required for requested plotting; install the post extra')


def _thermo_time(log_data, dt_fs):
    """Return a finite row-aligned, nondecreasing MD timeline in ps.

    Prefer parser-provided time_ps, otherwise convert elapsed_md_steps with
    dt_fs. Legacy step fallback is allowed only without explicit ambiguity;
    optimizer-only rows are rejected rather than interpreted as elapsed MD.
    A missing dt_fs warns before assuming 1 fs. Duplicate times are allowed,
    as at adjacent run boundaries, but decreasing times are not.
    """
    step = np.asarray(log_data['step'], dtype=float)
    if 'elapsed_md_steps' in log_data and log_data['elapsed_md_steps'] is None:
        raise ValueError('Optimizer-only thermo has no elapsed MD timeline; plot iterations separately')
    if 'time_ps' in log_data:
        time = np.asarray(log_data['time_ps'], dtype=float)
    else:
        if log_data.get('timeline_valid') is False and 'elapsed_md_steps' not in log_data:
            raise ValueError('Ambiguous thermo timeline: elapsed MD steps or explicit time_ps required')
        increments = np.asarray(log_data.get('elapsed_md_steps', step), dtype=float)
        if dt_fs is None:
            warnings.warn('Thermo timestep unknown: assuming 1 fs for the time axis; '
                          'supply confirmed dt_fs', RuntimeWarning, stacklevel=3)
            dt_fs = 1.0
        if not np.isfinite(dt_fs) or dt_fs <= 0:
            raise ValueError('Thermo dt_fs must be finite and positive')
        time = increments * dt_fs / 1000.0
    if (time.shape != step.shape or not np.all(np.isfinite(time))
            or np.any(np.diff(time) < 0)):
        raise ValueError('Thermo MD time must be finite, aligned with rows and nondecreasing')
    return time


def _pressure_scale(unit_system, pressure_unit):
    """Return multiplicative native-to-display pressure scale and axis label.

    LAMMPS metal pressure is bar and real pressure is atm; both can be shown
    in bar or GPa. Reject unsupported styles/displays rather than applying a
    conversion associated with a different unit system.
    """
    native_gpa = {'metal': BAR_TO_GPA, 'real': ATM_TO_GPA}
    if unit_system not in native_gpa:
        raise ValueError(f'Unsupported LAMMPS pressure units style: {unit_system!r}')
    display = pressure_unit.lower()
    if display not in ('bar', 'gpa'):
        raise ValueError(f'Unsupported pressure display unit: {pressure_unit!r}')
    return (native_gpa[unit_system] / (BAR_TO_GPA if display == 'bar' else 1.0),
            'bar' if display == 'bar' else 'GPa')


def _slab_volume_scale(log_data, slab_z_range, n_frames):
    """Return per-sample Lz/thickness for an explicitly z-aligned slab.

    Equal box/slab cross-sections cancel from the volume ratio. Validate any
    supplied lengths/volume for consistency, but never infer Lz from volume.
    Invalid requested bounds raise; missing/inconsistent per-sample geometry
    instead warns and returns None so a caller can label uncorrected box P.
    A valid ratio verifies geometry only, not the physical assumption that all
    box stress belongs to the selected slab.
    This helper has no tilt check of its own; plot_pressure checks retained tilt
    metadata, and the shell checks loaded cells before calling that entry point.
    """
    bounds = np.asarray(slab_z_range, dtype=float)
    if bounds.shape != (2,) or not np.all(np.isfinite(bounds)) or bounds[1] <= bounds[0]:
        raise ValueError('slab_z_range must be finite (z_lo, z_hi) with z_hi > z_lo')
    thickness = bounds[1] - bounds[0]
    try:
        lz = np.asarray(log_data.get('lz', []), dtype=float)
        if lz.shape != (n_frames,) or not np.all(np.isfinite(lz)):
            raise ValueError('lz must contain one finite box height per thermo sample')
        if np.any(lz <= 0) or np.any(lz < thickness):
            raise ValueError('lz must be positive and at least the chosen slab thickness')
        # If supplied, other lengths/volume must agree. Lz alone is sufficient
        # for this explicitly z-aligned, same-cross-section volume convention.
        for key in ('lx', 'ly', 'vol'):
            if key in log_data:
                values = np.asarray(log_data[key], dtype=float)
                if (values.shape != (n_frames,) or not np.all(np.isfinite(values))
                        or np.any(values <= 0)):
                    raise ValueError(f'{key} must contain positive finite per-frame values')
        if all(key in log_data for key in ('lx', 'ly', 'vol')):
            if not np.allclose(np.asarray(log_data['lx']) * np.asarray(log_data['ly']) * lz,
                               log_data['vol'], rtol=1e-4, atol=1e-8):
                raise ValueError('lx*ly*lz does not match the supplied box volume')
        return lz / thickness
    except (TypeError, ValueError) as exc:
        warnings.warn(f'Slab pressure left uncorrected: {exc}', RuntimeWarning, stacklevel=3)
        return None


def plot_thermo(log_data, output_dir, dpi=150, dt_fs=None,
                pressure_unit='bar', total_mass_amu=None, figsize=None,
                slab_z_range=None, unit_system='metal'):
    """
    Plot thermodynamic properties from parsed log data.

    Layout adapts based on available data:
    - Base 4 panels (2x2): Temperature, PE, Total Energy, Pressure
    - +1 panel if Pxx/Pyy/Pzz available: Stress tensor components
    - +1 panel if 'vol' in log data: Volume timeseries
    - +1 panel if volume + total_mass_amu: Density (g/cm^3) timeseries
    - Layout: 2x2 (4 panels), 2x3 (5-6 panels), 3x3 (7-9 panels)

    Each property is shown as a raw time series with a running average
    overlay for smoothing high-frequency fluctuations.

    Running means weight samples, not elapsed intervals; they are visual
    summaries rather than equilibrium tests. Mass/box-volume density includes
    vacuum in slab cells. All pressure here is uncorrected box pressure; an
    explicit slab range only adds a note. Missing scalar pressure is synthesized
    in the supplied dictionary when all diagonal components are available.

    Args:
        log_data:        dict — Parsed log data from parse_log()
        output_dir:      str  — Output directory for saved plot
        dpi:             int  — Plot resolution
        dt_fs:           float or None — Timestep in fs for time axis;
                         if None, uses log_data['time_ps'] or fallback 1.0 fs
        pressure_unit:   str  — 'bar' or 'gpa'; controls pressure axis label/scale
        total_mass_amu:  float or None — Total system mass for density calculation
        figsize:         tuple or None — (width, height); None uses adaptive default
        unit_system:     str — Native LAMMPS units ('metal': bar, 'real': atm)
        slab_z_range:    tuple or None — Explicit z bounds for a box-pressure note

    Output: thermo.png
    """
    _require_matplotlib()
    if log_data is None:
        return

    d = log_data
    step = d.get('step', np.array([]))
    if len(step) == 0:
        return

    # Parser MD increments exclude optimizer iterations and preserve resets.
    t = _thermo_time(d, dt_fs)

    # ── Determine layout based on available data ──
    has_vol = 'vol' in d and len(d['vol']) == len(step)
    has_density = has_vol and total_mass_amu is not None and total_mass_amu > 0
    has_stress = all(k in d and len(d[k]) == len(step) for k in ('pxx', 'pyy', 'pzz'))

    # Synthesize 'press' from stress tensor components if missing (e.g. ACE logs)
    if 'press' not in d and has_stress:
        d['press'] = (d['pxx'] + d['pyy'] + d['pzz']) / 3.0

    n_panels = 4 + int(has_stress) + int(has_vol) + int(has_density)
    if n_panels <= 4:
        nrows, ncols = 2, 2
    elif n_panels <= 6:
        nrows, ncols = 2, 3
    else:
        nrows, ncols = 3, 3

    if figsize is None:
        figsize = (7 * ncols, 5 * nrows)

    fig, axes = plt.subplots(nrows, ncols, figsize=figsize)
    fig.suptitle('Thermodynamic Properties')
    axes_flat = list(axes.flat)  # Convert to list; numpy flatiter is consumed by zip

    # Native pressure is bar in metal units, but atm in real units.
    press_scale, punit = _pressure_scale(unit_system, pressure_unit)
    press_label = f'Pressure ({punit})'

    energy_unit = 'kcal/mol' if unit_system == 'real' else 'eV'
    specs = [
        ('temp',   'Temperature (K)',   CLR['temp']),
        ('pe',     f'Potential Energy ({energy_unit})', CLR['pe']),
        ('etotal', f'Total Energy ({energy_unit})', CLR['etotal']),
        ('press',  press_label,         CLR['press']),
    ]

    # ── Plot base 4 panels ──
    for ax, (key, ylabel, color) in zip(axes_flat, specs):
        if key in d:
            data = d[key] * press_scale if key == 'press' else d[key]
            ax.plot(t, data, color=color, lw=0.5, alpha=0.7)
            # Running average
            w = max(10, len(data) // 100)
            if len(data) > w:
                smooth = np.convolve(data, np.ones(w) / w, mode='valid')
                t_s = t[w // 2: w // 2 + len(smooth)]
                ax.plot(t_s, smooth, color=CLR['smooth'], lw=1.5, label=f'Avg ({w} pts)')
                ax.legend()
            # Explicitly label this overview as uncorrected box pressure.
            if key == 'press' and slab_z_range is not None and has_vol:
                z_lo, z_hi = slab_z_range
                # This overview deliberately retains box pressure; the pressure
                # analysis plot separately offers a conditional volume rescale.
                ax.set_title(f'(box pressure — slab {z_lo:.0f}-{z_hi:.0f} Å)',
                             fontsize=8, style='italic')
        ax.set_xlabel('Time (ps)')
        ax.set_ylabel(ylabel)

    panel_idx = 4

    # ── Panel: Stress tensor components (Pxx, Pyy, Pzz) ──
    if has_stress:
        ax = axes_flat[panel_idx]
        pxx = d['pxx'] * press_scale
        pyy = d['pyy'] * press_scale
        pzz = d['pzz'] * press_scale
        p_in = (pxx + pyy) / 2  # In-plane pressure

        ax.plot(t, pxx, color=CLR['temp'], lw=0.3, alpha=0.4, label='Pxx')
        ax.plot(t, pyy, color=CLR['pe'], lw=0.3, alpha=0.4, label='Pyy')
        ax.plot(t, pzz, color=CLR['etotal'], lw=0.3, alpha=0.4, label='Pzz')

        # In-plane average with running mean
        w = max(10, len(p_in) // 100)
        if len(p_in) > w:
            smooth = np.convolve(p_in, np.ones(w) / w, mode='valid')
            t_s = t[w // 2: w // 2 + len(smooth)]
            ax.plot(t_s, smooth, color=CLR['smooth'], lw=1.5,
                    label=f'In-plane avg ({w} pts)')
        ax.set_xlabel('Time (ps)')
        ax.set_ylabel(f'Stress ({press_label.split("(")[1]}')
        ax.legend()
        ax.set_title('Stress Tensor (Pxx, Pyy, Pzz)', fontsize=9)
        panel_idx += 1

    # ── Panel 5: Volume ──
    if has_vol:
        ax = axes_flat[panel_idx]
        ax.plot(t, d['vol'], color=CLR['vol'], lw=0.5, alpha=0.7)
        w = max(10, len(d['vol']) // 100)
        if len(d['vol']) > w:
            smooth = np.convolve(d['vol'], np.ones(w) / w, mode='valid')
            t_s = t[w // 2: w // 2 + len(smooth)]
            ax.plot(t_s, smooth, color=CLR['smooth'], lw=1.5, label=f'Avg ({w} pts)')
            ax.legend()
        ax.set_xlabel('Time (ps)')
        ax.set_ylabel(r'Volume ($\AA^3$)')
        panel_idx += 1

    # ── Panel 6: Density (g/cm^3) ──
    if has_density:
        ax = axes_flat[panel_idx]
        density = (total_mass_amu * DENSITY_CONVERSION) / d['vol']
        ax.plot(t, density, color=CLR['smooth'], lw=0.5, alpha=0.7)
        w = max(10, len(density) // 100)
        if len(density) > w:
            smooth = np.convolve(density, np.ones(w) / w, mode='valid')
            t_s = t[w // 2: w // 2 + len(smooth)]
            ax.plot(t_s, smooth, color=CLR['density'], lw=1.5, label=f'Avg ({w} pts)')
            ax.legend()
        ax.set_xlabel('Time (ps)')
        ax.set_ylabel(r'Density ($g/cm^3$)')
        panel_idx += 1

    # ── Hide unused panels ──
    for idx in range(panel_idx, nrows * ncols):
        axes_flat[idx].set_visible(False)

    plt.tight_layout()
    _save_fig(fig, os.path.join(output_dir, 'thermo.png'), dpi)


def plot_thermostat_summary(log_data, output_dir, dpi=150, dt_fs=None,
                            pressure_unit='bar', figsize=None, unit_system='metal'):
    """
    Plot a compact thermostat QC summary with dual y-axes (twinx).
    Temperature on the left axis (red), Pressure on the right axis (blue).
    Useful for slides and papers where a single figure is preferred.

    A temperature series is required; the secondary pressure axis is optional
    and uses native-unit conversion without slab-volume rescaling. The two
    independent axis scales do not imply a quantitative temperature-pressure
    correlation. Time validation is shared with the full thermo overview.

    Reference: md_stats_plot.py plot_thermostat()

    Args:
        log_data:       dict — Parsed log data
        output_dir:     str  — Output directory
        dpi:            int  — Plot resolution
        dt_fs:          float or None — Timestep in fs
        pressure_unit:  str  — 'bar' or 'gpa'
        figsize:        tuple or None — (width, height)
        unit_system:    str — Native LAMMPS units ('metal': bar, 'real': atm)

    Output: thermostat_summary.png
    """
    _require_matplotlib()
    if log_data is None:
        return

    d = log_data
    step = d.get('step', np.array([]))
    if len(step) == 0 or 'temp' not in d:
        return

    t = _thermo_time(d, dt_fs)
    xlabel = 'Time (ps)'

    if figsize is None:
        figsize = (10, 5)

    fig, ax1 = plt.subplots(figsize=figsize)

    # Left axis: Temperature
    ax1.set_xlabel(xlabel)
    ax1.set_ylabel('Temperature (K)', color=CLR['temp'])
    ax1.plot(t, d['temp'], color=CLR['temp'], alpha=0.8, lw=1.0)
    ax1.tick_params(axis='y', labelcolor=CLR['temp'])

    # Right axis: Pressure
    if 'press' in d:
        ax2 = ax1.twinx()
        pscale, punit = _pressure_scale(unit_system, pressure_unit)
        press = d['press'] * pscale
        plabel = f'Pressure ({punit})'
        ax2.set_ylabel(plabel, color=CLR['pe'])
        ax2.plot(t, press, color=CLR['pe'], alpha=0.6, lw=1.0)
        ax2.tick_params(axis='y', labelcolor=CLR['pe'])

    fig.suptitle('Thermostat Summary')
    fig.tight_layout()
    _save_fig(fig, os.path.join(output_dir, 'thermostat_summary.png'), dpi)


def plot_pressure(log_data, output_dir, dpi=150, dt_fs=None,
                  pressure_unit='bar', slab_z_range=None, figsize=None,
                  unit_system='metal'):
    """
    Detailed pressure analysis plot for slab geometries.

    For slab simulations (p p f boundary), the total box pressure is
    vacuum-diluted because the virial is normalized by the full box volume.
    In-plane averaging alone does not remove that dilution. This plot shows:

    Panel (a): Raw pressure components Pxx, Pyy, Pzz
    Panel (b): In-plane P_in = (Pxx + Pyy) / 2 vs normal pressure,
               with running averages
    Panel (c): Conditional volume-rescaled in-plane pressure, if slab_z_range
               and finite per-sample log_data['lz'] are provided:
               P_eff = P_in * (Lz / slab_thickness).
               Assumes a z-aligned slab of this thickness occupying the full
               box cross-section and ALL relevant box stress belonging to it.
               This is not a local/material pressure or surface-stress estimator.
               Missing/invalid geometry warns and displays uncorrected box P.

    Without an explicit slab range, show box pressure with descriptive running
    statistics. No boundary flags are read here to classify slab versus bulk.
    Supplying a slab range alone is not evidence that volume rescaling has a
    physical material-pressure interpretation. If diagonal components are
    absent, a scalar trace cannot establish the in-plane pressure and is left
    uncorrected with a warning. A missing scalar pressure may be added to the
    input dictionary from its diagonal components.
    The direct-call guard can reject only retained cell/tilt metadata; lengths
    alone cannot establish orthogonality. Callers must not strip that evidence.

    Args:
        log_data:      dict  — Parsed log data from parse_log()
        output_dir:    str   — Output directory
        dpi:           int   — Plot resolution
        dt_fs:         float — Timestep in fs
        pressure_unit: str   — 'bar' or 'gpa'
        slab_z_range:  tuple — (z_lo, z_hi) of slab region in A, or None
        figsize:       tuple — (width, height)
        unit_system:   str — Native LAMMPS units ('metal': bar, 'real': atm)

    Output: pressure_analysis.png
    """
    if slab_z_range is not None and log_data is not None:
        cell = log_data.get('cell')
        tilted = any(np.any(np.asarray(log_data.get(key, 0)) != 0)
                     for key in ('tilt', 'tilt_factors', 'xy', 'xz', 'yz'))
        if tilted or (cell is not None and not cell.is_orthogonal):
            raise ValueError('Slab pressure normalization is orthogonal-only; '
                             'triclinic geometry is unsupported')
    _require_matplotlib()
    if log_data is None:
        return

    d = log_data
    step = d.get('step', np.array([]))
    if len(step) == 0:
        return

    has_stress = all(k in d and len(d[k]) == len(step) for k in ('pxx', 'pyy', 'pzz'))

    # Synthesize 'press' from stress tensor components if missing (e.g. ACE logs)
    if 'press' not in d and has_stress:
        d['press'] = (d['pxx'] + d['pyy'] + d['pzz']) / 3.0

    if 'press' not in d:
        return

    # Time axis
    t = _thermo_time(d, dt_fs)

    # Pressure scaling
    pscale, punit = _pressure_scale(unit_system, pressure_unit)

    press = d['press'] * pscale

    w = max(10, len(press) // 100)

    if has_stress:
        # ── 3-panel layout for full stress tensor ──
        n_cols = 3 if slab_z_range is not None else 2
        fig, axes = plt.subplots(1, n_cols, figsize=figsize or (6 * n_cols, 5))
        if n_cols == 1:
            axes = [axes]

        pxx = d['pxx'] * pscale
        pyy = d['pyy'] * pscale
        pzz = d['pzz'] * pscale
        p_in = (pxx + pyy) / 2

        # Panel (a): All components
        ax = axes[0]
        ax.plot(t, pxx, color=CLR['temp'], lw=0.3, alpha=0.3, label='Pxx')
        ax.plot(t, pyy, color=CLR['pe'], lw=0.3, alpha=0.3, label='Pyy')
        ax.plot(t, pzz, color=CLR['etotal'], lw=0.3, alpha=0.3, label='Pzz')
        if len(press) > w:
            for data, clr, lbl in [(pxx, CLR['temp'], None), (pyy, CLR['pe'], None),
                                    (pzz, CLR['etotal'], None)]:
                sm = np.convolve(data, np.ones(w) / w, mode='valid')
                ax.plot(t[w//2:w//2+len(sm)], sm, color=clr, lw=1.2)
        ax.set(xlabel='Time (ps)', ylabel=f'Stress ({punit})',
               title='(a) Stress Components')
        ax.legend()

        # Panel (b): In-plane vs normal
        ax = axes[1]
        ax.plot(t, p_in, color=CLR['avg'], lw=0.3, alpha=0.4, label='In-plane (Pxx+Pyy)/2')
        ax.plot(t, pzz, color=CLR['press'], lw=0.3, alpha=0.4, label='Normal Pzz')
        if len(press) > w:
            sm_in = np.convolve(p_in, np.ones(w) / w, mode='valid')
            sm_zz = np.convolve(pzz, np.ones(w) / w, mode='valid')
            t_s = t[w//2:w//2+len(sm_in)]
            ax.plot(t_s, sm_in, color=CLR['avg'], lw=1.5, label=f'In-plane avg ({w} pts)')
            ax.plot(t_s, sm_zz, color=CLR['press'], lw=1.5, label=f'Pzz avg ({w} pts)')
            # Statistics annotation
            ax.axhline(np.mean(sm_in), color=CLR['avg'], ls=':', alpha=0.5)
            ax.axhline(np.mean(sm_zz), color=CLR['press'], ls=':', alpha=0.5)
        ax.set(xlabel='Time (ps)', ylabel=f'Pressure ({punit})',
               title='(b) In-plane vs Normal')
        ax.legend()

        # Panel (c): Explicit, physically conditional volume convention.
        if slab_z_range is not None and n_cols == 3:
            ax = axes[2]
            volume_scale = _slab_volume_scale(d, slab_z_range, len(step))
            if volume_scale is not None:
                p_corr = p_in * volume_scale
                label = 'Volume-rescaled in-plane P'
                note = ('Assumes z-aligned slab, full box area,\n'
                        'all box stress assigned to chosen slab;\n'
                        'not a local/material pressure estimate.')
            else:
                p_corr = p_in
                label = 'Uncorrected in-plane box P'
                note = 'No valid Lz/slab volume ratio; includes vacuum.'

            ax.plot(t, p_corr, color=CLR['avg'], lw=0.3, alpha=0.4, label=label)
            ax.text(0.02, 0.98, note, transform=ax.transAxes, va='top', fontsize=7)
            if len(p_corr) > w:
                sm = np.convolve(p_corr, np.ones(w) / w, mode='valid')
                t_s = t[w//2:w//2+len(sm)]
                ax.plot(t_s, sm, color=CLR['smooth'], lw=1.5, label=f'Avg ({w} pts)')
                mean_val = np.mean(sm)
                ax.axhline(mean_val, color=CLR['smooth'], ls=':', alpha=0.5)
                ax.text(t_s[-1], mean_val, f' {mean_val:.1f} {punit}',
                        va='bottom', fontsize=8, color=CLR['smooth'])
            ax.set(xlabel='Time (ps)', ylabel=f'Pressure ({punit})',
                   title=f'(c) {label}')
            ax.legend()

    else:
        # ── No stress tensor: show total pressure with statistics ──
        n_cols = 2 if slab_z_range is not None else 1
        fig, axes = plt.subplots(1, n_cols, figsize=figsize or (6 * n_cols, 5))
        if n_cols == 1:
            axes = [axes]

        ax = axes[0]
        ax.plot(t, press, color=CLR['press'], lw=0.5, alpha=0.6)
        if len(press) > w:
            sm = np.convolve(press, np.ones(w) / w, mode='valid')
            t_s = t[w//2:w//2+len(sm)]
            ax.plot(t_s, sm, color=CLR['smooth'], lw=1.5, label=f'Avg ({w} pts)')
            mean_val = np.mean(sm)
            ax.axhline(mean_val, color=CLR['smooth'], ls=':', alpha=0.5)
            ax.text(t_s[-1], mean_val, f' {mean_val:.1f} {punit}',
                    va='bottom', fontsize=8, color=CLR['smooth'])
        ax.set(xlabel='Time (ps)', ylabel=f'Pressure ({punit})',
               title='Total Box Pressure')
        ax.legend()

        if slab_z_range is not None and n_cols == 2:
            warnings.warn('Slab pressure left uncorrected: Pxx/Pyy/Pzz are required '
                          'for in-plane volume rescaling', RuntimeWarning, stacklevel=2)
            ax = axes[1]
            ax.plot(t, press, color=CLR['press'], lw=0.5, alpha=0.6)
            if len(press) > w:
                ax.plot(t_s, sm, color=CLR['smooth'], lw=1.5)
            z_lo, z_hi = slab_z_range
            ax.set(xlabel='Time (ps)', ylabel=f'Pressure ({punit})',
                   title=f'Uncorrected Box P (slab {z_lo:.0f}-{z_hi:.0f} A)')
            ax.text(0.05, 0.95,
                    'Note: Box P includes vacuum.\n'
                    'Add Pxx/Pyy/Pzz to thermo_style\n'
                    'for in-plane pressure analysis.',
                    transform=ax.transAxes, fontsize=8, va='top',
                    bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.5))

    fig.suptitle('Pressure Analysis')
    plt.tight_layout()
    _save_fig(fig, os.path.join(output_dir, 'pressure_analysis.png'), dpi)


def plot_charge_evolution(data, output_dir, dpi=150, normalize=False, figsize=None):
    """
    Plot Fe charge evolution over time (ReaxFF only).
    Left panel: average and max Fe charge vs time.
    Right panel: oxidized Fe count or fraction (if normalize=True).
    Charges remain in elementary-charge units; normalization affects only the
    population panel, using the analysis denominator. None produces no file.
    The legacy count-axis threshold text is fixed at 0.3 even if the analysis
    was computed with another cutoff; this plot does not recover that metadata.
    Output: charge_evolution.png
    """
    _require_matplotlib()
    if data is None:
        return

    fig, (a1, a2) = plt.subplots(1, 2, figsize=figsize or (13, 5))
    fig.suptitle('Fe Charge Evolution (ReaxFF)')

    a1.plot(data['time'], data['avg'], color=CLR['avg'], lw=2, label='Average')
    a1.plot(data['time'], data['max'], color=CLR['max'], ls='--', lw=1, alpha=0.6, label='Max')
    a1.set(xlabel='Time (ps)', ylabel='Fe Charge (e)')
    a1.legend()

    if normalize and 'frac_oxidized' in data:
        a2.plot(data['time'], data['frac_oxidized'] * 100, color=CLR['oxidized'], lw=2)
        a2.set(xlabel='Time (ps)', ylabel='Oxidized Fe (%)',
               title='Oxidized Fe Fraction')
    else:
        a2.plot(data['time'], data['n_oxidized'], color=CLR['oxidized'], lw=2)
        a2.set(xlabel='Time (ps)', ylabel='N(Fe, q > 0.3)',
               title='Oxidized Fe Count')

    plt.tight_layout()
    _save_fig(fig, os.path.join(output_dir, 'charge_evolution.png'), dpi)


def plot_charge_z(data, output_dir, dpi=150, normalize=False, z_focus=None, figsize=None):
    """
    Plot z-direction charge distribution (ReaxFF only).
    Shows Fe charge (scatter, left y-axis) and O counts (fill, right y-axis)
    vs z-coordinate. The z_focus parameter crops the view to the relevant region.
    Suppress empty-metal-bin zero charges using fe_count. Normalized oxygen
    values sum to 100% over all supplied bins (or remain zero when empty),
    not over just the cropped view; they are not volume-normalized densities.
    Output: charge_z_distribution.png
    """
    _require_matplotlib()
    if data is None:
        return

    fig, a1 = plt.subplots(figsize=figsize or (8, 6))
    fig.suptitle('z-Direction Charge Distribution')

    m = data['fe_count'] > 0
    a1.scatter(data['z'][m], data['fe_charge'][m], c=CLR['Fe'], s=25, alpha=0.7, label='Fe charge')
    a1.set(xlabel=r'$z$ (Å)', ylabel='Fe Charge (e)')

    a2 = a1.twinx()
    if normalize:
        total_o = data['o_count'].sum()
        o_frac = data['o_count'] / total_o * 100 if total_o > 0 else data['o_count']
        a2.fill_between(data['z'], 0, o_frac, alpha=0.15, color=CLR['O'])
        a2.plot(data['z'], o_frac, color=CLR['O'], lw=1.2)
        a2.set_ylabel('O fraction per bin (%)', color=CLR['O'])
    else:
        a2.fill_between(data['z'], 0, data['o_count'], alpha=0.15, color=CLR['O'])
        a2.plot(data['z'], data['o_count'], color=CLR['O'], lw=1.2)
        a2.set_ylabel('O count', color=CLR['O'])

    if z_focus:
        a1.set_xlim(z_focus)

    a1.legend(loc='upper left')
    plt.tight_layout()
    _save_fig(fig, os.path.join(output_dir, 'charge_z_distribution.png'), dpi)


def _rdf_md_label(data):
    """Legend text for the MD curve: the averaged frame window when known.

    Results carrying compute_rdf's frame_window read 'MD, last 20 frames
    (steps 3400–3587)'; older cached results keep 'MD (20 frames)'.
    """
    window = data.get('frame_window')
    if window:
        from lammps_post.analysis import describe_frame_window
        return f'MD, {describe_frame_window(window)}'
    return f'MD ({data["n_frames"]} frames)'


def plot_rdf(data, output_dir, dpi=150, figsize=None, ref_rdfs=None):
    """
    Plot radial distribution function g(r).

    When reference RDFs are provided, uses a vertically stacked layout
    inspired by EELS/XRD comparison figures: each curve is offset vertically
    so peaks don't overlap, with phase labels placed directly next to each
    curve. The MD result is plotted at the top with the boldest line.

    Without references, shows the MD g(r) with vertical reference lines
    at known oxide bond lengths.

    Stacking divides each curve by its own maximum and adds arbitrary offsets:
    peak positions/shapes remain comparable, but absolute g(r) amplitudes do
    not. The simple view preserves g(r) and its ideal-gas baseline. Fe/O guide
    markers are label-triggered heuristics, not phase identification. A display
    label may change the title while the original pair label keeps filenames
    stable. None produces no file.

    Args:
        data:     dict — RDF data from compute_rdf()
        output_dir: str — Output directory
        dpi:      int — Plot resolution
        figsize:  tuple — (width, height)
        ref_rdfs: list[dict] or None — Reference RDF curves to overlay.

    Output: rdf_<pair>.png
    """
    _require_matplotlib()
    if data is None:
        return

    file_label = data['label']
    label = data.get('display_label', file_label)

    if ref_rdfs:
        # ── Stacked overlay style (like EELS comparison figures) ──
        # Finite nonnegative curves are peak-scaled to [0, 1] and offset.
        # This display path does not validate/repair negative or NaN input RDFs.
        # MD on top, references below in order.
        n_curves = 1 + len(ref_rdfs)
        fig, ax = plt.subplots(figsize=figsize or (8, 2 + 1.5 * n_curves))

        ref_colors = [WONG_PALETTE[1], WONG_PALETTE[3], WONG_PALETTE[7],
                      WONG_PALETTE[2], WONG_PALETTE[6]]
        offset_step = 1.2  # vertical spacing between curves

        # Plot references from bottom to top, then MD on top
        all_curves = list(ref_rdfs) + [data]  # references first, MD last (= top)
        for i, curve in enumerate(all_curves):
            is_md = (i == len(all_curves) - 1)
            r = curve['r']
            g = curve['g'].copy()

            # Divide by a positive maximum; an all-zero curve stays at its offset.
            g_max = np.max(g) if np.max(g) > 0 else 1.0
            g_norm = g / g_max

            offset = i * offset_step
            y = g_norm + offset

            if is_md:
                color = CLR['avg']
                lw = 2.0
                curve_label = _rdf_md_label(data)
            else:
                color = ref_colors[i % len(ref_colors)]
                lw = 1.2
                curve_label = curve['label']

            ax.plot(r, y, color=color, lw=lw)

            # Place label text directly to the right of the curve
            # Find position at r_max edge
            label_y = offset + 0.5  # middle of the normalized curve
            ax.text(data['r'][-1] * 0.98, label_y, curve_label,
                    color=color, fontsize=9, fontweight='bold',
                    va='center', ha='right',
                    bbox=dict(facecolor='white', alpha=0.7, edgecolor='none', pad=1))

        # Add amorphous FeO reference marker (no crystal structure, peak position only)
        if 'Fe' in label and 'O' in label:
            ax.axvline(1.76, color='grey', ls=':', alpha=0.6, lw=0.8)
            ax.text(1.76, (n_curves - 1) * offset_step + 1.1, 'amorph.\nFeO',
                    color='grey', fontsize=7, ha='center', va='bottom', style='italic')

        # Remove y-axis ticks (offsets are arbitrary)
        ax.set_yticks([])
        ax.set_ylabel('Intensity (a.u.)')
        ax.set_xlabel(r'$r$ (Å)')
        ax.set_title(f'{label} RDF — Phase Comparison')
        ax.set_xlim(0, None)

    else:
        # ── Simple single-curve plot with vertical reference lines ──
        fig, ax = plt.subplots(figsize=figsize or (8, 5))

        ax.plot(data['r'], data['g'], color=CLR['avg'], lw=2,
                label=_rdf_md_label(data))
        ax.axhline(1, linestyle='--', color='grey', alpha=0.5, lw=0.8)

        if 'Fe' in label and 'O' in label:
            refs = [('FeO amorph.', 1.76, 'gray'), ('FeO wustite', 2.16, WONG_PALETTE[1]),
                    ('Fe₂O₃', 1.95, WONG_PALETTE[3]), ('Fe₃O₄', 2.06, WONG_PALETTE[7])]
            for name, pos, c in refs:
                ax.axvline(pos, color=c, ls='--', alpha=0.5, label=f'{name} ({pos} Å)')

        ax.set(xlabel=r'$r$ (Å)', ylabel=r'$g(r)$',
               title=f'{label} RDF', xlim=(0, None))
        ax.legend()

    plt.tight_layout()
    _save_fig(fig, os.path.join(output_dir, f'rdf_{file_label.replace("-","_")}.png'), dpi)


def plot_oar(data, output_dir, dpi=150, normalize=False, figsize=None):
    """
    Plot Oxygen Absorption Rate (OAR) over time.
    Left: OAR percentage. Right: absorbed O count or fraction.
    Use the supplied instantaneous below-surface fraction; despite the legacy
    "rate" name this is not a derivative. Normalizing the right panel repeats
    that percentage rather than changing the left panel or its denominator.
    Output: oar.png
    """
    _require_matplotlib()
    if data is None:
        return

    fig, (a1, a2) = plt.subplots(1, 2, figsize=figsize or (12, 5))
    fig.suptitle('Oxygen Absorption')

    a1.plot(data['time'], data['oar'] * 100, color=CLR['oar'], lw=2)
    a1.set(xlabel='Time (ps)', ylabel='OAR (%)',
           title='(a) Absorption Rate')

    if normalize:
        a2.plot(data['time'], data['oar'] * 100, color=CLR['ads'], lw=2)
        a2.set(xlabel='Time (ps)', ylabel='O absorbed (%)',
               title='(b) Absorbed O Fraction')
    else:
        a2.plot(data['time'], data['n_absorbed'], color=CLR['ads'], lw=2)
        a2.set(xlabel='Time (ps)', ylabel='N(O absorbed)',
               title='(b) Absorbed O Count')

    plt.tight_layout()
    _save_fig(fig, os.path.join(output_dir, 'oar.png'), dpi)


def plot_or(data, output_dir, dpi=150, figsize=None):
    """
    Plot Fe oxidation rate over time (ReaxFF only).
    Shows the supplied fraction on a 0-to-1 scale, without differentiation or
    conversion to percent. The retained title mentions the default 0.3 e cutoff
    even when callers used a different analysis threshold. Partial-charge
    classification does not by itself establish oxidation states or phases.
    Output: oxidation_rate.png
    """
    _require_matplotlib()
    if data is None:
        return

    fig, ax = plt.subplots(figsize=figsize or (8, 5))
    ax.plot(data['time'], data['or'], color=CLR['avg'], lw=2)
    ax.set(xlabel='Time (ps)', ylabel='Oxidation Rate',
           title='Fe Oxidation Rate (q > 0.3)')
    plt.tight_layout()
    _save_fig(fig, os.path.join(output_dir, 'oxidation_rate.png'), dpi)


def plot_penetration(data, output_dir, dpi=150, normalize=False, figsize=None):
    """
    Plot oxygen penetration analysis (3-panel layout).
    (a) Maximum penetration depth vs time.
    (b) Adsorbed O count/fraction (below surface + near surface).
    (c) Penetration fraction (adsorbed / (adsorbed + near-surface)).
    Panel (a) subtracts the deepest stored coordinate from the fixed surface;
    negative depths remain visible if all atoms are above it, and NaNs form
    gaps. In (b), normalized fractions use all selected oxygen; in (c), only
    atoms in the two analysis bands enter the denominator. The deeper band
    uses the analysis offset, not simply z < surface_z.
    An empty band denominator displays zero (not an observed zero-probability
    event); NumPy evaluates the unused division too and may warn for 0/0.
    Output: penetration.png
    """
    _require_matplotlib()
    if data is None:
        return

    fig, axes = plt.subplots(1, 3, figsize=figsize or (16, 5))
    fig.suptitle('Oxygen Penetration Analysis')

    sz = data['surface_z']
    t = data['time']

    axes[0].plot(t, sz - data['o_min_z'], color=CLR['avg'], lw=1)
    axes[0].set(xlabel='Time (ps)', ylabel='Max Penetration Depth (Å)',
                title='(a) Penetration Depth')

    if normalize and 'frac_adsorbed' in data:
        axes[1].plot(t, data['frac_adsorbed'] * 100, color=CLR['ads'], lw=1, label='Below surface')
        axes[1].plot(t, data['frac_near_surface'] * 100, color=CLR['near'], lw=1, label='Near surface')
        axes[1].set(xlabel='Time (ps)', ylabel='O atom fraction (%)',
                    title='(b) Adsorbed O Fraction')
    else:
        axes[1].plot(t, data['n_adsorbed'], color=CLR['ads'], lw=1, label='Below surface')
        axes[1].plot(t, data['n_near_surface'], color=CLR['near'], lw=1, label='Near surface')
        axes[1].set(xlabel='Time (ps)', ylabel='O atom count',
                    title='(b) Adsorbed O Count')
    axes[1].legend()

    frac = np.where(data['n_adsorbed'] + data['n_near_surface'] > 0,
                    data['n_adsorbed'] / (data['n_adsorbed'] + data['n_near_surface']) * 100, 0)
    axes[2].plot(t, frac, color=CLR['frac'], lw=1)
    axes[2].set(xlabel='Time (ps)', ylabel='Fraction (%)',
                title='(c) Penetration Fraction')

    plt.tight_layout()
    _save_fig(fig, os.path.join(output_dir, 'penetration.png'), dpi)


def plot_density(data_list, output_dir, dpi=150, z_focus=None, figsize=None):
    """
    Plot z-direction density profiles for one or more species.
    Each species (e.g., Fe, O, Fe_up, Fe_down) is drawn as a separate
    colored line. z_focus crops the view to the relevant surface region.
    Values are already frame-averaged number densities in atoms/Å³; no mass
    conversion, curve rescaling or bin reweighting occurs here. Each profile
    retains its own supplied z grid. An empty collection produces no file.
    Output: density_profile.png
    """
    _require_matplotlib()
    if not data_list:
        return

    fig, ax = plt.subplots(figsize=figsize or (10, 6))
    fig.suptitle('z-Direction Density Profile')

    for i, d in enumerate(data_list):
        ax.plot(d['z'], d['density'], color=WONG_PALETTE[(i + 1) % len(WONG_PALETTE)],
                lw=1.5, label=d['species'])

    ax.set(xlabel=r'$z$ (Å)', ylabel=r'Density (atoms/Å$^3$)')
    if z_focus:
        ax.set_xlim(z_focus)
    ax.legend()
    plt.tight_layout()
    _save_fig(fig, os.path.join(output_dir, 'density_profile.png'), dpi)


def plot_dissociation(data, output_dir, dpi=150, normalize=False, figsize=None):
    """
    Plot O₂ dissociation tracking over time.
    Shows O₂ molecule count and dissociated O atom count (or fractions
    if normalize=True). These are instantaneous distance-pair assignments,
    not identity-resolved bond-breaking events or reaction-rate estimates.
    Counts compare molecules against atoms; normalized values instead compare
    atoms in pairs against unpaired atoms with the same oxygen denominator.
    Output: o2_dissociation.png
    """
    _require_matplotlib()
    if data is None:
        return

    fig, ax = plt.subplots(figsize=figsize or (8, 5))

    if normalize and 'frac_in_o2' in data:
        ax.plot(data['time'], data['frac_in_o2'] * 100, color=CLR['o2'], lw=1.5, label='O in O2 (%)')
        ax.plot(data['time'], data['frac_dissociated'] * 100, color=CLR['diss'], lw=1.5, label='Dissociated O (%)')
        ax.set(xlabel='Time (ps)', ylabel='Fraction of total O (%)',
               title='O2 Dissociation (normalized)')
    else:
        ax.plot(data['time'], data['n_o2'], color=CLR['o2'], lw=1.5, label='O2 molecules')
        ax.plot(data['time'], data['n_dissociated'], color=CLR['diss'], lw=1.5, label='Dissociated O atoms')
        ax.set(xlabel='Time (ps)', ylabel='Count',
               title='O2 Dissociation Tracking')

    ax.legend()
    plt.tight_layout()
    _save_fig(fig, os.path.join(output_dir, 'o2_dissociation.png'), dpi)


def plot_spin(data, output_dir, dpi=150, normalize=False, figsize=None):
    """
    Plot magnetic species evolution over time (ACE only).
    Top: Fe_up, Fe_down, O populations (counts or fractions).
    Bottom: spin-up fraction with conditional 1:2, reversed 2:1 and equal
    population guides. Counts/fractions alone establish neither magnetic order
    nor an oxide phase. In the normalized top panel Fe spin fractions use all
    recognized Fe, while the O fraction uses all recognized atoms; the curves
    therefore do not form one partition summing to 100%.
    Output: spin_evolution.png
    """
    _require_matplotlib()
    if data is None:
        return

    fig, (a1, a2) = plt.subplots(2, 1, figsize=figsize or (12, 8))
    fig.suptitle('Magnetic Species Evolution (ACE)')

    t = data['time']

    if normalize and 'up_fraction' in data:
        a1.plot(t, data['up_fraction'] * 100, color=CLR['up'], lw=1, label='Fe up / all Fe')
        a1.plot(t, data.get('down_fraction', 1 - data['up_fraction']) * 100,
                color=CLR['down'], lw=1, label='Fe down / all Fe')
        if 'o_fraction' in data:
            a1.plot(t, data['o_fraction'] * 100, color=CLR['oar'], lw=1, label='O / all atoms')
        a1.set(xlabel='Time (ps)', ylabel='Fraction (%; denominators in legend)',
               title='(a) Species Fractions (different denominators)')
    else:
        a1.plot(t, data['n_up'], color=CLR['up'], lw=1, label='Fe up (type 1)')
        a1.plot(t, data['n_down'], color=CLR['down'], lw=1, label='Fe down (type 2)')
        a1.plot(t, data['n_o'], color=CLR['oar'], lw=1, label='O (type 3)')
        a1.set(xlabel='Time (ps)', ylabel='Count', title='(a) Species Count')
    a1.legend()

    a2.plot(t, data['up_fraction'], color=CLR['smooth'], lw=1)
    a2.axhline(1 / 3, color=CLR['up'], ls='--', alpha=0.5,
               label='1:2 population (1/3; encoding dependent)')
    a2.axhline(2 / 3, color=CLR['up'], ls=':', alpha=0.5,
               label='2:1 population (2/3; reversed encoding)')
    a2.axhline(0.5, color=CLR['down'], ls='--', alpha=0.5, label='Equal populations (1/2; order not established)')
    a2.set(xlabel='Time (ps)', ylabel='Fe_up / (Fe_up + Fe_down)',
           title='(b) Spin Up Fraction', ylim=(0, 1))
    a2.legend()

    plt.tight_layout()
    _save_fig(fig, os.path.join(output_dir, 'spin_evolution.png'), dpi)


def plot_msd(data, species_name, output_dir, dpi=150, figsize=None):
    """
    Plot Mean Square Displacement vs time for a given species.
    Values describe the analysis's fixed initial ID cohort, even after type
    changes; species_name is an initial-selection label, not an instantaneous
    spin channel. Display_label may clarify that distinction without renaming
    the saved file. Interpreting slopes as diffusion requires a diffusive
    regime and the correct dimensional factor; this routine fits neither.
    Output: msd_<species>.png (e.g., msd_Fe.png)
    """
    _require_matplotlib()
    if data is None:
        return

    fig, ax = plt.subplots(figsize=figsize or (8, 5))
    ax.plot(data['time'], data['msd'], color=CLR['avg'], lw=1.5)
    ax.set(xlabel='Time (ps)', ylabel=r'MSD (Å$^2$)',
           title=f'Mean Square Displacement — {data.get("display_label", species_name)}')
    plt.tight_layout()
    _save_fig(fig, os.path.join(output_dir, f'msd_{species_name}.png'), dpi)


def plot_performance(stage_times, output_dir, dpi=150, figsize=None):
    """
    Plot stage-wise wall time breakdown as a bar chart.
    Left: absolute time per stage (hours). Right: percentage distribution.
    Useful for identifying computational bottlenecks.
    Parser stage times are seconds, converted to hours only for display. The
    second panel is drawn for multiple stages, and percentages use their total
    wall time, not aggregate CPU time. Input timings are assumed nonnegative
    with a positive total when percentages are requested.
    Output: performance.png
    """
    _require_matplotlib()
    if not stage_times:
        return

    fig, (a1, a2) = plt.subplots(1, 2, figsize=figsize or (13, 5))
    fig.suptitle('Simulation Performance')

    labels = list(stage_times.keys())
    times_hr = [stage_times[s] / 3600 for s in labels]
    colors = WONG_PALETTE[1:6]  # Wong palette (orange, sky blue, green, yellow, blue)

    bars = a1.bar(labels, times_hr, color=colors[:len(labels)], edgecolor='black', lw=0.5)
    for bar, t in zip(bars, times_hr):
        a1.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.05,
                f'{t:.2f} hr', ha='center', fontsize=9, fontweight='bold')
    a1.set_ylabel('Wall Time (hours)')
    a1.set_title('Stage-wise Wall Time')

    if len(times_hr) > 1:
        a2.bar(labels, times_hr, color=colors[:len(labels)], edgecolor='black', lw=0.5)
        total = sum(times_hr)
        for bar, t in zip(a2.patches, times_hr):
            a2.text(bar.get_x() + bar.get_width() / 2, bar.get_height() / 2,
                    f'{t / total * 100:.1f}%', ha='center', va='center', fontsize=10)
        a2.set_ylabel('Wall Time (hours)')
        a2.set_title(f'Time Distribution (Total: {total:.1f} hr)')

    plt.tight_layout()
    _save_fig(fig, os.path.join(output_dir, 'performance.png'), dpi)


def plot_structure(atoms_array, atom_types, output_dir, dpi=150,
                   z_fixed=None, z_surface=None, z_focus=None, figsize=None):
    """
    Plot the final structure analysis from a LAMMPS data file.
    Left: z-resolved atom type distribution (horizontal bar chart, binned
    by BCC lattice constant 2.87 A). Right: O atom z-histogram with
    Fe surface position marked.
    Expects [id, type, x, y, z] rows. This legacy view uses Fe-specific binning
    from z=0 and label-based oxygen inference (falling back to the largest
    type ID); it is not a generic species or surface detector. Negative-z
    atoms do not enter the left histogram. z_fixed/z_surface are optional
    left-panel guides; the right guide instead uses the highest non-O z.
    Overlaid type bars are not stacked totals. A guide at exactly z=0 is omitted
    by the legacy truth-value checks. No periodic wrapping or volume
    normalization is applied. No cell accompanies this array-only API: the
    shell guards tilted source geometry, but direct callers must do so themselves.
    Output: structure.png
    """
    _require_matplotlib()
    if len(atoms_array) == 0:
        return

    types = atoms_array[:, 1].astype(int)
    z = atoms_array[:, 4]

    fig, (a1, a2) = plt.subplots(1, 2, figsize=figsize or (14, 8))
    fig.suptitle('Final Structure Analysis')

    # (a) z-resolved type distribution
    bin_size = 2.87  # BCC lattice constant
    z_max = z.max() + 5
    bins = np.arange(0, z_max, bin_size)
    bin_centers = bins + bin_size / 2
    colors_map = {1: WONG_PALETTE[6], 2: WONG_PALETTE[5], 3: WONG_PALETTE[3], 4: WONG_PALETTE[7]}
    type_names = atom_types

    for t_val in sorted(set(types)):
        t_mask = types == t_val
        counts = np.array([np.sum(t_mask & (z >= b) & (z < b + bin_size)) for b in bins])
        name = type_names.get(t_val, f'Type {t_val}')
        a1.barh(bin_centers[:len(counts)], counts, height=bin_size * 0.9,
                color=colors_map.get(t_val, 'gray'), alpha=0.8, label=name)

    if z_fixed:
        a1.axhline(z_fixed, color='gray', ls='--', lw=1.5)
    if z_surface:
        a1.axhline(z_surface, color='red', ls='--', lw=1.5)
    a1.set(ylabel=r'$z$ (Å)', xlabel='Atom count', title='z-Resolved Type Distribution')
    if z_focus:
        a1.set_ylim(z_focus)
    a1.legend()

    # (b) O atom z-histogram
    o_types = [t for t, n in type_names.items() if 'O' in str(n)]
    o_type = o_types[0] if o_types else max(set(types))
    o_z = z[types == o_type]
    if len(o_z) > 0:
        a2.hist(o_z, bins=30, color='#2ECC71', edgecolor='black', alpha=0.8,
                orientation='horizontal')
        fe_z = z[types != o_type]
        if len(fe_z) > 0:
            a2.axhline(np.max(fe_z), color='red', ls='-', lw=2,
                        label=f'Fe surface ({np.max(fe_z):.1f} Å)')
        a2.legend()
    a2.set(ylabel=r'$z$ (Å)', xlabel='O atom count', title='O Atom z-Distribution')
    if z_focus:
        a2.set_ylim(z_focus)

    plt.tight_layout()
    _save_fig(fig, os.path.join(output_dir, 'structure.png'), dpi)


def plot_snapshot(frames, col_idx, atom_types, output_dir, indices=None,
                  dpi=150, z_focus=None, figsize=None):
    """
    Plot side-view (z-x plane) snapshots at selected trajectory frames.
    Fe atoms are shown in blue, O atoms in red. Default: 5 evenly-spaced
    frames across the trajectory. z_focus crops the vertical axis.
    The x-z projection uses stored positions without unwrapping or depth
    filtering. Selected frames are checked for orthogonal geometry before any
    figure is created; this is rejection, not tilted-cell rendering support.
    String-key element maps assume a legacy sorted-element synthesized type
    ordering, not the current parser's canonical ACE slots; absent recognizable
    labels retain the legacy type-1/type-2 fallbacks. These display heuristics
    must not be used as a scientific species assignment. Explicit indices are
    used as supplied.
    Output: snapshots.png (N panels side by side)
    """
    if not frames:
        return

    if indices is None:
        n = len(frames)
        indices = [0, n // 4, n // 2, 3 * n // 4, n - 1]
        indices = sorted(set(i for i in indices if 0 <= i < n))

    from lammps_post.analysis import _orthogonal_box
    for idx in indices:
        _orthogonal_box(frames[idx], 'Snapshot plotting')
    _require_matplotlib()
    xi, zi_col, ti = col_idx['x'], col_idx['z'], col_idx['type']
    n_snap = len(indices)
    fig, axes = plt.subplots(1, n_snap, figsize=figsize or (4 * n_snap, 8), sharey=True)
    if n_snap == 1:
        axes = [axes]

    # Identify Fe and O type numbers
    # atom_types keys can be int (type-based: {1:'Fe', 2:'O'}) or
    # str (element-based ACE: {'Fe':'Fe_up', 'O':'O'}).
    # For plotting, we need int type IDs that match the atoms array.
    int_keys = all(isinstance(k, int) for k in atom_types.keys())
    if int_keys:
        o_types = [t for t, n in atom_types.items() if 'O' in str(n)]
        fe_types = [t for t, n in atom_types.items() if 'Fe' in str(n) or 'Mn' in str(n)]
    else:
        # str keys (ACE element-based): map element names to synthesized type IDs
        # The type column was synthesized from sorted unique elements: {elem: i+1}
        # We need to figure out which int type IDs correspond to Fe/O
        sorted_elems = sorted(atom_types.keys())
        elem_to_id = {e: i + 1 for i, e in enumerate(sorted_elems)}
        fe_types = [elem_to_id[e] for e in sorted_elems
                    if 'Fe' in atom_types.get(e, '') or 'Mn' in e or 'Fe' in e]
        o_types = [elem_to_id[e] for e in sorted_elems if e == 'O' or 'O' in atom_types.get(e, '')]

    for ax, idx in zip(axes, indices):
        fr = frames[idx]
        atoms = fr['atoms']
        types = atoms[:, ti].astype(int)

        fe_mask = np.isin(types, fe_types) if fe_types else types == 1
        o_mask = np.isin(types, o_types) if o_types else types == 2

        ax.scatter(atoms[fe_mask, xi], atoms[fe_mask, zi_col],
                   c=CLR['Fe'], s=3, alpha=0.6, label='Fe')
        ax.scatter(atoms[o_mask, xi], atoms[o_mask, zi_col],
                   c=CLR['O'], s=5, alpha=0.8, label='O')
        ax.set_xlabel(r'$x$ (Å)')
        ax.set_title(f'Frame {idx}\n(step {fr["timestep"]})')
        if z_focus:
            ax.set_ylim(z_focus)
        ax.legend(loc='upper right')

    axes[0].set_ylabel(r'$z$ (Å)')
    fig.suptitle('Oxidation Snapshots (side view)')
    plt.tight_layout()
    _save_fig(fig, os.path.join(output_dir, 'snapshots.png'), dpi)


def plot_penetration_profile(data, output_dir, dpi=150, figsize=None,
                              z_focus=None, n_snapshots=8):
    """
    Comprehensive O penetration profiling — generates 6 plots from
    analyze_penetration_profile() output:

    1. o_trajectories.png       — Spaghetti plot of individual O atom z(t)
    2. o_kymograph.png          — 2D heatmap (time x z) of O density
    3. o_zdist_evolution.png    — Ridge/waterfall of z-histograms over time
    4. o_adsorption_timeline.png — Cumulative O surface crossing count
    5. o_penetration_3d.png     — 3D surface plot (time x z x density)
    6. o_penetration_metrics.png — 4 quantitative trend lines:
       (a) Mean O z-position with std band
       (b) Adsorption ratio (% below surface)
       (c) O distribution width (sigma_z)
       (d) Max penetration depth with sqrt(t) fit

    Input columns are ID-union trajectories with NaNs for absence/type exit;
    trajectory lines preserve those gaps. Histograms/position statistics use
    only finite present samples, and an empty frame retains NaN position metrics.
    Histogram colors/heights are counts per bin, not volume-normalized number
    densities, despite the historical density titles. z_focus sets histogram
    edges as well as display bounds, without restricting the metric reductions.

    The cumulative timeline and t50 refer to the initial population when its
    size is supplied; later-arriving IDs do not inflate that cohort's kinetics.
    First-below observations include initially absorbed atoms and do not
    interpolate missing crossings. The per-frame surface can itself move across
    an atom; a first-below observation need not be a physical trajectory crossing
    or lasting adsorption. Initial IDs remain eligible after absence/type exit
    and return. Without n_initial_o, the legacy path trusts cross_times/n_o and
    cannot recover initial-cohort membership from those values alone.
    The optional square-root curve is a visual
    heuristic, not a diffusion coefficient, uncertainty estimate or mechanism
    identification. None produces no files.

    Args:
        data:        dict — Output from analyze_penetration_profile()
        output_dir:  str  — Output directory
        dpi:         int  — Plot resolution
        figsize:     tuple — (width, height) for individual plots
        z_focus:     tuple — (z_lo, z_hi) to crop z-range, or None for auto
        n_snapshots: int  — Number of time snapshots for ridge plot
    """
    _require_matplotlib()
    if data is None:
        return

    time = data['time']
    o_z = np.asarray(data['o_z_traj'])   # (n_frames, ID-union size); absent IDs are NaN
    surface = data['surface_z']
    min_z = data['min_o_z']
    cross_times = np.sort(data['cross_times'])
    n_o = data['n_o']
    n_frames = len(time)
    # New ID-union analysis results distinguish the initial cohort from atoms
    # that enter later. Kinetics of that cohort must not count later arrivals.
    timeline_population = data.get('n_initial_o', n_o)
    if 'n_initial_o' in data:
        initially_present = np.flatnonzero(np.isfinite(o_z[0]))
        initial_crossings = []
        for j in initially_present:
            below = o_z[:, j] < surface
            if np.any(below):
                initial_crossings.append(time[np.argmax(below)])
        cross_times = np.sort(initial_crossings)

    # Auto z_focus
    if z_focus is None:
        all_z = o_z[np.isfinite(o_z)]
        if not len(all_z):
            raise ValueError('Cannot plot penetration profile without any finite O positions')
        z_lo = np.min(all_z) - 5
        finite_surface = np.asarray(surface)[np.isfinite(surface)]
        z_hi = max(np.max(all_z) + 5,
                   np.max(finite_surface) if len(finite_surface) else -np.inf)
    else:
        z_lo, z_hi = z_focus

    # ── 1. Spaghetti plot: individual O trajectories ──
    # Matplotlib breaks lines at NaNs: never connect observations across a
    # missing ID/type-selection sample as if its intermediate path were known.
    fig, ax = plt.subplots(figsize=figsize or (12, 6))
    for j in range(o_z.shape[1]):
        ax.plot(time, o_z[:, j], lw=0.5, alpha=0.4, color=CLR['O'])
    ax.plot(time, surface, color=CLR['Fe'], lw=2, ls='--', label='Fe surface')
    ax.plot(time, min_z, color=CLR['smooth'], lw=1.5, label='Deepest O')
    ax.set(xlabel='Time (ps)', ylabel=r'$z$ (Å)',
           title='Individual O Atom Trajectories')
    ax.set_ylim(z_lo, z_hi)
    ax.legend()
    plt.tight_layout()
    _save_fig(fig, os.path.join(output_dir, 'o_trajectories.png'), dpi)

    # ── 2. Kymograph (heatmap) ──
    n_zbins = 100
    z_edges = np.linspace(z_lo, z_hi, n_zbins + 1)
    z_centers = (z_edges[:-1] + z_edges[1:]) / 2

    heatmap = np.zeros((n_frames, n_zbins))
    # A changing present population changes count intensity. Do not divide by
    # union size or label the counts as atoms per unit volume.
    for i in range(n_frames):
        h, _ = np.histogram(o_z[i, np.isfinite(o_z[i])], bins=z_edges)
        heatmap[i] = h

    fig, ax = plt.subplots(figsize=figsize or (12, 6))
    im = ax.pcolormesh(time, z_centers, heatmap.T, cmap='hot_r', shading='auto')
    ax.plot(time, surface, color=CLR['Fe'], lw=1.5, ls='--', label='Fe surface')
    ax.set(xlabel='Time (ps)', ylabel=r'$z$ (Å)',
           title='O Atom Density Kymograph')
    ax.legend(loc='upper right')
    plt.colorbar(im, ax=ax, label='O count per bin')
    plt.tight_layout()
    _save_fig(fig, os.path.join(output_dir, 'o_kymograph.png'), dpi)

    # ── 3. Ridge / waterfall plot ──
    snap_indices = np.linspace(0, n_frames - 1, n_snapshots, dtype=int)
    colors = plt.cm.viridis(np.linspace(0.1, 0.9, n_snapshots))
    offset_step = max(1, n_o // 8)

    z_hist_edges = np.linspace(z_lo, z_hi, 40 + 1)
    z_hist_centers = (z_hist_edges[:-1] + z_hist_edges[1:]) / 2

    fig, ax = plt.subplots(figsize=figsize or (10, 2 + 1.2 * n_snapshots))
    for k, idx in enumerate(snap_indices):
        hist, _ = np.histogram(o_z[idx, np.isfinite(o_z[idx])], bins=z_hist_edges)
        offset = k * offset_step
        ax.fill_between(z_hist_centers, offset, hist + offset, alpha=0.3, color=colors[k])
        ax.plot(z_hist_centers, hist + offset, color=colors[k], lw=1.5)
        ax.text(z_hi - 0.5, offset + offset_step * 0.5, f'{time[idx]:.0f} ps',
                fontsize=9, fontweight='bold', color=colors[k], ha='right', va='center',
                bbox=dict(facecolor='white', alpha=0.8, edgecolor='none', pad=1))

    # Surface marker
    finite_surface = np.asarray(surface)[np.isfinite(surface)]
    if len(finite_surface):
        mean_surf = np.mean(finite_surface)
        ax.axvline(mean_surf, color=CLR['Fe'], ls='--', lw=1, alpha=0.6)
        ax.text(mean_surf + 0.3, n_snapshots * offset_step * 0.95, 'Fe surface',
                color=CLR['Fe'], fontsize=8, rotation=90, va='top')

    ax.set_yticks([])
    ax.set(xlabel=r'$z$ (Å)', ylabel='O count (offset)',
           title='O z-Distribution Evolution')
    ax.set_xlim(z_lo, z_hi)
    plt.tight_layout()
    _save_fig(fig, os.path.join(output_dir, 'o_zdist_evolution.png'), dpi)

    # ── 4. Adsorption timeline ──
    fig, ax = plt.subplots(figsize=figsize or (10, 5))
    if len(cross_times) > 0:
        cumulative = np.arange(1, len(cross_times) + 1)
        ax.step(cross_times, cumulative, color=CLR['avg'], lw=2, where='post')
        # t50 refers to the INITIAL cohort, not the eventually crossed subset.
        # ceil(N/2) crossings are required; the corresponding index is count-1.
        half_count = int(np.ceil(timeline_population / 2))
        half_idx = half_count - 1
        if half_count > 0 and len(cross_times) >= half_count:
            ax.axhline(cumulative[half_idx], color='grey', ls=':', alpha=0.5)
            ax.axvline(cross_times[half_idx], color='grey', ls=':', alpha=0.5)
            ax.text(cross_times[half_idx], cumulative[half_idx] + 1,
                    f' t₅₀ = {cross_times[half_idx]:.0f} ps', fontsize=9)
        ax.set(xlabel='Time (ps)', ylabel='Cumulative O atoms adsorbed',
               title=f'O Adsorption Timeline — {len(cross_times)}/{timeline_population} '
                     'initial O adsorbed')
        ax.set_ylim(bottom=0, top=max(timeline_population, len(cross_times)) + 2)
    else:
        ax.text(0.5, 0.5, 'No O atoms crossed the surface', transform=ax.transAxes,
                ha='center', va='center', fontsize=12)
        ax.set(xlabel='Time (ps)', ylabel='Cumulative O atoms adsorbed',
               title='O Adsorption Timeline')
    plt.tight_layout()
    _save_fig(fig, os.path.join(output_dir, 'o_adsorption_timeline.png'), dpi)

    # ── 5. 3D surface plot ──
    from mpl_toolkits.mplot3d import Axes3D  # noqa: F401  (registers '3d' on matplotlib < 3.2)

    fig = plt.figure(figsize=figsize or (12, 8))
    ax = fig.add_subplot(111, projection='3d')

    # Downsample time for cleaner 3D mesh
    t_step = max(1, n_frames // 60)
    t_idx = np.arange(0, n_frames, t_step)
    T_grid, Z_grid = np.meshgrid(time[t_idx], z_centers)
    D_grid = heatmap[t_idx].T  # (n_zbins, n_time_samples)

    ax.plot_surface(T_grid, Z_grid, D_grid, cmap='viridis', alpha=0.85,
                    rstride=1, cstride=1, linewidth=0, antialiased=True)

    # Surface line on the floor
    ax.plot(time[t_idx], surface[t_idx], zs=0, zdir='z',
            color=CLR['Fe'], lw=1.5, ls='--', alpha=0.6)

    ax.set(xlabel='Time (ps)', ylabel=r'$z$ (Å)', zlabel='O count')
    ax.set_title('O Penetration Profile (3D)')
    ax.view_init(elev=25, azim=-60)
    plt.tight_layout()
    _save_fig(fig, os.path.join(output_dir, 'o_penetration_3d.png'), dpi)

    # ── 6. Quantitative penetration metrics vs time ──
    fig, axes = plt.subplots(2, 2, figsize=figsize or (12, 9))
    fig.suptitle('O Penetration Metrics')

    # Smoothing window
    w = max(5, n_frames // 40)

    def _smooth(arr):
        """Return valid-window sample means with centered original time labels.

        Short series remain raw; long series lose edge samples. NaNs propagate
        through windows instead of being interpolated or counted as zero.
        Unequal time spacing does not change the equal-sample kernel.
        """
        if len(arr) > w:
            return np.convolve(arr, np.ones(w) / w, mode='valid'), time[w // 2:w // 2 + len(arr) - w + 1]
        return arr, time

    # (a) Mean O z-position + std band
    # Reduce over finite present IDs, not the eventual union denominator. The
    # population standard deviation is a spatial spread, not a mean uncertainty.
    present = np.isfinite(o_z)
    present_count = np.sum(present, axis=1)
    mean_z = np.divide(np.sum(np.where(present, o_z, 0.), axis=1), present_count,
                       out=np.full(n_frames, np.nan), where=present_count > 0)
    squared = np.where(present, (o_z - mean_z[:, None])**2, 0.)
    std_z = np.sqrt(np.divide(np.sum(squared, axis=1), present_count,
                            out=np.full(n_frames, np.nan), where=present_count > 0))
    sm_mean, t_sm = _smooth(mean_z)
    sm_std, _ = _smooth(std_z)

    ax = axes[0, 0]
    ax.fill_between(time, mean_z - std_z, mean_z + std_z, alpha=0.15, color=CLR['O'])
    ax.plot(time, mean_z, color=CLR['O'], lw=0.5, alpha=0.4)
    ax.plot(t_sm, sm_mean, color=CLR['smooth'], lw=1.5, label='Mean O $z$')
    ax.plot(time, surface, color=CLR['Fe'], ls='--', lw=1, label='Fe surface')
    ax.set(xlabel='Time (ps)', ylabel=r'$z$ (Å)', title='(a) Mean O Position')
    ax.legend()

    # (b) Fraction of O below surface (adsorption ratio)
    below_count = np.sum(present & (o_z < np.asarray(surface)[:, None]), axis=1)
    frac_below = np.divide(below_count, present_count, out=np.full(n_frames, np.nan),
                           where=(present_count > 0) & np.isfinite(surface))
    sm_frac, t_sm2 = _smooth(frac_below)

    ax = axes[0, 1]
    ax.plot(time, frac_below * 100, color=CLR['oar'], lw=0.5, alpha=0.4)
    ax.plot(t_sm2, sm_frac * 100, color=CLR['smooth'], lw=1.5, label='Adsorption ratio')
    ax.set(xlabel='Time (ps)', ylabel='Present O below surface (%)',
           title='(b) Adsorption Ratio', ylim=(-2, None))
    ax.legend()

    # (c) O z-spread (std) — measures how dispersed O is
    ax = axes[1, 0]
    ax.plot(time, std_z, color=CLR['press'], lw=0.5, alpha=0.4)
    sm_spread, t_sm3 = _smooth(std_z)
    ax.plot(t_sm3, sm_spread, color=CLR['smooth'], lw=1.5, label='O $z$ spread (σ)')
    ax.set(xlabel='Time (ps)', ylabel=r'σ$_z$ (Å)',
           title='(c) O Distribution Width')
    ax.legend()

    # (d) Penetration depth (surface - deepest O) + rate
    # Unlike plot_penetration's signed depth, this display clips above-surface
    # samples to zero. Missing minima/surfaces stay NaN, not zero-depth evidence.
    depth = np.maximum(surface - min_z, 0)
    sm_depth, t_sm4 = _smooth(depth)

    ax = axes[1, 1]
    ax.plot(time, depth, color=CLR['avg'], lw=0.5, alpha=0.4)
    ax.plot(t_sm4, sm_depth, color=CLR['smooth'], lw=1.5, label='Max depth')
    # Show a median d/sqrt(t) scaling guide after the first >1 Å sample. This
    # is not a least-squares fit or proof of parabolic/diffusion-controlled growth.
    onset_mask = depth > 1.0
    if np.sum(onset_mask) > 10:
        onset_idx = np.argmax(onset_mask)
        t_onset = time[onset_idx]
        t_rel = time[onset_idx:] - t_onset
        d_rel = depth[onset_idx:]
        valid = (t_rel > 0) & np.isfinite(d_rel)
        if np.sum(valid) > 5:
            A = np.median(d_rel[valid] / np.sqrt(t_rel[valid]))
            t_model = np.linspace(0, t_rel[-1], 200)
            ax.plot(t_model + t_onset, A * np.sqrt(t_model), color=CLR['press'],
                    ls=':', lw=1.5, label=f'√t fit: d={A:.1f}√t')
    ax.set(xlabel='Time (ps)', ylabel='Depth (Å)',
           title='(d) Max Penetration Depth')
    ax.legend()

    plt.tight_layout()
    _save_fig(fig, os.path.join(output_dir, 'o_penetration_metrics.png'), dpi)


def plot_penetration_trend(data, output_dir, dpi=150, figsize=None):
    """
    Plot smoothed O penetration trend lines — focused, clean visualization.

    Three vertically stacked subplots sharing x-axis (time):
      (a) Adsorption ratio (% O below surface) — primary oxidation metric
      (b) Mean O z-position with ±σ band — bulk O movement
      (c) Max penetration depth — deepest O trajectory

    Each subplot shows a faint raw trace with a bold smoothed overlay.
    Consume precomputed metrics without another smoothing pass. The shaded
    ±sigma band is instantaneous population spread, not a confidence interval;
    NaNs remain gaps. Surface_z is the fixed reference supplied to the trend
    analysis, unlike the per-frame percentile surface in profile plots.
    The displayed maximum depth is the analysis's zero-clipped depth, unlike
    the signed depth in plot_penetration. The adsorption denominator is the
    instantaneous selected population, not the initial-ID timeline cohort.
    Output: penetration_trend.png
    """
    _require_matplotlib()
    if data is None:
        return

    t = data['time']
    surface_z = data['surface_z']

    fig, axes = plt.subplots(3, 1, figsize=figsize or (10, 10), sharex=True)
    fig.suptitle('O Penetration Trend', fontsize=13, fontweight='bold')

    # ── (a) Adsorption ratio ──
    ax = axes[0]
    ax.plot(t, data['adsorption_ratio_raw'] * 100,
            color=CLR['oar'], lw=0.5, alpha=0.3)
    ax.plot(t, data['adsorption_ratio'] * 100,
            color=CLR['oar'], lw=2, label='O below surface (%)')
    ax.set_ylabel('Adsorption ratio (%)')
    ax.set_title('(a) O Adsorption Ratio', fontsize=11)
    ax.set_ylim(bottom=-2)
    ax.legend(loc='upper left')

    # ── (b) Mean O z-position ──
    ax = axes[1]
    mean_raw = data['mean_o_z_raw']
    std_raw = data['std_o_z_raw']
    ax.fill_between(t, mean_raw - std_raw, mean_raw + std_raw,
                    alpha=0.12, color=CLR['O'])
    ax.plot(t, mean_raw, color=CLR['O'], lw=0.5, alpha=0.3)
    ax.plot(t, data['mean_o_z'], color=CLR['O'], lw=2, label='Mean O $z$')
    ax.axhline(surface_z, color=CLR['Fe'], ls='--', lw=1.2,
               alpha=0.7, label=f'Fe surface ({surface_z:.1f} Å)')
    ax.set_ylabel(r'$z$ (Å)')
    ax.set_title('(b) Mean O Position (±σ)', fontsize=11)
    ax.legend(loc='upper right')

    # ── (c) Max penetration depth ──
    ax = axes[2]
    ax.plot(t, data['max_depth_raw'], color=CLR['avg'], lw=0.5, alpha=0.3)
    ax.plot(t, data['max_depth'], color=CLR['avg'], lw=2, label='Max depth')
    ax.set_ylabel('Depth (Å)')
    ax.set_xlabel('Time (ps)')
    ax.set_title('(c) Maximum Penetration Depth', fontsize=11)
    ax.legend(loc='upper left')

    plt.tight_layout()
    _save_fig(fig, os.path.join(output_dir, 'penetration_trend.png'), dpi)
