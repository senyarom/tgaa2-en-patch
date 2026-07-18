OUTPUT_FORMAT("elf32-littlearm")
OUTPUT_ARCH(arm)
ENTRY(court_record_detail_hook)

/* Override these with ld --defsym for another game/version. */
HOOK_START = DEFINED(HOOK_ADDRESS) ? HOOK_ADDRESS : 0x005BDA90;
HOOK_END = DEFINED(CODE_CAVE_END) ? CODE_CAVE_END : 0x005BEA90;

SECTIONS
{
    . = HOOK_START;

    .text : ALIGN(4)
    {
        KEEP(*(.text.court_record_hook))
        *(.text*)
        *(.rodata*)
    }

    /DISCARD/ :
    {
        *(.ARM.attributes)
        *(.comment)
        *(.data*)
        *(.bss*)
        *(.eh_frame*)
        *(.ARM.exidx*)
        *(.ARM.extab*)
        *(.note*)
    }
}

ASSERT(SIZEOF(.text) > 0, "hook payload is empty")
ASSERT(. <= HOOK_END, "hook payload exceeds the executable code cave")
