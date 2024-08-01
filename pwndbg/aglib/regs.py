"""
Reading register value from the inferior, and provides a
standardized interface to registers like "sp" and "pc".
"""

from __future__ import annotations

import ctypes
import re
import sys
from types import ModuleType
from typing import Any
from typing import Callable
from typing import Dict
from typing import Generator
from typing import List
from typing import Tuple
from typing import cast

import pwndbg
import pwndbg.aglib.arch
import pwndbg.aglib.qemu
import pwndbg.aglib.remote
import pwndbg.aglib.typeinfo
import pwndbg.lib.cache
from pwndbg.dbg import EventType
from pwndbg.lib.regs import BitFlags
from pwndbg.lib.regs import RegisterSet
from pwndbg.lib.regs import reg_sets


def get_register(name: str) -> pwndbg.dbg_mod.Value:
    frame = pwndbg.dbg.selected_frame()
    if frame is None:
        return None

    regs = frame.regs()
    value = regs.by_name(name)
    if value:
        return value
    return regs.by_name(name.upper())


def get_qemu_register(name: str) -> int:
    if not pwndbg.aglib.qemu.is_qemu_kernel():
        return None
    if pwndbg.dbg.selected_frame() is None:
        return None

    out = pwndbg.dbg.selected_inferior().send_monitor("info registers")
    match = re.search(rf'{name.split("_")[0]}=\s+([\da-fA-F]+)\s+([\da-fA-F]+)', out)

    if match:
        base = int(match.group(1), 16)
        limit = int(match.group(2), 16)

        if name.endswith("LIMIT"):
            return limit
        else:
            return base

    return None


# We need to manually make some ptrace calls to get fs/gs bases on Intel
PTRACE_ARCH_PRCTL = 30
ARCH_GET_FS = 0x1003
ARCH_GET_GS = 0x1004

gpr: Tuple[str, ...]
common: List[str]
frame: str | None
retaddr: Tuple[str, ...]
flags: Dict[str, BitFlags]
extra_flags: Dict[str, BitFlags]
stack: str
retval: str | None
all: List[str]
changed: List[str]
fsbase: int
gsbase: int
current: RegisterSet
fix: Callable[[str], str]
items: Callable[[], Generator[Tuple[str, Any], None, None]]
previous: Dict[str, int]
last: Dict[str, int]
pc: int | None


class module(ModuleType):
    previous: Dict[str, int] = {}
    last: Dict[str, int] = {}

    @pwndbg.lib.cache.cache_until("stop", "prompt")
    def __getattr__(self, attr: str) -> int | None:
        attr = attr.lstrip("$")
        try:
            value = get_register(attr)
            if value is None and attr.lower() == "xpsr":
                value = get_register("xPSR")
            if value is None:
                return None
            size = pwndbg.aglib.typeinfo.unsigned.get(
                value.type.sizeof, pwndbg.aglib.typeinfo.ulong
            )

            int_value = int(value.cast(size))

            if attr == "pc" and pwndbg.aglib.arch.name == "i8086":
                if self.cs is None:
                    return None
                int_value += self.cs * 16
            return int_value & pwndbg.aglib.arch.ptrmask
        except (ValueError, pwndbg.dbg_mod.Error):
            return None

    def __setattr__(self, attr: str, val: Any) -> None:
        if attr in ("last", "previous"):
            super().__setattr__(attr, val)
        else:
            pwndbg.dbg.selected_frame().reg_write(attr, int(val))

    @pwndbg.lib.cache.cache_until("stop", "prompt")
    def __getitem__(self, item: Any) -> int | None:
        if not isinstance(item, str):
            print("Unknown register type: %r" % (item))
            return None

        # e.g. if we're looking for register "$rax", turn it into "rax"
        item = item.lstrip("$")
        item = getattr(self, item.lower(), None)

        if item is not None:
            item &= pwndbg.aglib.arch.ptrmask

        return item

    def __contains__(self, reg: str) -> bool:
        regs = set(reg_sets[pwndbg.aglib.arch.name]) | {"pc", "sp"}
        return reg in regs

    def __iter__(self) -> Generator[str, None, None]:
        regs = set(reg_sets[pwndbg.aglib.arch.name]) | {"pc", "sp"}
        yield from regs

    @property
    def current(self) -> RegisterSet:
        return reg_sets[pwndbg.aglib.arch.name]

    # TODO: All these should be able to do self.current
    @property
    def gpr(self) -> Tuple[str, ...]:
        return reg_sets[pwndbg.aglib.arch.name].gpr

    @property
    def common(self) -> List[str]:
        return reg_sets[pwndbg.aglib.arch.name].common

    @property
    def frame(self) -> str | None:
        return reg_sets[pwndbg.aglib.arch.name].frame

    @property
    def retaddr(self) -> Tuple[str, ...]:
        return reg_sets[pwndbg.aglib.arch.name].retaddr

    @property
    def flags(self) -> Dict[str, BitFlags]:
        return reg_sets[pwndbg.aglib.arch.name].flags

    @property
    def extra_flags(self) -> Dict[str, BitFlags]:
        return reg_sets[pwndbg.aglib.arch.name].extra_flags

    @property
    def stack(self) -> str:
        return reg_sets[pwndbg.aglib.arch.name].stack

    @property
    def retval(self) -> str | None:
        return reg_sets[pwndbg.aglib.arch.name].retval

    @property
    def all(self) -> List[str]:
        regs = reg_sets[pwndbg.aglib.arch.name]
        retval: List[str] = []
        for regset in (
            regs.pc,
            regs.stack,
            regs.frame,
            regs.retaddr,
            regs.flags,
            regs.gpr,
            regs.misc,
        ):
            if regset is None:
                continue

            if isinstance(regset, (list, tuple)):  # regs.retaddr
                retval.extend(regset)
            elif isinstance(regset, dict):  # regs.flags
                retval.extend(regset.keys())
            else:
                retval.append(regset)  # type: ignore[arg-type]
        return retval

    def fix(self, expression: str) -> str:
        for regname in set(self.all + ["sp", "pc"]):
            expression = re.sub(rf"\$?\b{regname}\b", r"$" + regname, expression)
        return expression

    def items(self) -> Generator[Tuple[str, Any], None, None]:
        for regname in self.all:
            yield regname, self[regname]

    reg_sets = reg_sets

    @property
    def changed(self) -> List[str]:
        delta: List[str] = []
        for reg, value in self.previous.items():
            if self[reg] != value:
                delta.append(reg)
        return delta

    @property
    @pwndbg.lib.cache.cache_until("stop")
    def idt(self) -> int:
        if not pwndbg.aglib.qemu.is_qemu_kernel():
            return None
        arch = pwndbg.dbg.selected_inferior().arch().arch()
        if arch != "i386" and arch != "x86-64":
            return None

        return get_qemu_register("IDT")

    @property
    @pwndbg.lib.cache.cache_until("stop")
    def idt_limit(self) -> int:
        if not pwndbg.aglib.qemu.is_qemu_kernel():
            return None
        arch = pwndbg.dbg.selected_inferior().arch().arch()
        if arch != "i386" and arch != "x86-64":
            return None

        return get_qemu_register("IDT_LIMIT")

    @property
    @pwndbg.lib.cache.cache_until("stop")
    def fsbase(self) -> int:
        return self._fs_gs_helper("fs_base", ARCH_GET_FS)

    @property
    @pwndbg.lib.cache.cache_until("stop")
    def gsbase(self) -> int:
        return self._fs_gs_helper("gs_base", ARCH_GET_GS)

    @pwndbg.lib.cache.cache_until("stop")
    def _fs_gs_helper(self, regname: str, which: int) -> int:
        """Supports fetching based on segmented addressing, a la fs:[0x30].
        Requires ptrace'ing the child directory if i386."""

        if pwndbg.aglib.arch.name == "x86-64":
            reg_value = get_register(regname)
            return int(reg_value) if reg_value is not None else 0

        # We can't really do anything if the process is remote.
        if pwndbg.aglib.remote.is_remote():
            return 0

        # Use the lightweight process ID
        lwpid = pwndbg.dbg.selected_thread().ptid()
        if lwpid is None:
            return 0

        # Get the register
        ppvoid = ctypes.POINTER(ctypes.c_void_p)
        value = ppvoid(ctypes.c_void_p())
        value.contents.value = 0

        libc = ctypes.CDLL("libc.so.6")
        result = libc.ptrace(PTRACE_ARCH_PRCTL, lwpid, value, which)

        if result == 0:
            return (value.contents.value or 0) & pwndbg.aglib.arch.ptrmask

        return 0

    def __repr__(self) -> str:
        return "<module pwndbg.aglib.regs>"


# To prevent garbage collection
tether = sys.modules[__name__]
sys.modules[__name__] = module(__name__, "")


@pwndbg.dbg.event_handler(EventType.CONTINUE)
@pwndbg.dbg.event_handler(EventType.STOP)
def update_last() -> None:
    M: module = cast(module, sys.modules[__name__])
    M.previous = M.last
    M.last = {k: M[k] for k in M.common}

    # TODO: Port `context` to the debugger-agnostic interfaces and uncomment this.
    # if pwndbg.config.show_retaddr_reg:
    #    M.last.update({k: M[k] for k in M.retaddr})
