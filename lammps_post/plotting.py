"""
═══════════════════════════════════════════════════════════════
Section 4: Plotting Functions
═══════════════════════════════════════════════════════════════
Each analysis type has a corresponding plot function that:
  1. Takes a result dict (from analysis functions)
  2. Creates matplotlib figures with consistent styling
  3. Saves to the output directory as PNG/PDF/SVG files
  4. Supports optional normalize and z_focus parameters

All plot functions check HAS_MPL and return silently if matplotlib
is not available, so they can be called unconditionally.

Dependencies:
  Required : numpy, matplotlib (lazy-loaded)
  Uses     : WONG_PALETTE, BAR_TO_GPA, DENSITY_CONVERSION from __init__
             progress_msg, C from display
═══════════════════════════════════════════════════════════════
"""

import os
import numpy as np

from lammps_post import WONG_PALETTE, BAR_TO_GPA, DENSITY_CONVERSION
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
                         Follows journal submission guidelines (Nature, ACS, RSC).
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

    Args:
        fig:         matplotlib.Figure — The figure to save
        outpath:     str — Full file path (e.g., './output/rdf_Fe_O.png')
        dpi:         int — Resolution in dots per inch (default: 150)
        save_format: str or None — 'png', 'pdf', 'svg', or 'both' (png+pdf).
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

    Args:
        log_data:        dict — Parsed log data from parse_log()
        output_dir:      str  — Output directory for saved plot
        dpi:             int  — Plot resolution
        dt_fs:           float or None — Timestep in fs for time axis;
                         if None, uses log_data['time_ps'] or fallback 1.0 fs
        pressure_unit:   str  — 'bar' or 'gpa'; controls pressure axis label/scale
        total_mass_amu:  float or None — Total system mass for density calculation
        figsize:         tuple or None — (width, height); None uses adaptive default

    Output: thermo.png
    """
    if not HAS_MPL or log_data is None:
        return

    d = log_data
    step = d.get('step', np.array([]))
    if len(step) == 0:
        return

    # ── Time axis ──
    if 'time_ps' in d:
        t = d['time_ps']
    elif dt_fs is not None:
        t = step * dt_fs / 1000.0  # fs -> ps
    else:
        t = step * 0.001  # fallback: 1 fs = 0.001 ps (metal default)

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

    # ── Pressure unit handling ──
    if pressure_unit.lower() == 'gpa':
        press_label = 'Pressure (GPa)'
        press_scale = BAR_TO_GPA
    else:
        press_label = 'Pressure (bar)'
        press_scale = 1.0

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
            # Slab-corrected pressure annotation
            if key == 'press' and slab_z_range is not None and has_vol:
                z_lo, z_hi = slab_z_range
                slab_frac = (z_hi - z_lo)  # slab thickness in A
                # Approximate: V_slab / V_box ≈ slab_thickness / Lz
                # We annotate but don't replace, since exact Lz varies per frame
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
                            pressure_unit='bar', figsize=None):
    """
    Plot a compact thermostat QC summary with dual y-axes (twinx).
    Temperature on the left axis (red), Pressure on the right axis (blue).
    Useful for slides and papers where a single figure is preferred.

    Reference: md_stats_plot.py plot_thermostat()

    Args:
        log_data:       dict — Parsed log data
        output_dir:     str  — Output directory
        dpi:            int  — Plot resolution
        dt_fs:          float or None — Timestep in fs
        pressure_unit:  str  — 'bar' or 'gpa'
        figsize:        tuple or None — (width, height)

    Output: thermostat_summary.png
    """
    if not HAS_MPL or log_data is None:
        return

    d = log_data
    step = d.get('step', np.array([]))
    if len(step) == 0 or 'temp' not in d:
        return

    # Time axis
    if 'time_ps' in d:
        t = d['time_ps']
        xlabel = 'Time (ps)'
    elif dt_fs is not None:
        t = step * dt_fs / 1000.0
        xlabel = 'Time (ps)'
    else:
        t = step * 0.001
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
        if pressure_unit.lower() == 'gpa':
            press = d['press'] * BAR_TO_GPA
            plabel = 'Pressure (GPa)'
        else:
            press = d['press']
            plabel = 'Pressure (bar)'
        ax2.set_ylabel(plabel, color=CLR['pe'])
        ax2.plot(t, press, color=CLR['pe'], alpha=0.6, lw=1.0)
        ax2.tick_params(axis='y', labelcolor=CLR['pe'])

    fig.suptitle('Thermostat Summary')
    fig.tight_layout()
    _save_fig(fig, os.path.join(output_dir, 'thermostat_summary.png'), dpi)


def plot_pressure(log_data, output_dir, dpi=150, dt_fs=None,
                  pressure_unit='bar', slab_z_range=None, figsize=None):
    """
    Detailed pressure analysis plot for slab geometries.

    For slab simulations (p p f boundary), the total box pressure is
    physically misleading because it includes vacuum volume. This plot
    provides meaningful pressure metrics:

    Panel (a): Raw pressure components Pxx, Pyy, Pzz
               + in-plane average P_in = (Pxx + Pyy) / 2
    Panel (b): In-plane vs normal pressure with running averages
    Panel (c): Slab-corrected pressure (if slab_z_range provided):
               P_eff = P_box * (Lz / slab_thickness)

    For bulk (fully periodic) systems, shows standard P with statistics.

    Args:
        log_data:      dict  — Parsed log data from parse_log()
        output_dir:    str   — Output directory
        dpi:           int   — Plot resolution
        dt_fs:         float — Timestep in fs
        pressure_unit: str   — 'bar' or 'gpa'
        slab_z_range:  tuple — (z_lo, z_hi) of slab region in A, or None
        figsize:       tuple — (width, height)

    Output: pressure_analysis.png
    """
    if not HAS_MPL or log_data is None:
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
    if 'time_ps' in d:
        t = d['time_ps']
    elif dt_fs is not None:
        t = step * dt_fs / 1000.0
    else:
        t = step * 0.001

    # Pressure scaling
    if pressure_unit.lower() == 'gpa':
        pscale = BAR_TO_GPA
        punit = 'GPa'
    else:
        pscale = 1.0
        punit = 'bar'

    press = d['press'] * pscale
    has_vol = 'vol' in d and len(d['vol']) == len(step)

    w = max(10, len(press) // 100)

    if has_stress:
        # ── 3-panel layout for full stress tensor ──
        n_cols = 3 if slab_z_range else 2
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

        # Panel (c): Slab-corrected (if z_range provided)
        if slab_z_range and n_cols == 3:
            ax = axes[2]
            z_lo, z_hi = slab_z_range
            slab_thick = z_hi - z_lo
            if has_vol:
                # Per-frame correction: P_eff = P_in * (V_box / V_slab)
                # V_slab ~ Lx * Ly * slab_thick, V_box = Lx * Ly * Lz
                # ratio = Lz / slab_thick (area cancels)
                # Use volume: Lz = V / (Lx*Ly), but we don't know Lx*Ly separately
                # Approximation: assume constant box, use first-frame estimate
                box_vol_mean = np.mean(d['vol'])
                # From V = Lx*Ly*Lz, and z_range defines slab, ratio = Lz/slab_thick
                # We don't have Lz directly, but for slab: V_slab/V_box = slab_thick/Lz
                # So P_eff_in = P_in * Lz / slab_thick
                # Estimate Lz from thermo: not directly available.
                # Use the fact that for standard slab, Lz ~ 3*slab_thick typically.
                # Better: just report P_in which is already meaningful for slabs.
                p_corr = p_in  # In-plane is already the meaningful quantity
                label = f'In-plane P (slab {z_lo:.0f}-{z_hi:.0f} A)'
            else:
                p_corr = p_in
                label = f'In-plane P (slab {z_lo:.0f}-{z_hi:.0f} A)'

            ax.plot(t, p_corr, color=CLR['avg'], lw=0.3, alpha=0.4)
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
        n_cols = 2 if slab_z_range else 1
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

        if slab_z_range and n_cols == 2:
            ax = axes[1]
            ax.plot(t, press, color=CLR['press'], lw=0.5, alpha=0.6)
            if len(press) > w:
                ax.plot(t_s, sm, color=CLR['smooth'], lw=1.5)
            z_lo, z_hi = slab_z_range
            ax.set(xlabel='Time (ps)', ylabel=f'Pressure ({punit})',
                   title=f'Box P (slab {z_lo:.0f}-{z_hi:.0f} A)')
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
    Output: charge_evolution.png
    """
    if not HAS_MPL or data is None:
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
    Shows Fe charge (scatter, left y-axis) and O density (fill, right y-axis)
    vs z-coordinate. The z_focus parameter crops the view to the relevant region.
    Output: charge_z_distribution.png
    """
    if not HAS_MPL or data is None:
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


def plot_rdf(data, output_dir, dpi=150, figsize=None, ref_rdfs=None):
    """
    Plot radial distribution function g(r).

    When reference RDFs are provided, uses a vertically stacked layout
    inspired by EELS/XRD comparison figures: each curve is offset vertically
    so peaks don't overlap, with phase labels placed directly next to each
    curve. The MD result is plotted at the top with the boldest line.

    Without references, shows the MD g(r) with vertical reference lines
    at known oxide bond lengths.

    Args:
        data:     dict — RDF data from compute_rdf()
        output_dir: str — Output directory
        dpi:      int — Plot resolution
        figsize:  tuple — (width, height)
        ref_rdfs: list[dict] or None — Reference RDF curves to overlay.

    Output: rdf_<pair>.png
    """
    if not HAS_MPL or data is None:
        return

    label = data['label']

    if ref_rdfs:
        # ── Stacked overlay style (like EELS comparison figures) ──
        # Each curve is normalized to [0, 1] and offset vertically.
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

            # Normalize each curve to [0, 1] for consistent offset stacking
            g_max = np.max(g) if np.max(g) > 0 else 1.0
            g_norm = g / g_max

            offset = i * offset_step
            y = g_norm + offset

            if is_md:
                color = CLR['avg']
                lw = 2.0
                curve_label = f'MD ({data["n_frames"]} frames)'
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
                label=f'MD ({data["n_frames"]} frames)')
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
    _save_fig(fig, os.path.join(output_dir, f'rdf_{label.replace("-","_")}.png'), dpi)


def plot_oar(data, output_dir, dpi=150, normalize=False, figsize=None):
    """
    Plot Oxygen Absorption Rate (OAR) over time.
    Left: OAR percentage. Right: absorbed O count or fraction.
    Output: oar.png
    """
    if not HAS_MPL or data is None:
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
    Shows the fraction of Fe atoms with charge > 0.3 e.
    Output: oxidation_rate.png
    """
    if not HAS_MPL or data is None:
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
    Output: penetration.png
    """
    if not HAS_MPL or data is None:
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
    Output: density_profile.png
    """
    if not HAS_MPL or not data_list:
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
    if normalize=True). Reveals the kinetics of O₂ bond breaking.
    Output: o2_dissociation.png
    """
    if not HAS_MPL or data is None:
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
    Bottom: spin-up fraction with reference lines for Fe₃O₄ (1/3)
    and antiferromagnetic (1/2) ideal values.
    Output: spin_evolution.png
    """
    if not HAS_MPL or data is None:
        return

    fig, (a1, a2) = plt.subplots(2, 1, figsize=figsize or (12, 8))
    fig.suptitle('Magnetic Species Evolution (ACE)')

    t = data['time']

    if normalize and 'up_fraction' in data:
        a1.plot(t, data['up_fraction'] * 100, color=CLR['up'], lw=1, label='Fe up fraction')
        a1.plot(t, data.get('down_fraction', 1 - data['up_fraction']) * 100,
                color=CLR['down'], lw=1, label='Fe down fraction')
        if 'o_fraction' in data:
            a1.plot(t, data['o_fraction'] * 100, color=CLR['oar'], lw=1, label='O fraction')
        a1.set(xlabel='Time (ps)', ylabel='Fraction of total (%)',
               title='(a) Species Fraction')
    else:
        a1.plot(t, data['n_up'], color=CLR['up'], lw=1, label='Fe up (type 1)')
        a1.plot(t, data['n_down'], color=CLR['down'], lw=1, label='Fe down (type 2)')
        a1.plot(t, data['n_o'], color=CLR['oar'], lw=1, label='O (type 3)')
        a1.set(xlabel='Time (ps)', ylabel='Count', title='(a) Species Count')
    a1.legend()

    a2.plot(t, data['up_fraction'], color=CLR['smooth'], lw=1)
    a2.axhline(1 / 3, color=CLR['up'], ls='--', alpha=0.5, label='Fe3O4 ideal (1/3)')
    a2.axhline(0.5, color=CLR['down'], ls='--', alpha=0.5, label='AF equal (1/2)')
    a2.set(xlabel='Time (ps)', ylabel='Fe_up / (Fe_up + Fe_down)',
           title='(b) Spin Up Fraction', ylim=(0, 1))
    a2.legend()

    plt.tight_layout()
    _save_fig(fig, os.path.join(output_dir, 'spin_evolution.png'), dpi)


def plot_msd(data, species_name, output_dir, dpi=150, figsize=None):
    """
    Plot Mean Square Displacement vs time for a given species.
    MSD growth rate indicates diffusivity: steeper = more mobile atoms.
    Output: msd_<species>.png (e.g., msd_Fe.png)
    """
    if not HAS_MPL or data is None:
        return

    fig, ax = plt.subplots(figsize=figsize or (8, 5))
    ax.plot(data['time'], data['msd'], color=CLR['avg'], lw=1.5)
    ax.set(xlabel='Time (ps)', ylabel=r'MSD (Å$^2$)',
           title=f'Mean Square Displacement — {species_name}')
    plt.tight_layout()
    _save_fig(fig, os.path.join(output_dir, f'msd_{species_name}.png'), dpi)


def plot_performance(stage_times, output_dir, dpi=150, figsize=None):
    """
    Plot stage-wise wall time breakdown as a bar chart.
    Left: absolute time per stage (hours). Right: percentage distribution.
    Useful for identifying computational bottlenecks.
    Output: performance.png
    """
    if not HAS_MPL or not stage_times:
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
    Output: structure.png
    """
    if not HAS_MPL or len(atoms_array) == 0:
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
    Output: snapshots.png (N panels side by side)
    """
    if not HAS_MPL or not frames:
        return

    if indices is None:
        n = len(frames)
        indices = [0, n // 4, n // 2, 3 * n // 4, n - 1]
        indices = sorted(set(i for i in indices if 0 <= i < n))

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
    Comprehensive O penetration profiling — generates 5 plots from
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

    Args:
        data:        dict — Output from analyze_penetration_profile()
        output_dir:  str  — Output directory
        dpi:         int  — Plot resolution
        figsize:     tuple — (width, height) for individual plots
        z_focus:     tuple — (z_lo, z_hi) to crop z-range, or None for auto
        n_snapshots: int  — Number of time snapshots for ridge plot
    """
    if not HAS_MPL or data is None:
        return

    time = data['time']
    o_z = data['o_z_traj']   # (n_frames, n_o)
    surface = data['surface_z']
    min_z = data['min_o_z']
    cross_times = data['cross_times']
    n_o = data['n_o']
    n_frames = len(time)

    # Auto z_focus
    if z_focus is None:
        all_z = o_z.flatten()
        z_lo = max(0, np.min(all_z) - 5)
        z_hi = min(np.max(all_z) + 5, np.max(surface) + 15)
    else:
        z_lo, z_hi = z_focus

    # ── 1. Spaghetti plot: individual O trajectories ──
    fig, ax = plt.subplots(figsize=figsize or (12, 6))
    for j in range(n_o):
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
    for i in range(n_frames):
        h, _ = np.histogram(o_z[i], bins=z_edges)
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
        hist, _ = np.histogram(o_z[idx], bins=z_hist_edges)
        offset = k * offset_step
        ax.fill_between(z_hist_centers, offset, hist + offset, alpha=0.3, color=colors[k])
        ax.plot(z_hist_centers, hist + offset, color=colors[k], lw=1.5)
        ax.text(z_hi - 0.5, offset + offset_step * 0.5, f'{time[idx]:.0f} ps',
                fontsize=9, fontweight='bold', color=colors[k], ha='right', va='center',
                bbox=dict(facecolor='white', alpha=0.8, edgecolor='none', pad=1))

    # Surface marker
    mean_surf = np.mean(surface)
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
        # 50% annotation
        half_idx = len(cross_times) // 2
        if half_idx > 0:
            ax.axhline(cumulative[half_idx], color='grey', ls=':', alpha=0.5)
            ax.axvline(cross_times[half_idx], color='grey', ls=':', alpha=0.5)
            ax.text(cross_times[half_idx], cumulative[half_idx] + 1,
                    f' t₅₀ = {cross_times[half_idx]:.0f} ps', fontsize=9)
        ax.set(xlabel='Time (ps)', ylabel='Cumulative O atoms adsorbed',
               title=f'O Adsorption Timeline — {len(cross_times)}/{n_o} adsorbed')
    else:
        ax.text(0.5, 0.5, 'No O atoms crossed the surface', transform=ax.transAxes,
                ha='center', va='center', fontsize=12)
        ax.set(xlabel='Time (ps)', ylabel='Cumulative O atoms adsorbed',
               title='O Adsorption Timeline')
    plt.tight_layout()
    _save_fig(fig, os.path.join(output_dir, 'o_adsorption_timeline.png'), dpi)

    # ── 5. 3D surface plot ──
    from mpl_toolkits.mplot3d import Axes3D

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
        if len(arr) > w:
            return np.convolve(arr, np.ones(w) / w, mode='valid'), time[w // 2:w // 2 + len(arr) - w + 1]
        return arr, time

    # (a) Mean O z-position + std band
    mean_z = np.mean(o_z, axis=1)
    std_z = np.std(o_z, axis=1)
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
    frac_below = np.array([np.mean(o_z[i] < surface[i]) for i in range(n_frames)])
    sm_frac, t_sm2 = _smooth(frac_below)

    ax = axes[0, 1]
    ax.plot(time, frac_below * 100, color=CLR['oar'], lw=0.5, alpha=0.4)
    ax.plot(t_sm2, sm_frac * 100, color=CLR['smooth'], lw=1.5, label='Adsorption ratio')
    ax.set(xlabel='Time (ps)', ylabel='O below surface (%)',
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
    depth = np.maximum(surface - min_z, 0)
    sm_depth, t_sm4 = _smooth(depth)

    ax = axes[1, 1]
    ax.plot(time, depth, color=CLR['avg'], lw=0.5, alpha=0.4)
    ax.plot(t_sm4, sm_depth, color=CLR['smooth'], lw=1.5, label='Max depth')
    # Parabolic fit if significant penetration
    onset_mask = depth > 1.0
    if np.sum(onset_mask) > 10:
        onset_idx = np.argmax(onset_mask)
        t_onset = time[onset_idx]
        t_rel = time[onset_idx:] - t_onset
        d_rel = depth[onset_idx:]
        valid = t_rel > 0
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
    Output: penetration_trend.png
    """
    if not HAS_MPL or data is None:
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


