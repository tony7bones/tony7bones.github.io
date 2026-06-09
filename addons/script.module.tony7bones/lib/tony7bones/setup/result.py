"""LayerResult — the value object the apply_* layer modules return.

A small, log-friendly result type that lets a layer module REQUEST terminal
operations (skin activation, restart) that the ORCHESTRATOR decides. Modules do
the work and report what they reached; the orchestrator reads ``ok`` (BEFORE
restarting a gate), ``needs_skin_activation``, and ``needs_restart`` as requests
and owns the actual cadence (activate-skin-last, single vs per-gate restart).

This module is pure Python with no Kodi deps so it imports cleanly under tests.
"""

from __future__ import annotations

from dataclasses import dataclass, field

LAYERS = ("foundation", "iptv", "addons")


@dataclass
class LayerResult:
    """The outcome of applying one setup layer.

    Fields
    ------
    layer
        Which layer produced this result: ``"foundation"``, ``"iptv"`` or
        ``"addons"``.
    ok
        Did the layer reach a complete (success or acceptably-degraded) state?
        The orchestrator checks this BEFORE restarting a gate, so a swallowed
        failure can't restart into a broken box.
    already_done
        Re-entry no-op'd everything — the box was already in this layer's target
        state, nothing was installed or changed.
    installed
        ``{addon_id: state}`` for what this layer installed/enabled this run.
    failed
        ``{addon_id: reason}`` for what this layer could not complete.
    needs_skin_activation
        A REQUEST: the layer staged a skin that the orchestrator must activate
        (set ``lookandfeel.skin`` + accept "Keep this skin?") LAST, right before
        the restart. Only ``foundation`` sets this.
    needs_restart
        A REQUEST: the layer's changes need a Kodi restart to take effect. The
        orchestrator owns the actual restart cadence.
    detail
        A short human-readable note for logs / the summary dialog.
    """

    layer: str
    ok: bool
    already_done: bool = False
    installed: dict = field(default_factory=dict)
    failed: dict = field(default_factory=dict)
    needs_skin_activation: bool = False
    needs_restart: bool = False
    detail: str = ""

    def __repr__(self) -> str:
        flags = []
        if self.already_done:
            flags.append("already_done")
        if self.needs_skin_activation:
            flags.append("needs_skin_activation")
        if self.needs_restart:
            flags.append("needs_restart")
        flag_str = (" " + " ".join(flags)) if flags else ""
        detail_str = f" detail={self.detail!r}" if self.detail else ""
        return (
            f"<LayerResult {self.layer} "
            f"{'ok' if self.ok else 'FAILED'}{flag_str} "
            f"installed={len(self.installed)} failed={len(self.failed)}"
            f"{detail_str}>"
        )
