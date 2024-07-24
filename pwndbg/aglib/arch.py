from __future__ import annotations

from typing import Literal

import pwndbg
from pwndbg.lib.arch import Arch

# We will optimize this module in the future, by having it work in the same
# way the `gdblib` version of it works, and that will come at the same
# time this module gets expanded to have the full feature set of its `gdlib`
# coutnerpart. For now, though, this should be good enough.


ARCHS = (
    "x86-64",
    "i386",
    "aarch64",
    "mips",
    "powerpc",
    "sparc",
    "arm",
    "armcm",
    "riscv:rv32",
    "riscv:rv64",
    "riscv",
)


def read_thumb_bit() -> int | None:
    """
    Return 0 or 1, representing the status of the Thumb bit in the current Arm architecture

    Return None if the Thumb bit is not relevent to the current architecture
    """
    if pwndbg.aglib.arch.current == "arm":
        # When program initially starts, cpsr may not be readable
        if (cpsr := pwndbg.aglib.regs.cpsr) is not None:
            return (cpsr >> 5) & 1
    elif pwndbg.aglib.arch.current == "armcm":
        # ARM Cortex-M procesors only suport Thumb mode. However, there is still a bit
        # that represents the Thumb mode (which is currently architecturally defined to be 1)
        if (xpsr := pwndbg.aglib.regs.xpsr) is not None:
            return (xpsr >> 24) & 1
    # AArch64 does not have a Thumb bit
    return None


def get_thumb_mode_string() -> Literal["arm", "thumb"] | None:
    thumb_bit = read_thumb_bit()
    return None if thumb_bit is None else "thumb" if thumb_bit == 1 else "arm"


def __getattr__(name):
    arch = pwndbg.dbg.selected_inferior().arch()
    if name == "endian":
        return arch.endian
    elif name == "ptrsize":
        return arch.ptrsize
    else:
        return getattr(Arch(arch.name, arch.ptrsize, arch.endian), name)