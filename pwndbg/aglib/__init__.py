from __future__ import annotations


def load_aglib():
    import pwndbg.aglib.arch
    import pwndbg.aglib.disasm
    import pwndbg.aglib.disasm.aarch64
    import pwndbg.aglib.disasm.arm
    import pwndbg.aglib.disasm.mips
    import pwndbg.aglib.disasm.ppc
    import pwndbg.aglib.disasm.riscv
    import pwndbg.aglib.disasm.sparc
    import pwndbg.aglib.disasm.x86
    import pwndbg.aglib.file
    import pwndbg.aglib.memory
    import pwndbg.aglib.proc
    import pwndbg.aglib.qemu
    import pwndbg.aglib.regs
    import pwndbg.aglib.remote
    import pwndbg.aglib.strings
    import pwndbg.aglib.typeinfo
    import pwndbg.aglib.vmmap