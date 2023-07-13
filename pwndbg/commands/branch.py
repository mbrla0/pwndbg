import argparse

import gdb

from capstone import CS_GRP_JUMP
import pwndbg.color.message as message
import pwndbg.commands
import pwndbg.disasm
import pwndbg.gdblib.next

class BreakOnConditionalBranch(gdb.Breakpoint):
    """
    A breakpoint that only stops the inferior if a given branch is taken or not taken.
    """

    def __init__(self, instruction, taken):
        super().__init__("*%#x" % instruction.address, type=gdb.BP_BREAKPOINT, internal=False)
        self.instruction = instruction
        self.taken = taken

    def stop(self):
        # Return true if the branch is going to be taken and we were expecting 
        # it to and if the branch is not going to be taken and we were expecting
        # it not to. 
        assistant = pwndbg.disasm.arch.DisassemblyAssistant.for_current_arch()
        
        condition_met = assistant.condition(self.instruction)
        if condition_met is None:
            # Unconditional jumps are always taken.
            condition_met = 1
        condition_met = condition_met != 0

        return condition_met == self.taken

parser = argparse.ArgumentParser(description="Breaks on a branch if it is taken.")
parser.add_argument(
    "branch",
    type=str,
    help="The branch instruction to break on.",
)

@pwndbg.commands.ArgparsedCommand(parser, command_name="break-if-taken")
@pwndbg.commands.OnlyWhenRunning
def break_if_taken(branch) -> None:
    """Breaks at the next call instruction"""
    install_breakpoint(branch, taken=True)

parser = argparse.ArgumentParser(description="Breaks on a branch if it is not taken.")
parser.add_argument(
    "branch",
    type=str,
    help="The branch instruction to break on.",
)

@pwndbg.commands.ArgparsedCommand(parser, command_name="break-if-not-taken")
@pwndbg.commands.OnlyWhenRunning
def break_if_not_taken(branch) -> None:
    """Breaks at the next call instruction"""
    install_breakpoint(branch, taken=False)


def install_breakpoint(branch, taken):
    # Do our best to interpret branch as a locspec. Untimately, though, we're 
    # limited in what we can do from inside Python in that front.
    address = None
    try:
        # Try to interpret branch as an address literal
        address = int(branch, 0)
    except ValueError:
        pass

    if address is None:
        # That didn't work. Defer to GDB and see if it can make something out of
        # the address value we were given.
        try:
            value = gdb.parse_and_eval(branch)
            if value.address is None:
                print(message.warn(f"Value {branch} has no address, trying its value"))
                address = int(value)
            else:
                address = int(value.address)
        except gdb.error as e:
            # No such luck. Report to the user and quit.
            print(message.error(f"Could not resolve branch location {branch}: {e}"))
            return

    # We should've picked something by now, or errored out.
    instruction = pwndbg.disasm.one(address)
    if instruction is None:
        print(message.error("Could not decode instruction at address %#p" % address))
        return
    if CS_GRP_JUMP not in instruction.groups:
        fmt = (instruction.mnemonic, instruction.op_str, address)
        print(message.error("Instruction \"%s %s\" at address %#x is not a branch" % fmt))
        return

    # Not all architectures have assistants we can use for conditionals.
    if pwndbg.disasm.arch.DisassemblyAssistant.for_current_arch() is None:
        print(message.error("The current architecture is not supported for breaking on conditional branches"))
        return

    # Install the breakpoint.
    BreakOnConditionalBranch(instruction, taken)
    
