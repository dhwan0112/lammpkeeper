//! Supervise one Python backend process (`python -m lammpkeeper ...`).
//!
//! The Python side (EXEC-2 `lkpr run`) owns the scientific job: its state,
//! deadline, cancellation and cleanup of its own children. This module only
//! starts that process in its own process group, feeds stdin, collects stdout
//! (bounded), forwards one SIGINT on Ctrl-C, and as a last resort terminates an
//! unresponsive process or a straggler that kept stdout open after the backend
//! exited. A forced kill is never reported as cancellation.

use std::io::{Read, Write};
use std::os::unix::process::CommandExt;
use std::process::{Child, Command, ExitStatus, Stdio};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::mpsc;
use std::sync::Arc;
use std::thread;
use std::time::{Duration, Instant};

/// Largest backend stdout accepted. `lkpr run` bounds its own transport, so a
/// larger stream means a broken or unexpected backend, not a bigger result.
pub const MAX_STDOUT: usize = 16 * 1024 * 1024;
/// How long to wait for `lkpr run` to publish its snapshot after SIGINT. It
/// needs about 2 * (0.15 + 1.0) + 1 s for cleanup plus interpreter shutdown.
pub const INTERRUPT_GRACE: Duration = Duration::from_secs(10);
/// Wait between SIGTERM and SIGKILL when the backend must be stopped by force.
pub const KILL_GRACE: Duration = Duration::from_secs(2);
/// After the backend exits, wait this long for its stdout pipe to close. Only
/// a stray process still holding the pipe could delay it (EXEC-2 gives its own
/// children separate pipes), so a timeout is reported, never waited out; the
/// backend's process group is then stopped so no straggler is left behind.
pub const STDOUT_CLOSE_WAIT: Duration = Duration::from_secs(5);
const POLL: Duration = Duration::from_millis(20);

static INTERRUPTED: AtomicBool = AtomicBool::new(false);

/// SIGINT handler: record the interrupt for the supervision loop to forward.
extern "C" fn on_sigint(_: libc::c_int) {
    // Async-signal-safe: only an atomic store. The supervisor loop acts on it.
    INTERRUPTED.store(true, Ordering::SeqCst);
}

/// Route SIGINT to a flag instead of killing this process, so Ctrl-C can be
/// forwarded to the backend as a cancellation request.
pub fn install_sigint_handler() {
    // SAFETY: sigaction with a handler that only performs an atomic store.
    unsafe {
        let mut action: libc::sigaction = std::mem::zeroed();
        action.sa_sigaction = on_sigint as *const () as usize;
        libc::sigemptyset(&mut action.sa_mask);
        action.sa_flags = libc::SA_RESTART;
        libc::sigaction(libc::SIGINT, &action, std::ptr::null_mut());
    }
}

/// True once Ctrl-C (SIGINT) reached this process.
pub fn interrupted() -> bool {
    INTERRUPTED.load(Ordering::SeqCst)
}

/// Why the supervisor had to stop the backend itself.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Forced {
    /// No snapshot arrived within the deadline (or the post-SIGINT grace).
    Unresponsive,
    /// The backend wrote more than [`MAX_STDOUT`] bytes.
    OutputTooLarge,
}

/// Everything observed about one backend run.
#[derive(Debug)]
pub struct Outcome {
    /// Exit status, when the process was reaped.
    pub status: Option<ExitStatus>,
    /// Captured stdout (at most [`MAX_STDOUT`] bytes).
    pub stdout: Vec<u8>,
    /// SIGINT was received and forwarded to the backend.
    pub interrupted: bool,
    /// Set when this supervisor terminated the backend by force.
    pub forced: Option<Forced>,
    /// The backend exited but a member of its process group kept its stdout
    /// open past [`STDOUT_CLOSE_WAIT`]; the group was stopped and `stdout` is
    /// empty.
    pub stdout_held_open: bool,
}

/// Start `program args...` in a new process group with stdout captured and
/// stderr inherited (diagnostics stay visible and never mix into stdout).
pub fn spawn(program: &str, args: &[String], stdin: Option<&[u8]>) -> std::io::Result<Child> {
    let mut command = Command::new(program);
    command
        .args(args)
        .stdin(if stdin.is_some() {
            Stdio::piped()
        } else {
            Stdio::null()
        })
        .stdout(Stdio::piped())
        .stderr(Stdio::inherit())
        // Own process group: a terminal Ctrl-C reaches only this process, which
        // then forwards exactly one SIGINT. A duplicate SIGINT could interrupt
        // `lkpr run` while it is already cleaning up.
        .process_group(0);
    let mut child = command.spawn()?;
    if let (Some(bytes), Some(mut pipe)) = (stdin, child.stdin.take()) {
        // Write on a thread: a backend that never reads stdin must not block us
        // before the supervision loop (deadline, Ctrl-C) starts. A backend that
        // exits early closes the pipe; that shows up in its status and output.
        let bytes = bytes.to_vec();
        thread::spawn(move || {
            let _ = pipe.write_all(&bytes);
        });
    }
    Ok(child)
}

/// Send `sig` to the backend's whole process group (it was started as leader).
fn signal_group(pid: u32, sig: libc::c_int) {
    // SAFETY: plain kill(2) on the child's own process group (negative pid).
    unsafe {
        libc::kill(-(pid as libc::pid_t), sig);
    }
}

/// True once the child has exited, without reaping it (waitid WNOWAIT). While
/// unreaped, its pid and process-group id cannot be reused by another process.
fn exited_unreaped(pid: u32) -> bool {
    // SAFETY: waitid on our own child with WNOHANG|WNOWAIT only inspects state.
    unsafe {
        let mut info: libc::siginfo_t = std::mem::zeroed();
        let rc = libc::waitid(
            libc::P_PID,
            pid as libc::id_t,
            &mut info,
            libc::WEXITED | libc::WNOHANG | libc::WNOWAIT,
        );
        rc == 0 && info.si_pid() != 0
    }
}

/// Stop the backend by force: SIGTERM its group, wait up to a grace, then
/// SIGKILL the whole group before reaping the leader. Killing the group even
/// after the leader exited stops members that could hold the stdout pipe; the
/// unreaped leader keeps the group id from being reused meanwhile.
fn terminate(child: &mut Child) -> Option<ExitStatus> {
    let pid = child.id();
    signal_group(pid, libc::SIGTERM);
    let until = Instant::now() + KILL_GRACE;
    while Instant::now() < until && !exited_unreaped(pid) {
        thread::sleep(POLL);
    }
    signal_group(pid, libc::SIGKILL);
    child.wait().ok()
}

/// Stop the stragglers of a backend that already exited on its own: SIGTERM
/// its group, wait up to a grace for the stdout pipe to close, then SIGKILL the
/// group. The leader must still be unreaped so that its group id is reserved.
fn stop_group(pid: u32, reader: &mpsc::Receiver<Vec<u8>>) {
    signal_group(pid, libc::SIGTERM);
    let _ = reader.recv_timeout(KILL_GRACE);
    signal_group(pid, libc::SIGKILL);
}

/// Supervise a started backend until it exits or must be stopped.
///
/// `deadline` bounds the whole run; it should exceed the backend's own timeout
/// so that `lkpr run` normally reports `timed_out` itself.
pub fn supervise(mut child: Child, deadline: Instant) -> Outcome {
    let overflow = Arc::new(AtomicBool::new(false));
    let mut pipe = child.stdout.take().expect("stdout is piped");
    let flag = Arc::clone(&overflow);
    let (sender, receiver) = mpsc::channel();
    // Read on a thread so a full pipe can never block the child or this loop.
    thread::spawn(move || {
        let mut kept = Vec::new();
        let mut buf = [0u8; 65536];
        loop {
            match pipe.read(&mut buf) {
                Ok(0) | Err(_) => break,
                Ok(n) => {
                    if flag.load(Ordering::SeqCst) || kept.len() + n > MAX_STDOUT {
                        flag.store(true, Ordering::SeqCst);
                        // Keep draining so the writer is not blocked, but store
                        // nothing more: a later small chunk must not be appended
                        // after a dropped one and leave a hole in the stream.
                        continue;
                    }
                    kept.extend_from_slice(&buf[..n]);
                }
            }
        }
        let _ = sender.send(kept);
    });

    let mut forwarded = false;
    let mut cancel_deadline = deadline;
    let mut forced = None;
    // Order of checks: exit first (a finished backend needs no signal), then
    // Ctrl-C forwarding, then output overflow, then the deadline. Overflow that
    // happens in the same poll as the exit is caught after the loop.
    let status = loop {
        // Detect the exit without reaping: the leader's pid keeps the group id
        // reserved until the group is known to be gone or has been stopped.
        if exited_unreaped(child.id()) {
            break None;
        }
        if interrupted() && !forwarded {
            // One SIGINT to `lkpr run` itself (not its group): it cancels its
            // owned job, cleans up its children and prints a final snapshot.
            // SAFETY: kill(2) on our direct child's pid.
            unsafe {
                libc::kill(child.id() as libc::pid_t, libc::SIGINT);
            }
            forwarded = true;
            cancel_deadline = cancel_deadline.min(Instant::now() + INTERRUPT_GRACE);
        }
        if overflow.load(Ordering::SeqCst) {
            forced = Some(Forced::OutputTooLarge);
            break terminate(&mut child);
        }
        if Instant::now() >= cancel_deadline {
            forced = Some(Forced::Unresponsive);
            break terminate(&mut child);
        }
        thread::sleep(POLL);
    };
    // Bounded: a stray process holding the pipe must not hang the CLI.
    let (stdout, stdout_held_open) = match receiver.recv_timeout(STDOUT_CLOSE_WAIT) {
        Ok(bytes) => (bytes, false),
        Err(_) => {
            // The leader exited on its own, but a member of its group still
            // holds the pipe. Stop the group as the forced paths do, so the CLI
            // leaves no orphan behind; the run is still reported as held open.
            if forced.is_none() {
                stop_group(child.id(), &receiver);
            }
            (Vec::new(), true)
        }
    };
    // The forced paths reaped the leader in `terminate`; the normal path reaps
    // it here, after any group signal that needed its id reserved.
    let status = status.or_else(|| child.wait().ok());
    // The backend may exit in the same poll in which it overflowed; the reader
    // has then finished, so this final check sees every dropped chunk.
    if forced.is_none() && overflow.load(Ordering::SeqCst) {
        forced = Some(Forced::OutputTooLarge);
    }
    Outcome {
        status,
        stdout,
        interrupted: forwarded,
        forced,
        stdout_held_open,
    }
}
